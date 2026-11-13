"""Audit and safely clean obsolete synthetic dataset descriptions."""

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path("profiles/synthetic_fish")
FILES = ["scenarios_dev.csv", "expected_dev.csv"]

TEXT_FIELDS = {
    "customer_request",
    "expected_behavior",
    "notes",
}

OBSOLETE_PATTERNS = [
    r"доплат[а-яё\s+]*50\s*000\s*руб",
    r"50\s*000\s*руб[а-яё\s]*за\s*(?:неполный|недогруженный)\s*контейнер",
    r"скидк[а-яё\s]*суммир[а-яё]*",
    r"сумм[а-яё\s]*скид[а-яё]*",
    r"скидк[а-яё\s]*за\s*предзаказ",
    r"предзаказ[а-яё\s]*скидк[а-яё]*",
    r"лимит[а-яё\s]*скид[а-яё]*",
    r"потолок[а-яё\s]*скид[а-яё]*",
]

# Delete a sentence only when it explicitly contains an obsolete claim.
# Other text is left untouched and reported for review.
def clean_text(value):
    if not value:
        return value, []

    parts = re.split(r"(?<=[.!?])\s+", value)
    kept = []
    removed = []

    for part in parts:
        matches = [
            pattern for pattern in OBSOLETE_PATTERNS
            if re.search(pattern, part, flags=re.IGNORECASE)
        ]

        if matches:
            removed.append(part)
        else:
            kept.append(part)

    return " ".join(kept).strip(), removed


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BASE / f"backup_before_cleanup_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    total_changes = 0

    for filename in FILES:
        path = BASE / filename

        if not path.exists():
            print(f"NOT FOUND: {path}")
            continue

        shutil.copy2(path, backup_dir / filename)

        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            rows = list(reader)

        changes = []

        for row in rows:
            sid = row.get("scenario_id", "?")

            for field in TEXT_FIELDS.intersection(fields):
                original = row.get(field, "")
                cleaned, removed = clean_text(original)

                if removed:
                    row[field] = cleaned
                    changes.append((sid, field, removed))

        if changes:
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

        print(f"\n{filename}: {len(rows)} rows")
        print(f"Changed text fields: {len(changes)}")

        for sid, field, removed in changes:
            print(f"  {sid} | {field}")
            for sentence in removed:
                print(f"    REMOVED: {sentence}")

        total_changes += len(changes)

    print("\nCLEANUP COMPLETED")
    print(f"Total changed text fields: {total_changes}")
    print(f"Backups: {backup_dir}")
    print("Numeric fields, statuses and line items were not edited.")


if __name__ == "__main__":
    main()