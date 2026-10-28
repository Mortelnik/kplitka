"""Synthetic P4-schema fixtures; boundary cases edit temporary copies only."""

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds
from kp_plugin.llm.p4_catalog import P4DataError, load_p4_catalog
from kp_plugin.llm.selection import SelectionStatus, select_products

ROOT = Path(__file__).parent / "fixtures/p4_synthetic"
CATALOG = ROOT / "catalog/catalog.csv"
STOCK = ROOT / "prices_stock/warehouse_stock.csv"
AS_OF = date(2026, 10, 28)


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def write(path: Path, data: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(data[0]))
        writer.writeheader()
        writer.writerows(data)


@pytest.fixture
def copies(tmp_path: Path) -> tuple[Path, Path]:
    # Explicit TEST ONLY simulations derive from the committed synthetic fixture.
    catalog, stock = rows(CATALOG)[:1], rows(STOCK)[:1]
    catalog[0]["is_fictional"] = stock[0]["is_fictional"] = "нет"
    a, b = tmp_path / "catalog.csv", tmp_path / "warehouse_stock.csv"
    write(a, catalog)
    write(b, stock)
    return a, b


def test_original_p4_mapping_and_all_fields_preserved() -> None:
    before = CATALOG.read_bytes(), STOCK.read_bytes()
    result = load_p4_catalog(CATALOG, STOCK, as_of=AS_OF)
    assert len(result.products) == len(rows(CATALOG)) == 3
    assert len(result.stock_rows) == len(rows(STOCK))
    for product, record, raw in zip(result.products, result.catalog_rows, rows(CATALOG), strict=True):
        assert product.product_id == raw["product_id"]
        assert product.name == raw["name"]
        assert product.unit == raw["unit"]
        assert product.min_quantity == Decimal(raw["min_qty"])
        assert product.max_quantity is None
        assert product.status == raw["status"]
        assert dict(record.fields) == raw
        assert record.source.source_id == raw["source_ref"]
        assert record.source.version.startswith("sha256:")
        assert "synthetic" in record.issues
        assert product.stock_quantity is None
        assert product.constraints_check == "unknown"
    assert (CATALOG.read_bytes(), STOCK.read_bytes()) == before


def test_synthetic_p4_never_confirms_commercial_availability() -> None:
    result = load_p4_catalog(CATALOG, STOCK, as_of=AS_OF, max_stock_age_days=365)
    product = result.products[0]
    needs = CustomerNeeds([CustomerNeedItem(product.name, Decimal("1.5"), "т")])
    match = select_products(needs, result.products).positions[0]
    assert match.status == SelectionStatus.NEEDS_REVIEW
    assert "stock" in match.candidates[0].unknown_data


def test_explicit_freshness_policy_and_source_for_known_stock(copies: tuple[Path, Path]) -> None:
    result = load_p4_catalog(*copies, as_of=AS_OF, max_stock_age_days=27)
    assert result.products[0].stock_quantity == Decimal("40.0")
    assert result.products[0].stock_sources[0] == result.stock_rows[0].source
    assert result.products[0].constraints_check == "unknown"


def test_no_implicit_freshness_threshold(copies: tuple[Path, Path]) -> None:
    result = load_p4_catalog(*copies, as_of=AS_OF)
    assert result.products[0].stock_quantity is None
    assert "freshness_policy_missing" in result.stock_rows[0].issues


def test_multiple_parties_only_when_every_party_is_confirmed(copies: tuple[Path, Path]) -> None:
    a, b = copies
    data = rows(b)
    second = data[0] | {"line_id": "test-second-line", "batch": "test-second-batch", "stock_tons": "2.5"}
    write(b, [data[0], second])
    result = load_p4_catalog(a, b, as_of=AS_OF, max_stock_age_days=27)
    assert result.products[0].stock_quantity == Decimal("42.5")
    assert len(result.products[0].stock_sources) == 2
    second["stock_tons"] = ""
    write(b, [data[0], second])
    result = load_p4_catalog(a, b, as_of=AS_OF, max_stock_age_days=27)
    assert result.products[0].stock_quantity is None
    assert dict(result.stock_rows[0].fields)["stock_tons"] == "40"


@pytest.mark.parametrize("changes,issue", [
    ({"actual_date": "2026-09-01"}, "stale_stock"),
    ({"actual_date": "2026-11-01"}, "future_actual_date"),
    ({"actual_date": ""}, "missing_or_invalid_actual_date"),
    ({"actual_date": "invalid"}, "missing_or_invalid_actual_date"),
    ({"source_ref": ""}, "missing_source_ref"), ({"status": "draft"}, "inactive"),
    ({"is_fictional": "да"}, "synthetic"), ({"is_fictional": ""}, "unconfirmed_origin"),
    ({"batch": ""}, "missing_batch"), ({"stock_tons": ""}, "unknown_quantity"),
])
def test_uncertain_party_is_not_available(copies: tuple[Path, Path], changes: dict, issue: str) -> None:
    a, b = copies
    write(b, [rows(b)[0] | changes])
    result = load_p4_catalog(a, b, as_of=AS_OF, max_stock_age_days=27)
    assert result.products[0].stock_quantity is None
    assert issue in result.stock_rows[0].issues


@pytest.mark.parametrize("changes", [{"status": "draft"}, {"source_ref": ""}, {"unit": "кг"},
                                      {"is_fictional": "да"}, {"is_fictional": ""}])
def test_catalog_uncertainty_or_wrong_stock_unit_blocks_total(copies: tuple[Path, Path], changes: dict) -> None:
    a, b = copies
    write(a, [rows(a)[0] | changes])
    result = load_p4_catalog(a, b, as_of=AS_OF, max_stock_age_days=27)
    assert result.products[0].stock_quantity is None
    if changes.get("status") == "draft":
        item = result.products[0]
        needs = CustomerNeeds([CustomerNeedItem(item.name, Decimal("1.5"), "т")])
        assert not select_products(needs, result.products).positions[0].candidates


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "oops"])
def test_invalid_quantities_fail_explicitly(copies: tuple[Path, Path], bad: str) -> None:
    a, b = copies
    write(b, [rows(b)[0] | {"stock_tons": bad}])
    with pytest.raises(P4DataError):
        load_p4_catalog(a, b, as_of=AS_OF)


@pytest.mark.parametrize("text", ["product_id,name\nP1,fish\n", "name,name\na,b\n", '"unterminated'])
def test_invalid_csv_headers_and_syntax(copies: tuple[Path, Path], text: str) -> None:
    a, b = copies
    a.write_text(text, encoding="utf-8")
    with pytest.raises(P4DataError):
        load_p4_catalog(a, b, as_of=AS_OF)


def test_inconsistent_column_count(copies: tuple[Path, Path]) -> None:
    a, b = copies
    a.write_text(a.read_text(encoding="utf-8-sig") + "short,row\n", encoding="utf-8")
    with pytest.raises(P4DataError, match="column count"):
        load_p4_catalog(a, b, as_of=AS_OF)


@pytest.mark.parametrize("which", ["catalog", "stock"])
def test_duplicate_identity_rejected(copies: tuple[Path, Path], which: str) -> None:
    a, b = copies
    path = a if which == "catalog" else b
    data = rows(path)
    write(path, [data[0], data[0]])
    with pytest.raises(P4DataError):
        load_p4_catalog(a, b, as_of=AS_OF)


def test_orphan_stock_retained_as_diagnostic(copies: tuple[Path, Path]) -> None:
    a, b = copies
    write(b, [rows(b)[0] | {"product_id": "absent"}])
    result = load_p4_catalog(a, b, as_of=AS_OF)
    assert result.products[0].stock_quantity is None
    assert "product_not_in_catalog" in result.stock_rows[0].issues


def test_empty_optional_bounds_preserved(copies: tuple[Path, Path]) -> None:
    a, b = copies
    write(a, [rows(a)[0] | {"min_qty": "", "max_qty": ""}])
    product = load_p4_catalog(a, b, as_of=AS_OF).products[0]
    assert product.min_quantity is product.max_quantity is None


def test_contradictory_bounds_rejected(copies: tuple[Path, Path]) -> None:
    a, b = copies
    write(a, [rows(a)[0] | {"min_qty": "2.5", "max_qty": "1.5"}])
    with pytest.raises(P4DataError):
        load_p4_catalog(a, b, as_of=AS_OF)
