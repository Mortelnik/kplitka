from __future__ import annotations

from decimal import Decimal

import pytest

from kp_plugin.llm.clarify import (
    Clarification,
    apply_clarification_answer,
    build_clarifications,
    determine_missing_fields,
)
from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds


def test_single_item_full_cycle_preserves_source_and_finishes() -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=None, unit=None)])
    questions = build_clarifications(needs)
    assert [(q.field_name, q.position) for q in questions] == [("quantity", 1), ("unit", 1)]
    first = apply_clarification_answer(needs, questions[0], {"value": Decimal("2.5")})
    assert first.status == "updated"
    assert needs.items[0].quantity is None
    assert first.needs.items[0].product_name == "Лосось"
    assert [(q.field_name, q.position) for q in first.next_questions] == [("unit", 1)]
    final = apply_clarification_answer(first.needs, first.next_questions[0], {"value": "т"})
    assert final.status == "updated"
    assert final.needs.items[0] == CustomerNeedItem(product_name="Лосось", quantity=Decimal("2.5"), unit="т")
    assert first.needs.items[0].unit is None
    assert final.next_questions == build_clarifications(final.needs) == []
    assert final.needs.validate() == final.needs


def test_multiple_items_full_cycle_does_not_reask_known_fields() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Лосось", quantity=Decimal("2.0"), unit="т"),
            CustomerNeedItem(product_name="Треска", quantity=None, unit=None),
            CustomerNeedItem(product_name=None, quantity=Decimal("10.0"), unit="кг"),
        ],
        delivery_address="Москва", desired_deadline="ноябрь", budget_limit=Decimal("100000.0"),
        constraints=["самовывоз"],
    )
    state = needs
    for field_name, position, value in [("quantity", 2, Decimal("3.0")), ("unit", 2, "т"), ("product_name", 3, "Кальмар")]:
        question = build_clarifications(state)[0]
        assert (question.field_name, question.position) == (field_name, position)
        assert question.question
        result = apply_clarification_answer(state, question, {"value": value})
        assert result.status == "updated"
        assert result.needs.items[0] == needs.items[0]
        for known in ("delivery_address", "desired_deadline", "budget_limit", "constraints"):
            assert getattr(result.needs, known) == getattr(needs, known)
        assert (field_name, position) not in [(q.field_name, q.position) for q in result.next_questions]
        state = result.needs
    assert build_clarifications(state) == []
    assert state.validate() == state
    assert needs.items[1].quantity is None
    assert needs.items[2].product_name is None


@pytest.mark.parametrize("field_name,value", [
    ("budget_limit", Decimal("1000.0")), ("desired_deadline", "ноябрь"), ("delivery_address", "Москва"),
])
def test_optional_field_cycle_requires_explicit_configuration(field_name: str, value: object) -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=Decimal("2.0"), unit="т")])
    assert build_clarifications(needs) == []
    required = {"product_name", "quantity", "unit", field_name}
    questions = build_clarifications(needs, required)
    assert [(q.field_name, q.position) for q in questions] == [(field_name, None)]
    result = apply_clarification_answer(needs, questions[0], {"value": value}, required)
    assert result.status == "updated"
    assert getattr(result.needs, field_name) == value
    assert getattr(needs, field_name) is None
    assert result.next_questions == build_clarifications(result.needs, required) == []


@pytest.mark.parametrize("answer", [{}, {"unexpected": "2"}, {"value": None}, {"value": "  "}])
def test_bad_payload_can_be_retried_then_cycle_finishes(answer: dict) -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=None, unit="т")])
    question = build_clarifications(needs)[0]
    rejected = apply_clarification_answer(needs, question, answer)
    assert rejected.status == "clarify"
    assert rejected.needs == needs
    assert rejected.next_questions == [question]
    accepted = apply_clarification_answer(rejected.needs, rejected.next_questions[0], {"value": Decimal("2.0")})
    assert accepted.status == "updated"
    assert accepted.next_questions == []


def test_conflicting_repeated_answer_preserves_progress() -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=None, unit=None)])
    question = build_clarifications(needs)[0]
    first = apply_clarification_answer(needs, question, {"value": Decimal("2.0")})
    conflict = apply_clarification_answer(first.needs, question, {"value": Decimal("3.0")})
    assert conflict.status == "conflict"
    assert conflict.needs == first.needs
    assert conflict.next_questions == first.next_questions
    final = apply_clarification_answer(conflict.needs, conflict.next_questions[0], {"value": "т"})
    assert final.needs.items[0].quantity == Decimal("2.0")
    assert final.next_questions == []


@pytest.mark.parametrize("value", ["много", Decimal("0.0"), Decimal("-1.0"), Decimal("NaN"), True, []])
def test_invalid_quantity_must_not_complete_cycle(value: object) -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=None, unit="т")])
    question = build_clarifications(needs)[0]
    result = apply_clarification_answer(needs, question, {"value": value})
    assert result.status in {"invalid", "clarify"}
    assert result.needs == needs
    assert result.next_questions == [question]


def test_empty_product_list_answer_creates_position_and_advances() -> None:
    needs = CustomerNeeds(items=[])
    question = build_clarifications(needs)[0]
    result = apply_clarification_answer(needs, question, {"value": "Лосось"})
    assert result.status == "updated"
    assert len(result.needs.items) == 1
    assert result.needs.items[0].product_name == "Лосось"
    assert [(q.field_name, q.position) for q in result.next_questions] == [("quantity", 1), ("unit", 1)]


def test_blank_known_value_can_be_filled_in_cycle() -> None:
    needs = CustomerNeeds(items=[CustomerNeedItem(product_name="Лосось", quantity=Decimal("2.0"), unit=" ")])
    question = build_clarifications(needs)[0]
    result = apply_clarification_answer(needs, question, {"value": "т"})
    assert result.status == "updated"
    assert result.needs.items[0].unit == "т"
    assert result.next_questions == []


def test_default_requires_only_product_quantity_and_unit() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Лосось", quantity=Decimal(2), unit="т"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    assert build_clarifications(needs) == []
    assert determine_missing_fields(needs) == []


def test_missing_product_name_is_flagged() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name=None, quantity=Decimal(2), unit="т"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarifications = build_clarifications(needs)

    assert clarifications == [
        Clarification(
            field_name="product_name",
            position=1,
            question="Уточните товар для позиции 1. Что именно нужно купить?",
        )
    ]


def test_multiple_positions_are_identified_by_number() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Семга", quantity=Decimal("1.5"), unit="т"),
            CustomerNeedItem(product_name="Треска", quantity=Decimal(3), unit=None),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarifications = build_clarifications(needs)

    assert clarifications == [
        Clarification(
            field_name="unit",
            position=2,
            question="Укажите единицу измерения для позиции 2.",
        )
    ]


def test_optional_fields_are_only_requested_when_required() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Кальмар", quantity=Decimal(10), unit="кг"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarifications = build_clarifications(needs, required_fields={"product_name", "quantity", "unit", "delivery_address"})

    assert clarifications == [
        Clarification(
            field_name="delivery_address",
            position=None,
            question="Укажите адрес доставки.",
        )
    ]


def test_no_product_positions_generates_generic_question() -> None:
    needs = CustomerNeeds(
        items=[],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarifications = build_clarifications(needs)

    assert clarifications == [
        Clarification(
            field_name="product_name",
            position=None,
            question="Уточните товар. Что именно нужно купить?",
        )
    ]


def test_apply_clarification_updates_missing_quantity_in_sequence() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Лосось", quantity=None, unit="т"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarification = Clarification(field_name="quantity", position=1, question="Укажите количество товара для позиции 1.")
    result = apply_clarification_answer(needs, clarification, {"value": Decimal(2)})

    assert result.status == "updated"
    assert result.needs.items[0].quantity == Decimal(2)
    assert result.next_questions == []


def test_apply_clarification_keeps_other_items_and_known_values() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Семга", quantity=Decimal(1), unit="т"),
            CustomerNeedItem(product_name="Треска", quantity=Decimal(3), unit=None),
        ],
        delivery_address="Москва",
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarification = Clarification(field_name="unit", position=2, question="Укажите единицу измерения для позиции 2.")
    result = apply_clarification_answer(needs, clarification, {"value": "кг"})

    assert result.status == "updated"
    assert result.needs.items[0].unit == "т"
    assert result.needs.items[1].unit == "кг"
    assert result.needs.delivery_address == "Москва"


def test_apply_clarification_requires_follow_up_on_empty_response() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Кальмар", quantity=None, unit="кг"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarification = Clarification(field_name="quantity", position=1, question="Укажите количество товара для позиции 1.")
    result = apply_clarification_answer(needs, clarification, {"value": ""})

    assert result.status == "clarify"
    assert result.needs.items[0].quantity is None
    assert result.next_questions[0].field_name == "quantity"


def test_apply_clarification_rejects_conflicting_answer() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Лосось", quantity=Decimal(2), unit="т"),
        ],
        delivery_address="Москва",
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarification = Clarification(field_name="delivery_address", position=None, question="Укажите адрес доставки.")
    result = apply_clarification_answer(needs, clarification, {"value": "СПб"})

    assert result.status == "conflict"
    assert result.needs.delivery_address == "Москва"


def test_apply_clarification_rejects_invalid_position() -> None:
    needs = CustomerNeeds(
        items=[
            CustomerNeedItem(product_name="Форель", quantity=Decimal(5), unit="кг"),
        ],
        delivery_address=None,
        desired_deadline=None,
        budget_limit=None,
        constraints=[],
    )

    clarification = Clarification(field_name="unit", position=99, question="Не используется.")
    result = apply_clarification_answer(needs, clarification, {"value": "т"})

    assert result.status == "invalid"
    assert result.needs.items[0].unit == "кг"
