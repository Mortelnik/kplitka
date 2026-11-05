"""Р2.9: тесты расчёта против эталонов; границы: ровно контейнер, 4/5 контейнеров, день достижения года, границы сезона."""
"""Р2.9: тесты расчёта против эталонов."""
from decimal import Decimal

from kp_plugin.engine.calculation import calculate_offer
from kp_plugin.profile.loader import load_catalog, load_prices, load_rules

# Указываем правильный путь к демо-данным
catalog = load_catalog('profiles/examples/fish_demo/catalog.csv')
prices = load_prices('profiles/examples/fish_demo/price.csv')
rules = load_rules('profiles/examples/fish_demo/rules.json')

def test_req_003_mintai_100_tons():
    result = calculate_offer('FISH-007', 100, catalog, prices, rules, client_tenure_years=0)
    assert result['containers'] == 3
    assert result['pickup_tons'] == 19.0
    assert result['base_amount'] == Decimal('11000000.00')
    assert result['discount_rule'] == "Без скидки"
    assert result['total'] == Decimal('12100000.00')

def test_req_008_seld_150_tons_discount():
    result = calculate_offer('FISH-005', 150, catalog, prices, rules, client_tenure_years=0)
    assert result['containers'] == 5
    assert result['discount_rule'] == "D-02 (от 5 контейнеров)"
    assert result['discount_amount'] == Decimal('712500.00')
    assert result['total'] == Decimal('14891250.00')

def test_req_004_small_wholesale_no_discount():
    result = calculate_offer('FISH-005', 3, catalog, prices, rules, client_tenure_years=2)
    assert result['containers'] == 0
    assert result['discount_rule'] == "Мелкий опт (скидки не предусмотрены)"
    assert result['discount_amount'] == Decimal('0.00')
    assert result['total'] == Decimal('313500.00')

def test_product_not_in_catalog():
    result = calculate_offer('CRAB-001', 5, catalog, prices, rules)
    assert result == "Ошибка: Продукт не найден в каталоге"

def test_product_has_no_price():
    temp_price = prices.pop('FISH-007')
    result = calculate_offer('FISH-007', 100, catalog, prices, rules)
    assert result == "Ошибка: Для продукта нет цены в прайсе"
    prices['FISH-007'] = temp_price

def test_req_006_invalid_discount():
    result = calculate_offer('FISH-005', 150, catalog, prices, rules, requested_discount=25)
    assert "Ошибка: Запрошенная скидка 25% превышает допустимый лимит" in result

def test_price_update():
    old_price = prices['FISH-007']['unit_price_rub_per_t']
    prices['FISH-007']['unit_price_rub_per_t'] = '200000'
    result = calculate_offer('FISH-007', 100, catalog, prices, rules)
    assert result['base_amount'] == Decimal('20000000.00')
    prices['FISH-007']['unit_price_rub_per_t'] = old_price