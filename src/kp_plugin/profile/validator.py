"""Р2.2: валидация профиля — структура, связи, полнота; отчёт всех ошибок сразу."""
def validate_profile(catalog, prices, rules):
    errors = []
    for product_id in catalog:
        if product_id not in prices:
            errors.append(f"Для продукта {product_id} нет цены в прайсе!")
            
    for rule in rules.get('discounts', {}).get('rules', []):
        rule_id = rule.get('id', 'Неизвестное правило')
        if 'percent' in rule:
            if not isinstance(rule['percent'], (int, float)):
                errors.append(f"В правиле {rule_id} процент должен быть числом, а не '{rule['percent']}'")
        elif rule.get('type') in ['volume_containers', 'seasonal_line_clearance', 'loyalty']:
            errors.append(f"В правиле {rule_id} не задан процент (поле 'percent')")
    return errors