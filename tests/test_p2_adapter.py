"""Injected protocol fixtures only: local P2 is a stub, no real formulas tested."""

from copy import deepcopy
from decimal import Decimal

import pytest

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds
from kp_plugin.llm.p2_adapter import P2Settings, prepare_p2_invocation, run_p2
from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import CatalogProduct, SelectionSource, select_products
from kp_plugin.llm.selection_bridge import assess_selection
from kp_plugin.llm.unreachable import ConfirmedSource, Reason


def bundle():
    source = SelectionSource(source_id="test-catalog", version="v1", locator="P1")
    confirmed = ConfirmedSource(**source.model_dump(), confirmed=True)
    product = CatalogProduct(product_id="P1", name="Учебный товар", unit="т", status="active", sources=(source,),
                             stock_quantity=Decimal("50.5"), stock_sources=(source,), constraints_check="passed",
                             constraint_sources=(source,))
    needs = CustomerNeeds([CustomerNeedItem(product.name, Decimal("2.5"), "т")])
    profile = P4Catalog((product,), (), ())
    return {
        "needs": needs, "profile": profile, "selection": select_products(needs, profile.products),
        "catalog": {"P1": {"product_id": "P1", "name": product.name, "unit": "т", "status": "active",
                           "container_capacity_tons": "26", "source_ref": source.source_id, "is_fictional": "нет"}},
        "prices": {"P1": {"product_id": "P1", "currency": "RUB", "unit_price_rub_per_t": "100",
                          "tax_rate": "0.1", "source_ref": "test-price", "is_fictional": "нет"}},
        "rules": {"pricing": {"currency": "RUB"}, "discounts": {"rules": [
            {"id": "test-loyalty", "type": "loyalty", "percent": 5},
        ]}},
        "settings": P2Settings(profile_id="fixture-company", profile_version="v1", price_snapshot_id="prices-v1",
                               p2_implementation="fixture:NOT-REAL-P2", currency="RUB", trusted_inputs=True,
                               input_sources=(confirmed,)),
    }


def response():
    # Contract-only constants. No calculation of price, tax, discounts or total here.
    return {"product": "Учебный товар", "product_source": "test-catalog", "price_source": "test-price",
            "containers": 0, "pickup_tons": 2.5, "base_amount": Decimal("80.0"), "discount_rule": "fixture",
            "discount_amount": Decimal("0.0"), "tax": Decimal("8.0"), "total": Decimal("88.0")}


def calculate_offer(product_id, quantity_tons, catalog, prices, rules, client_tenure_years=0, requested_discount=0):
    """Same signature as audited 47cb831, not an emulation of its business logic."""
    assert product_id == "P1"
    assert quantity_tons == Decimal("2.5")
    return response()


def test_success_preserves_decimals_and_is_partial_delivery() -> None:
    data = bundle()
    before = deepcopy(data)
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert result.successful_calculation and result.trusted_inputs
    assert not result.complete_delivery_cost
    assert result.raw_output["total"] == Decimal("88.0")
    assert isinstance(result.raw_output["total"], Decimal)
    assert result.evidence.cost.known_total == result.raw_output["total"]
    assert result.evidence.cost.delivery_cost is None
    assert set(result.evidence.cost.unknown_components) == {"delivery", "other_costs"}
    assert data == before
    assert data["needs"].items[0].evidence == before["needs"].items[0].evidence


def test_current_evidence_passes_bridge_only_as_partial_cost() -> None:
    data = bundle()
    result = run_p2(**data, calculate_offer=calculate_offer)
    current = prepare_p2_invocation(**data)
    evidence = result.evidence_for(current)
    assert evidence is not None
    assessed = assess_selection(data["needs"], data["selection"], data["profile"],
                                calculation=evidence, calculation_context=current.bridge_context,
                                confirmed_sources=data["settings"].input_sources)
    assert assessed.calculation_issues == ()
    assert not assessed.calculation_confirmed
    assert Reason.UNKNOWN_COSTS in {problem.request.reason for problem in assessed.problems}
    assert not any(problem.response.alternatives for problem in assessed.problems)


def test_explicit_zero_delivery_and_no_other_unknown_costs_are_required_for_full_cost() -> None:
    data = bundle()
    data["settings"] = data["settings"].model_copy(update={"delivery_cost": Decimal("0.0"),
                                                         "delivery_sources": data["settings"].input_sources,
                                                         "other_unknown_costs": ()})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert result.complete_delivery_cost
    assert result.evidence.cost.unknown_components == ()
    assert result.evidence.cost.known_total == response()["total"]


def test_positive_known_delivery_not_added_to_p2_total() -> None:
    data = bundle()
    data["settings"] = data["settings"].model_copy(update={"delivery_cost": Decimal("10.5"),
                                                         "delivery_sources": data["settings"].input_sources,
                                                         "other_unknown_costs": ()})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert result.complete_delivery_cost
    assert result.evidence.cost.known_total == response()["total"]
    assert result.evidence.cost.unknown_components == ("delivery_not_in_p2_total",)


@pytest.mark.parametrize("amount", [None, True, "oops", Decimal("0.0"), Decimal("-1.5"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_quantity_never_calls_core(amount: object) -> None:
    data = bundle()
    data["needs"].items[0].quantity = amount
    data["selection"] = select_products(data["needs"], data["profile"].products)
    def fail(**kwargs):
        pytest.fail("Invalid input reached P2")
    result = run_p2(**data, calculate_offer=fail)
    assert not result.successful_calculation
    assert result.diagnostics


def test_unsupported_unit_and_multi_item_preserve_order() -> None:
    for multiple in (False, True):
        data = bundle()
        if multiple:
            data["needs"].items.append(deepcopy(data["needs"].items[0]))
        else:
            data["needs"].items[0].unit = "кг"
        data["selection"] = select_products(data["needs"], data["profile"].products)
        result = run_p2(**data, calculate_offer=calculate_offer)
        assert not result.successful_calculation
        assert len(result.needs.items) == len(data["needs"].items)


def test_text_error_kept_opaque_and_separate_from_exception() -> None:
    raw = "Ошибка: неизвестный текст без стабильного кода"
    result = run_p2(**bundle(), calculate_offer=lambda **kwargs: raw)
    assert result.error_text == result.raw_output == raw
    assert result.exception_type is None
    assert result.diagnostics == ("p2_text_error",)
    assert result.evidence is None


def test_exception_preserved_without_classification() -> None:
    def throws(**kwargs):
        raise RuntimeError("opaque failure")
    result = run_p2(**bundle(), calculate_offer=throws)
    assert result.exception_type == "RuntimeError"
    assert result.exception_message == "opaque failure"
    assert result.error_text is None


@pytest.mark.parametrize("field,value", [("total", "88"), ("total", Decimal("NaN")), ("tax", Decimal("Infinity")),
                                        ("total", Decimal("-1.5")), ("containers", True), ("pickup_tons", float("nan")),
                                        ("product_source", "wrong"), ("discount_rule", "")])
def test_corrupt_output_does_not_become_evidence(field: str, value: object) -> None:
    output = response() | {field: value}
    result = run_p2(**bundle(), calculate_offer=lambda **kwargs: output)
    assert not result.successful_calculation
    assert result.evidence is None
    assert result.raw_output.keys() == output.keys()


def test_missing_required_output_and_wrong_result_type() -> None:
    for output in ({"total": Decimal("88.0")}, [], None):
        result = run_p2(**bundle(), calculate_offer=lambda output=output, **kwargs: output)
        assert not result.successful_calculation
        assert result.diagnostics


@pytest.mark.parametrize("change", ["catalog", "prices", "rules", "client_tenure_years", "requested_discount", "p2_implementation"])
def test_execution_snapshot_changes_invalidate_old_evidence_even_if_price_label_reused(change: str) -> None:
    data = bundle()
    result = run_p2(**data, calculate_offer=calculate_offer)
    if change == "catalog":
        data["catalog"]["P1"]["container_capacity_tons"] = "27"
    elif change == "prices":
        data["prices"]["P1"]["unit_price_rub_per_t"] = "101"
    elif change == "rules":
        data["rules"]["discounts"]["rules"][0]["percent"] = 4
    else:
        value = "fixture:new-implementation" if change == "p2_implementation" else Decimal("1.5")
        data["settings"] = data["settings"].model_copy(update={change: value})
    current = prepare_p2_invocation(**data)
    assert result.evidence_for(current) is None
    assessed = assess_selection(data["needs"], data["selection"], data["profile"], calculation=result.evidence,
                                calculation_context=current.bridge_context)
    assert "calculation_context_changed" in assessed.calculation_issues


@pytest.mark.parametrize("field", ["profile_id", "profile_version", "price_snapshot_id", "p2_implementation", "currency"])
def test_missing_versions_block_call(field: str) -> None:
    data = bundle()
    data["settings"] = data["settings"].model_copy(update={field: None})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert not result.successful_calculation
    assert field in result.diagnostics[0]


def test_synthetic_inputs_may_compute_but_never_attest_commercial_trust() -> None:
    data = bundle()
    data["catalog"]["P1"]["is_fictional"] = "да"
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert result.successful_calculation
    assert not result.trusted_inputs
    assert result.evidence is None


def test_untrusted_inputs_and_missing_calculator() -> None:
    data = bundle()
    data["settings"] = data["settings"].model_copy(update={"trusted_inputs": False})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert result.successful_calculation and not result.trusted_inputs
    assert result.evidence is None
    assert run_p2(**data).diagnostics == ("calculate_offer_unavailable_local_stub",)


def test_input_mappings_are_detached_from_mutating_calculator() -> None:
    data = bundle()
    before = deepcopy(data)
    def mutates(**kwargs):
        kwargs["catalog"].clear()
        kwargs["prices"].clear()
        kwargs["rules"].clear()
        return response()
    result = run_p2(**data, calculate_offer=mutates)
    assert result.successful_calculation
    assert data == before
    assert result.invocation.catalog


@pytest.mark.parametrize("field", ["catalog", "prices", "rules"])
def test_invalid_structure_returns_diagnostic(field: str) -> None:
    data = bundle()
    data[field] = []
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert not result.successful_calculation


@pytest.mark.parametrize("change", ["draft", "capacity", "price", "currency", "rule", "identity_sources"])
def test_invalid_or_unconfirmed_inputs_block_core(change: str) -> None:
    data = bundle()
    if change == "draft":
        data["catalog"]["P1"]["status"] = "draft"
    elif change == "capacity":
        data["catalog"]["P1"]["container_capacity_tons"] = "0"
    elif change == "price":
        data["prices"]["P1"]["unit_price_rub_per_t"] = "NaN"
    elif change == "currency":
        data["prices"]["P1"]["currency"] = "USD"
    elif change == "rule":
        data["rules"]["discounts"]["rules"][0]["type"] = "seasonal_line_clearance"
    else:
        data["settings"] = data["settings"].model_copy(update={"input_sources": ()})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert not result.successful_calculation
    assert result.invocation is None


def test_delivery_zero_without_source_does_not_become_known() -> None:
    data = bundle()
    data["settings"] = data["settings"].model_copy(update={"delivery_cost": Decimal("0.0")})
    result = run_p2(**data, calculate_offer=calculate_offer)
    assert not result.complete_delivery_cost
    assert result.evidence.cost.delivery_cost is None
    assert "delivery" in result.evidence.cost.unknown_components
