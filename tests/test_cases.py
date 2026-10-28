"""Real P4 references + abstract contract examples, not invented success stories."""

from datetime import date
from pathlib import Path

import pytest

from kp_plugin.llm.cases import (
    CaseLink,
    CaseRecord,
    CaseStatus,
    CommercialPermission,
    case_links_from_p4,
    select_cases,
)
from kp_plugin.llm.p4_catalog import load_p4_catalog
from kp_plugin.llm.selection import SelectionSource


def source(locator: str = "case-record") -> SelectionSource:
    return SelectionSource(source_id="test-contract", version="v1", locator=locator)


def link(product: str = "P1", **overrides: object) -> CaseLink:
    return CaseLink(**({"case_id": "C1", "product_id": product, "source": source("catalog-link"),
                       "confirmed": True} | overrides))


def record(**overrides: object) -> CaseRecord:
    return CaseRecord(**({"case_id": "C1", "product_ids": ("P1",), "task_descriptions": ("Проверка задачи клиента",),
                         "content": "Абстрактное содержимое для проверки контракта, без утверждения об успехе.",
                         "sources": (source(),), "status": CaseStatus.VERIFIED, "source_confirmed": True,
                         "content_confirmed": True, "is_fictional": False,
                         "usage_limits": ("Только согласованное содержание.",)} | overrides))


def test_explicit_product_and_task_links_with_confirmed_content() -> None:
    result = select_cases(("P1",), (link(),),
                          (record(commercial_permission=CommercialPermission.ALLOWED, usage_limits_reviewed=True),),
                          client_task="  ПРОВЕРКА   задачи клиента ")[0]
    assert result.status == CaseStatus.VERIFIED
    assert result.commercial_use_allowed
    assert len(result.relevance_basis) == 2
    assert result.sources == (source("catalog-link"), source())
    assert result.usage_limits == ("Только согласованное содержание.",)


def test_unresolved_case_never_invents_content() -> None:
    result = select_cases(("P1",), (link(),))[0]
    assert result.case_id == "C1"
    assert result.status == CaseStatus.UNAVAILABLE
    assert result.reasons == ("unresolved_case_reference",)
    assert not result.commercial_use_allowed
    assert "content" not in result.model_dump()


@pytest.mark.parametrize("overrides,reason", [
    ({"sources": ()}, "source_unconfirmed"), ({"source_confirmed": False}, "source_unconfirmed"),
    ({"content": None}, "content_unconfirmed"), ({"content_confirmed": False}, "content_unconfirmed"),
    ({"is_fictional": True}, "synthetic_case"), ({"status": CaseStatus.NEEDS_REVIEW}, "record_not_verified"),
    ({"task_descriptions": ()}, "task_relevance_unconfirmed"),
])
def test_unconfirmed_case_is_review_only(overrides: dict, reason: str) -> None:
    result = select_cases(("P1",), (link(),), (record(**overrides),), client_task="Проверка задачи клиента")[0]
    assert result.status == CaseStatus.NEEDS_REVIEW
    assert reason in result.reasons
    assert not result.commercial_use_allowed
    assert len(result.usage_limits) > 1


@pytest.mark.parametrize("task", ["Проверка", "задачи", "Ресторан", "Проверка задачи клиента с доставкой"])
def test_keyword_or_category_overlap_is_not_relevance(task: str) -> None:
    result = select_cases(("P1",), (link(),), (record(),), client_task=task)[0]
    assert result.status == CaseStatus.UNAVAILABLE
    assert "task_not_relevant" in result.reasons


@pytest.mark.parametrize("task", [None, "", "  "])
def test_missing_task_stays_unconfirmed(task: str | None) -> None:
    result = select_cases(("P1",), (link(),), (record(),), client_task=task)[0]
    assert result.status == CaseStatus.NEEDS_REVIEW


def test_unconfirmed_link_blocks_verified_case() -> None:
    result = select_cases(("P1",), (link(confirmed=False),), (record(),), client_task="Проверка задачи клиента")[0]
    assert result.status == CaseStatus.NEEDS_REVIEW
    assert "catalog_link_unconfirmed" in result.reasons


def test_case_must_support_reverse_product_link() -> None:
    result = select_cases(("P1",), (link(),), (record(product_ids=("P2",)),), client_task="Проверка задачи клиента")[0]
    assert result.status == CaseStatus.UNAVAILABLE
    assert "product_link_not_supported_by_case" in result.reasons


def test_multiple_products_deduplicate_per_product_but_keep_sources() -> None:
    second_source = source("second-reference")
    links = (link(), link(), link(source=second_source), link("P2"))
    result = select_cases(("P1", "P2", "P1"), links, (record(product_ids=("P1", "P2")),),
                          client_task="Проверка задачи клиента")
    assert [(match.product_id, match.case_id) for match in result] == [("P1", "C1"), ("P2", "C1")]
    assert second_source in result[0].sources
    assert all(match.status == CaseStatus.VERIFIED for match in result)


def test_no_reference_means_no_case_search_or_inference() -> None:
    result = select_cases(("P1",), (), (record(),), client_task="Проверка задачи клиента")[0]
    assert result.status == CaseStatus.UNAVAILABLE
    assert result.case_id is None
    assert result.reasons == ("no_case_reference",)


def test_duplicate_case_ids_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        select_cases(("P1",), (link(),), (record(), record()))


def test_original_records_unchanged_and_no_automatic_offer_insertion() -> None:
    original_link, original_record = link(), record(is_fictional=True)
    before = original_link.model_dump_json(), original_record.model_dump_json()
    result = select_cases(("P1",), (original_link,), (original_record,), client_task="Проверка задачи клиента")
    assert (original_link.model_dump_json(), original_record.model_dump_json()) == before
    assert not result[0].commercial_use_allowed


def test_actual_p4_has_only_unresolved_synthetic_references() -> None:
    root = Path(__file__).parent / "fixtures/p4_synthetic"
    catalog_path, stock_path = root / "catalog/catalog.csv", root / "prices_stock/warehouse_stock.csv"
    before = catalog_path.read_bytes(), stock_path.read_bytes()
    profile = load_p4_catalog(catalog_path, stock_path, as_of=date(2026, 10, 28))
    links = case_links_from_p4(profile)
    assert len(links) == 2
    assert {item.case_id for item in links} == {"TEST-CASE-001", "TEST-CASE-002"}
    assert not any(item.confirmed for item in links)
    result = select_cases(tuple(product.product_id for product in profile.products), links)
    assert len(result) == 3
    assert sum("unresolved_case_reference" in match.reasons for match in result) == 2
    assert all(match.status == CaseStatus.UNAVAILABLE for match in result)
    assert (catalog_path.read_bytes(), stock_path.read_bytes()) == before
