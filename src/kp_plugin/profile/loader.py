"""Р2.1: загрузка профиля компании (catalog/price/rules/stock) из папки profiles/<name>."""
import csv
import json


def load_catalog(filepath):
    catalog = {}
    with open(filepath, mode='r', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        for row in reader:
            catalog[row['product_id']] = row
    return catalog

def load_prices(filepath):
    prices = {}
    with open(filepath, mode='r', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        for row in reader:
            prices[row['product_id']] = row
    return prices

def load_rules(filepath):
    with open(filepath, mode='r', encoding='utf-8') as file:
        return json.load(file)