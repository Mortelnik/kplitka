"""P3.4 stage 1: exact catalog matching, no ranking, conversions or substitutions.

The local catalog format is explicit, not an assumed CSV/ZIP layout. Adapters
attest stock freshness and static constraints via versioned sources. Confirmed
means only these local checks passed, not an accepted offer or reserved stock.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class SelectionStatus(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    NEEDS_CLARIFICATION = "needs_clarification"


class LocalModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class SelectionSource(LocalModel):
    source_id: Text
    version: Text
    locator: Text


class CatalogProduct(LocalModel):
    product_id: Text
    name: Text
    status: Literal["active", "draft"]
    sources: Annotated[tuple[SelectionSource, ...], Field(min_length=1)]
    synonyms: tuple[Text, ...] = ()
    unit: Text | None = None
    stock_quantity: Amount | None = None
    stock_sources: tuple[SelectionSource, ...] = ()
    # Explicit external attestation of static catalog constraints; not customer constraints.
    constraints_check: Literal["unknown", "passed", "failed"] = "unknown"
    constraint_sources: tuple[SelectionSource, ...] = ()
    min_quantity: Amount | None = None
    max_quantity: Amount | None = None


class MatchedField(LocalModel):
    request_field: Text
    catalog_field: Text
    request_value: Annotated[str, Field(min_length=1)]
    catalog_value: Annotated[str, Field(min_length=1)]


class SelectionChange(LocalModel):
    field_path: Text
    before: Text | None
    after: Text | None


class Candidate(LocalModel):
    product_id: Text
    request_position: Annotated[int, Field(ge=1)]
    matched_fields: tuple[MatchedField, ...]
    sources: tuple[SelectionSource, ...]
    status: SelectionStatus
    unknown_data: tuple[Text, ...] = ()
    exclusion_reasons: tuple[Text, ...] = ()
    requirement_changes: tuple[SelectionChange, ...] = ()


class PositionSelection(LocalModel):
    request_position: Annotated[int, Field(ge=1)]
    status: SelectionStatus
    candidates: tuple[Candidate, ...] = ()
    excluded: tuple[Candidate, ...] = ()
    unknown_data: tuple[Text, ...] = ()
    exclusion_reasons: tuple[Text, ...] = ()
    questions: tuple[Text, ...] = ()


class SelectionResult(LocalModel):
    positions: tuple[PositionSelection, ...]
    questions: tuple[Text, ...] = ()


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _quantity(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _check(product: CatalogProduct, item: CustomerNeedItem, position: int,
           matched: MatchedField, unknown: set[str], request_constraints: bool) -> Candidate:
    unknown = set(unknown)
    reasons = []
    sources = list(product.sources)
    if product.status == "draft":
        reasons.append("draft")
    quantity = _quantity(item.quantity)
    if quantity is None:
        unknown.add("quantity")
    if not item.unit or not isinstance(item.unit, str) or not item.unit.strip() or item.unit_requires_clarification:
        unknown.add("unit")
    if product.unit is None:
        unknown.add("catalog.unit")
    compatible = ("unit" not in unknown and product.unit is not None
                  and _normalize(item.unit) == _normalize(product.unit))
    if "unit" not in unknown and product.unit is not None and not compatible:
        unknown.add("unit_compatibility")
    if product.constraints_check == "unknown" or not product.constraint_sources:
        unknown.add("catalog.constraints")
    else:
        sources.extend(product.constraint_sources)
        if product.constraints_check == "failed":
            reasons.append("catalog_constraints_failed")
    if request_constraints:
        unknown.add("request.constraints")
    if product.stock_quantity is None or not product.stock_sources:
        unknown.add("stock")
    elif compatible and quantity is not None and "quantity" not in unknown:
        sources.extend(product.stock_sources)
        if quantity > product.stock_quantity:
            reasons.append("insufficient_stock")
    if compatible and quantity is not None and "quantity" not in unknown:
        if product.min_quantity is not None and quantity < product.min_quantity:
            reasons.append("below_min_quantity")
        if product.max_quantity is not None and quantity > product.max_quantity:
            reasons.append("above_max_quantity")
    clarify = unknown & {"product_name", "quantity", "unit", "unit_compatibility"}
    status = (SelectionStatus.REJECTED if reasons else SelectionStatus.NEEDS_CLARIFICATION if clarify
              else SelectionStatus.NEEDS_REVIEW if unknown else SelectionStatus.CONFIRMED)
    return Candidate(product_id=product.product_id, request_position=position, matched_fields=(matched,),
                     sources=tuple(sources), status=status, unknown_data=tuple(sorted(unknown)),
                     exclusion_reasons=tuple(reasons))


def select_products(needs: CustomerNeeds, catalog: tuple[CatalogProduct, ...], *,
                    product_ids: dict[int, str] | None = None) -> SelectionResult:
    """Return per-position matches without mutating needs or allocating stock.

    product_ids is an explicit caller-confirmed ID per 1-based request position.
    IDs are case sensitive. Names/synonyms normalize case and whitespace only.
    Draft matches are diagnostics in excluded, never eligible candidates. Repeated
    requests for the same SKU require joint stock review, not independent approval.
    """
    ids = [product.product_id for product in catalog]
    if len(ids) != len(set(ids)):
        raise ValueError("Catalog product_id must be unique")
    explicit = product_ids or {}
    if any(type(position) is not int or not 1 <= position <= len(needs.items)
           or not isinstance(value, str) or not value.strip() for position, value in explicit.items()):
        raise ValueError("product_ids must map existing 1-based positions to nonempty IDs")
    positions = []
    for position, item in enumerate(needs.items, 1):
        unknown = set(item.unknown_fields) | set(needs.unknown_fields) & {"product_name", "quantity", "unit"}
        name = item.product_name
        identifier = explicit.get(position)
        if identifier is None and isinstance(name, str) and name in ids and "product_name" not in unknown:
            identifier = name
        matches = []
        if identifier is not None:
            for product in catalog:
                if product.product_id == identifier:
                    field = MatchedField(request_field="product_id", catalog_field="product_id",
                                         request_value=identifier, catalog_value=product.product_id)
                    matches.append((product, field))
                    if name and name != identifier and "product_name" not in unknown and _normalize(name) not in {
                        _normalize(value) for value in (product.name, *product.synonyms)
                    }:
                        unknown.add("product_name")
        elif isinstance(name, str) and name.strip() and "product_name" not in unknown:
            for product in catalog:
                for field_name, value in (("name", product.name), *(("synonyms", alias) for alias in product.synonyms)):
                    if _normalize(name) == _normalize(value):
                        matches.append((product, MatchedField(request_field="product_name", catalog_field=field_name,
                                                              request_value=name, catalog_value=value)))
                        break
        elif identifier is None:
            unknown.add("product_name")
        candidates, excluded = [], []
        for product, field in matches:
            candidate = _check(product, item, position, field, unknown,
                               bool(item.constraints or needs.constraints or "constraints" in unknown))
            (excluded if candidate.status == SelectionStatus.REJECTED else candidates).append(candidate)
        # Resolve identity before stock/constraint filtering: no silent choice between homonyms.
        active_count = sum(product.status == "active" for product, _ in matches)
        if active_count > 1:
            candidates = [candidate.model_copy(update={"status": SelectionStatus.NEEDS_CLARIFICATION,
                                                       "unknown_data": (*candidate.unknown_data, "product_identity")})
                          for candidate in candidates]
            status = SelectionStatus.NEEDS_CLARIFICATION
            questions = (f"Уточните product_id для позиции {position}: совпало несколько товаров.",)
        elif candidates:
            status = candidates[0].status
            questions = ((f"Уточните поля позиции {position}: {', '.join(candidates[0].unknown_data)}.",)
                         if status == SelectionStatus.NEEDS_CLARIFICATION else ())
        elif "product_name" in unknown and identifier is None:
            status = SelectionStatus.NEEDS_CLARIFICATION
            questions = (f"Уточните подтверждённое название или product_id позиции {position}.",)
        else:
            status, questions = SelectionStatus.REJECTED, ()
        positions.append(PositionSelection(request_position=position, status=status, candidates=tuple(candidates),
                                           excluded=tuple(excluded), unknown_data=tuple(sorted(unknown)),
                                           exclusion_reasons=(() if matches or status != SelectionStatus.REJECTED
                                                              else ("not_in_catalog",)), questions=questions))
    # Stock allocation across repeated SKU lines is outside this local stage.
    occurrences = [candidate.product_id for result in positions for candidate in result.candidates]
    for index, result in enumerate(positions):
        candidates = tuple(candidate.model_copy(update={
            "status": SelectionStatus.NEEDS_REVIEW,
            "unknown_data": (*candidate.unknown_data, "joint_stock_allocation"),
        }) if occurrences.count(candidate.product_id) > 1 and candidate.status == SelectionStatus.CONFIRMED
                           else candidate for candidate in result.candidates)
        if candidates != result.candidates:
            positions[index] = result.model_copy(update={"candidates": candidates, "status": SelectionStatus.NEEDS_REVIEW})
    return SelectionResult(positions=tuple(positions), questions=(() if needs.items else ("Уточните товары запроса.",)))
