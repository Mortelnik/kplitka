"""P3.4 case contract: curated product/task links, no semantic or keyword inference.

P4 currently supplies references only, not case content. A future profile adapter
must attest content and source verification. Exact full-task matching is a local
conservative rule, not a claim of natural-language understanding.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import SelectionSource

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CaseStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    UNAVAILABLE = "unavailable"


class CommercialPermission(StrEnum):
    ALLOWED = "allowed"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class CaseModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CaseLink(CaseModel):
    case_id: Text
    product_id: Text
    source: SelectionSource
    confirmed: bool = False


class CaseRecord(CaseModel):
    case_id: Text
    product_ids: tuple[Text, ...]
    task_descriptions: tuple[Text, ...] = ()
    content: Text | None = None
    sources: tuple[SelectionSource, ...] = ()
    status: CaseStatus = CaseStatus.NEEDS_REVIEW
    source_confirmed: bool = False
    content_confirmed: bool = False
    is_fictional: bool = True
    usage_limits: tuple[Text, ...] = ()
    commercial_permission: CommercialPermission = CommercialPermission.UNKNOWN
    permission_conflict: bool = False
    # Explicit manual attestation that text restrictions are compatible with permission.
    # Merely reading them is insufficient; no text interpretation is performed here.
    usage_limits_reviewed: bool = False


class CaseMatch(CaseModel):
    case_id: Text | None
    product_id: Text
    status: CaseStatus
    relevance_basis: tuple[Text, ...]
    sources: tuple[SelectionSource, ...]
    reasons: tuple[Text, ...] = ()
    usage_limits: tuple[Text, ...] = ()
    commercial_permission: CommercialPermission = CommercialPermission.UNKNOWN
    permission_conflict: bool = False
    usage_limits_reviewed: bool = False

    @property
    def commercial_use_allowed(self) -> bool:
        return (
            self.status == CaseStatus.VERIFIED
            and self.commercial_permission == CommercialPermission.ALLOWED
            and not self.permission_conflict
            and (not self.usage_limits or self.usage_limits_reviewed)
        )


def case_links_from_p4(profile: P4Catalog) -> tuple[CaseLink, ...]:
    """Actual P4 cells contain one ID each. Do not guess multi-ID delimiters.

    Preserve every source when the same reference occurs in multiple rows; matching
    deduplicates per product/case and keeps all those sources. Synthetic references
    remain unconfirmed even if content is subsequently supplied.
    """
    links = []
    for record in profile.catalog_rows:
        row = dict(record.fields)
        reference = row.get("related_cases", "").strip()
        if reference and row.get("status", "").strip() == "active":
            links.append(CaseLink(case_id=reference, product_id=row["product_id"], source=record.source,
                                  confirmed=not record.issues))
    return tuple(links)


def _normalize(task: str) -> str:
    return " ".join(task.split()).casefold()


def select_cases(product_ids: tuple[str, ...], links: tuple[CaseLink, ...],
                 cases: tuple[CaseRecord, ...] = (), *, client_task: str | None = None) -> tuple[CaseMatch, ...]:
    """Select only explicitly referenced cases; never invent content or alternatives.

    product_ids must be explicit catalog identities, not ambiguous name matches.
    Record.product_ids confirms the reverse link, task_descriptions are curated
    full descriptions (not keywords/categories). No fuzzy or substring matching.
    """
    records = {record.case_id: record for record in cases}
    if len(records) != len(cases):
        raise ValueError("Case identifiers must be unique")
    results = []
    for product_id in dict.fromkeys(product_ids):
        if not product_id.strip():
            raise ValueError("Product identifiers must not be blank")
        relevant_links = [link for link in links if link.product_id == product_id]
        ids = dict.fromkeys(link.case_id for link in relevant_links)
        if not ids:
            results.append(CaseMatch(case_id=None, product_id=product_id, status=CaseStatus.UNAVAILABLE,
                                     relevance_basis=(), sources=(), reasons=("no_case_reference",),
                                     usage_limits=("Кейс не предоставлен; коммерческое использование запрещено.",)))
        for case_id in ids:
            group = [link for link in relevant_links if link.case_id == case_id]
            source_refs = tuple(dict.fromkeys(link.source for link in group))
            record = records.get(case_id)
            basis = (f"Явная ссылка related_cases: {product_id} → {case_id}",)
            if record is None:
                results.append(CaseMatch(case_id=case_id, product_id=product_id, status=CaseStatus.UNAVAILABLE,
                                         relevance_basis=basis, sources=source_refs,
                                         reasons=("unresolved_case_reference",),
                                         usage_limits=("Нет содержания кейса; нельзя использовать как историю успеха.",)))
                continue
            reasons = []
            status = CaseStatus.NEEDS_REVIEW
            if product_id not in record.product_ids:
                reasons.append("product_link_not_supported_by_case")
                status = CaseStatus.UNAVAILABLE
            if record.status == CaseStatus.UNAVAILABLE:
                reasons.append("case_unavailable")
                status = CaseStatus.UNAVAILABLE
            if not client_task or not client_task.strip() or not record.task_descriptions:
                reasons.append("task_relevance_unconfirmed")
            elif _normalize(client_task) not in {_normalize(task) for task in record.task_descriptions}:
                reasons.append("task_not_relevant")
                status = CaseStatus.UNAVAILABLE
            else:
                basis += (f"Совпадает полное описание задачи: {client_task.strip()}",)
            if not all(link.confirmed for link in group):
                reasons.append("catalog_link_unconfirmed")
            if not record.sources or not record.source_confirmed:
                reasons.append("source_unconfirmed")
            if not record.content or not record.content_confirmed:
                reasons.append("content_unconfirmed")
            if record.is_fictional:
                reasons.append("synthetic_case")
            if record.status != CaseStatus.VERIFIED:
                reasons.append("record_not_verified")
            if not reasons:
                status = CaseStatus.VERIFIED
            # Permission diagnostics must not change the independent credibility status.
            if record.commercial_permission != CommercialPermission.ALLOWED:
                reasons.append(f"commercial_permission_{record.commercial_permission.value}")
            if record.permission_conflict:
                reasons.append("commercial_permission_conflict")
            if record.usage_limits and not record.usage_limits_reviewed:
                reasons.append("usage_limits_require_manual_review")
            limits = record.usage_limits
            if status != CaseStatus.VERIFIED:
                limits += ("Коммерческое использование запрещено до подтверждения содержания, источников и релевантности.",)
            results.append(CaseMatch(case_id=case_id, product_id=product_id, status=status,
                                     relevance_basis=basis, sources=tuple(dict.fromkeys((*source_refs, *record.sources))),
                                     reasons=tuple(reasons), usage_limits=limits,
                                     commercial_permission=record.commercial_permission,
                                     permission_conflict=record.permission_conflict,
                                     usage_limits_reviewed=record.usage_limits_reviewed))
    return tuple(results)
