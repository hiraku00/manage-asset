#!/usr/bin/env python3
"""Convert the one-time Lido CSV import into the runtime JSONL format."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "lido-rewards.csv"
TARGET = ROOT / "data" / "lido-rewards.jsonl"


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    with TARGET.open("w", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"converted {len(rows)} rows: {SOURCE.name} -> {TARGET.name}")


if __name__ == "__main__":
    main()
