"""Limited single-line protocol adapter for P2 audited at commit 47cb831.

The local P2 module is a stub. A caller must inject the actual calculate_offer;
this adapter contains no price, discount, tax or container formula. Attestations
are supplied separately; execution success is never proof of commercial facts.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict

from kp_plugin.llm.needs import CustomerNeeds
from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import SelectionResult, select_products
from kp_plugin.llm.selection_bridge import (
    CalculationContext,
    CalculationEvidence,
    build_calculation_context,
    calculation_fingerprint,
    canonical_fingerprint,
)
from kp_plugin.llm.unreachable import ConfirmedSource, ExternalCost


class P2Settings(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    profile_id: str | None = None
    profile_version: str | None = None
    price_snapshot_id: str | None = None
    p2_implementation: str | None = None
    currency: str | None = None
    client_tenure_years: Decimal = Decimal(0)
    requested_discount: Decimal = Decimal(0)
    trusted_inputs: bool = False
    input_sources: tuple[ConfirmedSource, ...] = ()
    delivery_cost: Decimal | None = None
    delivery_sources: tuple[ConfirmedSource, ...] = ()
    other_unknown_costs: tuple[str, ...] = ("other_costs",)


class P2Invocation(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    base_context: CalculationContext
    product_id: str
    quantity_tons: Decimal
    catalog: dict[str, dict[str, Any]]
    prices: dict[str, dict[str, Any]]
    rules: dict[str, Any]
    settings: P2Settings

    @property
    def fingerprint(self) -> str:
        return canonical_fingerprint(self)

    @property
    def bridge_context(self) -> CalculationContext:
        return self.base_context.model_copy(update={"execution_fingerprint": self.fingerprint})


@dataclass(frozen=True)
class P2AdapterResult:
    needs: CustomerNeeds
    input_snapshot: dict[str, Any]
    invocation: P2Invocation | None
    raw_output: object
    error_text: str | None
    exception_type: str | None
    exception_message: str | None
    diagnostics: tuple[str, ...]
    successful_calculation: bool
    trusted_inputs: bool
    complete_delivery_cost: bool
    evidence: CalculationEvidence | None

    def evidence_for(self, current: P2Invocation) -> CalculationEvidence | None:
        """Caller builds current from CURRENT inputs, never reuses an old invocation."""
        if self.invocation is None or self.invocation.fingerprint != current.fingerprint:
            return None
        if self.evidence is None or self.evidence.context != current.bridge_context:
            return None
        return self.evidence


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise TypeError(f"invalid_numeric_type:{name}")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid_number:{name}") from exc
    if not amount.is_finite() or amount < 0 or positive and amount == 0:
        raise ValueError(f"invalid_number:{name}")
    return amount


def prepare_p2_invocation(needs: CustomerNeeds, selection: SelectionResult, profile: P4Catalog, *,
                          catalog: dict, prices: dict, rules: dict, settings: P2Settings,
                          product_ids: dict[int, str] | None = None) -> P2Invocation:
    """Validate a detached snapshot before invoking the audited single-line API."""
    if len(needs.items) != 1:
        raise ValueError("unsupported_item_count")
    if selection != select_products(needs, profile.products, product_ids=product_ids):
        raise ValueError("selection_mismatch")
    if len(selection.positions[0].candidates) != 1:
        raise ValueError("ambiguous_or_rejected_product")
    candidate = selection.positions[0].candidates[0]
    if any(field in candidate.unknown_data for field in ("product_name", "product_identity", "quantity", "unit", "unit_compatibility")):
        raise ValueError("unconfirmed_item_values")
    approved = {(source.source_id, source.version, source.locator) for source in settings.input_sources}
    product = next(item for item in profile.products if item.product_id == candidate.product_id)
    if not product.sources or not all((s.source_id, s.version, s.locator) in approved for s in product.sources):
        raise ValueError("product_identity_source_unconfirmed")
    if needs.items[0].unit != "т" or product.unit != "т":
        raise ValueError("unsupported_unit")
    quantity = _decimal(needs.items[0].quantity, "quantity_tons", positive=True)
    for field in ("profile_id", "profile_version", "price_snapshot_id", "p2_implementation", "currency"):
        if not (getattr(settings, field) or "").strip():
            raise ValueError(f"missing_version_or_currency:{field}")
    _decimal(settings.client_tenure_years, "client_tenure_years")
    _decimal(settings.requested_discount, "requested_discount")
    if settings.delivery_cost is not None:
        _decimal(settings.delivery_cost, "delivery_cost")
    if not all(isinstance(value, dict) for value in (catalog, prices, rules)):
        raise ValueError("invalid_input_structure")
    # Validate every row: malformed unused data must not silently enter a trusted snapshot.
    for identifier, row in catalog.items():
        if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(row, dict)
                or row.get("product_id") != identifier
                or any(not isinstance(row.get(field), str) or not row[field].strip() for field in ("name", "source_ref"))):
            raise ValueError("invalid_catalog_row")
        if row.get("status") != "active" or row.get("unit") != "т":
            raise ValueError("inactive_or_unsupported_catalog_row")
        _decimal(row.get("container_capacity_tons"), "container_capacity_tons", positive=True)
    for identifier, row in prices.items():
        if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(row, dict)
                or row.get("product_id") != identifier or not isinstance(row.get("source_ref"), str)
                or not row["source_ref"].strip()):
            raise ValueError("invalid_price_row")
        if row.get("currency") != settings.currency:
            raise ValueError("currency_mismatch")
        for field in ("unit_price_rub_per_t", "tax_rate"):
            if not isinstance(row.get(field), (str, Decimal)):
                raise TypeError(f"unsupported_price_type:{field}")
            _decimal(row[field], field)
    row, price = catalog.get(product.product_id), prices.get(product.product_id)
    if row is None or price is None or row["name"] != product.name:
        raise ValueError("selected_product_data_mismatch")
    discounts = rules.get("discounts")
    if not isinstance(discounts, dict) or not isinstance(discounts.get("rules"), list):
        raise TypeError("invalid_discount_structure")
    for rule in discounts["rules"]:
        if not isinstance(rule, dict) or not rule.get("id") or rule.get("type") not in {"loyalty", "volume_containers"}:
            raise ValueError("unsupported_rule_for_audited_p2")
        percent = rule.get("percent")
        if type(percent) not in (int, float) or not isfinite(percent) or not 0 <= percent <= 100:
            raise ValueError("invalid_rule_percent")
    if not isinstance(rules.get("pricing"), dict) or rules["pricing"].get("currency") != settings.currency:
        raise ValueError("rules_currency_mismatch")
    unknown = list(settings.other_unknown_costs)
    if any(not name.strip() or name == "delivery" for name in unknown):
        raise ValueError("invalid_unknown_costs")
    if settings.delivery_cost is None or not settings.delivery_sources:
        unknown.append("delivery")
    else:
        _decimal(settings.delivery_cost, "delivery_cost")
        if settings.delivery_cost != 0:
            # P2 total excludes delivery. Do not add it independently or claim a full total.
            unknown.append("delivery_not_in_p2_total")
    context = build_calculation_context(needs, selection, profile, profile_id=settings.profile_id,
                                        profile_version=settings.profile_version, price_snapshot_id=settings.price_snapshot_id,
                                        currency=settings.currency, unknown_components=tuple(unknown))
    invocation = P2Invocation(base_context=context, product_id=product.product_id, quantity_tons=quantity,
                              catalog=deepcopy(catalog), prices=deepcopy(prices), rules=deepcopy(rules), settings=settings)
    # Validate even unused extra fields before execution rather than failing during attestation.
    canonical_fingerprint(invocation)
    return invocation


def _output_issues(output: object) -> tuple[str, ...]:
    if not isinstance(output, dict):
        return ("invalid_result_type",)
    issues = []
    for name in ("product", "product_source", "price_source", "discount_rule"):
        if not isinstance(output.get(name), str) or not output[name].strip():
            issues.append(f"invalid_result:{name}")
    if type(output.get("containers")) is not int or output["containers"] < 0:
        issues.append("invalid_result:containers")
    pickup = output.get("pickup_tons")
    try:
        finite_pickup = pickup.is_finite() if isinstance(pickup, Decimal) else (
            isfinite(pickup) if type(pickup) in (int, float) else False
        )
    except OverflowError:
        finite_pickup = False
    if not finite_pickup or pickup < 0:
        issues.append("invalid_result:pickup_tons")
    for name in ("base_amount", "discount_amount", "tax", "total"):
        value = output.get(name)
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            issues.append(f"invalid_result:{name}")
    return tuple(issues)


def run_p2(needs: CustomerNeeds, selection: SelectionResult, profile: P4Catalog, *, catalog: dict,
           prices: dict, rules: dict, settings: P2Settings, calculate_offer: Callable[..., object] | None = None,
           product_ids: dict[int, str] | None = None) -> P2AdapterResult:
    """Invoke injected calculate_offer with exact published keywords, on copies only."""
    snapshot = deepcopy(needs)
    inputs = deepcopy({"catalog": catalog, "prices": prices, "rules": rules, "settings": settings})
    invocation, raw, error, exception_type, exception_message = None, None, None, None, None
    issues = ()
    try:
        invocation = prepare_p2_invocation(snapshot, selection, profile, catalog=catalog, prices=prices,
                                           rules=rules, settings=settings, product_ids=product_ids)
    except (ValueError, TypeError, ArithmeticError) as exc:
        issues = (str(exc),)
    else:
        if calculate_offer is None:
            issues = ("calculate_offer_unavailable_local_stub",)
        else:
            try:
                raw = calculate_offer(product_id=invocation.product_id, quantity_tons=invocation.quantity_tons,
                                      catalog=deepcopy(invocation.catalog), prices=deepcopy(invocation.prices),
                                      rules=deepcopy(invocation.rules), client_tenure_years=settings.client_tenure_years,
                                      requested_discount=settings.requested_discount)
                raw = deepcopy(raw)
            except Exception as exc:  # noqa: BLE001 - external engine boundary must preserve opaque failures
                exception_type, exception_message = type(exc).__name__, str(exc)
                issues = ("p2_exception",)
            else:
                if isinstance(raw, str):
                    error, issues = raw, ("p2_text_error",)
                else:
                    issues = _output_issues(raw)
                    if not issues and (raw["product"] != invocation.catalog[invocation.product_id]["name"]
                                       or raw["product_source"] != invocation.catalog[invocation.product_id]["source_ref"]
                                       or raw["price_source"] != invocation.prices[invocation.product_id]["source_ref"]):
                        issues = ("result_source_or_product_mismatch",)
    success = not issues
    synthetic = True
    if isinstance(catalog, dict) and isinstance(prices, dict):
        synthetic = any(not isinstance(row, dict) or row.get("is_fictional") != "нет"
                        for row in (*catalog.values(), *prices.values()))
    trusted = bool(invocation and settings.trusted_inputs and settings.input_sources and not synthetic)
    delivery_complete = bool(invocation and settings.delivery_cost is not None and settings.delivery_sources)
    evidence = None
    if success and trusted:
        unknown = invocation.base_context.unknown_components
        cost = ExternalCost(calculation_ref=f"{settings.p2_implementation}:{invocation.fingerprint}",
                            currency=settings.currency, known_total=raw["total"],
                            delivery_cost=None if "delivery" in unknown else settings.delivery_cost,
                            unknown_components=unknown)
        context = invocation.bridge_context
        evidence = CalculationEvidence(request_fingerprint=context.request_fingerprint, cost=cost,
                                       sources=(*settings.input_sources, *settings.delivery_sources), verified=True,
                                       context=context, context_fingerprint=calculation_fingerprint(context))
    return P2AdapterResult(snapshot, inputs, invocation, raw, error, exception_type, exception_message, issues,
                           success, trusted, delivery_complete, evidence)
