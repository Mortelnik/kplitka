"""Synthetic adapter inputs; no P2 implementation, catalog search or LLM calls."""

from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from kp_plugin.llm.unreachable import (
    Alternative,
    AlternativeReadiness,
    ConfirmedSource,
    ConflictDetail,
    ExternalCost,
    HandlingRequest,
    MissingDatum,
    Reason,
    RequestChange,
    Status,
    handle_unreachable,
)


def sources() -> tuple[ConfirmedSource, ...]:
    return (ConfirmedSource(source_id="adapter", version="test-v1", locator="checked-request-1", confirmed=True),)


def cost(total: str = "150.25", currency: str = "RUB", unknown: tuple[str, ...] = ()) -> ExternalCost:
    return ExternalCost(calculation_ref="p2:test-1", currency=currency, known_total=Decimal(total),
                        delivery_cost=None if "delivery" in unknown else Decimal("0.0"),
                        unknown_components=unknown)


def option(option_id: str = "less", **overrides: object) -> Alternative:
    fields = {
        "alternative_id": option_id, "explanation": "Уменьшение объёма, проверено внешним адаптером.",
        "sources": sources(), "requires_client_confirmation": True,
        "changes": (RequestChange(field_path="items[0].quantity", before="2.5", after="1.5"),),
        "readiness": AlternativeReadiness.VERIFIED, "externally_validated": True, "cost": cost("90.25"),
    }
    return Alternative(**(fields | overrides))


def budget_request(**overrides: object) -> HandlingRequest:
    return HandlingRequest(**({
        "reason": Reason.INSUFFICIENT_BUDGET, "sources": sources(), "cost": cost(),
        "calculation_verified": True, "budget": Decimal("100.25"), "budget_currency": "RUB",
    } | overrides))


def test_conflict_lists_both_conditions_and_specific_question() -> None:
    request = HandlingRequest(reason=Reason.CONFLICT, sources=sources(), conflicts=(
        ConflictDetail(field_path="delivery", first_condition="только доставка", second_condition="только самовывоз"),
        ConflictDetail(field_path="date", first_condition="до 1 ноября", second_condition="не раньше 5 ноября"),
    ))
    snapshot = request.model_dump_json()
    result = handle_unreachable(request)
    assert result.status == Status.CLARIFY
    assert result.reason == Reason.CONFLICT
    assert "только доставка" in result.explanation
    assert "только самовывоз" in result.explanation
    assert len(result.questions) == 2
    assert "date" in result.questions[1]
    assert result.sources == request.sources
    assert request.model_dump_json() == snapshot


@pytest.mark.parametrize("overrides", [{"sources": ()}, {"conflicts": ()}])
def test_incomplete_conflict_is_not_invented(overrides: dict) -> None:
    request = HandlingRequest(**({"reason": Reason.CONFLICT, "sources": sources(), "conflicts": (
        ConflictDetail(field_path="unit", first_condition="кг", second_condition="т"),
    )} | overrides))
    result = handle_unreachable(request)
    assert result.reason == Reason.MISSING_DATA
    assert result.status == Status.CLARIFY


def test_verified_budget_difference_and_options_without_recalculation() -> None:
    candidate = option()
    request = budget_request(alternatives=(candidate,))
    snapshot = request.model_dump_json()
    result = handle_unreachable(request)
    assert result.status == Status.ALTERNATIVES
    assert result.reason == Reason.INSUFFICIENT_BUDGET
    assert "150.25 RUB" in result.explanation
    assert "100.25 RUB" in result.explanation
    assert "50.00 RUB" in result.explanation
    assert "items[0].quantity: 2.5 → 1.5" in result.explanation
    assert "Требуется согласие клиента" in result.explanation
    assert result.alternatives == (candidate,)
    assert result.alternatives[0].cost.known_total == Decimal("90.25")
    assert request.model_dump_json() == snapshot


def test_exact_difference_does_not_depend_on_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 3
        result = handle_unreachable(budget_request(cost=cost("1000000000000000000000000000000.25"),
                                                  budget=Decimal("1000000000000000000000000000000.24")))
        assert "Превышение бюджета: 0.01 RUB" in result.explanation
        assert context.prec == 3


@pytest.mark.parametrize("total,budget", [("0.0", "0.0"), ("100.25", "100.25"), ("99.25", "100.25")])
def test_no_false_budget_rejection_at_or_below_boundary(total: str, budget: str) -> None:
    result = handle_unreachable(budget_request(cost=cost(total), budget=Decimal(budget)))
    assert result.reason == Reason.MISSING_DATA
    assert result.status == Status.CLARIFY
    assert "не подтверждает превышение" in result.questions[0]


def test_zero_budget_is_not_missing() -> None:
    result = handle_unreachable(budget_request(cost=cost("0.01"), budget=Decimal("0.0")))
    assert result.reason == Reason.INSUFFICIENT_BUDGET
    assert "0.01 RUB" in result.explanation


@pytest.mark.parametrize("overrides,question_fragment", [
    ({"cost": None}, "расчёт"), ({"calculation_verified": False}, "расчёт"),
    ({"sources": ()}, "источники"), ({"budget": None}, "бюджет"),
    ({"budget_currency": None}, "валюту"), ({"budget_currency": "USD"}, "одной валюте"),
])
def test_incomplete_budget_inputs_ask_instead_of_guessing(overrides: dict, question_fragment: str) -> None:
    result = handle_unreachable(budget_request(**overrides))
    assert result.reason == Reason.MISSING_DATA
    assert result.status == Status.CLARIFY
    assert question_fragment in result.questions[0]
    assert result.alternatives == ()


@pytest.mark.parametrize("unknown", [("delivery",), ("storage",), ("delivery", "handling")])
@pytest.mark.parametrize("total", ["50.25", "150.25"])
def test_unknown_costs_block_budget_claim_even_when_subtotal_is_low(unknown: tuple[str, ...], total: str) -> None:
    result = handle_unreachable(budget_request(cost=cost(total, unknown=unknown), alternatives=(option(),)))
    assert result.reason == Reason.UNKNOWN_COSTS
    assert result.status == Status.CLARIFY
    assert "не подтверждено" in result.explanation
    assert "не приняты за ноль" in result.explanation
    assert len(result.questions) == len(unknown)
    assert result.alternatives == ()


def test_unknown_costs_without_calculation_asks_for_full_breakdown() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.UNKNOWN_COSTS))
    assert result.reason == Reason.UNKNOWN_COSTS
    assert "доставки" in result.questions[0]


def test_unavailable_product_only_offers_supplied_verified_candidates() -> None:
    accepted = option("verified")
    conditional = option("conditional", readiness=AlternativeReadiness.CONDITIONAL, externally_validated=False)
    request = HandlingRequest(reason=Reason.PRODUCT_UNAVAILABLE, product_name="горбуша",
                              product_unavailable_confirmed=True, sources=sources(),
                              alternatives=(conditional, accepted))
    result = handle_unreachable(request)
    assert "горбуша» недоступен" in result.explanation
    assert result.reason == Reason.PRODUCT_UNAVAILABLE
    assert result.alternatives == (accepted,)
    assert result.alternatives[0].sources == accepted.sources
    assert result.alternatives[0].requires_client_confirmation


@pytest.mark.parametrize("overrides", [{"product_name": None}, {"product_unavailable_confirmed": False}, {"sources": ()}])
def test_product_unavailability_needs_structured_confirmation(overrides: dict) -> None:
    request = HandlingRequest(**({"reason": Reason.PRODUCT_UNAVAILABLE, "product_name": "горбуша",
                                 "product_unavailable_confirmed": True, "sources": sources()} | overrides))
    result = handle_unreachable(request)
    assert result.status == Status.CLARIFY
    assert result.reason == Reason.MISSING_DATA


def test_confirmed_unavailability_without_candidates_is_not_a_search() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.PRODUCT_UNAVAILABLE, product_name="краб",
                                               product_unavailable_confirmed=True, sources=sources()))
    assert result.status == Status.UNAVAILABLE
    assert result.alternatives == ()
    assert "не предоставлены" in result.explanation


@pytest.mark.parametrize("candidate", [
    option(cost=cost("100.26")), option(cost=cost("90.25", currency="USD")),
    option(cost=None, readiness=AlternativeReadiness.CONDITIONAL),
    option(cost=cost(unknown=("delivery",)), readiness=AlternativeReadiness.CONDITIONAL),
])
def test_budget_alternatives_must_have_confirmed_affordable_complete_cost(candidate: Alternative) -> None:
    result = handle_unreachable(budget_request(alternatives=(candidate,)))
    assert result.status == Status.UNAVAILABLE
    assert result.alternatives == ()


def test_alternative_at_budget_boundary_is_allowed() -> None:
    candidate = option(cost=cost("100.25"))
    assert handle_unreachable(budget_request(alternatives=(candidate,))).alternatives == (candidate,)


def test_missing_fields_generate_specific_questions_without_values() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.MISSING_DATA, missing_data=(
        MissingDatum(field_path="items[1].quantity", label="количество второй позиции"),
        MissingDatum(field_path="items[1].unit", label="единицу измерения второй позиции"),
    )))
    assert result.reason == Reason.MISSING_DATA
    assert result.questions == ("Уточните количество второй позиции (items[1].quantity).",
                                "Уточните единицу измерения второй позиции (items[1].unit).")
    assert result.alternatives == ()


def test_missing_field_list_itself_requires_clarification() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.MISSING_DATA))
    assert "какие поля" in result.questions[0]


def test_p2_error_text_cannot_be_treated_as_structured_calculation() -> None:
    with pytest.raises(ValidationError):
        budget_request(cost="Ошибка: Продукт не найден в каталоге")
    result = handle_unreachable(HandlingRequest(reason=Reason.INSUFFICIENT_BUDGET))
    assert result.reason == Reason.MISSING_DATA


def test_request_and_output_json_are_adapter_compatible() -> None:
    request = budget_request(alternatives=(option(),))
    decoded = HandlingRequest.model_validate_json(request.model_dump_json())
    assert handle_unreachable(decoded) == handle_unreachable(request)


def test_identical_conditions_do_not_establish_conflict() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.CONFLICT, sources=sources(), conflicts=(
        ConflictDetail(field_path="unit", first_condition="кг", second_condition="кг"),
    )))
    assert result.reason == Reason.MISSING_DATA
    assert result.sources == sources()


def test_complete_verified_cost_conflicts_with_unknown_cost_reason() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.UNKNOWN_COSTS, cost=cost(),
                                               calculation_verified=True, sources=sources()))
    assert result.reason == Reason.MISSING_DATA
    assert "отмечен как полный" in result.questions[0]


def test_product_alternatives_with_budget_require_currency() -> None:
    result = handle_unreachable(HandlingRequest(reason=Reason.PRODUCT_UNAVAILABLE, product_name="краб",
                                               sources=sources(), product_unavailable_confirmed=True,
                                               budget=Decimal("100.25"), alternatives=(option(),)))
    assert result.reason == Reason.MISSING_DATA
    assert "валюту" in result.questions[0]


def test_duplicate_candidate_ids_rejected_before_handling() -> None:
    with pytest.raises(ValidationError, match="identifiers"):
        budget_request(alternatives=(option(), option()))
