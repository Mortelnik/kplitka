from __future__ import annotations

from decimal import Decimal

import pytest

from kp_plugin.llm.needs import (
    CustomerNeedItem,
    CustomerNeeds,
    FakeLLMClient,
    NeedsExtractor,
    extract_customer_needs,
)


class DictClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def extract_needs(self, raw_text: str) -> dict:
        return self.payload


def test_extract_customer_needs_single_item():
    client = DictClient(
        {
            "items": [
                {
                    "product_name": "Лосось Atlantic",
                    "quantity": "2",
                    "unit": "т",
                    "desired_deadline": "до 15 ноября 2026",
                    "delivery_address": "Москва, склад на МКАД",
                    "budget_limit": "50000000",
                    "constraints": ["без предварительной оплаты"],
                }
            ],
            "delivery_address": "Москва, склад на МКАД",
            "budget_limit": "50000000",
            "desired_deadline": "до 15 ноября 2026",
            "constraints": ["без предварительной оплаты"],
        }
    )

    needs = extract_customer_needs("Нужны 2 т лосося Atlantic до 15 ноября 2026. Доставка в Москву, склад на МКАД. Бюджет до 50 млн. Без предоплаты.", client)

    assert needs.items[0].product_name == "Лосось Atlantic"
    assert needs.items[0].quantity == Decimal(2)
    assert needs.items[0].unit == "т"
    assert needs.budget_limit == Decimal(50000000)
    assert needs.delivery_address == "Москва, склад на МКАД"
    assert needs.constraints == ["без предварительной оплаты"]


def test_extract_customer_needs_multiple_items_and_no_guesses():
    client = DictClient(
        {
            "items": [
                {
                    "product_name": "Семга",
                    "quantity": "1.5",
                    "unit": "т",
                    "desired_deadline": None,
                    "delivery_address": None,
                    "budget_limit": None,
                    "constraints": ["для переработки"],
                },
                {
                    "product_name": "Треска",
                    "quantity": "3",
                    "unit": "т",
                    "desired_deadline": "до конца месяца",
                    "delivery_address": "СПб",
                    "budget_limit": None,
                    "constraints": ["без замораживания"],
                },
            ],
            "delivery_address": None,
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": ["нужен скорый ответ"],
        }
    )

    needs = extract_customer_needs("Нужно 1.5 т семги и 3 т трески. Скорый ответ.", client)

    assert len(needs.items) == 2
    assert needs.items[0].product_name == "Семга"
    assert needs.items[1].quantity == Decimal(3)
    assert needs.items[1].delivery_address is None
    assert "delivery_address" in needs.items[1].unknown_fields
    assert needs.items[0].budget_limit is None
    assert needs.items[0].desired_deadline is None


def test_extract_customer_needs_marks_unknown_fields_as_none():
    client = DictClient(
        {
            "items": [{
                "product_name": "Кальмар",
                "quantity": "1",
                "unit": "кг",
                "desired_deadline": None,
                "delivery_address": None,
                "budget_limit": None,
                "constraints": None,
            }],
            "delivery_address": None,
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": None,
        }
    )

    needs = extract_customer_needs("Купить кальмар.", client)

    assert needs.items[0].delivery_address is None
    assert needs.items[0].budget_limit is None
    assert needs.items[0].desired_deadline is None
    assert needs.delivery_address is None
    assert needs.budget_limit is None


def test_validation_rejects_missing_product_name():
    with pytest.raises(ValueError, match="product_name"):
        CustomerNeeds(
            items=[CustomerNeedItem(product_name="", quantity=Decimal(1), unit="т")],
            delivery_address=None,
            desired_deadline=None,
            budget_limit=None,
            constraints=[],
        ).validate()


def test_validation_rejects_invalid_quantity():
    with pytest.raises(ValueError, match="quantity"):
        CustomerNeeds(
            items=[CustomerNeedItem(product_name="Семга", quantity=None, unit="т")],
            delivery_address=None,
            desired_deadline=None,
            budget_limit=None,
            constraints=[],
        ).validate()


def test_validation_rejects_conflicting_delivery_and_items():
    with pytest.raises(ValueError, match="delivery_address"):
        CustomerNeeds(
            items=[
                CustomerNeedItem(product_name="Семга", quantity=Decimal(1), unit="т", delivery_address="Москва"),
            ],
            delivery_address="СПб",
            desired_deadline=None,
            budget_limit=None,
            constraints=[],
        ).validate()


def test_custom_llm_client_contract_is_used():
    class ExampleClient:
        def extract_needs(self, raw_text: str) -> dict:
            return {"items": [{"product_name": "Форель", "quantity": "4", "unit": "кг", "desired_deadline": None, "delivery_address": None, "budget_limit": None, "constraints": []}], "delivery_address": None, "budget_limit": None, "desired_deadline": None, "constraints": []}

    needs = NeedsExtractor(ExampleClient()).extract("Нужна форель 4 кг")

    assert needs.items[0].product_name == "Форель"
    assert needs.items[0].quantity == Decimal(4)


def test_fake_llm_client_returns_structured_payload():
    client = FakeLLMClient(
        {
            "items": [{"product_name": "Криль", "quantity": "10", "unit": "кг", "desired_deadline": None, "delivery_address": "Екатеринбург", "budget_limit": None, "constraints": ["не более 3 кг в коробке"]}],
            "delivery_address": "Екатеринбург",
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": ["не более 3 кг в коробке"],
        }
    )

    result = client.extract_needs("Нужен криль 10 кг в Екатеринбург")
    assert result["items"][0]["product_name"] == "Криль"
    assert result["delivery_address"] == "Екатеринбург"


def test_client_payload_missing_items_is_rejected():
    client = DictClient({"delivery_address": "Воронеж"})
    extractor = NeedsExtractor(client)

    with pytest.raises(ValueError, match="items"):
        extractor.extract("Нужны продукты")


def test_unknown_data_is_not_invented_from_not_provided_field_names():
    client = DictClient({
        "items": [{"product_name": "Горбуша", "quantity": "1", "unit": "т", "desired_deadline": None, "delivery_address": None, "budget_limit": None, "constraints": None}],
        "delivery_address": None,
        "budget_limit": None,
        "desired_deadline": None,
        "constraints": None,
    })
    needs = extract_customer_needs("Нужна горбуша 1 т.", client)
    assert needs.items[0].desired_deadline is None
    assert needs.items[0].delivery_address is None
    assert needs.items[0].budget_limit is None
    assert needs.unknown_fields == []


def test_extract_customer_needs_handles_list_of_constraints():
    client = DictClient({
        "items": [{"product_name": "Ставрида", "quantity": "5", "unit": "кг", "desired_deadline": "срок до 10.11", "delivery_address": None, "budget_limit": "100000", "constraints": ["сухой транспорт", "без заморозки"]}],
        "delivery_address": None,
        "budget_limit": "100000",
        "desired_deadline": "срок до 10.11",
        "constraints": ["сухой транспорт", "без заморозки"],
    })

    needs = extract_customer_needs("Нужна ставрида 5 кг до 10.11. Сухой транспорт, без заморозки. Бюджет 100000.", client)
    assert needs.constraints == ["сухой транспорт", "без заморозки"]
    assert needs.budget_limit == Decimal(100000)


@pytest.mark.parametrize(
    "text, expected_name, expected_units",
    [
        ("Нужны 2 т лосося и 1 т судака", "Лосось", "т"),
        ("Потребуется 500 кг креветок и 3 кг филе", "Креветки", "кг"),
        ("Заказ на 10 кг филе и 2 кг икры", "Филе", "кг"),
    ],
)
def test_request_examples_do_not_guess_unmentioned_products(text, expected_name, expected_units):
    client = DictClient(
        {
            "items": [
                {"product_name": expected_name, "quantity": "1", "unit": expected_units, "desired_deadline": None, "delivery_address": None, "budget_limit": None, "constraints": []}
            ],
            "delivery_address": None,
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": [],
        }
    )

    needs = extract_customer_needs(text, client)
    assert needs.items[0].product_name == expected_name
    assert needs.items[0].unit == expected_units


@pytest.mark.parametrize("bad_quantity", [0, -1, "0", "-1", float("nan"), float("inf")])
def test_quantity_must_be_positive_and_finite(bad_quantity):
    with pytest.raises(ValueError, match="quantity"):
        CustomerNeeds(
            items=[CustomerNeedItem(product_name="Семга", quantity=bad_quantity, unit="кг")],
            delivery_address=None,
            desired_deadline=None,
            budget_limit=None,
            constraints=[],
        ).validate()


@pytest.mark.parametrize("bad_budget", ["nan", "inf", "Infinity", "-1", "-0.01", float("nan")])
def test_budget_limit_must_be_non_negative_and_finite(bad_budget):
    with pytest.raises(ValueError, match="budget_limit"):
        CustomerNeedItem(
            product_name="Семга",
            quantity="1",
            unit="кг",
            budget_limit=bad_budget,
        ).validate()


def test_empty_raw_text_is_rejected():
    client = DictClient({"items": [{"product_name": "Семга", "quantity": "1", "unit": "кг"}]})
    with pytest.raises(ValueError, match="raw_text"):
        extract_customer_needs("   ", client)


def test_wrong_client_payload_type_is_rejected():
    client = DictClient(123)
    with pytest.raises(TypeError, match="dict|JSON"):
        NeedsExtractor(client).extract("Нужна семга 1 кг")


def test_malformed_json_from_client_is_rejected():
    class JsonClient:
        def extract_needs(self, raw_text: str):
            return '{"items": [}'

    with pytest.raises(ValueError, match="Malformed JSON|JSON"):
        extract_customer_needs("Нужна семга 1 кг", JsonClient())


def test_invented_facts_without_evidence_are_marked_unknown():
    client = DictClient(
        {
            "items": [{
                "product_name": "Тунец",
                "quantity": "2",
                "unit": "кг",
                "desired_deadline": None,
                "delivery_address": "Санкт-Петербург",
                "budget_limit": None,
                "constraints": [],
            }],
            "delivery_address": "Санкт-Петербург",
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": [],
        }
    )

    needs = extract_customer_needs("Нужны 2 кг лосося.", client)
    assert needs.items[0].product_name == "Тунец"
    assert "product_name" in needs.items[0].unknown_fields
    assert "delivery_address" in needs.items[0].unknown_fields
    assert needs.items[0].delivery_address is None


def test_invalid_evidence_fragments_are_marked_unknown():
    client = DictClient(
        {
            "items": [{
                "product_name": "Горбуша",
                "quantity": "1",
                "unit": "т",
                "desired_deadline": "до 10 ноября 2026",
                "delivery_address": "Пермь",
                "budget_limit": None,
                "constraints": [],
            }],
            "delivery_address": "Пермь",
            "budget_limit": None,
            "desired_deadline": "до 10 ноября 2026",
            "constraints": [],
        }
    )

    needs = extract_customer_needs("Нужна горбуша 1 т.", client)
    assert needs.items[0].product_name == "Горбуша"
    assert "delivery_address" in needs.items[0].unknown_fields
    assert "desired_deadline" in needs.items[0].unknown_fields


def test_multiple_items_are_extracted_without_guessing_unknowns():
    client = DictClient(
        {
            "items": [
                {"product_name": "Лосось", "quantity": "2", "unit": "т", "desired_deadline": None, "delivery_address": None, "budget_limit": None, "constraints": []},
                {"product_name": "Кальмар", "quantity": "1", "unit": "кг", "desired_deadline": "до 15 ноября", "delivery_address": "Москва", "budget_limit": None, "constraints": ["без упаковки"]},
            ],
            "delivery_address": None,
            "budget_limit": None,
            "desired_deadline": None,
            "constraints": [],
        }
    )

    needs = extract_customer_needs("Нужны 2 т лосося и 1 кг кальмара до 15 ноября в Москву. Без упаковки.", client)
    assert [item.product_name for item in needs.items] == ["Лосось", "Кальмар"]
    assert needs.items[0].quantity == Decimal(2)
    assert needs.items[1].delivery_address == "Москва"
    assert needs.items[0].delivery_address is None
    assert needs.items[1].constraints == ["без упаковки"]
