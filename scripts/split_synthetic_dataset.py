import csv
from pathlib import Path

BASE = Path("profiles/synthetic_fish")


def read_csv(filename):
    with (BASE / filename).open(
        "r", encoding="utf-8-sig", newline=""
    ) as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_csv(filename, columns, rows):
    with (BASE / filename).open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


scenario_cols, scenarios = read_csv("scenarios_v8.csv")
expected_cols, expected = read_csv("expected_lines_v8.csv")

dev = [
    row for row in scenarios
    if row["dataset_split"].strip().lower() == "development"
]

holdout = [
    row for row in scenarios
    if row["dataset_split"].strip().lower() == "holdout"
]

assert len(scenarios) == 80, "Ожидалось 80 сценариев"
assert len(dev) == 65, "Ожидалось 65 development"
assert len(holdout) == 15, "Ожидалось 15 holdout"

dev_ids = {row["scenario_id"] for row in dev}
holdout_ids = {row["scenario_id"] for row in holdout}

assert dev_ids.isdisjoint(holdout_ids)

expected_dev = [
    row for row in expected
    if row["scenario_id"] in dev_ids
]

expected_holdout = [
    row for row in expected
    if row["scenario_id"] in holdout_ids
]

assert len(expected_dev) + len(expected_holdout) == len(expected), (
    "Есть эталонные строки без соответствующего сценария"
)

def needs_identity(row):
    return row["identity_test_case"].strip().upper() in {
        "YES", "TRUE", "1"
    }


assert sum(map(needs_identity, dev)) == 6
assert sum(map(needs_identity, holdout)) == 3

write_csv("scenarios_dev.csv", scenario_cols, dev)
write_csv("expected_dev.csv", expected_cols, expected_dev)

# Holdout сохраняем отдельно, вне репозитория.
private_dir = BASE.resolve().parent.parent.parent / "synthetic_holdout_private"
private_dir.mkdir(exist_ok=True)

def write_private(filename, columns, rows):
    with (private_dir / filename).open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

write_private("scenarios_holdout.csv", scenario_cols, holdout)
write_private("expected_holdout.csv", expected_cols, expected_holdout)

print("Development:", len(dev))
print("Holdout:", len(holdout))
print("Development expected lines:", len(expected_dev))
print("Holdout expected lines:", len(expected_holdout))
print("Holdout folder:", private_dir)