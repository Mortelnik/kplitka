"""Independent recalculation of synthetic expected results.

Run:
    python scripts/recalculate_synthetic_expected.py

No P2 engine imports. Uses Decimal and ROUND_HALF_UP.
"""

import csv
import shutil
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "profiles" / "synthetic_fish"
CENT = Decimal("0.01")


def load_csv(filename):
    with (BASE_DIR / filename).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def save_csv(filename, columns, rows):
    with (BASE_DIR / filename).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def number(value):
    return Decimal(str(value).strip().replace(",", "."))


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def full_years(start_date, order_date):
    if not start_date or not order_date:
        return 0

    start = date.fromisoformat(start_date[:10])
    order = date.fromisoformat(order_date[:10])

    years = order.year - start.year

    if (order.month, order.day) < (start.month, start.day):
        years -= 1

    return max(years, 0)


def calculate_containers(lines, catalog):
    total = 0
    pickup = Decimal(0)

    for line in lines:
        product = catalog[line["product_id"]]

        quantity = number(line["quantity_t"])
        capacity = number(product["container_capacity_tons"])

        containers = int(quantity // capacity)

        total += containers
        pickup += quantity - Decimal(containers) * capacity

    return total, pickup


def select_discount(years, containers):
    """Best discount, without stacking."""

    if containers == 0:
        return "SMALL_WHOLESALE", 0

    if containers >= 5:
        return "D-02", 5

    if years >= 1:
        return "D-01", 2

    return "NO_DISCOUNT", 0


def calculate_money(
    quantity_t,
    unit_price,
    tax_rate,
    discount_pct,
):
    quantity = number(quantity_t)
    price = number(unit_price)
    tax = number(tax_rate)

    base = quantity * price

    discount = money(base * Decimal(discount_pct) / 100)

    after_discount = base - discount

    vat = money(after_discount * tax)

    total = money(after_discount + vat)

    return {
        "base_rub": money(base),
        "discount_rub": discount,
        "vat_rub": vat,
        "line_total_rub": total,
    }


def is_seasonal(scenario, lines):
    texts = [
        scenario.get("test_type", ""),
        scenario.get("notes", ""),
        scenario.get("expected_behavior", ""),
    ]

    for line in lines:
        texts.extend(
            [
                line.get("discount_rule", ""),
                line.get("applied_rule", ""),
            ]
        )

    combined = " ".join(texts).lower()

    return "d-03" in combined or "d03" in combined or "сезонн" in combined


def set_if_exists(row, key, value):
    if key in row:
        row[key] = str(value)


def main():
    _, customers = load_csv("customers_v8.csv")
    _, catalog_rows = load_csv("catalog_v8.csv")
    _, price_rows = load_csv("prices_v8.csv")

    scenario_columns, scenarios = load_csv("scenarios_dev.csv")

    expected_columns, expected = load_csv("expected_dev.csv")

    customers_by_id = {row["customer_id"]: row for row in customers}

    catalog = {row["product_id"]: row for row in catalog_rows}

    prices = {row["product_id"]: row for row in price_rows}

    lines_by_sid = defaultdict(list)

    for line in expected:
        lines_by_sid[line["scenario_id"]].append(line)

    # Backup both files before changing anything.
    for filename in (
        "scenarios_dev.csv",
        "expected_dev.csv",
    ):
        original = BASE_DIR / filename
        backup = BASE_DIR / (original.stem + "_before_recalc.csv")

        if not backup.exists():
            shutil.copy2(original, backup)

    counts = Counter()
    examples = []

    for scenario in scenarios:
        sid = scenario["scenario_id"]

        if scenario.get("expected_validation_status", "").strip().upper() != "VALID":
            counts["not_valid"] += 1
            continue

        lines = lines_by_sid.get(sid, [])

        if not lines:
            counts["missing_lines"] += 1
            continue

        if is_seasonal(scenario, lines):
            counts["seasonal"] += 1
            continue

        customer = customers_by_id.get(scenario.get("customer_id", ""))

        years = (
            full_years(
                customer.get("cooperation_start_date", ""),
                scenario["order_date"],
            )
            if customer
            else 0
        )

        containers, _pickup = calculate_containers(lines, catalog)

        rule, discount_pct = select_discount(years, containers)

        base_sum = Decimal(0)
        discount_sum = Decimal(0)
        vat_sum = Decimal(0)
        total_sum = Decimal(0)

        for line in lines:
            product_id = line["product_id"]
            price = prices[product_id]

            result = calculate_money(
                quantity_t=line["quantity_t"],
                unit_price=price["unit_price_rub_per_t"],
                tax_rate=price["tax_rate"],
                discount_pct=discount_pct,
            )

            # Update line-level expectations.
            for key, value in result.items():
                set_if_exists(line, key, f"{value:.2f}")

            set_if_exists(line, "loyalty_pct", 2 if years >= 1 else 0)

            set_if_exists(line, "volume_pct", 5 if containers >= 5 else 0)

            set_if_exists(line, "applied_discount_pct", discount_pct)

            set_if_exists(line, "discount_rule", rule)

            base_sum += result["base_rub"]
            discount_sum += result["discount_rub"]
            vat_sum += result["vat_rub"]
            total_sum += result["line_total_rub"]

        # Update scenario-level totals.
        set_if_exists(scenario, "goods_before_discount_rub", f"{base_sum:.2f}")

        set_if_exists(scenario, "goods_discount_rub", f"{discount_sum:.2f}")

        set_if_exists(scenario, "goods_vat_rub", f"{vat_sum:.2f}")

        set_if_exists(scenario, "goods_after_discount_vat_rub", f"{total_sum:.2f}")

        set_if_exists(scenario, "container_count", containers)

        set_if_exists(scenario, "underfilled_container_count", 0)

        set_if_exists(scenario, "delivery_surcharge_rub", "0.00")

        set_if_exists(scenario, "delivery_status", "NO_SURCHARGE")

        set_if_exists(scenario, "loyalty_pct", 2 if years >= 1 else 0)

        set_if_exists(scenario, "volume_pct", 5 if containers >= 5 else 0)

        set_if_exists(scenario, "grand_total_rub", f"{total_sum:.2f}")

        counts["recalculated"] += 1
        counts[rule] += 1

        if len(examples) < 10:
            examples.append(
                (
                    sid,
                    containers,
                    rule,
                    discount_pct,
                    f"{total_sum:.2f}",
                )
            )

    save_csv(
        "expected_dev.csv",
        expected_columns,
        expected,
    )

    save_csv(
        "scenarios_dev.csv",
        scenario_columns,
        scenarios,
    )

    print("=" * 60)
    print("INDEPENDENT RECALCULATION COMPLETED")
    print("=" * 60)

    print("Scenarios:", len(scenarios))
    print("Expected lines:", len(expected))

    print("Recalculated:", counts["recalculated"])

    print("Skipped D-03:", counts["seasonal"])

    print("Skipped non-VALID:", counts["not_valid"])

    print("Missing lines:", counts["missing_lines"])

    print("\nDiscount coverage:")

    for rule in (
        "SMALL_WHOLESALE",
        "NO_DISCOUNT",
        "D-01",
        "D-02",
    ):
        print(rule, counts[rule])

    print("\nExamples:")

    for sid, containers, rule, pct, total in examples:
        print(
            sid,
            "| containers:",
            containers,
            "| rule:",
            rule,
            "| discount:",
            pct,
            "| total:",
            total,
        )

    print("\nBackups created if absent.")
    print("Original column structure preserved.")


if __name__ == "__main__":
    main()
