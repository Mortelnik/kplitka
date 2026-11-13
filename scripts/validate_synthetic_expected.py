"""Массовая сверка эталонных расчетов с движком P2.

Запуск из корня проекта:
    python scripts/validate_synthetic_expected.py

Скрипт не изменяет исходные CSV, JSON и код P2.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "synthetic_fish"

sys.path.insert(0, str(ROOT / "src"))

from kp_plugin.engine.calculation import calculate_offer

MONEY_FIELDS = {
    "base_rub": "base_amount",
    "discount_rub": "discount_amount",
    "vat_rub": "tax",
    "line_total_rub": "total",
}


def load_csv(filename):
    path = PROFILE / filename

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def decimal_value(value):
    return Decimal(
        str(value)
        .strip()
        .replace(" ", "")
        .replace(",", ".")
    )


def full_years(start, end):
    """Количество полных лет сотрудничества."""

    if not start or not end:
        return 0

    start_date = date.fromisoformat(start[:10])
    end_date = date.fromisoformat(end[:10])

    years = end_date.year - start_date.year

    if (end_date.month, end_date.day) < (
        start_date.month,
        start_date.day,
    ):
        years -= 1

    return max(0, years)


def has_seasonal_discount(scenario, lines):
    """Выявить сценарии D-03, не поддерживаемые P2."""

    values = [
        scenario.get("expected_behavior", ""),
        scenario.get("notes", ""),
        scenario.get("test_type", ""),
    ]

    for line in lines:
        values.append(line.get("discount_rule", ""))
        values.append(line.get("applied_rule", ""))

    text = " ".join(str(value) for value in values).lower()

    return (
        "d-03" in text
        or "d03" in text
        or "сезонн" in text
    )


def main():
    # 1. Загружаем исходные данные

    scenarios = load_csv("scenarios_dev.csv")
    expected = load_csv("expected_dev.csv")
    catalog_rows = load_csv("catalog_v8.csv")
    price_rows = load_csv("prices_v8.csv")
    customers = load_csv("customers_v8.csv")

    with (PROFILE / "rules_v8.json").open(
        encoding="utf-8-sig"
    ) as file:
        rules = json.load(file)

    # 2. Формируем справочники

    catalog = {
        row["product_id"]: row
        for row in catalog_rows
    }

    prices = {
        row["product_id"]: row
        for row in price_rows
    }

    customers_by_id = {
        row["customer_id"]: row
        for row in customers
    }

    lines_by_sid = defaultdict(list)

    for line in expected:
        sid = line["scenario_id"]
        lines_by_sid[sid].append(line)

    # 3. Начинаем проверку

    print("=" * 65)
    print("МАССОВАЯ СВЕРКА ЭТАЛОНОВ С ДВИЖКОМ P2")
    print("=" * 65)

    print("Сценариев:", len(scenarios))
    print("Эталонных строк:", len(expected))
    print("Товаров:", len(catalog))
    print("Цен:", len(prices))
    print("Клиентов:", len(customers_by_id))

    print("-" * 65)

    counts = Counter()
    failures = []
    skipped = []

    # 4. Перебираем сценарии

    for scenario in scenarios:

        sid = scenario["scenario_id"]

        status = scenario.get(
            "expected_validation_status", ""
        ).strip().upper()

        lines = lines_by_sid.get(sid, [])

        # Не проверяем невалидные сценарии

        if status != "VALID":
            counts["not_valid"] += 1

            skipped.append(
                (sid, f"Статус: {status}")
            )
            continue

        counts["valid"] += 1

        # P2 пока поддерживает одну товарную позицию

        if len(lines) != 1:
            counts["multi_or_missing"] += 1

            skipped.append(
                (
                    sid,
                    f"Товарных строк: {len(lines)}"
                )
            )

            continue

        # D-03 пока не реализована в P2

        if has_seasonal_discount(scenario, lines):
            counts["seasonal"] += 1

            skipped.append(
                (sid, "Сезонная скидка D-03")
            )
            continue

        line = lines[0]

        product_id = line.get("product_id", "")

        if (
            product_id not in catalog
            or product_id not in prices
        ):
            counts["errors"] += 1

            failures.append(
                (
                    sid,
                    f"Нет товара или цены: {product_id}"
                )
            )
            continue

        # 5. Определяем стаж клиента

        customer = customers_by_id.get(
            scenario.get("customer_id", "")
        )

        try:
            years = full_years(
                customer.get(
                    "cooperation_start_date", ""
                ) if customer else "",
                scenario.get("order_date", ""),
            )

            quantity = decimal_value(
                line["quantity_t"]
            )

            # 6. Вызываем настоящий движок P2

            actual = calculate_offer(
                product_id=product_id,
                quantity_tons=quantity,
                catalog=catalog,
                prices=prices,
                rules=rules,
                client_tenure_years=years,
            )

        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            counts["errors"] += 1

            
            failures.append(
    (
        sid,
        f"Ошибка P2: {type(exc).__name__}: {exc}",
    )
)
            continue

        if not isinstance(actual, dict):
            counts["errors"] += 1

            failures.append(
                (sid, f"Неожиданный ответ P2: {actual}")
            )
            continue

        if "Ошибка" in actual:
            counts["errors"] += 1

            failures.append(
                (sid, str(actual["Ошибка"]))
            )
            continue

        # 7. Сравниваем денежные показатели

        differences = []

        for expected_key, actual_key in MONEY_FIELDS.items():

            raw = line.get(expected_key, "")

            if not str(raw).strip():
                differences.append(
                    f"{expected_key}: нет значения"
                )
                continue

            try:
                target = decimal_value(raw).quantize(
                    Decimal("0.01")
                )

                received = decimal_value(
                    actual[actual_key]
                ).quantize(
                    Decimal("0.01")
                )

            except (
                KeyError,
                ValueError,
                TypeError,
                InvalidOperation,
            ) as exc:
                differences.append(
                    f"{expected_key}: ошибка {exc}"
                )
                continue

            if target != received:
                differences.append(
                    f"{expected_key}: "
                    f"эталон={target}, "
                    f"P2={received}"
                )

        # 8. Проверяем контейнеры и самовывоз

        try:
            capacity = decimal_value(
                catalog[product_id][
                    "container_capacity_tons"
                ]
            )

            expected_containers = int(
                quantity // capacity
            )

            expected_pickup = (
                quantity
                - Decimal(expected_containers) * capacity
            )

            actual_containers = int(
                actual["containers"]
            )

            actual_pickup = decimal_value(
                actual["pickup_tons"]
            )

            if actual_containers != expected_containers:
                differences.append(
                    "containers: "
f"эталон={expected_containers}, "
                    f"P2={actual_containers}"
                )

            if actual_pickup != expected_pickup:
                differences.append(
                    "pickup_tons: "
                    f"эталон={expected_pickup}, "
                    f"P2={actual_pickup}"
                )

        except (
            KeyError,
            ValueError,
            TypeError,
            InvalidOperation,
        ) as exc:
            differences.append(
                f"Ошибка проверки контейнеров: {exc}"
            )

        # 9. Записываем результат проверки

        if differences:
            counts["mismatch"] += 1

            failures.append(
                (sid, "; ".join(differences))
            )

        else:
            counts["match"] += 1

    # 10. Итоговый отчет

    print()
    print("=" * 65)
    print("РЕЗУЛЬТАТЫ ПРОВЕРКИ")
    print("=" * 65)

    print(
        "VALID-сценариев:",
        counts["valid"]
    )

    print(
        "Совпали с P2:",
        counts["match"]
    )

    print(
        "Расхождения:",
        counts["mismatch"]
    )

    print(
        "Ошибки проверки/P2:",
        counts["errors"]
    )

    print(
        "Пропущены (много товаров или нет строк):",
        counts["multi_or_missing"]
    )

    print(
        "Пропущены (D-03):",
        counts["seasonal"]
    )

    print(
        "Пропущены (не VALID):",
        counts["not_valid"]
    )

    # 11. Выводим расхождения

    if failures:
        print()
        print("=" * 65)
        print("РАСХОЖДЕНИЯ И ОШИБКИ")
        print("=" * 65)

        for sid, reason in failures:
            print(f"{sid}: {reason}")

    # 12. Выводим пропущенные сценарии

    if skipped:
        print()
        print("=" * 65)
        print("ПРОПУЩЕННЫЕ СЦЕНАРИИ")
        print("=" * 65)

        for sid, reason in skipped:
            print(f"{sid}: {reason}")

    print()
    print("Исходные CSV и движок P2 не изменены.")

    if counts["mismatch"] or counts["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
