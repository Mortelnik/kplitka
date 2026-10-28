"""P3.3 structure/invariants only; all facts and costs are supplied by test callers."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kp_plugin.llm.unreachable import (
    Alternative,
    AlternativeReadiness,
    ConfirmedSource,
    ExternalCost,
    Reason,
    RequestChange,
    Status,
    UnreachableResult,
)


def source() -> ConfirmedSource:
    return ConfirmedSource(source_id="catalog", version="demo-v1", locator="FISH-007", confirmed=True)


def option(**overrides: object) -> Alternative:
    fields = {
        "alternative_id": "reduce_quantity", "explanation": "Предлагается уменьшить объём; нужно согласие клиента.",
        "changes": (RequestChange(field_path="items[0].quantity", before=Decimal("2.5"), after=Decimal("1.5")),),
        "sources": (source(),), "requires_client_confirmation": True,
    }
    return Alternative(**(fields | overrides))


def cost(**overrides: object) -> ExternalCost:
    return ExternalCost(**({"calculation_ref": "p2:demo-1", "currency": "RUB", "known_total": Decimal("100.25"),
                           "delivery_cost": Decimal("0.0"), "unknown_components": ()} | overrides))


@pytest.mark.parametrize("reason", list(Reason))
def test_all_typed_reasons_can_request_resolution(reason: Reason) -> None:
    result = UnreachableResult(status=Status.CLARIFY, reason=reason,
                               explanation="Условия требуют уточнения.", sources=(source(),),
                               questions=("Какие условия можно изменить?",))
    assert result.reason == reason
    assert result.alternatives == ()


def test_unknown_delivery_is_preserved_and_cannot_be_verified() -> None:
    partial_cost = cost(delivery_cost=None, unknown_components=("delivery",))
    candidate = option(cost=partial_cost)
    assert candidate.readiness == AlternativeReadiness.CONDITIONAL
    assert candidate.cost.unknown_components == ("delivery",)
    assert candidate.cost.delivery_cost is None
    with pytest.raises(ValidationError, match="complete cost"):
        option(cost=partial_cost, externally_validated=True, readiness=AlternativeReadiness.VERIFIED)


def test_verified_option_retains_external_total_and_explicit_changes() -> None:
    external = cost()
    candidate = option(cost=external, externally_validated=True, readiness=AlternativeReadiness.VERIFIED)
    result = UnreachableResult(status=Status.ALTERNATIVES, reason=Reason.INSUFFICIENT_BUDGET,
                               explanation="Исходный заказ превышает бюджет; уменьшение объёма требует согласия.",
                               sources=(source(),), alternatives=(candidate,))
    assert result.alternatives[0].cost.known_total == external.known_total
    assert result.alternatives[0].changes[0].before == "2.5"
    assert result.alternatives[0].requires_client_confirmation is True
    assert UnreachableResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("overrides", [
    {}, {"cost": cost()}, {"externally_validated": True},
])
def test_no_verified_availability_without_complete_external_data(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        option(readiness=AlternativeReadiness.VERIFIED, **overrides)


@pytest.mark.parametrize("overrides", [
    {"changes": ()}, {"sources": ()}, {"requires_client_confirmation": False},
    {"requires_client_confirmation": None}, {"explanation": " "},
])
def test_alternative_requires_evidence_delta_and_confirmation(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        option(**overrides)


def test_no_implicit_confirmation_default() -> None:
    with pytest.raises(ValidationError):
        Alternative(alternative_id="a", explanation="Вариант", changes=option().changes, sources=(source(),))


@pytest.mark.parametrize("before,after", [("рыба", "рыба"), (None, None), (Decimal("1.5"), Decimal("1.50")),
                                        (True, "да"), (Decimal("NaN"), "нет"), ([], "нет")])
def test_invalid_change_is_rejected(before: object, after: object) -> None:
    with pytest.raises(ValidationError):
        RequestChange(field_path="items[0].product_name", before=before, after=after)


def test_duplicate_deltas_are_ambiguous() -> None:
    change = option().changes[0]
    with pytest.raises(ValidationError, match="unambiguous"):
        option(changes=(change, change))


@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), True, 1.5, "100.25"])
def test_cost_requires_finite_nonnegative_decimal(value: object) -> None:
    with pytest.raises(ValidationError):
        cost(known_total=value)


def test_unknown_components_cannot_be_omitted_or_blank() -> None:
    with pytest.raises(ValidationError):
        ExternalCost(calculation_ref="p2:x", currency="RUB", known_total=Decimal("0.0"))
    with pytest.raises(ValidationError):
        cost(unknown_components=(" ",))


@pytest.mark.parametrize("overrides", [
    {"delivery_cost": None}, {"unknown_components": ("delivery",)}, {"delivery_cost": Decimal("-1.5")},
])
def test_inconsistent_or_invalid_delivery_is_rejected(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        cost(**overrides)


def test_delivery_must_be_supplied_without_zero_default() -> None:
    with pytest.raises(ValidationError):
        ExternalCost(calculation_ref="p2:x", currency="RUB", known_total=Decimal("100.25"), unknown_components=())


@pytest.mark.parametrize("overrides", [{"confirmed": False}, {"version": " "}, {"locator": ""}])
def test_only_confirmed_identifiable_sources(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        ConfirmedSource(**(source().model_dump() | overrides))


@pytest.mark.parametrize("status,questions,alternatives", [
    (Status.CLARIFY, (), ()), (Status.ALTERNATIVES, (), ()),
    (Status.UNAVAILABLE, (), (option(),)), (Status.CLARIFY, ("Уточните?",), (option(),)),
])
def test_status_matches_response_content(status: Status, questions: tuple, alternatives: tuple) -> None:
    with pytest.raises(ValidationError):
        UnreachableResult(status=status, reason=Reason.MISSING_DATA, explanation="Нужны данные.",
                          sources=(), questions=questions, alternatives=alternatives)


@pytest.mark.parametrize("reason", [Reason.CONFLICT, Reason.INSUFFICIENT_BUDGET, Reason.PRODUCT_UNAVAILABLE])
def test_confirmed_problem_requires_sources(reason: Reason) -> None:
    with pytest.raises(ValidationError):
        UnreachableResult(status=Status.UNAVAILABLE, reason=reason, explanation="Причина.", sources=())


def test_duplicate_alternative_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="identifiers"):
        UnreachableResult(status=Status.ALTERNATIVES, reason=Reason.CONFLICT, explanation="Условия несовместимы.",
                          sources=(source(),), alternatives=(option(), option()))


def test_contract_rejects_unknown_fields_and_mutation() -> None:
    with pytest.raises(ValidationError):
        option(available=True)
    candidate = option()
    with pytest.raises(ValidationError):
        candidate.externally_validated = True
    assert "reason" in UnreachableResult.model_json_schema()["properties"]


def test_unknown_reason_cannot_enter_json_adapter() -> None:
    with pytest.raises(ValidationError):
        UnreachableResult.model_validate_json(
            '{"status":"unavailable","reason":"invented","explanation":"Причина","sources":[]}'
        )
