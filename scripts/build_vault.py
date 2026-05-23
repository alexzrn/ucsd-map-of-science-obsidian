#!/usr/bin/env python3
"""Build an Obsidian vault from the UCSD Map of Science data tables."""

from __future__ import annotations

import csv
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
VAULT = ROOT / "vault"
XLSX = RAW / "UCSDmapDataTables.xlsx"
HTML_CATEGORIES = RAW / "html_visual_categories.csv"

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def colnum(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    num = 0
    for ch in letters:
        num = num * 26 + ord(ch) - 64
    return num - 1


def clean_filename(value: str) -> str:
    value = value.replace("&", "and")
    value = re.sub(r"[\\/:*?\"<>|]", "-", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:140].rstrip(" .")


def slug(value: str) -> str:
    value = value.lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_name(value: str) -> str:
    value = value.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def fmt_num(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return str(int(number))
    return f"{number:.6g}"


def read_shared_strings(zf: ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    ]


def workbook_sheet_paths(zf: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: "xl/" + rel.attrib["Target"]
        for rel in rels
        if "worksheet" in rel.attrib["Type"]
    }
    return {
        sheet.attrib["name"]: targets[
            sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
        ]
        for sheet in workbook.find("m:sheets", NS)
    }


def read_sheet(zf: ZipFile, shared_strings: list[str], path: str) -> list[dict[str, str]]:
    root = ET.fromstring(zf.read(path))
    rows: list[list[str]] = []
    for row in root.findall(".//m:sheetData/m:row", NS):
        values: list[str] = []
        for cell in row.findall("m:c", NS):
            idx = colnum(cell.attrib.get("r", "A"))
            while len(values) < idx:
                values.append("")
            raw = cell.find("m:v", NS)
            value = ""
            if raw is not None:
                value = raw.text or ""
                if cell.attrib.get("t") == "s":
                    value = shared_strings[int(value)]
            values.append(value)
        rows.append(values)

    header_index = next(
        idx for idx, row in enumerate(rows) if row and row[0] in {"subd_id", "disc_id", "subd_id1", "journ_id"}
    )
    headers = rows[header_index]
    records = []
    for row in rows[header_index + 1 :]:
        if not any(row):
            continue
        records.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))})
    return records


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def frontmatter(items: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in items.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(str(item), ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    if not XLSX.exists():
        raise SystemExit(f"Missing {XLSX}")

    if VAULT.exists():
        shutil.rmtree(VAULT)
    (VAULT / "Disciplines").mkdir(parents=True)
    (VAULT / "Subdisciplines").mkdir(parents=True)
    (VAULT / "Sources").mkdir(parents=True)

    with ZipFile(XLSX) as zf:
        strings = read_shared_strings(zf)
        sheets = workbook_sheet_paths(zf)
        subdisciplines = read_sheet(zf, strings, sheets["Table 1"])
        disciplines = read_sheet(zf, strings, sheets["Table 2"])
        edges = read_sheet(zf, strings, sheets["Table 3"])
        terms = read_sheet(zf, strings, sheets["Table 9"])

    visual_categories = {}
    if HTML_CATEGORIES.exists():
        with HTML_CATEGORIES.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                visual_categories[normalize_name(row["subd_name"])] = row

    write_csv(PROCESSED / "disciplines.csv", disciplines)
    write_csv(PROCESSED / "subdisciplines.csv", subdisciplines)
    write_csv(PROCESSED / "edges.csv", edges)

    terms_by_subd: dict[str, list[dict[str, str]]] = defaultdict(list)
    for term in terms:
        terms_by_subd[term["subd_id"]].append(term)

    top_terms = []
    for subd_id, rows in terms_by_subd.items():
        rows.sort(key=lambda row: float(row["tfraction"]), reverse=True)
        top_terms.extend(rows[:20])
    write_csv(PROCESSED / "top_terms.csv", top_terms)
    matched_categories = []
    for row in subdisciplines:
        category = visual_categories.get(normalize_name(row["subd_name"]))
        if category:
            matched_categories.append(
                {
                    "subd_id": row["subd_id"],
                    "subd_name": row["subd_name"],
                    "visual_category": category["visual_category"],
                    "visual_color": category["visual_color"],
                    "tag": f"category/{slug(category['visual_category'])}",
                }
            )
    if matched_categories:
        write_csv(PROCESSED / "visual_categories.csv", matched_categories)

    disciplines_by_id = {row["disc_id"]: row for row in disciplines}
    subdisciplines_by_id = {row["subd_id"]: row for row in subdisciplines}

    discipline_note = {
        row["disc_id"]: f"{row['disc_id']} - {clean_filename(row['disc_name'])}"
        for row in disciplines
    }
    subdiscipline_note = {
        row["subd_id"]: f"{row['subd_id']} - {clean_filename(row['subd_name'])}"
        for row in subdisciplines
    }

    neighbors: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in edges:
        left, right = edge["subd_id1"], edge["subd_id2"]
        neighbors[left].append((right, edge["weight"]))
        neighbors[right].append((left, edge["weight"]))

    for row in disciplines:
        discipline_tag = f"discipline/{slug(row['disc_name'])}"
        children = [s for s in subdisciplines if s["disc_id"] == row["disc_id"]]
        children.sort(key=lambda item: item["subd_name"])
        content = frontmatter(
            {
                "type": "discipline",
                "ucsd_disc_id": row["disc_id"],
                "x": fmt_num(row["x"]),
                "y": fmt_num(row["y"]),
                "color": row["color"],
                "tags": [discipline_tag],
                "source": "UCSD Map of Science 2010",
            }
        )
        content += f"# {row['disc_name']}\n\n"
        content += "## Subdisciplines\n\n"
        content += "\n".join(
            f"- [[{subdiscipline_note[item['subd_id']]}|{item['subd_name']}]]"
            for item in children
        )
        content += "\n"
        (VAULT / "Disciplines" / f"{discipline_note[row['disc_id']]}.md").write_text(
            content, encoding="utf-8"
        )

    for row in subdisciplines:
        discipline = disciplines_by_id[row["disc_id"]]
        category = visual_categories.get(normalize_name(row["subd_name"]))
        tags = [f"discipline/{slug(discipline['disc_name'])}"]
        if category:
            tags.append(f"category/{slug(category['visual_category'])}")
        top = terms_by_subd.get(row["subd_id"], [])[:20]
        related = sorted(
            neighbors[row["subd_id"]],
            key=lambda item: float(item[1]),
            reverse=True,
        )[:12]
        content = frontmatter(
            {
                "type": "subdiscipline",
                "ucsd_subd_id": row["subd_id"],
                "ucsd_disc_id": row["disc_id"],
                "discipline": f"[[{discipline_note[row['disc_id']]}|{discipline['disc_name']}]]",
                "visual_category": category["visual_category"] if category else "",
                "visual_color": category["visual_color"] if category else "",
                "x": fmt_num(row["x"]),
                "y": fmt_num(row["y"]),
                "size": fmt_num(row["size"]),
                "tags": tags,
                "source": "UCSD Map of Science 2010",
            }
        )
        content += f"# {row['subd_name']}\n\n"
        content += f"Discipline: [[{discipline_note[row['disc_id']]}|{discipline['disc_name']}]]\n\n"
        content += "## Related Subdisciplines\n\n"
        if related:
            content += "\n".join(
                f"- [[{subdiscipline_note[other]}|{subdisciplines_by_id[other]['subd_name']}]]"
                f" (weight: {fmt_num(weight)})"
                for other, weight in related
            )
        else:
            content += "- None listed in the source edge table."
        content += "\n\n## Top Terms\n\n"
        if top:
            content += "\n".join(
                f"- `{term['term']}` ({fmt_num(term['tfraction'])})" for term in top
            )
        else:
            content += "- None listed in the source term table."
        content += "\n"
        (VAULT / "Subdisciplines" / f"{subdiscipline_note[row['subd_id']]}.md").write_text(
            content, encoding="utf-8"
        )

    index = frontmatter({"type": "index", "source": "UCSD Map of Science 2010"})
    index += "# UCSD Map of Science\n\n"
    index += (
        "An Obsidian vault generated from the 2010 UCSD Map of Science and Classification "
        "System. The map organizes 554 subdisciplines into 13 disciplines and preserves "
        "source coordinates, node sizes, terms, and strongest map edges.\n\n"
    )
    index += "## Disciplines\n\n"
    index += "\n".join(
        f"- [[{discipline_note[row['disc_id']]}|{row['disc_name']}]]"
        for row in disciplines
    )
    index += "\n\n## Source Notes\n\n"
    index += "- [[Citation and License]]\n- [[Data Dictionary]]\n"
    (VAULT / "00 Index.md").write_text(index, encoding="utf-8")

    citation = """---
type: source
---

# Citation and License

Primary source:

Börner, Katy, Richard Klavans, Michael Patek, Angela Zoss, Joseph R. Biberstine, Robert Light, Vincent Larivière, and Kevin W. Boyack. 2012. "Design and Update of a Classification System: The UCSD Map of Science." PLoS ONE 7(7): e39464. https://doi.org/10.1371/journal.pone.0039464

Required acknowledgment:

> The authors wish to acknowledge The Regents of the University of California, SciTech Strategies, Observatoire des Sciences et des Technologies, and the Cyberinfrastructure for Network Science Center for making the 2010 UCSD Map of Science and Classification System available for this work.

The 2005 and 2010 UCSD Map of Science classification systems are distributed under CC BY-NC-SA 3.0. This derivative vault follows the same non-commercial, share-alike constraint.
"""
    (VAULT / "Sources" / "Citation and License.md").write_text(citation, encoding="utf-8")

    dictionary = """---
type: source
---

# Data Dictionary

Generated notes use these source tables from `data/raw/UCSDmapDataTables.xlsx`:

- Table 1: 554 subdisciplines, discipline IDs, map coordinates, node sizes.
- Table 2: 13 disciplines, map coordinates, colors.
- Table 3: base-map edges between subdisciplines.
- Table 9: terms associated with subdisciplines.
- `data/raw/html_visual_categories.csv`: visual categories and colors extracted from the distributed HTML visualization.

Processed CSV exports are in `data/processed/`.
"""
    (VAULT / "Sources" / "Data Dictionary.md").write_text(dictionary, encoding="utf-8")

    print(f"Wrote {len(disciplines)} disciplines and {len(subdisciplines)} subdisciplines.")


if __name__ == "__main__":
    main()
