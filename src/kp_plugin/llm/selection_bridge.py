"""Local P3.4 -> P3.3 bridge, without P2 imports or shared contract changes.

ConfirmedSource values are explicit external attestations. Catalog references,
hashes and a local 'confirmed' selection status never manufacture attestations.
No alternatives are manufactured: selection alone has no checked request delta
or full recalculation of an alternative. Cases stay separate from product options.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from kp_plugin.llm.cases import CaseMatch, CaseRecord, case_links_from_p4, select_cases
from kp_plugin.llm.needs import CustomerNeeds
from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import (
    SelectionResult,
    SelectionSource,
    SelectionStatus,
    select_products,
)
from kp_plugin.llm.unreachable import (
    ConfirmedSource,
    ExternalCost,
    HandlingRequest,
    MissingDatum,
    Reason,
    UnreachableResult,
    handle_unreachable,
)


class EvidenceModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class UnavailabilityEvidence(EvidenceModel):
    """External confirmation, distinct from a local rejected candidate."""

    request_position: Annotated[int, Field(ge=1)]
    request_fingerprint: str
    sources: Annotated[tuple[ConfirmedSource, ...], Field(min_length=1)]


class CalculationEvidence(EvidenceModel):
    request_fingerprint: str
    cost: ExternalCost
    sources: Annotated[tuple[ConfirmedSource, ...], Field(min_length=1)]
    verified: bool = False
    context: CalculationContext | None = None
    context_fingerprint: str | None = None


class CalculationLine(EvidenceModel):
    request_position: Annotated[int, Field(ge=1)]
    product_id: Annotated[str, Field(min_length=1)]
    quantity: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
    unit: Annotated[str, Field(min_length=1)]


class CalculationContext(EvidenceModel):
    request_fingerprint: str
    lines: tuple[CalculationLine, ...]
    profile_id: str | None = None
    profile_version: str | None = None
    profile_snapshot: str
    price_snapshot_id: str | None = None
    currency: str
    unknown_components: tuple[str, ...]
    execution_fingerprint: str | None = None


class BudgetEvidence(EvidenceModel):
    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    currency: Annotated[str, Field(min_length=1)]
    sources: Annotated[tuple[ConfirmedSource, ...], Field(min_length=1)]


@dataclass(frozen=True)
class ProductBinding:
    request_position: int
    product_id: str
    confirmed: bool


@dataclass(frozen=True)
class Problem:
    request_position: int | None
    request: HandlingRequest
    response: UnreachableResult


@dataclass(frozen=True)
class SelectionAssessment:
    # Detached snapshot, including metadata; mutable dataclass internals do not alias the caller.
    needs: CustomerNeeds
    fingerprint: str
    selection: SelectionResult
    profile: P4Catalog
    bindings: tuple[ProductBinding, ...]
    problems: tuple[Problem, ...]
    case_matches: tuple[CaseMatch, ...]
    commercial_cases: tuple[CaseMatch, ...]
    case_records: tuple[CaseRecord, ...]
    client_task: str | None
    task_sources: tuple[ConfirmedSource, ...]
    confirmed_sources: tuple[ConfirmedSource, ...]
    calculation: CalculationEvidence | None
    budget: BudgetEvidence | None
    unavailability_evidence: tuple[UnavailabilityEvidence, ...]
    calculation_context: CalculationContext | None
    calculation_issues: tuple[str, ...]
    calculation_confirmed: bool


def needs_fingerprint(needs: CustomerNeeds) -> str:
    """Bind supplied calculations/facts to exact request data AND evidence metadata."""
    return _fingerprint(needs)


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal cannot enter calculation identity")
        text = format(value, "f")
        text = text.rstrip("0").rstrip(".") if "." in text else text
        return {"$decimal": "0" if value == 0 else text}
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Canonical mappings require string keys")
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Non-finite float cannot enter calculation identity")
        return {"$float": value.hex()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError("Unsupported value in canonical calculation identity")


def _fingerprint(value: object) -> str:
    text = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calculation_fingerprint(context: CalculationContext) -> str:
    return _fingerprint(context)


def canonical_fingerprint(value: object) -> str:
    """Stable typed snapshot identity for local execution adapters; not an attestation."""
    return _fingerprint(value)


def build_calculation_context(needs: CustomerNeeds, selection: SelectionResult, profile: P4Catalog, *,
                              profile_id: str | None, profile_version: str | None, price_snapshot_id: str | None,
                              currency: str, unknown_components: tuple[str, ...],
                              execution_fingerprint: str | None = None) -> CalculationContext:
    """Build current context, not evidence of a calculation or trust in a hash.

    Version identifiers must come from the caller's CURRENT profile/pricing state,
    never be copied from an old CalculationEvidence to bypass invalidation.
    Missing versions can be represented, but assess_selection will reject them.
    """
    if len(selection.positions) != len(needs.items) or not needs.items:
        raise ValueError("Calculation context requires every request position")
    lines = []
    for number, (item, position) in enumerate(zip(needs.items, selection.positions, strict=True), 1):
        if (position.request_position != number or len(position.candidates) != 1
                or position.status == SelectionStatus.NEEDS_CLARIFICATION
                or {"product_name", "quantity", "unit"} & (set(item.unknown_fields) | set(needs.unknown_fields))):
            raise ValueError("Calculation context requires unambiguous confirmed item values")
        lines.append(CalculationLine(request_position=number, product_id=position.candidates[0].product_id,
                                     quantity=Decimal(str(item.quantity)), unit=item.unit))
    return CalculationContext(request_fingerprint=needs_fingerprint(needs), lines=tuple(lines),
                              profile_id=profile_id, profile_version=profile_version, profile_snapshot=_fingerprint(profile),
                              price_snapshot_id=price_snapshot_id, currency=currency,
                              unknown_components=tuple(sorted(set(unknown_components))),
                              execution_fingerprint=execution_fingerprint)


def _key(source: SelectionSource | ConfirmedSource) -> tuple[str, str, str]:
    return source.source_id, source.version, source.locator


def assess_selection(needs: CustomerNeeds, selection: SelectionResult, profile: P4Catalog, *,
                     product_ids: dict[int, str] | None = None,
                     confirmed_sources: tuple[ConfirmedSource, ...] = (),
                     unavailable: tuple[UnavailabilityEvidence, ...] = (),
                     calculation: CalculationEvidence | None = None,
                     calculation_context: CalculationContext | None = None,
                     budget: BudgetEvidence | None = None,
                     case_records: tuple[CaseRecord, ...] = (),
                     client_task: str | None = None,
                     task_sources: tuple[ConfirmedSource, ...] = ()) -> SelectionAssessment:
    """Preserve every diagnostic; handle each structured problem independently.

    Selection is recomputed to reject stale/mismatched inputs. External cost and
    unavailability attestations must carry this request's fingerprint. A valid
    request without a calculation remains unpriced, never an accepted offer.
    """
    snapshot = deepcopy(needs)
    fingerprint = needs_fingerprint(snapshot)
    if selection != select_products(snapshot, profile.products, product_ids=product_ids):
        raise ValueError("Selection does not correspond to the supplied request/profile")
    if any(fact.request_position > len(snapshot.items) for fact in unavailable):
        raise ValueError("Unavailability position is outside the request")
    approved = {_key(source): source for source in confirmed_sources}
    problems, bindings = [], []

    def problem(reason: Reason, position: int | None = None, **fields: object) -> None:
        request = HandlingRequest(reason=reason, **fields)
        problems.append(Problem(position, request, handle_unreachable(request)))

    def missing(position: int | None, path: str, label: str) -> None:
        problem(Reason.MISSING_DATA, position, missing_data=(MissingDatum(field_path=path, label=label),))

    for position in selection.positions:
        number = position.request_position
        path = f"items[{number - 1}]"
        for candidate in position.candidates:
            supported = (position.status == SelectionStatus.CONFIRMED and len(position.candidates) == 1
                         and candidate.status == SelectionStatus.CONFIRMED and not candidate.unknown_data
                         and not candidate.exclusion_reasons and bool(candidate.sources)
                         and all(_key(source) in approved for source in candidate.sources))
            bindings.append(ProductBinding(number, candidate.product_id, supported))
            if not all(_key(source) in approved for source in candidate.sources):
                missing(number, f"{path}.sources", "подтверждения источников выбранного товара")
            for field in candidate.unknown_data:
                missing(number, f"{path}.{field}", f"проверку {field}")
        for field in position.unknown_data:
            missing(number, f"{path}.{field}", f"подтверждённое значение {field}")
        for index, question in enumerate(position.questions):
            missing(number, f"{path}.question[{index}]", question)
        for candidate in position.excluded:
            for reason in (*candidate.exclusion_reasons, *candidate.unknown_data):
                missing(number, f"{path}.excluded[{candidate.product_id}].{reason}", f"проверку причины {reason}")
        for reason in position.exclusion_reasons:
            missing(number, f"{path}.{reason}", f"подтверждение причины {reason}")
    for index, question in enumerate(selection.questions):
        missing(None, f"request.question[{index}]", question)
    for fact in unavailable:
        if fact.request_fingerprint != fingerprint:
            missing(fact.request_position, "availability.request_fingerprint", "проверку доступности текущего запроса")
        else:
            item = snapshot.items[fact.request_position - 1]
            if item.product_name and "product_name" not in item.unknown_fields:
                problem(Reason.PRODUCT_UNAVAILABLE, fact.request_position, sources=fact.sources,
                        product_name=item.product_name, product_unavailable_confirmed=True)
            else:
                missing(fact.request_position, "availability.product_name", "подтверждённый товар проверки доступности")

    trusted_budget = False
    if budget is not None:
        known_budget = snapshot.budget_limit
        trusted_budget = (known_budget is not None and "budget_limit" not in snapshot.unknown_fields
                          and Decimal(str(known_budget)) == budget.amount)
        if not trusted_budget:
            missing(None, "budget_limit", "подтверждённый бюджет, соответствующий потребностям клиента")
    elif snapshot.budget_limit is not None:
        missing(None, "budget.sources", "подтверждение бюджета и его валюты")
    calculation_issues = []
    if calculation is None:
        calculation_issues.append("calculation_missing")
    elif not calculation.verified:
        calculation_issues.append("calculation_not_verified")
    if calculation_context is None:
        calculation_issues.append("calculation_context_missing")
    else:
        for name in ("profile_id", "profile_version", "price_snapshot_id", "currency"):
            if not (getattr(calculation_context, name) or "").strip():
                calculation_issues.append(f"{name}_missing")
        try:
            rebuilt = build_calculation_context(
                snapshot, selection, profile, profile_id=calculation_context.profile_id,
                profile_version=calculation_context.profile_version, price_snapshot_id=calculation_context.price_snapshot_id,
                currency=calculation_context.currency, unknown_components=calculation_context.unknown_components,
                execution_fingerprint=calculation_context.execution_fingerprint,
            )
        except (ValueError, TypeError, ArithmeticError):
            calculation_issues.append("current_composition_incomplete")
        else:
            if calculation_context != rebuilt:
                calculation_issues.append("current_context_stale")
    if calculation is not None:
        if calculation.request_fingerprint != fingerprint:
            calculation_issues.append("request_changed")
        if calculation.context is None or calculation.context_fingerprint is None:
            calculation_issues.append("evidence_context_missing")
        elif calculation.context_fingerprint != calculation_fingerprint(calculation.context):
            calculation_issues.append("evidence_fingerprint_mismatch")
        if calculation_context is not None:
            if calculation.context != calculation_context:
                calculation_issues.append("calculation_context_changed")
            if calculation.cost.currency != calculation_context.currency:
                calculation_issues.append("calculation_currency_mismatch")
            if tuple(sorted(set(calculation.cost.unknown_components))) != calculation_context.unknown_components:
                calculation_issues.append("cost_completeness_changed")
    if calculation_issues:
        for issue in calculation_issues:
            missing(None, f"calculation.{issue}", f"повторный проверенный расчёт текущего заказа: {issue}")
    else:
        if calculation.cost.unknown_components:
            problem(Reason.UNKNOWN_COSTS, sources=calculation.sources, cost=calculation.cost, calculation_verified=True)
        if budget is not None and trusted_budget:
            if budget.currency != calculation.cost.currency:
                missing(None, "budget.currency", "бюджет и расчёт в одной валюте")
            elif not calculation.cost.unknown_components and calculation.cost.known_total > budget.amount:
                problem(Reason.INSUFFICIENT_BUDGET, sources=(*calculation.sources, *budget.sources),
                        cost=calculation.cost, calculation_verified=True, budget=budget.amount,
                        budget_currency=budget.currency)

    identity_ids = tuple(dict.fromkeys(
        position.candidates[0].product_id for position in selection.positions
        if len(position.candidates) == 1 and position.status != SelectionStatus.NEEDS_CLARIFICATION
    ))
    confirmed_ids = {binding.product_id for binding in bindings if binding.confirmed}
    links = case_links_from_p4(profile)
    matches = select_cases(identity_ids, links, case_records, client_task=client_task if task_sources else None)
    commercial = tuple(match for match in matches
                       if match.commercial_use_allowed and task_sources and match.product_id in confirmed_ids)
    return SelectionAssessment(snapshot, fingerprint, selection.model_copy(deep=True), deepcopy(profile),
                               tuple(bindings), tuple(problems), matches, commercial,
                               tuple(case_records), client_task, tuple(task_sources), tuple(confirmed_sources),
                               calculation, budget, tuple(unavailable), calculation_context, tuple(calculation_issues),
                               not calculation_issues and calculation is not None and not calculation.cost.unknown_components)
