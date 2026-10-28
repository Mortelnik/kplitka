"""Calculation-scope regression fixtures; these amounts are not P2 outputs."""

from copy import deepcopy
from decimal import Decimal

import pytest

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds
from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import CatalogProduct, SelectionSource, select_products
from kp_plugin.llm.selection_bridge import (
    CalculationEvidence,
    assess_selection,
    build_calculation_context,
    calculation_fingerprint,
    needs_fingerprint,
)
from kp_plugin.llm.unreachable import ConfirmedSource, ExternalCost, Reason


def environment():
    source = SelectionSource(source_id="binding-fixture", version="1", locator="catalog")
    products = tuple(CatalogProduct(product_id=identifier, name="Горбуша", unit="кг", status="active",
                                    sources=(source,), stock_quantity=Decimal("100.5"), stock_sources=(source,),
                                    constraints_check="passed", constraint_sources=(source,)) for identifier in ("P1", "P2"))
    needs = CustomerNeeds([CustomerNeedItem("Горбуша", Decimal("2.5"), "кг")])
    return needs, P4Catalog(products, (), ()), {1: "P1"}


def context(needs, profile, ids, **versions):
    selected = select_products(needs, profile.products, product_ids=ids)
    return build_calculation_context(needs, selected, profile, **({
        "profile_id": "company-1", "profile_version": "profile-v1", "price_snapshot_id": "price-v1",
        "currency": "RUB", "unknown_components": (),
    } | versions))


def evidence(scope, **overrides):
    return CalculationEvidence(**({
        "request_fingerprint": scope.request_fingerprint, "context": scope,
        "context_fingerprint": calculation_fingerprint(scope), "verified": True,
        "sources": (ConfirmedSource(source_id="fixture:NOT-P2", version="1", locator="calculation", confirmed=True),),
        "cost": ExternalCost(calculation_ref="fixture:NOT-P2", currency="RUB", known_total=Decimal("100.25"),
                             delivery_cost=Decimal("0.0"), unknown_components=()),
    } | overrides))


def assess(needs, profile, ids, current, external):
    return assess_selection(needs, select_products(needs, profile.products, product_ids=ids), profile,
                            product_ids=ids, calculation_context=current, calculation=external)


def test_all_scope_fields_match_and_snapshot_is_detached() -> None:
    needs, profile, ids = environment()
    before = deepcopy(needs)
    scope = context(needs, profile, ids)
    result = assess(needs, profile, ids, scope, evidence(scope))
    assert result.calculation_confirmed
    assert result.calculation_issues == ()
    assert needs == before
    assert needs.items[0].evidence == before.items[0].evidence
    result.needs.items[0].quantity = Decimal("9.5")
    assert needs.items[0].quantity == Decimal("2.5")


def test_same_needs_and_profile_but_different_selected_id() -> None:
    needs, profile, ids = environment()
    old = evidence(context(needs, profile, ids))
    changed_ids = {1: "P2"}
    current = context(needs, profile, changed_ids)
    assert current.request_fingerprint == old.request_fingerprint
    assert current.profile_snapshot == old.context.profile_snapshot
    result = assess(needs, profile, changed_ids, current, old)
    assert not result.calculation_confirmed
    assert "calculation_context_changed" in result.calculation_issues


@pytest.mark.parametrize("changes", [
    {"profile_id": "company-2"}, {"profile_version": "profile-v2"}, {"price_snapshot_id": "price-v2"},
    {"currency": "USD"}, {"unknown_components": ("delivery",)},
])
def test_changed_current_scope_rejects_old_calculation(changes: dict) -> None:
    needs, profile, ids = environment()
    old = evidence(context(needs, profile, ids))
    result = assess(needs, profile, ids, context(needs, profile, ids, **changes), old)
    assert not result.calculation_confirmed
    assert "calculation_context_changed" in result.calculation_issues
    assert all(problem.request.reason == Reason.MISSING_DATA for problem in result.problems)
    assert any("повторный" in problem.request.missing_data[0].label for problem in result.problems)
    assert result.calculation == old


@pytest.mark.parametrize("field,value", [("quantity", Decimal("3.5")), ("unit", "т")])
def test_changed_quantity_or_unit_blocks_old_scope(field: str, value: object) -> None:
    needs, profile, ids = environment()
    old_scope = context(needs, profile, ids)
    setattr(needs.items[0], field, value)
    # Supplying the old context as current does not bypass rebuilding the composition.
    result = assess(needs, profile, ids, old_scope, evidence(old_scope))
    assert not result.calculation_confirmed
    assert "request_changed" in result.calculation_issues
    assert "current_context_stale" in result.calculation_issues or "current_composition_incomplete" in result.calculation_issues


def test_every_line_of_multi_position_order_is_bound() -> None:
    needs, profile, ids = environment()
    needs.items.append(CustomerNeedItem("Горбуша", Decimal("1.5"), "кг"))
    ids[2] = "P2"
    old = evidence(context(needs, profile, ids))
    needs.items[1].quantity = Decimal("4.5")
    current = context(needs, profile, ids)
    assert len(current.lines) == 2
    assert current.lines[0] == old.context.lines[0]
    assert not assess(needs, profile, ids, current, old).calculation_confirmed


@pytest.mark.parametrize("field,value", [
    ("profile_id", None), ("profile_version", None), ("price_snapshot_id", None),
    ("profile_version", " "), ("price_snapshot_id", ""), ("currency", ""),
])
def test_missing_versions_never_get_defaults(field: str, value: str | None) -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids, **{field: value})
    result = assess(needs, profile, ids, scope, evidence(scope))
    assert not result.calculation_confirmed
    assert f"{field}_missing" in result.calculation_issues


def test_changed_profile_contents_block_even_if_version_label_is_reused() -> None:
    needs, profile, ids = environment()
    old_scope = context(needs, profile, ids)
    changed = P4Catalog((profile.products[0].model_copy(update={"stock_quantity": Decimal("80.5")}),
                         profile.products[1]), (), ())
    result = assess(needs, changed, ids, old_scope, evidence(old_scope))
    assert not result.calculation_confirmed
    assert "current_context_stale" in result.calculation_issues


def test_hash_alone_does_not_attest_calculation() -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids)
    result = assess(needs, profile, ids, scope, evidence(scope, verified=False))
    assert not result.calculation_confirmed
    assert "calculation_not_verified" in result.calculation_issues


def test_missing_context_in_legacy_evidence_is_safe() -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids)
    result = assess(needs, profile, ids, scope, evidence(scope, context=None, context_fingerprint=None))
    assert not result.calculation_confirmed
    assert "evidence_context_missing" in result.calculation_issues


def test_cost_currency_cannot_disagree_with_scope() -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids)
    cost = ExternalCost(calculation_ref="fixture", currency="USD", known_total=Decimal("100.25"),
                        delivery_cost=Decimal("0.0"), unknown_components=())
    result = assess(needs, profile, ids, scope, evidence(scope, cost=cost))
    assert "calculation_currency_mismatch" in result.calculation_issues
    assert not result.calculation_confirmed


def test_canonical_fingerprint_ignores_dictionary_insertion_order_but_keeps_types() -> None:
    needs, _profile, _ids = environment()
    needs.items[0].model_payload = {"first": "x", "second": {"a": 1, "b": 2}}
    initial = needs_fingerprint(needs)
    needs.items[0].model_payload = {"second": {"b": 2, "a": 1}, "first": "x"}
    assert needs_fingerprint(needs) == initial
    needs.items[0].quantity = "2.5"
    assert needs_fingerprint(needs) != initial


def test_bad_digest_not_accepted_even_with_verified_flag() -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids)
    result = assess(needs, profile, ids, scope, evidence(scope, context_fingerprint="tampered"))
    assert "evidence_fingerprint_mismatch" in result.calculation_issues
    assert not result.calculation_confirmed


def test_incomplete_cost_is_bound_but_never_confirmed_as_full_cost() -> None:
    needs, profile, ids = environment()
    scope = context(needs, profile, ids, unknown_components=("delivery",))
    cost = ExternalCost(calculation_ref="fixture", currency="RUB", known_total=Decimal("100.25"),
                        delivery_cost=None, unknown_components=("delivery",))
    result = assess(needs, profile, ids, scope, evidence(scope, cost=cost))
    assert result.calculation_issues == ()
    assert not result.calculation_confirmed
    assert Reason.UNKNOWN_COSTS in {problem.request.reason for problem in result.problems}


def test_forged_omission_of_second_position_is_blocked() -> None:
    needs, profile, ids = environment()
    needs.items.append(CustomerNeedItem("Горбуша", Decimal("1.5"), "кг"))
    ids[2] = "P2"
    scope = context(needs, profile, ids)
    truncated = scope.model_copy(update={"lines": scope.lines[:1]})
    result = assess(needs, profile, ids, truncated, evidence(truncated))
    assert not result.calculation_confirmed
    assert "current_context_stale" in result.calculation_issues
