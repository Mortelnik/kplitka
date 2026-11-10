"""Р3.2: уточнения — список недостающих полей определяет код, LLM формулирует вопросы.

The implementation here is intentionally deterministic and provider-agnostic. It produces
structured clarification records from the already-extracted CustomerNeeds object without
making any real LLM or API calls. The caller may inject a future question-template strategy
or LLM formatter later, but the default logic remains explicit and auditable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds, EvidenceRef

DEFAULT_REQUIRED_FIELDS = frozenset({"product_name", "quantity", "unit"})
ITEM_FIELDS = {"product_name", "quantity", "unit"}
TOP_LEVEL_FIELDS = {"desired_deadline", "delivery_address", "budget_limit", "constraints"}


@dataclass(frozen=True)
class Clarification:
    field_name: str
    position: int | None = None
    question: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "position": self.position,
            "question": self.question,
        }


@dataclass(frozen=True)
class ClarificationUpdateResult:
    status: str
    needs: CustomerNeeds
    clarification: Clarification
    next_questions: list[Clarification]
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "clarification": self.clarification.as_dict(),
            "next_questions": [question.as_dict() for question in self.next_questions],
            "message": self.message,
        }


def _normalize_required_fields(required_fields: Iterable[str] | set[str] | str | None) -> set[str]:
    if required_fields is None:
        return set(DEFAULT_REQUIRED_FIELDS)
    if isinstance(required_fields, str):
        values = [required_fields]
    else:
        values = list(required_fields)
    normalized: set[str] = set()
    for value in values:
        field_name = str(value).strip()
        if field_name:
            normalized.add(field_name)
    return normalized


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _question_text(field_name: str, position: int | None) -> str:
    suffix = f" для позиции {position}" if position is not None else ""
    mapping = {
        "product_name": "Уточните товар" + suffix + ". Что именно нужно купить?",
        "quantity": "Укажите количество товара" + suffix + ".",
        "unit": "Укажите единицу измерения" + suffix + ".",
        "desired_deadline": "Укажите срок поставки.",
        "delivery_address": "Укажите адрес доставки.",
        "budget_limit": "Укажите бюджет на закупку.",
        "constraints": "Уточните ограничения или условия поставки.",
    }
    return mapping.get(field_name, f"Уточните поле {field_name}{suffix}.")


def determine_missing_fields(
    needs: CustomerNeeds,
    required_fields: Iterable[str] | set[str] | str | None = None,
) -> list[tuple[str, int | None]]:
    """Return ordered missing fields in the form (field_name, position_or_none)."""
    required = _normalize_required_fields(required_fields)
    missing: list[tuple[str, int | None]] = []

    if not needs.items:
        if required & ITEM_FIELDS:
            missing.append(("product_name", None))
        for field_name in sorted(required & TOP_LEVEL_FIELDS):
            if _is_missing(getattr(needs, field_name, None)) or field_name in needs.unknown_fields:
                missing.append((field_name, None))
        return missing

    for index, item in enumerate(needs.items, start=1):
        for field_name in sorted(required & ITEM_FIELDS):
            if (_is_missing(getattr(item, field_name, None)) or field_name in item.unknown_fields
                    or (field_name == "unit" and item.unit_requires_clarification)):
                missing.append((field_name, index))

    for field_name in sorted(required & TOP_LEVEL_FIELDS):
        if _is_missing(getattr(needs, field_name, None)) or field_name in needs.unknown_fields:
            missing.append((field_name, None))

    return missing


def build_clarifications(
    needs: CustomerNeeds,
    required_fields: Iterable[str] | set[str] | str | None = None,
    templates: dict[str, Callable[[int | None], str]] | None = None,
) -> list[Clarification]:
    """Build explicit clarification records from the structured customer-needs object.

    By default the requirement is intentionally narrow: only product_name, quantity and unit
    are mandatory for each item. The caller may pass any additional required fields for the
    next stage (for example delivery_address), and the function will ask only for those
    fields that are still missing.
    """
    required = _normalize_required_fields(required_fields)
    if not required:
        return []

    templates_map = templates or {}
    clarifications: list[Clarification] = []
    for field_name, position in determine_missing_fields(needs, required):
        if field_name in templates_map:
            question = templates_map[field_name](position)
        else:
            question = _question_text(field_name, position)
        clarifications.append(Clarification(field_name=field_name, position=position, question=question))

    return clarifications


def build_clarification_questions(
    needs: CustomerNeeds,
    required_fields: Iterable[str] | set[str] | str | None = None,
    templates: dict[str, Callable[[int | None], str]] | None = None,
) -> list[dict[str, Any]]:
    """Compatibility helper returning dict payloads for future LLM or UI adapters."""
    return [clarification.as_dict() for clarification in build_clarifications(needs, required_fields, templates)]


def _extract_answer_value(answer: Any) -> Any:
    if isinstance(answer, dict):
        for key in ("value", "answer", "response"):
            if key in answer:
                return answer[key]
        return None
    return answer


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        return left == right
    if isinstance(left, tuple) and isinstance(right, tuple):
        return left == right
    if isinstance(left, set) and isinstance(right, set):
        return left == right
    return left == right


def _normalize_answer_field(field_name: str, answer_value: Any) -> Any:
    if field_name in {"product_name", "unit", "delivery_address", "desired_deadline"}:
        if not isinstance(answer_value, str) or not answer_value.strip():
            raise ValueError(f"Поле {field_name} должно быть непустой строкой.")
        return answer_value.strip()
    if field_name == "quantity":
        if isinstance(answer_value, bool) or not isinstance(answer_value, (str, int, float, Decimal)):
            raise ValueError("Количество должно быть положительным конечным числом.")
        try:
            quantity = Decimal(str(answer_value).strip())
        except InvalidOperation as exc:
            raise ValueError("Количество должно быть положительным конечным числом.") from exc
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("Количество должно быть положительным конечным числом.")
        return quantity
    if field_name == "constraints":
        if answer_value is None:
            return []
        if isinstance(answer_value, str):
            cleaned = [part.strip() for part in answer_value.split(",") if part.strip()]
            return cleaned
        if isinstance(answer_value, (list, tuple, set)):
            return [str(part).strip() for part in answer_value if str(part).strip()]
        return [str(answer_value).strip()]
    return answer_value


def apply_clarification_answer(
    needs: CustomerNeeds,
    clarification: Clarification,
    answer: Any,
    required_fields: Iterable[str] | set[str] | str | None = None,
) -> ClarificationUpdateResult:
    """Apply a structured clarification answer without inventing missing facts.

    Response payloads may be a direct value or a dict containing a "value" field. The
    function updates only the relevant field and preserves the rest of the state.
    """
    if not isinstance(clarification, Clarification):
        raise TypeError("clarification must be a Clarification instance")

    field_name = clarification.field_name
    if field_name not in ITEM_FIELDS | TOP_LEVEL_FIELDS:
        return ClarificationUpdateResult(
            status="invalid", needs=needs, clarification=clarification,
            next_questions=build_clarifications(needs, required_fields),
            message="Неподдерживаемое поле уточнения.",
        )
    answer_value = _extract_answer_value(answer)
    if answer_value is None or (isinstance(answer_value, str) and not answer_value.strip()):
        return ClarificationUpdateResult(
            status="clarify",
            needs=needs,
            clarification=clarification,
            next_questions=build_clarifications(needs, required_fields),
            message="Пустой ответ; требуется уточнение.",
        )

    updated_needs = deepcopy(needs)
    item: CustomerNeedItem | None = None
    if clarification.position is not None:
        index = clarification.position - 1
        if index < 0 or index >= len(updated_needs.items):
            return ClarificationUpdateResult(
                status="invalid",
                needs=updated_needs,
                clarification=clarification,
                next_questions=build_clarifications(updated_needs, required_fields),
                message="Неверный номер позиции для уточнения.",
            )
        item = updated_needs.items[index]

    current_value = None
    if item is not None:
        current_value = getattr(item, field_name, None)
        if field_name not in {"product_name", "quantity", "unit", "desired_deadline", "delivery_address", "budget_limit", "constraints"}:
            return ClarificationUpdateResult(
                status="invalid",
                needs=updated_needs,
                clarification=clarification,
                next_questions=build_clarifications(updated_needs, required_fields),
                message=f"Поле {field_name} не поддерживается в этом уточнении.",
            )
    else:
        current_value = getattr(updated_needs, field_name, None)

    try:
        normalized_value = _normalize_answer_field(field_name, answer_value)
    except ValueError as exc:
        return ClarificationUpdateResult(
            status="invalid",
            needs=needs,
            clarification=clarification,
            next_questions=build_clarifications(needs, required_fields),
            message=str(exc),
        )
    target = item if item is not None else updated_needs
    unconfirmed = field_name in target.unknown_fields or (
        field_name == "unit" and item is not None and item.unit_requires_clarification
    )
    if not unconfirmed and not _is_missing(current_value) and not _values_equal(current_value, normalized_value):
        return ClarificationUpdateResult(
            status="conflict",
            needs=updated_needs,
            clarification=clarification,
            next_questions=build_clarifications(updated_needs, required_fields),
            message="Получено значение, противоречащее ранее подтверждённым данным.",
        )

    if field_name == "product_name" and clarification.position is None and not updated_needs.items:
        item = CustomerNeedItem(product_name=normalized_value, quantity=None, unit=None)
        updated_needs.items.append(item)
        target = item
    elif item is not None:
        setattr(item, field_name, normalized_value)
    else:
        setattr(updated_needs, field_name, normalized_value)

    # Validate the candidate copy before publishing any change to the caller.
    try:
        updated_needs.validate_partial()
    except (ValueError, TypeError, AttributeError) as exc:
        return ClarificationUpdateResult(
            status="invalid", needs=needs, clarification=clarification,
            next_questions=build_clarifications(needs, required_fields), message=str(exc),
        )
    target.unknown_fields = [name for name in target.unknown_fields if name != field_name]
    if field_name in target.evidence:
        target.evidence_history.setdefault(field_name, []).append(target.evidence[field_name])
    target.evidence[field_name] = EvidenceRef(field_name=field_name, quote=str(answer_value), verified=True)

    next_questions = build_clarifications(updated_needs, required_fields)
    return ClarificationUpdateResult(
        status="updated",
        needs=updated_needs,
        clarification=clarification,
        next_questions=next_questions,
        message="Поле обновлено.",
    )


update_needs_after_clarification = apply_clarification_answer


__all__ = [
    "DEFAULT_REQUIRED_FIELDS",
    "Clarification",
    "ClarificationUpdateResult",
    "apply_clarification_answer",
    "build_clarification_questions",
    "build_clarifications",
    "determine_missing_fields",
    "update_needs_after_clarification",
]
