"""Read-only adapter for P4 catalog.csv/warehouse_stock.csv, not a rules engine.

Raw fields and batch diagnostics live beside the unchanged selection models.
File hashes identify the exact input version. A source_ref is provenance, not
proof of commercial availability. Synthetic/unknown data is never promoted.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from kp_plugin.llm.selection import CatalogProduct, SelectionSource

CATALOG_FIELDS = {"product_id", "name", "unit", "min_qty", "max_qty", "status", "source_ref",
                  "description", "category", "related_cases", "is_fictional"}
STOCK_FIELDS = {"line_id", "product_id", "stock_tons", "batch", "actual_date", "status", "source_ref", "is_fictional"}


class P4DataError(ValueError):
    """Malformed structure or ambiguous identifiers; no partial catalog is returned."""


@dataclass(frozen=True)
class P4Row:
    line: int
    fields: tuple[tuple[str, str], ...]
    source: SelectionSource
    issues: tuple[str, ...]


@dataclass(frozen=True)
class P4Catalog:
    products: tuple[CatalogProduct, ...]
    catalog_rows: tuple[P4Row, ...]
    stock_rows: tuple[P4Row, ...]


def _read(path: Path, required: set[str]) -> tuple[list[tuple[int, dict[str, str]]], str]:
    data = path.read_bytes()
    version = "sha256:" + hashlib.sha256(data).hexdigest()
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = reader.fieldnames
        if not header or len(set(header)) != len(header) or not required <= set(header):
            raise P4DataError(f"{path.name}: missing or duplicate CSV headers")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise P4DataError(f"{path.name}:{reader.line_num}: inconsistent column count")
            rows.append((reader.line_num, row))
        return rows, version
    except (UnicodeError, csv.Error) as exc:
        raise P4DataError(f"{path.name}: invalid UTF-8/CSV") from exc


def _amount(raw: str, label: str) -> Decimal | None:
    if not raw.strip():
        return None
    try:
        amount = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise P4DataError(f"Invalid decimal in {label}") from exc
    if not amount.is_finite() or amount < 0:
        raise P4DataError(f"Non-finite or negative amount in {label}")
    return amount


def _source(path: Path, version: str, line: int, row: dict[str, str]) -> SelectionSource:
    return SelectionSource(source_id=row["source_ref"].strip() or path.name, version=version,
                           locator=f"{path.name}:line={line}")


def _base_issues(row: dict[str, str]) -> list[str]:
    issues = []
    if not row["source_ref"].strip():
        issues.append("missing_source_ref")
    fictional = row["is_fictional"].strip().casefold()
    if fictional != "нет":
        issues.append("synthetic" if fictional == "да" else "unconfirmed_origin")
    if row["status"].strip() != "active":
        issues.append("inactive")
    return issues


def load_p4_catalog(catalog_path: Path, stock_path: Path, *, as_of: date,
                    max_stock_age_days: int | None = None) -> P4Catalog:
    """Load two explicitly supplied files. No default stock freshness threshold.

    Only non-fictional, active, sourced, dated batches can be aggregated, and only
    with an explicit age policy and catalog unit 'т'. If any batch for a product
    is uncertain, its total remains unknown; known batches are still retained.
    Static constraints remain unknown: min/max alone do not prove all rules.
    """
    if max_stock_age_days is not None and (type(max_stock_age_days) is not int or max_stock_age_days < 0):
        raise ValueError("max_stock_age_days must be a nonnegative integer or None")
    catalog_data, catalog_version = _read(catalog_path, CATALOG_FIELDS)
    stock_data, stock_version = _read(stock_path, STOCK_FIELDS)
    catalog_rows, stock_rows = [], []
    products_by_id = {}
    for line, row in catalog_data:
        identifier = row["product_id"].strip()
        status = row["status"].strip()
        if not identifier or identifier in products_by_id or not row["name"].strip() or status not in {"active", "draft"}:
            raise P4DataError(f"catalog.csv:{line}: invalid identity, status or duplicate product_id")
        issues = _base_issues(row)
        source = _source(catalog_path, catalog_version, line, row)
        minimum = _amount(row["min_qty"], f"catalog:{line}:min_qty")
        maximum = _amount(row["max_qty"], f"catalog:{line}:max_qty")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise P4DataError(f"catalog.csv:{line}: min_qty exceeds max_qty")
        catalog_rows.append(P4Row(line, tuple(row.items()), source, tuple(issues)))
        products_by_id[identifier] = (row, source, minimum, maximum, issues)
    batches: dict[str, list[tuple[Decimal | None, P4Row]]] = {}
    line_ids, batch_ids = set(), set()
    for line, row in stock_data:
        identifier, line_id, batch = (row[key].strip() for key in ("product_id", "line_id", "batch"))
        if not identifier or not line_id or line_id in line_ids or (batch and (identifier, batch) in batch_ids):
            raise P4DataError(f"warehouse_stock.csv:{line}: missing/duplicate line or batch identity")
        line_ids.add(line_id)
        if batch:
            batch_ids.add((identifier, batch))
        issues = _base_issues(row)
        if identifier not in products_by_id:
            issues.append("product_not_in_catalog")
        if not batch:
            issues.append("missing_batch")
        amount = _amount(row["stock_tons"], f"stock:{line}:stock_tons")
        if amount is None:
            issues.append("unknown_quantity")
        try:
            actual = date.fromisoformat(row["actual_date"].strip())
        except ValueError:
            issues.append("missing_or_invalid_actual_date")
        else:
            if actual > as_of:
                issues.append("future_actual_date")
            elif max_stock_age_days is not None and (as_of - actual).days > max_stock_age_days:
                issues.append("stale_stock")
        if max_stock_age_days is None:
            issues.append("freshness_policy_missing")
        record = P4Row(line, tuple(row.items()), _source(stock_path, stock_version, line, row), tuple(issues))
        stock_rows.append(record)
        batches.setdefault(identifier, []).append((amount, record))
    products = []
    for identifier, (row, source, minimum, maximum, issues) in products_by_id.items():
        records = batches.get(identifier, [])
        available = (bool(records) and not issues and row["unit"].strip() == "т"
                     and all(not record.issues and amount is not None for amount, record in records))
        total = None
        if available:
            amounts = [amount for amount, _ in records]
            with localcontext() as context:
                low = min(amount.as_tuple().exponent for amount in amounts)
                high = max(amount.adjusted() for amount in amounts)
                context.prec = max(28, high - low + len(str(len(amounts))) + 2)
                total = sum(amounts, Decimal(0))
        products.append(CatalogProduct(product_id=identifier, name=row["name"], status=row["status"].strip(),
                                       sources=(source,), unit=row["unit"].strip() or None,
                                       min_quantity=minimum, max_quantity=maximum, stock_quantity=total,
                                       stock_sources=tuple(record.source for _, record in records) if available else ()))
    return P4Catalog(tuple(products), tuple(catalog_rows), tuple(stock_rows))
