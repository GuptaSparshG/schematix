"""CSV / JSON exporters."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def export_csv(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Category", "Label", "Value", "Type/Notes"])
        for cat in data.get("components", []):
            cat_name = cat.get("category", "")
            for item in cat.get("items", []):
                writer.writerow([
                    cat_name,
                    item.get("label", ""),
                    item.get("value", ""),
                    item.get("type", ""),
                ])


def export_json(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2))
