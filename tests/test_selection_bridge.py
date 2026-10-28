"""Local pipeline only. Costs below are explicit fixtures, NOT outputs of P2."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from kp_plugin.llm.cases import CaseRecord, CaseStatus, CommercialPermission
from kp_plugin.llm.clarify import apply_clarification_answer, build_clarifications
from kp_plugin.llm.needs import FakeLLMClient, NeedsExtractor
from kp_plugin.llm.p4_catalog import P4Catalog, P4Row, load_p4_catalog
from kp_plugin.llm.selection import CatalogProduct, SelectionSource, select_products
from kp_plugin.llm.selection_bridge import (
    BudgetEvidence,
    CalculationEvidence,
    UnavailabilityEvidence,
    assess_selection,
    build_calculation_context,
    calculation_fingerprint,
    needs_fingerprint,
)
from kp_plugin.llm.unreachable import ConfirmedSource, ExternalCost, Reason


def source() -> SelectionSource:
    return SelectionSource(source_id="fixture", version="v1", locator="explicit-test-facts")


def approved() -> ConfirmedSource:
    return ConfirmedSource(**source().model_dump(), confirmed=True)


def profile(**overrides: object) -> P4Catalog:
    product = CatalogProduct(**({"product_id": "P1", "name": "Горбуша", "unit": "кг", "status": "active",
                                 "sources": (source(),), "stock_quantity": Decimal("10.5"),
                                 "stock_sources": (source(),), "constraints_check": "passed",
                                 "constraint_sources": (source(),)} | overrides))
    row = P4Row(2, (("product_id", "P1"), ("status", "active"), ("related_cases", "C1")), source(), ())
    return P4Catalog((product,), (row,), ())


def extracted():
    return NeedsExtractor(FakeLLMClient({"items": [{"product_name": "Горбуша"}]})).extract("Горбуша")


def ready():
    state = extracted()
    for value in ("2.5", "кг"):
        result = apply_clarification_answer(state, build_clarifications(state)[0], {"value": value})
        assert result.status == "updated"
        state = result.needs
    return state


def calculation(state, unknown: tuple[str, ...] = (), **overrides: object) -> CalculationEvidence:
    context = None
    try:
        context = build_calculation_context(state, select_products(state, profile().products), profile(),
                                            profile_id="fixture-profile", profile_version="v1", price_snapshot_id="prices-v1",
                                            currency="RUB", unknown_components=unknown)
    except ValueError:
        pass  # Incomplete composition must not acquire a trusted calculation context.
    return CalculationEvidence(**({
        "request_fingerprint": needs_fingerprint(state), "verified": True, "sources": (approved(),),
        "cost": ExternalCost(calculation_ref="fixture:NOT-P2", currency="RUB", known_total=Decimal("150.25"),
                             delivery_cost=None if "delivery" in unknown else Decimal("0.0"),
                             unknown_components=unknown),
        "context": context, "context_fingerprint": calculation_fingerprint(context) if context else None,
    } | overrides))


def assess(state, catalog=None, **kwargs):
    catalog = catalog or profile()
    if kwargs.get("calculation") is not None:
        kwargs.setdefault("calculation_context", kwargs["calculation"].context)
    return assess_selection(state, select_products(state, catalog.products), catalog, **kwargs)


def test_full_local_cycle_retains_every_stage_and_separates_cases() -> None:
    initial = extracted()
    initial_snapshot = deepcopy(initial)
    partial = assess(initial)
    assert any(p.request.reason == Reason.MISSING_DATA for p in partial.problems)
    state = ready()
    before = deepcopy(state)
    result = assess(state, confirmed_sources=(approved(),), calculation=calculation(state))
    assert result.bindings[0].confirmed
    assert result.bindings[0].product_id == "P1"
    assert result.bindings[0].request_position == 1
    assert not result.problems
    assert result.case_matches[0].reasons == ("unresolved_case_reference",)
    assert result.commercial_cases == ()
    assert state == before
    assert state.items[0].evidence == before.items[0].evidence
    assert state.items[0].model_payload == before.items[0].model_payload
    assert initial == initial_snapshot
    result.needs.items[0].product_name = "detached snapshot"
    assert state.items[0].product_name == "Горбуша"


def test_hash_or_source_locator_never_creates_confirmed_fact() -> None:
    state = ready()
    result = assess(state)
    assert not result.bindings[0].confirmed
    assert result.confirmed_sources == ()
    assert any("sources" in item.field_path for p in result.problems for item in p.request.missing_data)
    assert all(not p.request.alternatives for p in result.problems)


@pytest.mark.parametrize("changes", [{"status": "draft"}, {"stock_quantity": None},
                                     {"constraints_check": "unknown"}, {"stock_quantity": Decimal("0.0")}])
def test_local_rejection_or_unknown_is_not_confirmed_unavailability(changes: dict) -> None:
    state = ready()
    catalog = profile(**changes)
    selection = select_products(state, catalog.products)
    result = assess_selection(state, selection, catalog, confirmed_sources=(approved(),))
    assert result.selection == selection
    assert all(p.request.reason == Reason.MISSING_DATA for p in result.problems)
    assert not any(binding.confirmed for binding in result.bindings)


def test_ambiguity_keeps_all_candidates_and_questions() -> None:
    state = ready()
    p = profile()
    p = P4Catalog((p.products[0], p.products[0].model_copy(update={"product_id": "P2"})), p.catalog_rows, ())
    result = assess(state, p)
    assert len(result.selection.positions[0].candidates) == 2
    assert result.selection.positions[0].questions
    assert not any(binding.confirmed for binding in result.bindings)


def test_multiple_problems_and_positions_survive() -> None:
    state = ready()
    second = deepcopy(state.items[0])
    second.product_name = "absent"
    state.items.append(second)
    state.budget_limit = Decimal("100.25")
    result = assess(state, profile(stock_quantity=None), confirmed_sources=(approved(),),
                    calculation=calculation(state, ("delivery",)),
                    budget=BudgetEvidence(amount=Decimal("100.25"), currency="USD", sources=(approved(),)))
    assert len(result.selection.positions) == 2
    assert result.selection.positions[1].exclusion_reasons == ("not_in_catalog",)
    assert any(p.request_position == 1 for p in result.problems)
    assert any(p.request_position == 2 for p in result.problems)
    assert result.calculation_issues  # Missing product identity now blocks the whole calculation.
    assert result.calculation.cost.unknown_components == ("delivery",)
    assert all(not p.response.alternatives for p in result.problems)


def test_external_unavailability_attestation_is_distinct_from_rejected() -> None:
    state = ready()
    state.items[0].product_name = "absent"
    fact = UnavailabilityEvidence(request_position=1, request_fingerprint=needs_fingerprint(state), sources=(approved(),))
    result = assess(state, unavailable=(fact,))
    assert any(p.request.reason == Reason.PRODUCT_UNAVAILABLE for p in result.problems)
    assert any(p.request.reason == Reason.MISSING_DATA for p in result.problems)


@pytest.mark.parametrize("verified,fp", [(False, None), (True, "stale")])
def test_unverified_or_stale_cost_never_supports_budget_comparison(verified: bool, fp: str | None) -> None:
    state = ready()
    evidence = calculation(state, verified=verified, request_fingerprint=fp or needs_fingerprint(state))
    result = assess(state, calculation=evidence)
    assert all(p.request.reason == Reason.MISSING_DATA for p in result.problems)


def test_budget_problem_uses_supplied_full_cost_only() -> None:
    state = ready()
    state.budget_limit = Decimal("100.25")
    result = assess(state, confirmed_sources=(approved(),), calculation=calculation(state),
                    budget=BudgetEvidence(amount=Decimal("100.25"), currency="RUB", sources=(approved(),)))
    assert len(result.problems) == 1
    assert result.problems[0].request.reason == Reason.INSUFFICIENT_BUDGET
    assert "50.00 RUB" in result.problems[0].response.explanation


def case(**overrides: object) -> CaseRecord:
    return CaseRecord(**({"case_id": "C1", "product_ids": ("P1",), "task_descriptions": ("task",),
                         "content": "Abstract fixture, not a success story", "sources": (source(),),
                         "status": CaseStatus.VERIFIED, "source_confirmed": True, "content_confirmed": True,
                         "is_fictional": False, "commercial_permission": CommercialPermission.ALLOWED} | overrides))


@pytest.mark.parametrize("permission", list(CommercialPermission))
def test_case_permission_is_not_product_alternative(permission: CommercialPermission) -> None:
    state = ready()
    result = assess(state, confirmed_sources=(approved(),), calculation=calculation(state),
                    case_records=(case(commercial_permission=permission),), client_task="task", task_sources=(approved(),))
    assert len(result.case_matches) == 1
    assert bool(result.commercial_cases) == (permission == CommercialPermission.ALLOWED)
    assert not result.problems


def test_missing_task_source_prevents_verified_case() -> None:
    result = assess(ready(), confirmed_sources=(approved(),), case_records=(case(),), client_task="task")
    assert result.case_matches[0].status != CaseStatus.VERIFIED
    assert result.commercial_cases == ()


def test_real_synthetic_p4_cannot_produce_verified_alternative() -> None:
    root = Path(__file__).parent / "fixtures/p4_synthetic"
    p = load_p4_catalog(root / "catalog/catalog.csv", root / "prices_stock/warehouse_stock.csv", as_of=date(2026, 10, 28))
    state = ready()
    state.items[0].product_name = p.products[0].name
    state.items[0].unit = "т"
    result = assess(state, p)
    assert result.profile == p
    assert result.profile.stock_rows[0].issues
    assert not result.bindings[0].confirmed
    assert all(not issue.response.alternatives for issue in result.problems)
    assert result.commercial_cases == ()


def test_stale_selection_is_rejected_not_silently_rebound() -> None:
    state = ready()
    p = profile()
    selected = select_products(state, p.products)
    state.items[0].quantity = Decimal("100.5")
    with pytest.raises(ValueError, match="does not correspond"):
        assess_selection(state, selected, p)


def test_missing_budget_attestation_not_lost_when_calculation_is_also_missing() -> None:
    state = ready()
    state.budget_limit = Decimal("100.25")
    result = assess(state)
    fields = {d.field_path for p in result.problems for d in p.request.missing_data}
    assert {"budget.sources", "calculation.calculation_missing"} <= fields


def test_stale_unavailability_kept_but_not_asserted_as_current_fact() -> None:
    state = ready()
    fact = UnavailabilityEvidence(request_position=1, request_fingerprint="old", sources=(approved(),))
    result = assess(state, unavailable=(fact,))
    assert result.unavailability_evidence == (fact,)
    assert not any(p.request.reason == Reason.PRODUCT_UNAVAILABLE for p in result.problems)
