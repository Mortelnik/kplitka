"""P3.3 local contract, independent of the unfinished shared P1/P2 schemas.

Adapters supply facts, candidates and calculations; this module does not discover
products or compute money. Source confirmation and external validation are caller
attestations, not checks against a catalog or a real-world source. Models expose
Pydantic JSON Schema and JSON serialization (Decimal amounts become strings).
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


def _change_scalar(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("Change values cannot be bool")  # noqa: TRY004 - Pydantic wraps ValueError, not TypeError
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Change values must be finite")
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return value


# Canonical decimal text avoids ambiguous Decimal/string unions in JSON adapters.
ChangeScalar = Annotated[Text | int | None, BeforeValidator(_change_scalar)]


class Reason(StrEnum):
    CONFLICT = "conflict"
    INSUFFICIENT_BUDGET = "insufficient_budget"
    PRODUCT_UNAVAILABLE = "product_unavailable"
    UNKNOWN_COSTS = "unknown_costs"
    MISSING_DATA = "missing_data"


class Status(StrEnum):
    CLARIFY = "clarify"
    ALTERNATIVES = "alternatives"
    UNAVAILABLE = "unavailable"


class AlternativeReadiness(StrEnum):
    CONDITIONAL = "conditional"
    VERIFIED = "verified"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @field_validator("confirmed", "requires_client_confirmation", mode="before", check_fields=False)
    @classmethod
    def require_explicit_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Confirmation must be explicitly true")
        return value


class ConfirmedSource(ContractModel):
    """An adapter-confirmed record/field in a versioned source."""

    source_id: Text
    version: Text
    locator: Text
    confirmed: Literal[True]


class RequestChange(ContractModel):
    """Explicit before/after delta; quantities and money may use Decimal strings in JSON."""

    field_path: Text
    before: ChangeScalar
    after: ChangeScalar

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.before == self.after:
            raise ValueError("An alternative must change the original request")
        return self


class ExternalCost(ContractModel):
    """Known subtotal from P2; unknown_components explicitly prevent a full-cost claim.

    An adapter MUST list delivery here if its tariff is unknown. An explicit zero
    is a confirmed amount only; absence of a tariff must never be converted to zero.
    """

    calculation_ref: Text
    currency: Text
    known_total: Amount
    delivery_cost: Amount | None
    unknown_components: tuple[Text, ...]

    @model_validator(mode="after")
    def check_delivery(self) -> Self:
        if (self.delivery_cost is None) != ("delivery" in self.unknown_components):
            raise ValueError("Unknown delivery must be listed explicitly; a known delivery cannot be unknown")
        return self


class Alternative(ContractModel):
    alternative_id: Text
    explanation: Text
    changes: Annotated[tuple[RequestChange, ...], Field(min_length=1)]
    sources: Annotated[tuple[ConfirmedSource, ...], Field(min_length=1)]
    requires_client_confirmation: Literal[True]
    readiness: AlternativeReadiness = AlternativeReadiness.CONDITIONAL
    # Catalog membership, stock and hard constraints must be checked outside P3.3.
    externally_validated: bool = False
    cost: ExternalCost | None = None

    @model_validator(mode="after")
    def check_feasibility(self) -> Self:
        paths = [change.field_path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("Each changed field must have one unambiguous delta")
        if self.readiness == AlternativeReadiness.VERIFIED and (
            not self.externally_validated or self.cost is None or self.cost.unknown_components
        ):
            raise ValueError("Verified alternatives require external checks and complete cost data")
        return self


class UnreachableResult(ContractModel):
    """A problem response, never an accepted offer or an automatic request update.

    Conditional alternatives must be presented as requiring checks. Empty sources
    are allowed only when data or costs are unknown; confirmed rejection reasons
    must reference their supporting facts. No classifier or renderer is implemented.
    """

    status: Status
    reason: Reason
    explanation: Text
    sources: tuple[ConfirmedSource, ...]
    questions: tuple[Text, ...] = ()
    alternatives: tuple[Alternative, ...] = ()

    @model_validator(mode="after")
    def check_response(self) -> Self:
        if not self.sources and self.reason not in {Reason.MISSING_DATA, Reason.UNKNOWN_COSTS}:
            raise ValueError("This reason requires confirmed supporting sources")
        if self.status == Status.CLARIFY and not self.questions:
            raise ValueError("Clarify status requires a question")
        if self.status == Status.ALTERNATIVES:
            if not self.alternatives:
                raise ValueError("Alternatives status requires at least one option")
        elif self.alternatives:
            raise ValueError("Options require alternatives status")
        ids = [option.alternative_id for option in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("Alternative identifiers must be unique")
        return self


class ConflictDetail(ContractModel):
    """Two externally identified incompatible conditions, not free-text detection."""

    field_path: Text
    first_condition: Text
    second_condition: Text


class MissingDatum(ContractModel):
    field_path: Text
    label: Text


class HandlingRequest(ContractModel):
    """Adapter input. Flags attest external verification, not verification by P3.3.

    cost must cover the original request; each alternative cost must cover that
    alternative. Sources must support the supplied facts. P2 error strings are
    deliberately not an input. Original CustomerNeeds need not be passed or changed.
    """

    reason: Reason
    sources: tuple[ConfirmedSource, ...] = ()
    conflicts: tuple[ConflictDetail, ...] = ()
    missing_data: tuple[MissingDatum, ...] = ()
    product_name: Text | None = None
    product_unavailable_confirmed: bool = False
    budget: Amount | None = None
    budget_currency: Text | None = None
    cost: ExternalCost | None = None
    calculation_verified: bool = False
    alternatives: tuple[Alternative, ...] = ()

    @model_validator(mode="after")
    def unique_options(self) -> Self:
        ids = [option.alternative_id for option in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("Alternative identifiers must be unique")
        return self


def _clarify(reason: Reason, explanation: str, questions: tuple[str, ...],
             sources: tuple[ConfirmedSource, ...] = ()) -> UnreachableResult:
    return UnreachableResult(status=Status.CLARIFY, reason=reason, explanation=explanation,
                             questions=questions, sources=sources)


def _missing(*questions: str, sources: tuple[ConfirmedSource, ...] = ()) -> UnreachableResult:
    return _clarify(Reason.MISSING_DATA, "Для проверки заказа недостаточно подтверждённых данных.", questions, sources)


def _unknown_costs(request: HandlingRequest) -> UnreachableResult:
    if request.cost is not None and not request.cost.unknown_components and request.calculation_verified:
        return _missing("Укажите неизвестные расходы: переданный проверенный расчёт отмечен как полный.",
                        sources=request.sources)
    components = request.cost.unknown_components if request.cost is not None else ()
    labels = {"delivery": "стоимость доставки"}
    questions = tuple(f"Уточните {labels.get(name, name)}." for name in components)
    return _clarify(
        Reason.UNKNOWN_COSTS,
        "Полная стоимость неизвестна; неизвестные расходы не приняты за ноль. "
        "Соответствие заказа бюджету не подтверждено.",
        questions or ("Предоставьте проверенный полный расчёт с указанием стоимости доставки и прочих расходов.",),
        request.sources,
    )


def _confirmed_options(request: HandlingRequest) -> tuple[Alternative, ...]:
    options = []
    for option in request.alternatives:
        if (option.readiness != AlternativeReadiness.VERIFIED or not option.externally_validated
                or option.cost is None or option.cost.unknown_components):
            continue
        if request.budget is not None and (
            request.budget_currency is None or option.cost.currency != request.budget_currency
            or option.cost.known_total > request.budget
        ):
            continue
        options.append(option)
    return tuple(options)


def _with_options(request: HandlingRequest, explanation: str) -> UnreachableResult:
    options = _confirmed_options(request)
    if options:
        changes = "; ".join(
            f"{option.alternative_id}: " + ", ".join(
                f"{change.field_path}: {change.before!s} → {change.after!s}" for change in option.changes
            ) for option in options
        )
        return UnreachableResult(
            status=Status.ALTERNATIVES, reason=request.reason, sources=request.sources,
            explanation=f"{explanation} Предложены проверенные извне варианты. Изменения: {changes}. "
                        "Требуется согласие клиента; исходный запрос не изменён.",
            alternatives=options, questions=("Какой вариант изменения запроса вы согласовываете?",),
        )
    return UnreachableResult(
        status=Status.UNAVAILABLE, reason=request.reason, sources=request.sources,
        explanation=f"{explanation} Подтверждённые допустимые альтернативы не предоставлены. "
                    "Исходный запрос не изменён.",
        questions=("Какие требования вы готовы изменить для последующей проверки вариантов?",),
    )


def handle_unreachable(request: HandlingRequest) -> UnreachableResult:
    """Deterministic response to a structured problem; no calculation/selection engine.

    Only a difference between externally verified full total and budget is derived.
    Missing evidence produces a question, never inferred availability or zero cost.
    """
    if request.reason == Reason.MISSING_DATA:
        questions = tuple(f"Уточните {datum.label} ({datum.field_path})." for datum in request.missing_data)
        return _missing(*(questions or ("Укажите, какие поля потребностей клиента отсутствуют.",)),
                        sources=request.sources)
    if request.reason == Reason.UNKNOWN_COSTS:
        return _unknown_costs(request)
    if request.reason == Reason.CONFLICT:
        if (not request.conflicts or not request.sources or any(
            item.first_condition == item.second_condition for item in request.conflicts
        )):
            return _missing("Укажите различные конфликтующие условия и подтверждающие их источники.",
                            sources=request.sources)
        conditions = "; ".join(
            f"{item.field_path}: «{item.first_condition}» и «{item.second_condition}»"
            for item in request.conflicts
        )
        questions = tuple(
            f"Для {item.field_path} какое условие следует сохранить: «{item.first_condition}» "
            f"или «{item.second_condition}»?" for item in request.conflicts
        )
        return _clarify(Reason.CONFLICT, f"Переданы несовместимые требования: {conditions}. "
                        "Исходные требования сохранены до вашего решения.", questions, request.sources)
    if request.reason == Reason.PRODUCT_UNAVAILABLE:
        if not request.product_name or not request.product_unavailable_confirmed or not request.sources:
            return _missing("Укажите товар и подтверждённый результат проверки его доступности с источником.",
                            sources=request.sources)
        if request.budget is not None and request.budget_currency is None:
            return _missing("Укажите валюту бюджета для проверки переданных альтернатив.", sources=request.sources)
        return _with_options(request, f"По переданной проверке товар «{request.product_name}» недоступен.")

    # The remaining typed reason is insufficient_budget.
    if request.cost is None or not request.calculation_verified or not request.sources:
        return _missing("Предоставьте проверенный структурированный расчёт заказа и его источники.",
                        sources=request.sources)
    if request.cost.unknown_components:
        return _unknown_costs(request)
    if request.budget is None or request.budget_currency is None:
        return _missing("Укажите подтверждённый бюджет и его валюту для сравнения с полной стоимостью.",
                        sources=request.sources)
    if request.budget_currency != request.cost.currency:
        return _missing("Предоставьте бюджет и проверенный расчёт в одной валюте; курс не предполагается.",
                        sources=request.sources)
    if request.cost.known_total <= request.budget:
        return _missing("Переданный расчёт не подтверждает превышение бюджета. Уточните причину недостижимости заказа.",
                        sources=request.sources)
    total = request.cost.known_total
    # Preserve exact subtraction even for amounts beyond the ambient Decimal precision.
    low = min(total.as_tuple().exponent, request.budget.as_tuple().exponent)
    high = max(total.adjusted(), request.budget.adjusted())
    with localcontext() as context:
        context.prec = max(28, high - low + 2)
        difference = total - request.budget
    return _with_options(request, f"По проверенному расчёту полная стоимость {total} {request.cost.currency}, "
                         f"бюджет {request.budget} {request.budget_currency}. "
                         f"Превышение бюджета: {difference} {request.cost.currency}.")
