"""Synchronize scenario totals with independently recalculated expected lines."""

import csv
import shutil
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BASE = Path("profiles/synthetic_fish")
SCENARIOS = BASE / "scenarios_dev.csv"
EXPECTED = BASE / "expected_dev.csv"
BACKUP = BASE / "scenarios_dev_before_sync.csv"

ZERO = Decimal(0)
CENT = Decimal("0.01")


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def money(value):
    return f"{value.quantize(CENT):.2f}"


def decimal_value(value):
    return Decimal(str(value or "0"))


def main():
    fields, scenarios = load_csv(SCENARIOS)
    _, expected = load_csv(EXPECTED)

    lines_by_scenario = defaultdict(list)

    for line in expected:
        lines_by_scenario[line["scenario_id"]].append(line)

    required = {
        "goods_before_discount_rub",
        "goods_discount_rub",
        "goods_vat_rub",
        "goods_after_discount_vat_rub",
        "delivery_surcharge_rub",
        "grand_total_rub",
        "container_count",
        "underfilled_container_count",
        "delivery_status",
        "notes",
    }

    missing = required - set(fields)
    if missing:
        raise ValueError(f"Missing scenario columns: {sorted(missing)}")

    updated = 0
    skipped = defaultdict(int)
    errors = []

    for scenario in scenarios:
        sid = scenario["scenario_id"]
        status = scenario["expected_validation_status"]
        lines = lines_by_scenario[sid]

        if status != "VALID":
            skipped[status] += 1
            continue

        if not lines:
            errors.append(f"{sid}: no expected lines")
            continue

        # Seasonal D-03 requires separate integration and verification.
        if "D-03" in (scenario.get("notes") or ""):
            skipped["D-03"] += 1
            continue

        # Only update rows whose independent monetary expectations exist.
        try:
            base = sum(
                decimal_value(line["base_rub"])
                for line in lines
            )
            discount = sum(
                decimal_value(line["discount_rub"])
                for line in lines
            )
            vat = sum(
                decimal_value(line["vat_rub"])
                for line in lines
            )
            total = base - discount + vat

            if any(
                line.get("validation_status") != "VALID"
                for line in lines
            ):
                skipped["NON_VALID_LINE"] += 1
                continue

        except (KeyError, ValueError, ArithmeticError) as exc:
            errors.append(f"{sid}: {exc}")
            continue

        scenario["goods_before_discount_rub"] = money(base)
        scenario["goods_discount_rub"] = money(discount)
        scenario["goods_vat_rub"] = money(vat)
        scenario["goods_after_discount_vat_rub"] = money(total)
        scenario["delivery_surcharge_rub"] = "0.00"
        scenario["grand_total_rub"] = money(total)
        scenario["underfilled_container_count"] = "0"
        scenario["delivery_status"] = "NO_SURCHARGE"

        # Container count is left unchanged here: it must be recalculated
        # from SKU-specific capacities, not inferred from monetary fields.
        scenario["notes"] = (
            "Учебная демонстрационная модель. "
            "Доплата за неполный контейнер не применяется. "
            "Остаток сверх полных контейнеров — самовывоз. "
            "Скидки не суммируются; применяется максимальная допустимая."
        )

        updated += 1

    if errors:
        print("Synchronization stopped; no files changed.")
        for error in errors:
            print("ERROR:", error)
        raise SystemExit(1)

    if not BACKUP.exists():
        shutil.copy2(SCENARIOS, BACKUP)

    with SCENARIOS.open(
        "w", encoding="utf-8-sig", newline=""
        ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(scenarios)

    print("SYNCHRONIZATION COMPLETED")
    print("Scenarios:", len(scenarios))
    print("Updated:", updated)
    print("Skipped:", dict(skipped))
    print("Errors:", len(errors))
    print("Backup:", BACKUP)
    print("Engine P2 was not modified.")


if __name__ == "__main__":
    main()