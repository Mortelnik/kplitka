"""P3.6: генератор КП и адаптер P2 -> DOCX."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from docx import Document

from kp_plugin.docgen.builder import (
    OfferPosition,
    OfferPresentation,
    build_offer_document,
)

VALID_RESULT = {
    "product": "Семга Atlantic, филе без кожи",
    "product_source": "catalog.csv#product_id=SALMON-ATL-01",
    "price_source": "price.csv#price_id=PRICE-ATL-01",
    "containers": 1,
    "pickup_tons": Decimal("1.50"),
    "base_amount": Decimal("10_500_000.00"),
    "discount_rule": "без скидки",
    "discount_amount": Decimal("0.00"),
    "tax": Decimal("2_100_000.00"),
    "total": Decimal("12_600_000.00"),
}


def _document_text(path: Path) -> str:
    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            paragraphs.extend(cell.text for cell in row.cells)
    return "\n".join(paragraphs)


def test_build_offer_document_success(tmp_path):
    output_path = tmp_path / "offer.docx"

    result = build_offer_document(VALID_RESULT, output_path)

    assert result == output_path
    assert output_path.exists()
    text = _document_text(output_path)
    assert "Семга Atlantic, филе без кожи" in text
    assert "Источники" in text
    assert "catalog.csv#product_id=SALMON-ATL-01" in text


def test_build_offer_document_p2_error_string(tmp_path):
    output_path = tmp_path / "broken.docx"

    with pytest.raises(TypeError, match="Ошибка расчёта"):
        build_offer_document("Ошибка: продукт не найден", output_path)

    assert not output_path.exists()


def test_build_offer_document_missing_required_field(tmp_path):
    output_path = tmp_path / "missing.docx"
    invalid = dict(VALID_RESULT)
    invalid.pop("total")

    with pytest.raises(ValueError, match="Отсутствует обязательное поле"):
        build_offer_document(invalid, output_path)

    assert not output_path.exists()


def test_build_offer_document_total_matches_p2(tmp_path):
    output_path = tmp_path / "total_check.docx"

    build_offer_document(VALID_RESULT, output_path)

    text = _document_text(output_path)
    assert "12 600 000,00 ₽" in text
    assert str(VALID_RESULT["total"]) in text or "12 600 000,00 ₽" in text


SINGLE_ITEM_TEST_SCENARIO = OfferPresentation(
    document_date="2026-10-26",
    seller={"name": "ООО «Калитка»", "role": "Продавец"},
    buyer={"name": "ООО «Лесная Гавань»", "role": "Покупатель"},
    client_task="Нужна поставка филе лосося для сезонного производства в течение месяца.",
    proposed_solution="Предлагаем поставку одной партии филе Atlantic в согласованные сроки.",
    items=[
        OfferPosition(
            product="Семга Atlantic, филе без кожи",
            quantity=Decimal("1.50"),
            unit="т",
            unit_price=Decimal("7_000_000.00"),
            line_total=Decimal("10_500_000.00"),
        )
    ],
    totals={
        "base_amount": Decimal("10_500_000.00"),
        "discount_amount": Decimal("0.00"),
        "tax": Decimal("2_100_000.00"),
        "total": Decimal("12_600_000.00"),
    },
    delivery_terms=["Поставка в течение 10 рабочих дней после подтверждения заказа."],
    contacts=["Иван Петров — sales@kalitka-demo.local | +7 (900) 000-00-00"],
    is_test_data=True,
    source_note="Демонстрационный сценарий: тестовые данные, расчёт P2 не подтверждён.",
)


MULTI_ITEM_VIEW = OfferPresentation(
    document_date="2026-10-26",
    seller={"name": "ООО «Калитка»", "role": "Продавец"},
    buyer={"name": "ООО «Лесная Гавань»", "role": "Покупатель"},
    client_task="Нужны поставки рыбы для сезонной переработки в течение месяца.",
    proposed_solution="Предлагаем согласовать поставку двух лотов с фиксированной логистикой и сроками отгрузки.",
    items=[
        OfferPosition(
            product="Семга Atlantic, филе без кожи",
            quantity=Decimal("1.50"),
            unit="т",
            unit_price=Decimal("7_000_000.00"),
            line_total=Decimal("10_500_000.00"),
        ),
        OfferPosition(
            product="Треска северная, филе",
            quantity=Decimal("2.00"),
            unit="т",
            unit_price=Decimal("5_500_000.00"),
            line_total=Decimal("11_000_000.00"),
        ),
    ],
    totals={
        "base_amount": Decimal("21_500_000.00"),
        "discount_amount": Decimal("1_075_000.00"),
        "tax": Decimal("4_085_000.00"),
        "total": Decimal("24_510_000.00"),
    },
    delivery_terms=["Доставка — по согласованному графику, отгрузка по согласованию."],
    contacts=["Иван Петров — sales@kalitka-demo.local | +7 (900) 000-00-00"],
    technical_summary={
        "note": "Это демонстрационный многострочный сценарий P3, не расчёт P2.",
        "source_ids": ["catalog.csv#id=SALMON-ATL-01", "price.csv#id=PRICE-ATL-01"],
    },
    is_test_data=True,
    source_note="Тестовый многопозиционный макет, расчёт P2 не подтверждён.",
)

THREE_ITEM_TEST_VIEW = OfferPresentation(
    document_date="2026-10-26",
    seller={"name": "ООО «Калитка»", "role": "Продавец"},
    buyer={"name": "ООО «Лесная Гавань»", "role": "Покупатель"},
    client_task="Нужны поставки рыбы на сезонный выпуск продукции.",
    proposed_solution="Предлагаем три лота по согласованному графику и фиксированной цене.",
    items=[
        OfferPosition(product="Семга Atlantic, филе без кожи", quantity=Decimal("1.50"), unit="т", unit_price=Decimal("7_000_000.00"), line_total=Decimal("10_500_000.00")),
        OfferPosition(product="Треска северная, филе", quantity=Decimal("2.00"), unit="т", unit_price=Decimal("5_500_000.00"), line_total=Decimal("11_000_000.00")),
        OfferPosition(product="Лосось тихоокеанский, филе", quantity=Decimal("1.00"), unit="т", unit_price=Decimal("6_200_000.00"), line_total=Decimal("6_200_000.00")),
    ],
    totals={
        "base_amount": Decimal("27_700_000.00"),
        "discount_amount": Decimal("1_385_000.00"),
        "tax": Decimal("5_262_000.00"),
        "total": Decimal("31_577_000.00"),
    },
    delivery_terms=["Поставка в течение 12 рабочих дней после согласования заказа."],
    contacts=["Марина Соколова — sales@kalitka-demo.local | +7 (900) 000-00-01"],
    is_test_data=True,
    source_note="Тестовый сценарий на 3 позиции: расчёт P2 не подтверждён.",
)


def test_build_offer_document_multi_position_offer_view(tmp_path):
    output_path = tmp_path / "multi_offer.docx"

    path = build_offer_document(MULTI_ITEM_VIEW, output_path)

    assert path == output_path
    assert output_path.exists()
    text = _document_text(output_path)
    assert "Коммерческое предложение" in text
    assert "Семга Atlantic, филе без кожи" in text
    assert "Треска северная, филе" in text
    assert "24 510 000,00 ₽" in text
    assert "catalog.csv" not in text
    assert "price.csv" not in text


def test_build_offer_document_three_item_test_view(tmp_path):
    output_path = tmp_path / "three_item_test.docx"

    path = build_offer_document(THREE_ITEM_TEST_VIEW, output_path)

    assert path == output_path
    text = _document_text(output_path)
    assert "Семга Atlantic, филе без кожи" in text
    assert "Треска северная, филе" in text
    assert "Лосось тихоокеанский, филе" in text
    assert "31 577 000,00 ₽" in text
    assert "тестовый сценарий" in text.lower()
    assert "p2 не подтверждён" in text.lower()
    assert "catalog.csv" not in text
    assert "price.csv" not in text


def test_offer_presentation_rejects_base_amount_mismatch():
    presentation = OfferPresentation(
        document_date="2026-10-26",
        client_task="N",
        proposed_solution="S",
        items=[
            OfferPosition(product="A", quantity=Decimal(1), unit="т", line_total=Decimal("50.00")),
            OfferPosition(product="B", quantity=Decimal(2), unit="т", line_total=Decimal("60.00")),
        ],
        totals={
            "base_amount": Decimal("200.00"),
            "discount_amount": Decimal("0.00"),
            "tax": Decimal("0.00"),
            "total": Decimal("200.00"),
        },
    )

    with pytest.raises(ValueError, match="base_amount|сумме строк|сумма строк"):
        presentation.validate()


def test_offer_presentation_total_matches_sum_of_all_positions():
    total = sum((item.line_total for item in THREE_ITEM_TEST_VIEW.items), Decimal("0.00"))
    assert total == THREE_ITEM_TEST_VIEW.totals["base_amount"]
    assert total == Decimal("27_700_000.00")


def test_build_offer_document_requires_required_offer_view_fields(tmp_path):
    output_path = tmp_path / "bad_view.docx"
    invalid = OfferPresentation(
        document_date="2026-10-26",
        seller={"name": "ООО «Калитка»"},
        buyer={"name": "ООО «Лесная Гавань»"},
        client_task="Нужна поставка.",
        proposed_solution="Предлагаем решение.",
        items=[OfferPosition(product="Товар", quantity=Decimal(1), unit="т", line_total=Decimal(100))],
        totals={"base_amount": Decimal(100), "discount_amount": Decimal(0), "tax": Decimal(20), "total": Decimal(120)},
    )
    invalid.items[0].product = ""

    with pytest.raises(ValueError, match="Обязательное поле|обязательное поле"):
        build_offer_document(invalid, output_path)

    assert not output_path.exists()


def test_demo_scenario_is_marked_as_test_data_and_self_consistent():
    demo = SINGLE_ITEM_TEST_SCENARIO
    demo.validate()

    assert demo.is_test_data is True
    assert "не подтверждён" in (demo.source_note or "")
    assert demo.items[0].line_total == demo.totals["base_amount"]
    assert demo.totals["total"] == demo.totals["base_amount"] - demo.totals["discount_amount"] + demo.totals["tax"]


def test_real_p2_reference_if_available():
    try:
        from kp_plugin.engine.calculation import calculate_offer  # type: ignore
    except ImportError:
        # Execute unchanged, checksum-verified published P2 while production remains a stub.
        from test_p2_published import core as published_core
        calculate_offer = published_core.__wrapped__()

    # When contract becomes available, it should be checked against the same single-item etalon.
    reference = calculate_offer(
        product_id="SALMON-ATL-01",
        quantity_tons=Decimal("1.50"),
        catalog={"SALMON-ATL-01": {"name": "Семга Atlantic, филе без кожи", "container_capacity_tons": "26",
                                   "source_ref": VALID_RESULT["product_source"]}},
        # Rate derived ONLY from this existing educational etalon's tax/base (20%), not a new business rule.
        prices={"SALMON-ATL-01": {"unit_price_rub_per_t": "7000000",
                                  "tax_rate": str(VALID_RESULT["tax"] / VALID_RESULT["base_amount"]),
                                  "source_ref": VALID_RESULT["price_source"]}},
        rules={"discounts": {"rules": []}},
    )
    assert isinstance(reference, dict)
    assert reference["base_amount"] == SINGLE_ITEM_TEST_SCENARIO.totals["base_amount"]
    for field in ("discount_amount", "tax", "total"):
        assert isinstance(reference[field], Decimal)
        assert reference[field] == SINGLE_ITEM_TEST_SCENARIO.totals[field]
    assert reference["product_source"] == VALID_RESULT["product_source"]
    assert reference["price_source"] == VALID_RESULT["price_source"]


def test_build_offer_document_rejects_technical_ids_in_customer_doc(tmp_path):
    output_path = tmp_path / "technical_ids.docx"

    build_offer_document(MULTI_ITEM_VIEW, output_path)

    text = _document_text(output_path)
    assert "catalog.csv" not in text
    assert "price.csv" not in text
    assert "source_ids" not in text
    assert "Техническая сводка" not in text
