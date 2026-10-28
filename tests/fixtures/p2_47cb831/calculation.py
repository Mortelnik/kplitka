"""Р2.4: расчёт — Decimal, скидки (D-01..D-03), НДС по ставке позиции, явные точки округления."""
"""Р2.4: расчёт — Decimal, скидки (D-01..D-03), НДС по ставке позиции, явные точки округления."""
import math
from decimal import ROUND_HALF_UP, Decimal


def calculate_offer(product_id, quantity_tons, catalog, prices, rules, client_tenure_years=0, requested_discount=0):
    product = catalog.get(product_id)
    price_info = prices.get(product_id)
    
    if not product:
        return "Ошибка: Продукт не найден в каталоге"
    if not price_info:
        return "Ошибка: Для продукта нет цены в прайсе"

    quantity = Decimal(str(quantity_tons))
    price_per_ton = Decimal(price_info['unit_price_rub_per_t'])
    tax_rate = Decimal(price_info['tax_rate'])
    capacity = Decimal(product['container_capacity_tons'])

    containers = math.floor(quantity / capacity) 
    pickup_tons = quantity - (containers * capacity)
    base_amount = price_per_ton * quantity
    
    applicable_discounts = []

    if containers == 0:
        applied_rule = "Мелкий опт (скидки не предусмотрены)"
        discount_percent = Decimal(0)
    else:
        for rule in rules['discounts']['rules']:
            rule_type = rule.get('type')
            rule_id = rule.get('id')
            
            if 'percent' not in rule or not isinstance(rule['percent'], (int, float)):
                continue
                
            percent = Decimal(str(rule['percent'])) / Decimal(100)
            
            if percent > 0:
                # Объединили if, чтобы Lint был доволен
                if rule_type == 'volume_containers' and containers >= 5:
                    applicable_discounts.append((percent, f"{rule_id} (от 5 контейнеров)"))
                elif rule_type == 'loyalty' and client_tenure_years >= 1:
                    applicable_discounts.append((percent, f"{rule_id} (стаж от 1 года)"))

        if applicable_discounts:
            applicable_discounts.sort(key=lambda x: x[0], reverse=True)
            discount_percent, applied_rule = applicable_discounts[0]
        else:
            discount_percent = Decimal(0)
            applied_rule = "Без скидки"

    req_disc_decimal = Decimal(str(requested_discount)) / Decimal(100)
    if req_disc_decimal > discount_percent:
        return f"Ошибка: Запрошенная скидка {requested_discount}% превышает допустимый лимит ({discount_percent * 100}%)"

    discount_amount = base_amount * discount_percent
    amount_after_discount = base_amount - discount_amount
    tax_amount = amount_after_discount * tax_rate
    total = amount_after_discount + tax_amount

    def round_money(value):
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        "product": product['name'],
        "product_source": product['source_ref'],
        "price_source": price_info['source_ref'],
        "containers": containers,
        "pickup_tons": float(pickup_tons),
        "base_amount": round_money(base_amount),
        "discount_rule": applied_rule,
        "discount_amount": round_money(discount_amount),
        "tax": round_money(tax_amount),
        "total": round_money(total)
    }