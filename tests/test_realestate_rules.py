"""The rule engine is the ground truth of phase 1: every rule has a case solved by hand.

Each test quotes the article it checks. If a test and the law disagree, the law wins and
both the engine and the test change.
"""

import pytest

from rlm import realestate_rules as r


def test_itp_uses_reference_value_when_higher():
    # TRLITPAJD art. 10 after Ley 11/2021: base = max(price, reference value).
    cost = r.acquisition_cost(180_000, 195_000, False, 0.07, 0.0, 3_200, 0, 12_000)
    assert cost.tax_base == 195_000
    assert cost.transfer_tax == 13_650
    assert cost.total == 208_850


def test_itp_uses_price_when_reference_is_lower():
    cost = r.acquisition_cost(200_000, 170_000, False, 0.06, 0.0, 2_000, 0, 0)
    assert cost.transfer_tax == 12_000
    assert cost.total == 214_000


def test_new_build_pays_vat_and_ajd_not_itp():
    cost = r.acquisition_cost(250_000, 240_000, True, 0.10, 0.012, 3_000, 0, 0)
    assert cost.transfer_tax == 0
    assert cost.vat == 25_000
    assert cost.stamp_duty == 3_000  # 1.2 % of max(250.000, 240.000)
    assert cost.total == 281_000


def test_net_yield_applies_percentages_to_collected_rent():
    result = r.net_yield(1_000, 1, 400, 50, 200, 0.05, 0.0, 200_000)
    # collected 11.000; costs 400 + 600 + 200 + 550 = 1.750; net 9.250 -> 4,625 % -> 4,63
    assert result.collected_rent == 11_000
    assert result.operating_costs == 1_750
    assert result.net_yield_pct == 4.63


@pytest.mark.parametrize(
    ("total", "m2", "in_zone", "lowers", "expected"),
    [
        (10, 900, 0, False, False),  # "más de diez": ten is not enough
        (11, 900, 0, False, True),
        (3, 1_501, 0, False, True),  # more than 1.500 m2 residential
        (5, 400, 5, True, True),  # zone declaration lowers the threshold to five in the zone
        (5, 400, 5, False, False),
        (6, 500, 4, True, False),  # five in total but only four in the zone
    ],
)
def test_large_holder_thresholds(total, m2, in_zone, lowers, expected):
    # Ley 12/2023 art. 3.k.
    assert r.is_large_holder(total, m2, in_zone, lowers) is expected


def cap(**overrides):
    params = dict(
        market_rent=950,
        stressed_zone=True,
        large_holder=False,
        previous_rent_updated=780,
        ten_percent_exception=False,
        index_upper_eur_m2=12.0,
        area_m2=70,
        declaration_caps_unrented=False,
    )
    params.update(overrides)
    return r.legal_rent_cap(**params)


def test_no_cap_outside_stressed_zone():
    assert cap(stressed_zone=False).max_rent == 950


def test_previous_rent_caps_small_landlord():
    # LAU 17.6: last rent, updated, of a contract in the last five years.
    result = cap()
    assert (result.max_rent, result.rule) == (780, "previous_rent")


def test_ten_percent_exception():
    assert cap(ten_percent_exception=True).max_rent == 858


def test_large_holder_gets_the_lower_of_both_caps():
    # LAU 17.7 applies "sin perjuicio" of 17.6: index 12 x 70 = 840 vs previous 780.
    assert cap(large_holder=True).max_rent == 780
    assert cap(large_holder=True, previous_rent_updated=900).max_rent == 840


def test_unrented_dwelling_depends_on_the_declaration():
    assert cap(previous_rent_updated=None).rule == "zone_uncapped"
    assert cap(previous_rent_updated=None, declaration_caps_unrented=True).max_rent == 840


def test_market_below_cap_wins():
    result = cap(market_rent=700)
    assert (result.max_rent, result.rule) == (700, "market_below_cap")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (dict(stressed_zone=True, previously_rented=True, rent_cut_over_5pct=True), 90),
        (dict(stressed_zone=True, previously_rented=False, tenant_age=27), 70),
        (dict(stressed_zone=True, previously_rented=False, tenant_age=36), 50),
        (dict(stressed_zone=False, previously_rented=False, tenant_age=27), 50),
        (dict(public_or_social_tenant=True), 70),
        (dict(rehabilitation_last_2y=True), 60),
        (dict(stressed_zone=True, previously_rented=True, rehabilitation_last_2y=True), 60),
    ],
)
def test_irpf_reduction_order(kwargs, expected):
    # LIRPF art. 23.2, applied in order 90 > 70 > 60 > 50.
    base = dict(
        stressed_zone=False,
        previously_rented=False,
        rent_cut_over_5pct=False,
        tenant_age=50,
        public_or_social_tenant=False,
        rehabilitation_last_2y=False,
    )
    base.update(kwargs)
    assert r.rental_reduction_pct(**base) == expected


def test_rental_income_tax_worked_example():
    # The example in docs/propuesta.md: depreciation 3 % x 190.000 x 60 % = 3.420.
    result = r.rental_income_tax(10_200, 420, 720, 180, 2_900, 400, 190_000, 110_000, 0.4, 70)
    assert result.depreciation == 3_420
    assert result.net_income == 2_160
    assert result.reduced_net_income == 648


def test_interest_and_repairs_are_capped_at_gross_income():
    result = r.rental_income_tax(6_000, 300, 600, 150, 7_000, 800, 150_000, 90_000, 0.5, 50)
    assert result.deductible_financing_repairs == 6_000
    assert result.net_income < 0


def test_no_reduction_on_negative_income():
    result = r.rental_income_tax(6_000, 300, 600, 150, 7_000, 800, 150_000, 90_000, 0.5, 90)
    assert result.reduction_pct == 0
    assert result.reduced_net_income == result.net_income


def test_mortgage_payment_matches_proposal():
    assert r.round2(r.mortgage_payment(180_000, 0.029, 25)) == 844.25


def test_cash_on_cash():
    result = r.cash_on_cash(212_000, 114_000, 0.0225, 20, 9_400)
    assert result.monthly_payment == 590.30
    assert result.cash_on_cash_pct == 2.36


def test_max_price_inverts_the_yield():
    price = r.max_price_for_target_yield(13_120, 0.04, 0.035, 13_500)
    assert 13_120 / (price * 1.035 + 13_500) == pytest.approx(0.04, abs=1e-6)
