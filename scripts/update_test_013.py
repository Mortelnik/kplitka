import csv
import shutil
from decimal import Decimal
from pathlib import Path

BASE = Path("profiles/synthetic_fish")
SID = "TEST-013"

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)

def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

scenario_path = BASE / "scenarios_dev.csv"
expected_path = BASE / "expected_dev.csv"

s_fields, scenarios = read_csv(scenario_path)
e_fields, expected = read_csv(expected_path)

scenario_rows = [r for r in scenarios if r["scenario_id"] == SID]
expected_rows = [r for r in expected if r["scenario_id"] == SID]

assert len(scenario_rows) == 1
assert len(expected_rows) == 1

# Резервные копии
for path in (scenario_path, expected_path):
    shutil.copy2(path, path.with_suffix(".csv.bak"))

base = Decimal(130) * Decimal(140000)
discount = base * Decimal("0.05")
vat = (base - discount) * Decimal("0.10")
total = base - discount + vat

s = scenario_rows[0]
s.update({
    "test_type": "Граница скидки D-02",
    "customer_request": (
        "Добрый день! Это ООО «Океанские поставки», "
        "ИНН TEST-INN-0008. Хотим заказать "
        "130 т скумбрии FISH-013. "
        "Рассчитайте КП с учетом наших условий."
    ),
    "expected_validation_status": "VALID",
    "expected_error_code": "OK",
    "total_order_t": "130",
    "goods_before_discount_rub": f"{base:.2f}",
    "goods_discount_rub": f"{discount:.2f}",
    "goods_vat_rub": f"{vat:.2f}",
    "goods_after_discount_vat_rub": f"{total:.2f}",
    "container_count": "5",
    "underfilled_container_count": "0",
    "delivery_surcharge_rub": "0.00",
    "grand_total_rub": f"{total:.2f}",
    "loyalty_pct": "2",
    "volume_pct": "5",
    "delivery_status": "NO_SURCHARGE",
    "notes": (
        "Граничный тест D-02: ровно 5 контейнеров. "
        "D-01=2%, D-02=5%. Применяется только D-02. "
        "Остаток на складе 160 т."
    ),
})

e = expected_rows[0]
e.update({
    "product_id": "FISH-013",
    "product_name": "Скумбрия с/м НРГ 300+",
    "quantity_t": "130",
    "available_qty_t": "160",
    "unit_price_rub_t": "140000",
    "loyalty_pct": "2",
    "volume_pct": "5",
    "applied_discount_pct": "5",
    "validation_status": "VALID",
    "error_code": "OK",
    "base_rub": f"{base:.2f}",
    "discount_rub": f"{discount:.2f}",
    "vat_rub": f"{vat:.2f}",
    "line_total_rub": f"{total:.2f}",
})

write_csv(scenario_path, s_fields, scenarios)
write_csv(expected_path, e_fields, expected)

print("TEST-013 обновлен")
print("Контейнеров: 5")
print("Скидка D-02: 5%")
print("Итого:", total)
print("Сценариев:", len(scenarios))
print("Товарных строк:", len(expected))