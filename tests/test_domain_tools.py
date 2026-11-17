"""Domain tools: the calculators agree with the rule engine and the portfolio keeps state."""

from __future__ import annotations

import pytest

from tool_use.registry import split_docstring
from tool_use.tools import arithmetic_registry, calculator, default_registry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_PORTFOLIO_DB", str(tmp_path / "portfolio.sqlite"))
    return default_registry()


def run(registry, name, **arguments):
    record = registry.call(name, arguments)
    assert record.ok, record.error
    return record.result


def test_docstring_args_become_property_descriptions():
    description, args = split_docstring(
        """Do a thing.

        Longer text.

        Args:
            x: The first
                argument, continued.
            y (int): The second.

        Returns:
            Something.
        """
    )
    assert description == "Do a thing.\n\nLonger text.\n\nReturns:\n    Something."
    assert args == {"x": "The first argument, continued.", "y": "The second."}


def test_every_argument_of_every_tool_is_described(registry):
    for definition in registry.definitions():
        params = definition["function"]["parameters"]
        assert "Args:" not in definition["function"]["description"]
        for name, prop in params["properties"].items():
            assert prop.get("description"), f"{definition['function']['name']}.{name}"
            assert "title" not in prop


def test_acquisition_cost_uses_reference_value_and_regional_itp(registry):
    # docs/propuesta.md, first worked example: Málaga, ITP 7 % on the reference value.
    result = run(
        registry,
        "acquisition_cost",
        price=180000,
        region="andalucia",
        reference_value=195000,
        notary_registry=3200,
        renovation=12000,
    )
    assert result["transfer_tax"] == 13650 and result["total"] == 208850
    assert any("sin verificar" in w for w in result["warnings"])


def test_acquisition_cost_new_build_needs_ajd(registry):
    record = registry.call(
        "acquisition_cost", {"price": 200000, "region": "madrid", "new_build": True}
    )
    assert not record.ok and "ajd_rate_pct" in record.error
    result = run(
        registry,
        "acquisition_cost",
        price=200000,
        region="madrid",
        new_build=True,
        ajd_rate_pct=0.75,
    )
    assert result["vat"] == 20000 and result["stamp_duty"] == 1500 and result["transfer_tax"] == 0


def test_bad_region_is_a_validation_error(registry):
    record = registry.call("acquisition_cost", {"price": 1, "region": "valencia"})
    assert not record.ok and "comunidad_valenciana" in record.error


def test_rental_returns_with_mortgage_and_stress(registry):
    result = run(
        registry,
        "rental_returns",
        monthly_rent=900,
        total_investment=200000,
        loan=120000,
        interest_rate_pct=3.2,
        loan_years=25,
        rate_shock_pct=2,
    )
    assert result["gross_yield_pct"] == 5.4 and result["net_yield_pct"] == 5.4
    assert result["financing"]["monthly_payment"] == 581.61
    assert result["stress"]["cash_on_cash_pct"] < result["financing"]["cash_on_cash_pct"]


def test_max_offer_price_reaches_the_target(registry):
    result = run(
        registry,
        "max_offer_price",
        target_net_yield_pct=5,
        monthly_rent=1000,
        region="madrid",
        fixed_costs=5000,
    )
    price = result["max_price"]
    assert abs(12000 / (price * 1.06 + 5000) - 0.05) < 1e-4


def test_legal_rent_cap_previous_rent_and_index(registry):
    # docs/propuesta.md, second worked example: not a large holder, 17.6 applies.
    result = run(
        registry,
        "legal_rent_cap",
        market_rent=950,
        stressed_zone=True,
        large_holder=False,
        area_m2=70,
        previous_rent=780,
    )
    assert result["max_monthly_rent"] == 780 and result["binding_rule"] == "previous_rent"
    record = registry.call(
        "legal_rent_cap",
        {"market_rent": 950, "stressed_zone": True, "large_holder": True, "area_m2": 70},
    )
    assert not record.ok and "index_upper_eur_m2" in record.error


def test_rental_income_tax_derives_the_reduction(registry):
    # docs/propuesta.md, third worked example: young tenant, first rental, stressed zone.
    base = dict(
        annual_rent=10200,
        ibi=420,
        community_annual=720,
        insurance=180,
        interest=2900,
        repairs=400,
        acquisition_cost_total=190000,
        cadastral_value=110000,
        land_share_pct=40,
        stressed_zone=True,
        previously_rented=False,
        tenant_age=27,
    )
    result = run(registry, "rental_income_tax", contract_date="2024-03-01", **base)
    assert result["depreciation"] == 3420 and result["reduced_net_income"] == 648
    assert result["reduction_pct"] == 70
    old = run(registry, "rental_income_tax", contract_date="2022-01-10", **base)
    assert old["reduction_pct"] == 60
    # Same facts after 01/12/2026: first rental, stressed zone, tenant under 35 -> 95 %.
    new = run(registry, "rental_income_tax", contract_date="2026-12-15", **base)
    assert new["reduction_pct"] == 95 and "RDL 29/2026" in new["reduction_rule"]
    # Below the SERPAVI limit it reaches 100 %, and nothing is taxed.
    below = run(
        registry,
        "rental_income_tax",
        contract_date="2026-12-15",
        monthly_rent=850,
        index_max_rent=900,
        **base,
    )
    assert below["reduction_pct"] == 100 and below["reduced_net_income"] == 0


def test_rental_income_tax_new_regime_needs_the_rent_change(registry):
    base = dict(
        annual_rent=12000,
        acquisition_cost_total=200000,
        cadastral_value=100000,
        land_share_pct=40,
        contract_date="2027-01-01",
    )
    record = registry.call("rental_income_tax", base)
    assert not record.ok and "previous_rent" in record.error
    raised = run(registry, "rental_income_tax", monthly_rent=1250, previous_rent=1000, **base)
    assert raised["reduction_pct"] == 15  # +25 %
    cut = run(registry, "rental_income_tax", monthly_rent=900, previous_rent=1000, **base)
    assert cut["reduction_pct"] == 70  # -10 %, no other condition


def test_portfolio_saves_deduplicates_and_detects_large_holder(registry):
    empty = run(registry, "get_portfolio")
    assert empty["dwellings"] == 0 and not empty["large_holder"]
    for i in range(5):
        run(
            registry,
            "save_to_portfolio",
            label=f"Piso {i}",
            municipality="Barcelona",
            area_m2=80,
            stressed_zone=True,
            cadastral_ref=f"9872023VH5797S{i:04d}AB",
        )
    again = run(
        registry,
        "save_to_portfolio",
        label="Piso 0",
        municipality="Barcelona",
        area_m2=80,
        stressed_zone=True,
        cadastral_ref="9872023VH5797S0000AB",
    )
    assert again["saved"] is False
    general = run(registry, "get_portfolio")
    assert general["dwellings"] == 5 and not general["large_holder"]
    zone = run(registry, "get_portfolio", municipality="barcelona", zone_lowers_threshold=True)
    assert zone["dwellings_in_zone"] == 5 and zone["large_holder"]


def test_save_to_portfolio_requires_confirmation(registry):
    assert registry.tools["save_to_portfolio"].requires_confirmation
    assert not registry.tools["get_portfolio"].requires_confirmation


def test_arithmetic_registry_is_only_the_calculator():
    assert list(arithmetic_registry().tools) == ["calculator"]
    assert calculator(expression="2 ** 10") == 1024
