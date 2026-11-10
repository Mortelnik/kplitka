"""P3.1: isolated customer-needs extraction for free-text requests.

This module is intentionally scoped to the extraction contract only.
It does not modify P2, DOCX, or shared contracts yet.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class LLMClientProtocol(Protocol):
    """Minimal protocol for a provider-backed LLM integration.

    Production integrations can implement the same method using OpenAI/Anthropic/etc.
    The code here only requires a structured dictionary payload, not a real API call.
    """

    def extract_needs(self, raw_text: str) -> dict[str, Any] | str:
        ...


@dataclass
class EvidenceRef:
    field_name: str
    quote: str | None = None
    char_range: tuple[int, int] | None = None
    verified: bool = False


def _as_decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, bool):
        raise TypeError(f"Invalid decimal value for {field_name}: {value!r}")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")
        dec = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
        if not text or text.lower() in {"null", "none"}:
            raise ValueError(f"{field_name} is required")
        if text.lower() in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            raise ValueError(f"{field_name} must be a finite number")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Invalid decimal value for {field_name}: {value!r}") from exc
    else:
        raise TypeError(f"Invalid decimal value for {field_name}: {value!r}")

    if not dec.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return dec


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value).strip() or None


def _clean_optional_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        cleaned = [_clean_optional_str(item) for item in value]
        cleaned = [item for item in cleaned if item is not None]
        return cleaned or []
    return [str(value)]


def _looks_finite_non_negative_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    dec = _as_decimal(value, field_name)
    if not dec.is_finite() or dec < 0:
        raise ValueError(f"{field_name} must be a finite non-negative Decimal or None")
    return dec


def _normalize_numeric_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, bool):
        return ""
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        text = str(value)
    else:
        text = str(value).strip()
    return text.replace(" ", "").replace("\u00a0", "")


def _numeric_evidence_in_text(raw_text: str, value: Any) -> bool:
    if value is None:
        return False
    text = _normalize_numeric_text(value)
    if not text:
        return False
    normalized_raw = re.sub(r"\s+", " ", raw_text.lower())
    numbers = re.findall(r"\d+(?:[.,]\d+)?", normalized_raw)
    if not numbers:
        return False
    raw_candidates = [candidate.replace(" ", "") for candidate in numbers]
    if text in raw_candidates:
        return True
    if text in normalized_raw:
        return True
    try:
        dec_value = _as_decimal(value, "value")
    except ValueError:
        return False
    for raw_candidate in raw_candidates:
        try:
            candidate_decimal = Decimal(raw_candidate.replace(",", "."))
        except InvalidOperation:
            continue
        if candidate_decimal == dec_value:
            return True
        if "млн" in normalized_raw and candidate_decimal * Decimal(1_000_000) == dec_value:
            return True
        if "тыс" in normalized_raw and candidate_decimal * Decimal(1_000) == dec_value:
            return True
    return False


def _normalize_tokens(value: str) -> set[str]:
    raw_tokens = re.findall(r"[A-Za-zА-Яа-я0-9]+", value.lower())
    tokens: set[str] = set()
    for token in raw_tokens:
        stem = re.sub(r"[уеыаоэяию]$", "", token)
        tokens.add(stem or token)
    return tokens


def _field_has_evidence(raw_text: str, field_name: str, value: Any) -> tuple[bool, str | None, tuple[int, int] | None]:
    if value is None:
        return False, None, None
    if isinstance(value, (list, tuple, set)):
        all_verified = True
        quote = None
        span = None
        for item in value:
            item_ok, item_quote, item_span = _field_has_evidence(raw_text, field_name, item)
            if not item_ok:
                all_verified = False
                break
            quote = item_quote or quote
            span = item_span or span
        return all_verified, quote, span
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return False, None, None
        lowered_text = raw_text.lower()
        lowered_value = cleaned.lower()
        if field_name in {"product_name", "delivery_address", "desired_deadline", "unit", "constraints"}:
            pos = lowered_text.find(lowered_value)
            if pos >= 0:
                return True, cleaned, (pos, pos + len(cleaned))

            candidate_tokens = _normalize_tokens(cleaned)
            if candidate_tokens and any(token in lowered_text for token in candidate_tokens):
                return True, cleaned, None

            if field_name == "constraints":
                for item in cleaned.split(","):
                    item_text = item.strip()
                    check = lowered_text.find(item_text.lower())
                    if check >= 0:
                        return True, item_text, (check, check + len(item_text))
                normalized_constraints = [
                    cleaned.lower().replace("предварительной", "").replace("предоплаты", "предоплата").strip(),
                    cleaned.lower().replace("без ", "").strip(),
                ]
                for token in normalized_constraints:
                    if token and token in lowered_text:
                        return True, cleaned, None
            return False, None, None
        if field_name in {"quantity", "budget_limit"}:
            if _numeric_evidence_in_text(raw_text, value):
                pos = lowered_text.find(lowered_value)
                if pos >= 0:
                    return True, cleaned, (pos, pos + len(cleaned))
                return True, cleaned, None
            return False, None, None
        return lowered_text.find(lowered_value) >= 0, cleaned if lowered_text.find(lowered_value) >= 0 else None, None
    if isinstance(value, Decimal):
        return _numeric_evidence_in_text(raw_text, value), str(value), None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return False, None, None
        return _numeric_evidence_in_text(raw_text, Decimal(str(value))), str(value), None
    return False, None, None


@dataclass
class CustomerNeedItem:
    product_name: str | None
    quantity: Decimal | int | float | str | None
    unit: str | None
    desired_deadline: str | None = None
    delivery_address: str | None = None
    budget_limit: Decimal | int | float | str | None = None
    constraints: list[str] | None = None
    evidence: dict[str, EvidenceRef] = field(default_factory=dict, compare=False)
    unknown_fields: list[str] = field(default_factory=list)
    unit_requires_clarification: bool = False
    model_payload: dict[str, Any] = field(default_factory=dict, compare=False)
    evidence_history: dict[str, list[EvidenceRef]] = field(default_factory=dict, compare=False)

    def validate(self) -> CustomerNeedItem:
        """Strict readiness check; partial extraction must use validate_partial."""
        self.validate_partial()
        if self.unknown_fields:
            unresolved = set(self.unknown_fields) & {"product_name", "quantity", "unit"}
            if unresolved:
                raise ValueError(f"Unconfirmed required fields: {sorted(unresolved)}")
        if not isinstance(self.product_name, str) or not self.product_name.strip():
            raise ValueError("product_name is required")
        if self.quantity is None:
            raise ValueError("quantity is required")
        if self.unit is None:
            raise ValueError("unit is required")
        if self.unit_requires_clarification:
            raise ValueError("unit requires clarification")
        return self

    def validate_partial(self) -> CustomerNeedItem:
        """Validate supplied values without requiring missing facts."""
        for name in ("product_name", "unit"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be a string or None")
                setattr(self, name, value.strip() or None)
        if self.quantity is not None:
            self.quantity = _as_decimal(self.quantity, "quantity")
            if self.quantity <= 0:
                raise ValueError("quantity must be a positive finite Decimal")

        self.desired_deadline = _clean_optional_str(self.desired_deadline)
        self.delivery_address = _clean_optional_str(self.delivery_address)
        self.budget_limit = _looks_finite_non_negative_decimal(self.budget_limit, "budget_limit") if self.budget_limit is not None else None
        self.constraints = _clean_optional_list(self.constraints)
        if self.unit:
            self.unit_requires_clarification = not bool(re.fullmatch(r"[A-Za-zА-Яа-я0-9./\-\s]+", self.unit))
        else:
            self.unit_requires_clarification = False
        return self


@dataclass
class CustomerNeeds:
    items: list[CustomerNeedItem]
    delivery_address: str | None = None
    desired_deadline: str | None = None
    budget_limit: Decimal | int | float | str | None = None
    constraints: list[str] | None = None
    unknown_fields: list[str] = field(default_factory=list)
    evidence: dict[str, EvidenceRef] = field(default_factory=dict, compare=False)
    model_payload: dict[str, Any] = field(default_factory=dict, compare=False)
    evidence_history: dict[str, list[EvidenceRef]] = field(default_factory=dict, compare=False)

    def validate(self) -> CustomerNeeds:
        """Strict readiness check, retained for downstream consumers."""
        if not isinstance(self.items, list) or not self.items:
            raise ValueError("items is required")
        self.validate_partial()
        for item in self.items:
            item.validate()
        return self

    def validate_partial(self) -> CustomerNeeds:
        if not isinstance(self.items, list):
            raise TypeError("items must be a list")
        for item in self.items:
            if not isinstance(item, CustomerNeedItem):
                raise TypeError("items must contain CustomerNeedItem instances")
            item.validate_partial()

        self.delivery_address = _clean_optional_str(self.delivery_address)
        self.desired_deadline = _clean_optional_str(self.desired_deadline)
        self.budget_limit = _looks_finite_non_negative_decimal(self.budget_limit, "budget_limit") if self.budget_limit is not None else None
        self.constraints = _clean_optional_list(self.constraints)

        for item in self.items:
            if self.delivery_address and item.delivery_address and item.delivery_address != self.delivery_address:
                raise ValueError("Conflicting delivery_address between item and top-level request")
            if self.budget_limit is not None and item.budget_limit is not None and item.budget_limit != self.budget_limit:
                raise ValueError("Conflicting budget_limit between item and top-level request")

        return self


class FakeLLMClient:
    """Simple test double for isolated validation.

    It is not a real LLM connector. It is only a deterministic object used to test the
    extraction contract without network calls or API keys.
    """

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {
            "items": [],
            "delivery_address": None,
            "desired_deadline": None,
            "budget_limit": None,
            "constraints": [],
        }

    def extract_needs(self, raw_text: str) -> dict[str, Any]:
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("raw_text must be a non-empty string")
        return dict(self.payload)


class NeedsExtractor:
    """Extraction facade for a structured client.

    The real production implementation should call an LLM provider and validate the
    returned JSON according to the same normalization rules used here. This class is a
    thin boundary to keep P3.1 isolated from P2 and DOCX.

    Important limitation: evidence checks only verify that a candidate value appears in the
    original request text; they do not prove the value is semantically correct in a broader
    business sense or that the LLM did not hallucinate the underlying intention.
    """

    def __init__(self, client: LLMClientProtocol) -> None:
        self.client = client

    def extract(self, raw_text: str) -> CustomerNeeds:
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("raw_text must be a non-empty string")
        payload = self.client.extract_needs(raw_text)
        payload = _coerce_llm_payload(payload, raw_text)
        return _normalize_payload(payload, raw_text)


def _coerce_llm_payload(payload: Any, raw_text: str) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON from LLM client: {payload!r}") from exc
    if not isinstance(payload, dict):
        raise TypeError("LLM output must be a dict or a JSON string")
    if "items" not in payload or payload.get("items") is None:
        raise ValueError("items is required")
    if not isinstance(payload.get("items"), list):
        raise ValueError("items is required")  # noqa: TRY004 - retain extraction error contract
    return payload


def _apply_evidence(raw_text: str, item: CustomerNeedItem) -> None:
    item.evidence = {}
    item.unknown_fields = []

    for field_name, value in [
        ("product_name", item.product_name),
        ("quantity", item.quantity),
        ("unit", item.unit),
    ]:
        ok, quote, span = _field_has_evidence(raw_text, field_name, value)
        if ok:
            item.evidence[field_name] = EvidenceRef(field_name=field_name, quote=quote, char_range=span, verified=True)
        else:
            item.unknown_fields.append(field_name)
            if value is not None:
                item.evidence[field_name] = EvidenceRef(field_name=field_name, quote=str(value), verified=False)

    for field_name, value in [
        ("desired_deadline", item.desired_deadline),
        ("delivery_address", item.delivery_address),
        ("budget_limit", item.budget_limit),
    ]:
        if value is None:
            continue
        ok, quote, span = _field_has_evidence(raw_text, field_name, value)
        if not ok:
            item.unknown_fields.append(field_name)
            setattr(item, field_name, None)
            continue
        item.evidence[field_name] = EvidenceRef(field_name=field_name, quote=quote, char_range=span, verified=True)

    if item.constraints:
        valid_constraints: list[str] = []
        for constraint in item.constraints:
            ok, quote, span = _field_has_evidence(raw_text, "constraints", constraint)
            if ok:
                valid_constraints.append(constraint)
                item.evidence[f"constraint:{constraint}"] = EvidenceRef(field_name="constraints", quote=quote, char_range=span, verified=True)
            else:
                item.unknown_fields.append("constraints")
        item.constraints = valid_constraints or []

    item.unknown_fields = sorted(set(item.unknown_fields))


def _normalize_item(raw_item: Any, raw_text: str) -> CustomerNeedItem:
    if not isinstance(raw_item, dict):
        raise TypeError("Each item must be a mapping")

    item = CustomerNeedItem(
        product_name=raw_item.get("product_name"),
        quantity=raw_item.get("quantity"),
        unit=raw_item.get("unit"),
        desired_deadline=_clean_optional_str(raw_item.get("desired_deadline")),
        delivery_address=_clean_optional_str(raw_item.get("delivery_address")),
        budget_limit=raw_item.get("budget_limit"),
        constraints=_clean_optional_list(raw_item.get("constraints")),
        model_payload=deepcopy(raw_item),
    )
    item.validate_partial()
    _apply_evidence(raw_text, item)
    return item


def _normalize_payload(payload: dict[str, Any], raw_text: str) -> CustomerNeeds:
    if not isinstance(payload, dict):
        raise TypeError("LLM output must be a dict or a JSON string")

    items_raw = payload.get("items")
    if items_raw is None:
        raise ValueError("items is required")
    if not isinstance(items_raw, list):
        raise ValueError("items is required")  # noqa: TRY004 - retain extraction error contract

    items = [_normalize_item(item, raw_text) for item in items_raw]
    needs = CustomerNeeds(
        items=items,
        delivery_address=_clean_optional_str(payload.get("delivery_address")),
        desired_deadline=_clean_optional_str(payload.get("desired_deadline")),
        budget_limit=payload.get("budget_limit"),
        constraints=_clean_optional_list(payload.get("constraints")),
        model_payload=deepcopy(payload),
    )
    needs.validate_partial()

    for field_name, value in [
        ("delivery_address", needs.delivery_address),
        ("desired_deadline", needs.desired_deadline),
        ("budget_limit", needs.budget_limit),
    ]:
        if value is None:
            continue
        ok, quote, span = _field_has_evidence(raw_text, field_name, value)
        if not ok:
            needs.unknown_fields.append(field_name)
            setattr(needs, field_name, None)
        else:
            needs.evidence[field_name] = EvidenceRef(field_name=field_name, quote=quote, char_range=span, verified=True)

    if needs.constraints:
        valid_constraints: list[str] = []
        for constraint in needs.constraints:
            ok, quote, span = _field_has_evidence(raw_text, "constraints", constraint)
            if ok:
                valid_constraints.append(constraint)
                needs.evidence[f"constraint:{constraint}"] = EvidenceRef(field_name="constraints", quote=quote, char_range=span, verified=True)
            else:
                needs.unknown_fields.append("constraints")
        needs.constraints = valid_constraints or []

    needs.unknown_fields = sorted(set(needs.unknown_fields))

    if needs.constraints:
        valid_constraints: list[str] = []
        for constraint in needs.constraints:
            ok, quote, span = _field_has_evidence(raw_text, "constraints", constraint)
            if ok:
                valid_constraints.append(constraint)
                needs.evidence[f"constraint:{constraint}"] = EvidenceRef(field_name="constraints", quote=quote, char_range=span, verified=True)
            else:
                needs.unknown_fields.append("constraints")
        needs.constraints = valid_constraints

    return needs


def extract_customer_needs(raw_text: str, client: LLMClientProtocol | None = None) -> CustomerNeeds:
    """Public helper for safe, isolated extraction.

    The client is injected for testability and real provider integration. The function never
    invents missing data; unknown values remain None and must be clarified later.

    The evidence check is intentionally narrow: it only verifies the text was present in the
    request. It does not prove the extracted business fact is semantically correct or that
    the LLM did not hallucinate the underlying intent.
    """

    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("raw_text must be a non-empty string")
    if client is None:
        raise RuntimeError(
            "No LLM client configured. Inject a test or provider-backed implementation "
            "via NeedsExtractor or extract_customer_needs(client=...)."
        )
    return NeedsExtractor(client).extract(raw_text)
