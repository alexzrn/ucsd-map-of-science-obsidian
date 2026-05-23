#!/usr/bin/env python3
"""Basic integrity checks for the generated Obsidian vault."""

from pathlib import Path
import csv


ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"


def main() -> None:
    disciplines = list((VAULT / "Disciplines").glob("*.md"))
    subdisciplines = list((VAULT / "Subdisciplines").glob("*.md"))
    assert (VAULT / "00 Index.md").exists(), "missing index"
    assert len(disciplines) == 13, f"expected 13 disciplines, got {len(disciplines)}"
    assert len(subdisciplines) == 554, f"expected 554 subdisciplines, got {len(subdisciplines)}"
    assert (ROOT / "data" / "processed" / "edges.csv").exists(), "missing edges.csv"
    categories = list(csv.DictReader((ROOT / "data" / "processed" / "visual_categories.csv").open()))
    assert len(categories) == 554, f"expected 554 visual categories, got {len(categories)}"
    assert (ROOT / ".obsidian" / "graph.json").exists(), "missing Obsidian graph config"
    print("Vault validation passed.")


if __name__ == "__main__":
    main()
