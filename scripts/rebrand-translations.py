#!/usr/bin/env python3
"""
Replace "Open WebUI" brand variants with "YuIA" across all translation files.

Only modifies VALUES (not keys). Preserves template variables like {{webUIName}}.

Usage:
    python scripts/rebrand-translations.py            # Apply changes
    python scripts/rebrand-translations.py --dry-run  # Preview only
"""

import json
import os
import re
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

BRAND_NAME = "YuIA"
LOCALES_DIR = Path("src/lib/i18n/locales")


def replace_brand_in_value(value: str) -> str:
    """Replace brand name variants in a translation value string."""
    if not isinstance(value, str) or not value:
        return value

    # 1. Replace "Open WebUI", "Open-WebUI", "OpenWebUI" (case-insensitive)
    #    Matches: "Open WebUI", "open webui", "Open-WebUI", "OpenWebUI", etc.
    result = re.sub(
        r"\bOpen[\s\-]?WebUI\b", BRAND_NAME, value, flags=re.IGNORECASE
    )

    # 2. Replace standalone "WebUI" (CASE-SENSITIVE — avoids touching "webui.sh" etc.)
    #    Matches: "WebUI" but NOT lowercase "webui" (commands/filenames)
    result = re.sub(r"\bWebUI\b", BRAND_NAME, result)

    return result


def process_file(filepath: Path, dry_run: bool = False) -> tuple[bool, int]:
    """Process a single translation file. Returns (modified, change_count)."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    changes = 0
    for key in data:
        new_value = replace_brand_in_value(data[key])
        if new_value != data[key]:
            if dry_run:
                print(f'    [{key}]: "{data[key]}" -> "{new_value}"')
            data[key] = new_value
            changes += 1

    if changes > 0 and not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent="\t")
            f.write("\n")

    return changes > 0, changes


def main():
    dry_run = "--dry-run" in sys.argv

    if not LOCALES_DIR.is_dir():
        print(f"Error: {LOCALES_DIR} not found. Run from project root.")
        sys.exit(1)

    if dry_run:
        print("=== DRY RUN (no files will be modified) ===\n")

    total_modified = 0
    total_changes = 0

    for locale_dir in sorted(LOCALES_DIR.iterdir()):
        filepath = locale_dir / "translation.json"
        if not filepath.is_file():
            continue

        modified, changes = process_file(filepath, dry_run)
        if modified:
            print(f"  + {locale_dir.name}: {changes} replacement(s)")
            total_modified += 1
            total_changes += changes

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Summary: {total_changes} replacements across {total_modified} files")


if __name__ == "__main__":
    main()
