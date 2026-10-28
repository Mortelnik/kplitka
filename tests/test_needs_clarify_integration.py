"""Local P3.1 -> P3.2 contract tests; FakeLLMClient never interprets text."""

from copy import deepcopy
from decimal import Decimal

import pytest

from kp_plugin.llm.clarify import apply_clarification_answer, build_clarifications
from kp_plugin.llm.needs import (
    CustomerNeedItem,
    CustomerNeeds,
    FakeLLMClient,
    NeedsExtractor,
)


def extract(text: str, items: list[dict], **extra: object) -> CustomerNeeds:
    return NeedsExtractor(FakeLLMClient({"items": items, **extra})).extract(text)


def answer_first(state: CustomerNeeds, value: object) -> CustomerNeeds:
    result = apply_clarification_answer(state, build_clarifications(state)[0], {"value": value})
    assert result.status == "updated"
    return result.needs


def test_incomplete_request_extraction_to_ready_state() -> None:
    payload = {"product_name": "замороженная горбуша", "constraints": ["для ресторана"]}
    source = extract("Здравствуйте, нужна замороженная горбуша для ресторана", [payload])
    snapshot = deepcopy(source)
    assert source.items[0].quantity is source.items[0].unit is None
    assert source.validate_partial() is source
    with pytest.raises(ValueError):
        deepcopy(source).validate()
    assert [(q.field_name, q.position) for q in build_clarifications(source)] == [("quantity", 1), ("unit", 1)]
    first = answer_first(source, "2.5")
    assert first.items[0].quantity == Decimal("2.5")
    assert [q.field_name for q in build_clarifications(first)] == ["unit"]
    final = answer_first(first, "кг")
    assert build_clarifications(final) == []
    assert final.validate() is final
    assert final.items[0].constraints == ["для ресторана"]
    assert final.items[0].evidence["quantity"].verified
    assert final.items[0].evidence["unit"].quote == "кг"
    assert final.items[0].evidence["product_name"] == snapshot.items[0].evidence["product_name"]
    assert final.items[0].model_payload == payload
    assert source == snapshot
    assert source.items[0].evidence == snapshot.items[0].evidence


def test_multiple_items_and_unconfirmed_guess_keep_provenance() -> None:
    source = extract("горбуша 2 кг, кальмар для ресторана", [
        {"product_name": "горбуша", "quantity": "2", "unit": "кг"},
        {"product_name": "кальмар", "quantity": "77", "unit": "ящик", "constraints": ["для ресторана"]},
    ])
    original = deepcopy(source)
    assert source.items[1].unknown_fields == ["quantity", "unit"]
    with pytest.raises(ValueError, match="Unconfirmed"):
        deepcopy(source).validate()
    old_evidence = deepcopy(source.items[1].evidence)
    first = answer_first(source, "3.5")
    final = answer_first(first, "кг")
    assert final.validate() is final
    assert not build_clarifications(final)
    assert final.items[0] == original.items[0]
    assert final.items[0].evidence == original.items[0].evidence
    assert final.items[1].unknown_fields == []
    assert final.items[1].model_payload["quantity"] == "77"
    assert final.items[1].evidence_history["quantity"] == [old_evidence["quantity"]]
    assert final.items[1].evidence_history["unit"] == [old_evidence["unit"]]
    assert source.items[1].evidence == old_evidence
    assert source == original


def test_unknown_product_can_be_confirmed_with_different_name() -> None:
    source = extract("нужна рыба 2 кг", [{"product_name": "тунец", "quantity": "2", "unit": "кг"}])
    assert [q.field_name for q in build_clarifications(source)] == ["product_name"]
    final = answer_first(source, "горбуша")
    assert final.items[0].product_name == "горбуша"
    assert final.items[0].model_payload["product_name"] == "тунец"
    assert final.items[0].evidence_history["product_name"][0].verified is False
    assert final.validate() is final


@pytest.mark.parametrize("items", [[], [{"product_name": None, "quantity": None, "unit": None}]])
def test_no_known_product_full_cycle(items: list[dict]) -> None:
    state = extract("Здравствуйте", items)
    with pytest.raises(ValueError):
        deepcopy(state).validate()
    for value in ("горбуша", "2.5", "кг"):
        state = answer_first(state, value)
    assert state.validate() is state
    assert not build_clarifications(state)


@pytest.mark.parametrize("bad", ["много", "0", "-1", "NaN", "Infinity", True, [], {}])
def test_invalid_response_does_not_change_partial_state(bad: object) -> None:
    source = extract("горбуша", [{"product_name": "горбуша"}])
    snapshot = deepcopy(source)
    result = apply_clarification_answer(source, build_clarifications(source)[0], {"value": bad})
    assert result.status == "invalid"
    assert result.needs == snapshot
    assert source == snapshot
    assert result.needs.items[0].evidence == snapshot.items[0].evidence
    assert result.next_questions == build_clarifications(source)


@pytest.mark.parametrize("field,value", [
    ("quantity", "0"), ("quantity", "NaN"), ("quantity", True),
    ("product_name", []), ("unit", 42),
])
def test_partial_extractor_rejects_invalid_supplied_values(field: str, value: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        extract("горбуша", [{"product_name": "горбуша", field: value}])


def test_confirmation_of_same_guess_updates_metadata() -> None:
    source = extract("горбуша", [{"product_name": "горбуша", "quantity": "3.5"}])
    result = answer_first(source, "3.5")
    assert result.items[0].quantity == Decimal("3.5")
    assert "quantity" not in result.items[0].unknown_fields
    assert result.items[0].evidence["quantity"].verified
    assert "quantity" in source.items[0].unknown_fields


def test_confirmed_data_conflict_preserves_evidence() -> None:
    source = extract("горбуша 2 кг", [{"product_name": "горбуша", "quantity": "2", "unit": "кг"}])
    from kp_plugin.llm.clarify import Clarification

    result = apply_clarification_answer(source, Clarification("quantity", 1), {"value": "3.5"})
    assert result.status == "conflict"
    assert result.needs.items[0].evidence == source.items[0].evidence
    assert result.needs.items[0].quantity == Decimal("2.0")


def test_partial_validation_preserves_unknown_metadata() -> None:
    state = CustomerNeeds(items=[CustomerNeedItem("горбуша", None, None)], unknown_fields=["delivery_address"])
    assert state.validate_partial().unknown_fields == ["delivery_address"]
