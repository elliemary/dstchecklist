#!/usr/bin/env python3
"""
Populate the 'url' column in ../bosses.csv by matching names to entries
in boss_urls.txt.

Heuristics:
 - Normalizes names to Fandom page titles (spaces -> underscores)
 - Keeps slashes (e.g., Moose/Goose)
 - For any name containing "Reanimated Skeleton", maps to Reanimated_Skeleton
 - Leaves url blank if no match is found
"""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse, unquote


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "bosses.csv"
URLS_PATH = ROOT / "scraping" / "boss_urls.txt"


def load_boss_urls() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with URLS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            url = line.strip()
            if not url:
                continue
            path = unquote(urlparse(url).path)
            if "/wiki/" not in path:
                continue
            page = path.split("/wiki/", 1)[1]
            mapping[page] = url
    return mapping


def normalize_name_to_page(name: str) -> str:
    # Keep slashes as-is; Fandom pages can include '/'
    # Replace spaces with underscores
    page = name.strip().replace(" ", "_")
    # Specific rule: any of the reanimated skeleton variants map to the base page
    if "Reanimated Skeleton" in name:
        return "Reanimated_Skeleton"
    return page


def main() -> int:
    name_to_url = load_boss_urls()

    rows: list[dict[str, str]] = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        # Ensure 'url' exists in header
        if 'url' not in fieldnames:
            fieldnames.insert(1, 'url')
        for row in reader:
            rows.append(row)

    for row in rows:
        name = row.get('name', '').strip().strip('"')
        page = normalize_name_to_page(name)
        url = name_to_url.get(page, '')
        row['url'] = url

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Updated URLs for {sum(1 for r in rows if r.get('url'))}/{len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


