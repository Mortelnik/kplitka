"""Execute the unchanged published P2; inputs are educational, never commercial proof."""

import hashlib
import importlib.util
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from kp_plugin.llm.needs import CustomerNeedItem, CustomerNeeds
from kp_plugin.llm.p2_adapter import P2Settings, prepare_p2_invocation, run_p2
from kp_plugin.llm.p4_catalog import P4Catalog
from kp_plugin.llm.selection import CatalogProduct, SelectionSource, select_products
from kp_plugin.llm.selection_bridge import assess_selection
from kp_plugin.llm.unreachable import ConfirmedSource, Reason

COMMIT = "47cb8314048da277ec4f85f969a01600a7b2965e"
SHA256 = "56eaa710080d061dba7ce395297db45031736618ad76016854de5a48be56643e"
FIXTURE = Path(__file__).parent / "fixtures" / "p2_47cb831" / "calculation.py"


@pytest.fixture
def core():
    content = FIXTURE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == SHA256
    assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == (
        "b36145c8b79f6377bde9f3067c7feb02471719f3"
    )
    spec = importlib.util.spec_from_file_location("published_p2_47cb831", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.calculate_offer


def inputs(quantity="26", tenure="2", discount="5"):
    source = SelectionSource(source_id="educational:catalog", version="v1", locator="P1")
    # This attests identity within this fixture ONLY, never prices, stock or business rules.
    identity = ConfirmedSource(**source.model_dump(), confirmed=True)
    product = CatalogProduct(product_id="P1", name="Учебный товар", unit="т", status="active", sources=(source,))
    needs = CustomerNeeds([CustomerNeedItem(product.name, Decimal(quantity), "т")])
    profile = P4Catalog((product,), (), ())
    return {
        "needs": needs, "profile": profile, "selection": select_products(needs, profile.products),
        "catalog": {"P1": {"product_id": "P1", "name": product.name, "unit": "т", "status": "active",
                            "container_capacity_tons": "26", "source_ref": source.source_id, "is_fictional": "да"}},
        "prices": {"P1": {"product_id": "P1", "currency": "RUB", "unit_price_rub_per_t": "100", "tax_rate": "0.1",
                           "source_ref": "educational:price", "is_fictional": "да"}},
        "rules": {"pricing": {"currency": "RUB"}, "discounts": {"rules": [
            {"id": "L", "type": "loyalty", "percent": 5},
            {"id": "V", "type": "volume_containers", "percent": 10},
        ]}},
        "settings": P2Settings(profile_id="educational", profile_version="v1", price_snapshot_id="v1",
                            p2_implementation=COMMIT, currency="RUB", input_sources=(identity,),
                            client_tenure_years=Decimal(tenure), requested_discount=Decimal(discount)),
    }


# Independent fixed expectations: 26t costs 2600; 5%=130; net2470; VAT247; total2717.
# 132t costs13200; 10%=1320; net11880; VAT1188; total13068. No runtime oracle/formula copy.
@pytest.mark.parametrize("quantity,tenure,discount,containers,pickup,base,reduction,tax,total,rule", [
    ("2.5", "2", "0", 0, 2.5, "250.00", "0.00", "25.00", "275.00", "Мелкий опт (скидки не предусмотрены)"),
    ("26", "2", "5", 1, 0.0, "2600.00", "130.00", "247.00", "2717.00", "L (стаж от 1 года)"),
    ("132", "2", "10", 5, 2.0, "13200.00", "1320.00", "1188.00", "13068.00", "V (от 5 контейнеров)"),
    ("26", "0", "0", 1, 0.0, "2600.00", "0.00", "260.00", "2860.00", "Без скидки"),
])
def test_real_calculations(core, quantity, tenure, discount, containers, pickup, base, reduction, tax, total, rule):
    data = inputs(quantity, tenure, discount)
    before = deepcopy(data)
    result = run_p2(**data, calculate_offer=core)
    assert result.successful_calculation, result.diagnostics
    assert result.raw_output == {"product": "Учебный товар", "product_source": "educational:catalog",
                                    "price_source": "educational:price", "containers": containers, "pickup_tons": pickup,
                                    "base_amount": Decimal(base), "discount_amount": Decimal(reduction),
                                    "tax": Decimal(tax), "total": Decimal(total), "discount_rule": rule}
    assert all(isinstance(result.raw_output[k], Decimal) for k in ("base_amount", "discount_amount", "tax", "total"))
    assert not result.trusted_inputs and not result.complete_delivery_cost
    assert result.evidence is None
    assert data == before
    assert data["needs"].__dict__ == before["needs"].__dict__


def test_real_discount_error_preserved(core):
    data = inputs(discount="6")
    result = run_p2(**data, calculate_offer=core)
    assert result.error_text == "Ошибка: Запрошенная скидка 6% превышает допустимый лимит (5.00%)"
    assert result.diagnostics == ("p2_text_error",)
    assert not result.successful_calculation and result.evidence is None


@pytest.mark.parametrize("missing,expected", [
    ("catalog", "Ошибка: Продукт не найден в каталоге"),
    ("prices", "Ошибка: Для продукта нет цены в прайсе"),
])
def test_real_core_lookup_errors(core, missing, expected):
    data = inputs()
    data[missing] = {}
    # Adapter correctly blocks these before invocation; exercise raw P2 error contract separately.
    assert core("P1", Decimal(26), data["catalog"], data["prices"], data["rules"]) == expected
    result = run_p2(**data, calculate_offer=core)
    assert not result.successful_calculation and result.evidence is None
    assert result.diagnostics == ("selected_product_data_mismatch",)


@pytest.mark.parametrize("unsupported", ["unit", "multiple", "seasonal", "zero"])
def test_unsupported_inputs_never_reach_real_core(core, unsupported):
    data = inputs()
    if unsupported == "unit":
        data["needs"].items[0].unit = "кг"
    elif unsupported == "multiple":
        data["needs"].items.append(deepcopy(data["needs"].items[0]))
    elif unsupported == "seasonal":
        data["rules"]["discounts"]["rules"][0]["type"] = "seasonal_line_clearance"
    else:
        data["needs"].items[0].quantity = Decimal(0)
    data["selection"] = select_products(data["needs"], data["profile"].products)
    before = deepcopy(data["needs"])
    calls = []

    def observed(**kwargs):
        calls.append(kwargs)
        return core(**kwargs)

    result = run_p2(**data, calculate_offer=observed)
    assert not calls
    assert not result.successful_calculation and result.evidence is None
    assert result.needs == before and data["needs"] == before


def test_real_pipeline_keeps_unknown_commercial_facts(core):
    data = inputs()
    before = deepcopy(data["needs"])
    current = prepare_p2_invocation(**data)
    result = run_p2(**data, calculate_offer=core)
    assert result.successful_calculation
    assert set(current.base_context.unknown_components) == {"delivery", "other_costs"}
    assessed = assess_selection(data["needs"], data["selection"], data["profile"],
                                calculation=result.evidence_for(current), calculation_context=current.bridge_context,
                                confirmed_sources=data["settings"].input_sources)
    assert not assessed.calculation_confirmed
    # No trusted evidence is fabricated: bridge reports missing calculation rather than a verified partial cost.
    assert "calculation_missing" in assessed.calculation_issues
    assert Reason.MISSING_DATA in {p.request.reason for p in assessed.problems}
    assert any(c.unknown_data for p in assessed.selection.positions for c in p.candidates)
    assert not any(p.response.alternatives for p in assessed.problems)
    assert data["needs"] == before


def test_real_decimal_exception_is_preserved(core):
    data = inputs()
    data["prices"]["P1"]["unit_price_rub_per_t"] = "1e100"
    result = run_p2(**data, calculate_offer=core)
    assert result.exception_type == "InvalidOperation"
    assert result.exception_message
    assert result.diagnostics == ("p2_exception",)
    assert not result.successful_calculation and result.evidence is None
