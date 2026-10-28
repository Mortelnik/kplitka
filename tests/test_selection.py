"""Synthetic local catalog only; no assumptions about the unavailable P4 archive."""

from copy import deepcopy
from decimal import Decimal

import pytest

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds
from kp_plugin.llm.selection import (
    CatalogProduct,
    SelectionResult,
    SelectionSource,
    SelectionStatus,
    select_products,
)


def product(identifier: str = "P1", name: str = "Горбуша", **overrides: object) -> CatalogProduct:
    refs = (SelectionSource(source_id="synthetic", version="v1", locator=identifier),)
    return CatalogProduct(**({"product_id": identifier, "name": name, "status": "active", "sources": refs,
                             "unit": "кг", "stock_quantity": Decimal("10.5"), "stock_sources": refs,
                             "constraints_check": "passed", "constraint_sources": refs} | overrides))


def needs(name: str | None = "Горбуша", **overrides: object) -> CustomerNeeds:
    return CustomerNeeds(items=[CustomerNeedItem(**({"product_name": name, "quantity": Decimal("2.5"),
                                                    "unit": "кг"} | overrides))])


@pytest.mark.parametrize("name", ["Горбуша", "  ГОРБУША  ", "P1"])
def test_exact_identity(name: str) -> None:
    result = select_products(needs(name), (product(),))
    candidate = result.positions[0].candidates[0]
    assert candidate.product_id == "P1"
    assert candidate.status == SelectionStatus.CONFIRMED
    assert candidate.sources
    assert candidate.matched_fields[0].request_value == name
    assert candidate.requirement_changes == ()
    assert SelectionResult.model_validate_json(result.model_dump_json()) == result


def test_explicit_id_without_changing_customer_model() -> None:
    result = select_products(needs(None), (product(),), product_ids={1: "P1"})
    assert result.positions[0].candidates[0].status == SelectionStatus.CONFIRMED


def test_explicit_id_conflicting_with_name_needs_clarification() -> None:
    result = select_products(needs("Треска"), (product(),), product_ids={1: "P1"})
    assert result.positions[0].status == SelectionStatus.NEEDS_CLARIFICATION
    assert result.positions[0].candidates[0].requirement_changes == ()


def test_explicit_synonym_only() -> None:
    assert select_products(needs("Красная рыба"), (product(),)).positions[0].status == SelectionStatus.REJECTED
    result = select_products(needs("Красная рыба"), (product(synonyms=("красная рыба",)),))
    assert result.positions[0].candidates[0].matched_fields[0].catalog_field == "synonyms"


@pytest.mark.parametrize("name", ["горбуш", "горбуша замороженная", "Треска"])
def test_no_fuzzy_or_automatic_substitution(name: str) -> None:
    result = select_products(needs(name), (product(),)).positions[0]
    assert result.status == SelectionStatus.REJECTED
    assert result.exclusion_reasons == ("not_in_catalog",)
    assert not result.candidates


def test_unknown_id_does_not_fall_back_to_matching_name() -> None:
    result = select_products(needs(), (product(),), product_ids={1: "absent"}).positions[0]
    assert result.status == SelectionStatus.REJECTED


def test_ambiguous_name_requires_identity_even_if_only_one_has_stock() -> None:
    result = select_products(needs(), (product(), product("P2", stock_quantity=Decimal("0.0")))).positions[0]
    assert result.status == SelectionStatus.NEEDS_CLARIFICATION
    assert result.questions
    assert all(c.status != SelectionStatus.CONFIRMED for c in result.candidates)


def test_draft_is_excluded_with_reason() -> None:
    result = select_products(needs(), (product(status="draft"),)).positions[0]
    assert result.status == SelectionStatus.REJECTED
    assert result.candidates == ()
    assert "draft" in result.excluded[0].exclusion_reasons


def test_draft_does_not_shadow_unique_active_match() -> None:
    result = select_products(needs(), (product(), product("P2", status="draft"))).positions[0]
    assert result.status == SelectionStatus.CONFIRMED
    assert len(result.candidates) == len(result.excluded) == 1


@pytest.mark.parametrize("field", ["product_name", "quantity", "unit"])
def test_unconfirmed_request_fields_never_confirmed(field: str) -> None:
    result = select_products(needs(unknown_fields=[field]), (product(),)).positions[0]
    assert result.status == SelectionStatus.NEEDS_CLARIFICATION
    assert result.questions


@pytest.mark.parametrize("overrides", [{"stock_quantity": None}, {"stock_sources": ()},
                                       {"constraints_check": "unknown"}, {"constraint_sources": ()}])
def test_unknown_checks_remain_unknown(overrides: dict) -> None:
    result = select_products(needs(), (product(**overrides),)).positions[0]
    assert result.status == SelectionStatus.NEEDS_REVIEW
    assert result.candidates[0].unknown_data


@pytest.mark.parametrize("quantity", [None, True, "много", Decimal("NaN"), Decimal("0.0"), Decimal("-1.5")])
def test_missing_or_invalid_quantity_not_used(quantity: object) -> None:
    result = select_products(needs(quantity=quantity), (product(),)).positions[0]
    assert result.status == SelectionStatus.NEEDS_CLARIFICATION


def test_no_unit_conversion_or_stock_comparison_in_wrong_unit() -> None:
    result = select_products(needs(unit="т"), (product(stock_quantity=Decimal("0.0")),)).positions[0]
    assert result.status == SelectionStatus.NEEDS_CLARIFICATION
    assert "unit_compatibility" in result.candidates[0].unknown_data
    assert not result.excluded


@pytest.mark.parametrize("overrides,reason", [
    ({"stock_quantity": Decimal("0.0")}, "insufficient_stock"),
    ({"min_quantity": Decimal("3.5")}, "below_min_quantity"),
    ({"max_quantity": Decimal("1.5")}, "above_max_quantity"),
    ({"constraints_check": "failed"}, "catalog_constraints_failed"),
])
def test_explicit_constraints_exclude(overrides: dict, reason: str) -> None:
    result = select_products(needs(), (product(**overrides),)).positions[0]
    assert result.status == SelectionStatus.REJECTED
    assert reason in result.excluded[0].exclusion_reasons


def test_quantity_boundaries_are_inclusive() -> None:
    result = select_products(needs(), (product(stock_quantity=Decimal("2.5"), min_quantity=Decimal("2.5"),
                                               max_quantity=Decimal("2.5")),)).positions[0]
    assert result.status == SelectionStatus.CONFIRMED


def test_customer_constraints_are_not_guessed() -> None:
    result = select_products(needs(constraints=["контейнер не менее 80%"]), (product(),)).positions[0]
    assert result.status == SelectionStatus.NEEDS_REVIEW
    assert "request.constraints" in result.candidates[0].unknown_data


def test_multiple_items_and_original_metadata_preserved() -> None:
    original = needs()
    original.items.append(CustomerNeedItem("Треска", Decimal("3.5"), "кг"))
    original.items[0].model_payload = {"quantity": "2.5"}
    snapshot = deepcopy(original)
    result = select_products(original, (product(), product("P2", "Треска")))
    assert [p.request_position for p in result.positions] == [1, 2]
    assert [p.candidates[0].product_id for p in result.positions] == ["P1", "P2"]
    assert original == snapshot
    assert original.items[0].model_payload == snapshot.items[0].model_payload
    assert original.items[0].evidence == snapshot.items[0].evidence


def test_repeated_sku_needs_joint_stock_review() -> None:
    original = needs()
    original.items.append(CustomerNeedItem("Горбуша", Decimal("2.5"), "кг"))
    result = select_products(original, (product(),))
    assert all(p.status == SelectionStatus.NEEDS_REVIEW for p in result.positions)
    assert all("joint_stock_allocation" in p.candidates[0].unknown_data for p in result.positions)


def test_empty_request_asks_for_products() -> None:
    assert select_products(CustomerNeeds(items=[]), (product(),)).questions


def test_duplicate_catalog_id_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        select_products(needs(), (product(), product()))


@pytest.mark.parametrize("ids", [{0: "P1"}, {2: "P1"}, {True: "P1"}, {1: " "}])
def test_invalid_explicit_positions_rejected(ids: dict) -> None:
    with pytest.raises(ValueError):
        select_products(needs(), (product(),), product_ids=ids)
