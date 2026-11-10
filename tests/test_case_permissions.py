"""Commercial permission is independent of credibility and free-text limits."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from kp_plugin.llm.cases import (
    CaseLink,
    CaseMatch,
    CaseRecord,
    CaseStatus,
    CommercialPermission,
    case_links_from_p4,
    select_cases,
)
from kp_plugin.llm.p4_catalog import load_p4_catalog
from kp_plugin.llm.selection import SelectionSource


def record(**overrides: object) -> CaseRecord:
    source = SelectionSource(source_id="test", version="v1", locator="case")
    return CaseRecord(**({
        "case_id": "C1", "product_ids": ("P1",), "task_descriptions": ("task",),
        "content": "Abstract contract fixture", "sources": (source,),
        "source_confirmed": True, "content_confirmed": True,
        "is_fictional": False, "status": CaseStatus.VERIFIED,
    } | overrides))


def match(item: CaseRecord) -> CaseMatch:
    link = CaseLink(case_id="C1", product_id="P1", source=item.sources[0], confirmed=True)
    return select_cases(("P1",), (link,), (item,), client_task="task")[0]


@pytest.mark.parametrize("permission,allowed", [
    (CommercialPermission.ALLOWED, True), (CommercialPermission.PROHIBITED, False),
    (CommercialPermission.UNKNOWN, False),
])
def test_verified_permission_matrix(permission: CommercialPermission, allowed: bool) -> None:
    result = match(record(commercial_permission=permission))
    assert result.status == CaseStatus.VERIFIED
    assert result.commercial_permission == permission
    assert result.commercial_use_allowed is allowed


@pytest.mark.parametrize("status", [CaseStatus.NEEDS_REVIEW, CaseStatus.UNAVAILABLE])
def test_allowed_does_not_override_credibility(status: CaseStatus) -> None:
    result = match(record(status=status, commercial_permission=CommercialPermission.ALLOWED))
    assert result.status == status
    assert not result.commercial_use_allowed


def test_legacy_record_without_permission_defaults_to_unknown() -> None:
    item = record()
    result = match(item)
    assert item.commercial_permission == CommercialPermission.UNKNOWN
    assert result.status == CaseStatus.VERIFIED
    assert not result.commercial_use_allowed
    assert "commercial_permission_unknown" in result.reasons


@pytest.mark.parametrize("text", ["Commercial use prohibited", "Только согласованное содержание.",
                                  "Commercial use allowed", "Any arbitrary text"])
def test_any_unreviewed_text_blocks_allowed_without_parsing(text: str) -> None:
    item = record(commercial_permission=CommercialPermission.ALLOWED, usage_limits=(text,))
    before = item.model_dump_json()
    result = match(item)
    assert result.status == CaseStatus.VERIFIED
    assert not result.commercial_use_allowed
    assert "usage_limits_require_manual_review" in result.reasons
    assert result.usage_limits == (text,)
    assert item.model_dump_json() == before


def test_manual_compatibility_confirmation_can_allow_text_limited_use() -> None:
    limits = ("Только согласованное содержание.",)
    result = match(record(commercial_permission=CommercialPermission.ALLOWED,
                          usage_limits=limits, usage_limits_reviewed=True))
    assert result.commercial_use_allowed
    assert result.usage_limits == limits


@pytest.mark.parametrize("reviewed", [False, True])
def test_explicit_conflict_always_blocks_even_after_review(reviewed: bool) -> None:
    result = match(record(commercial_permission=CommercialPermission.ALLOWED, permission_conflict=True,
                          usage_limits=("Commercial use prohibited",), usage_limits_reviewed=reviewed))
    assert result.status == CaseStatus.VERIFIED
    assert not result.commercial_use_allowed
    assert result.permission_conflict
    assert "commercial_permission_conflict" in result.reasons


@pytest.mark.parametrize("permission", [CommercialPermission.PROHIBITED, CommercialPermission.UNKNOWN])
def test_review_never_overrides_prohibition_or_unknown(permission: CommercialPermission) -> None:
    result = match(record(commercial_permission=permission, usage_limits=("Limited use",), usage_limits_reviewed=True))
    assert result.status == CaseStatus.VERIFIED
    assert not result.commercial_use_allowed


def test_permission_metadata_survives_json_roundtrip() -> None:
    result = match(record(commercial_permission=CommercialPermission.ALLOWED, permission_conflict=True))
    restored = CaseMatch.model_validate_json(result.model_dump_json())
    assert restored == result
    assert not restored.commercial_use_allowed
    assert CaseRecord.model_validate_json(record().model_dump_json()).commercial_permission == CommercialPermission.UNKNOWN


def test_permission_is_typed_and_strict() -> None:
    with pytest.raises(ValidationError):
        record(commercial_permission="invented")
    with pytest.raises(ValidationError):
        record(usage_limits_reviewed="true")


def test_existing_p4_references_have_no_commercial_permission() -> None:
    root = Path(__file__).parent / "fixtures/p4_synthetic"
    profile = load_p4_catalog(root / "catalog/catalog.csv", root / "prices_stock/warehouse_stock.csv",
                              as_of=date(2026, 10, 28))
    matches = select_cases(tuple(product.product_id for product in profile.products), case_links_from_p4(profile))
    assert len(matches) == 3
    assert all(item.commercial_permission == CommercialPermission.UNKNOWN for item in matches)
    assert not any(item.commercial_use_allowed for item in matches)
