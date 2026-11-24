"""One property through the whole rule engine: purchase, legal rent, yield, financing, IRPF.

``analyze`` is a pure function of a ``Property`` and an ``InvestorProfile``: it reads nothing
from the network and changes nothing. Three tools share it, so they cannot disagree:
``analyze_property`` (one property), ``screen_properties`` (all of them) and ``what_if``
(the same property with a lever applied). The rules live in ``rlm/realestate_rules.py`` and
the phase-2 calculators; this module only chains them and records what it had to assume.

Chaining is where the "listillo" starts: the rent that counts is the *legal* one, the ITP base
is the higher of price and reference value, the IRPF reduction depends on the contract date,
and the large-holder status depends on the investor's other dwellings. A user who looks at
each piece separately misses how they interact; the engine does not.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from agent.case_file import Assumption, CaseFile, InvestorProfile, Property
from rlm import realestate_rules as rules
from tool_use import calculators
from tool_use.itp_rates import ITP_GENERAL
from tool_use.public_data import declared_zones
from tool_use.regions import resolve_region

# Defaults used when the user does not say; each one becomes an Assumption in the answer.
DEFAULT_AJD_PCT = 1.5
DEFAULT_DOWN_PAYMENT_PCT = 20.0
DEFAULT_LOAN_YEARS = 25
DEFAULT_MARGINAL_TAX_PCT = 30.0

UNITS = {
    "price": "EUR",
    "transfer_tax": "EUR",
    "vat": "EUR",
    "stamp_duty": "EUR",
    "total_investment": "EUR",
    "itp_rate_pct": "%",
    "asking_rent": "EUR/month",
    "legal_max_rent": "EUR/month",
    "effective_rent": "EUR/month",
    "collected_rent": "EUR/year",
    "operating_costs": "EUR/year",
    "net_income": "EUR/year",
    "gross_yield_pct": "%",
    "net_yield_pct": "%",
    "loan": "EUR",
    "monthly_payment": "EUR/month",
    "annual_cash_flow": "EUR/year",
    "cash_on_cash_pct": "%",
    "irpf_depreciation": "EUR/year",
    "irpf_net_income": "EUR/year",
    "irpf_reduction_pct": "%",
    "irpf_reduced_net_income": "EUR/year",
    "income_tax": "EUR/year",
    "after_tax_income": "EUR/year",
    "after_tax_yield_pct": "%",
}


class Analysis(BaseModel):
    """Everything the engine says about one property, plus what was assumed or missing."""

    property_id: str
    figures: dict[str, float] = Field(default_factory=dict)
    region: str | None = None
    stressed_zone: bool | None = None
    large_holder: bool | None = None
    rules: dict[str, str] = Field(default_factory=dict)
    assumptions: list[Assumption] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def assume(self, field: str, value: Any, reason: str) -> Any:
        self.assumptions.append(
            Assumption(property_id=self.property_id, field=field, value=value, reason=reason)
        )
        return value

    def set(self, name: str, value: float) -> None:
        self.figures[name] = rules.round2(value)

    def record(self, case: CaseFile, tool: str, scenario: str = "base") -> None:
        """Write the figures (and, for the base scenario, the assumptions) into the case."""
        for name, value in self.figures.items():
            case.add_figure(name, value, UNITS.get(name, ""), tool, self.property_id, scenario)
        if scenario == "base":
            for a in self.assumptions:
                case.add_assumption(a.field, a.value, a.reason, a.property_id)

    def summary(self) -> dict[str, Any]:
        """What a tool returns to the model: compact, figures first."""
        out: dict[str, Any] = {"property_id": self.property_id, **self.figures}
        for key in ("region", "stressed_zone", "large_holder"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.rules:
            out["rules"] = self.rules
        if self.missing:
            out["missing"] = self.missing
        if self.warnings:
            out["warnings"] = self.warnings
        if self.assumptions:
            out["assumed"] = {a.field: a.value for a in self.assumptions}
        return out


def _region(prop: Property, profile: InvestorProfile, out: Analysis) -> str | None:
    for place in (prop.region, prop.municipality, profile.region):
        if place:
            try:
                return resolve_region(place)
            except (ValueError, KeyError) as exc:
                out.warnings.append(str(exc))
    out.missing.append("region (municipality or autonomous community)")
    return None


def _zone(prop: Property, out: Analysis) -> tuple[bool, bool, bool]:
    """(stressed_zone, zone_lowers_threshold, declaration_caps_unrented)."""
    zones = declared_zones(prop.municipality) if prop.municipality else []
    lowers = any(z["lowers_large_holder_threshold"] for z in zones)
    caps_unrented = any(z["caps_unrented"] for z in zones)
    if prop.stressed_zone is not None:
        return prop.stressed_zone, lowers, caps_unrented
    if prop.municipality:
        stressed = bool(zones)
        out.rules["stressed_zone"] = (
            "declarada en el BOE" if stressed else "municipio sin declaración vigente"
        )
        return stressed, lowers, caps_unrented
    out.assume("stressed_zone", False, "sin municipio no se puede consultar la declaración")
    return False, False, False


def _large_holder(profile: InvestorProfile, prop: Property, stressed: bool, lowers: bool, out):
    owned = profile.properties_owned
    if owned is None:
        owned = out.assume("properties_owned", 0, "el usuario no dijo cuántas viviendas tiene")
    in_zone = profile.properties_owned_stressed or 0
    area = (profile.area_owned_m2 or 0) + (prop.area_m2 or 0)
    lowers = profile.zone_lowers_threshold if profile.zone_lowers_threshold is not None else lowers
    # The status that matters is the one at signing, with this dwelling already bought.
    return rules.is_large_holder(
        dwellings_total=owned + 1,
        residential_m2=area,
        dwellings_in_zone=in_zone + (1 if stressed else 0),
        zone_lowers_threshold=lowers,
    )


def _first_year_interest(loan: float, rate_pct: float, years: int) -> float:
    i = rate_pct / 100 / 12
    payment = rules.mortgage_payment(loan, rate_pct / 100, years)
    balance, interest = loan, 0.0
    for _ in range(12):
        month_interest = balance * i
        interest += month_interest
        balance -= payment - month_interest
    return interest


def analyze(prop: Property, profile: InvestorProfile, today: date | None = None) -> Analysis:
    """Run one property through the engine. Never raises on missing data: it reports it."""
    out = Analysis(property_id=prop.id)
    if prop.price is None:
        out.missing.append("price")
        return out
    region = _region(prop, profile, out)
    out.region = region
    stressed, lowers, caps_unrented = _zone(prop, out)
    out.stressed_zone = stressed
    large_holder = _large_holder(profile, prop, stressed, lowers, out)
    out.large_holder = large_holder

    # 1. Purchase: ITP on max(price, reference value), or VAT + AJD for a new build.
    reference = prop.reference_value
    if reference is None and not prop.new_build:
        reference = out.assume(
            "reference_value", prop.price, "sin valor de referencia se supone igual al precio"
        )
    ajd = prop.ajd_rate_pct
    if prop.new_build and ajd is None:
        ajd = out.assume("ajd_rate_pct", DEFAULT_AJD_PCT, "tipo de AJD habitual")
    if region is None and not prop.new_build:
        return out
    itp_pct = ITP_GENERAL[region].rate_pct if region else 0.0
    cost = rules.acquisition_cost(
        price=prop.price,
        reference_value=reference or 0.0,
        new_build=prop.new_build,
        itp_rate=itp_pct / 100,
        ajd_rate=(ajd or 0.0) / 100,
        notary_registry=prop.notary_registry,
        agency_fee=prop.agency_fee,
        renovation=prop.renovation,
    )
    out.set("price", prop.price)
    if prop.new_build:
        out.set("vat", cost.vat)
        out.set("stamp_duty", cost.stamp_duty)
    else:
        out.set("itp_rate_pct", itp_pct)
        out.set("transfer_tax", cost.transfer_tax)
    out.set("total_investment", cost.total)
    investment = cost.total

    # 2. Rent: the one that counts is the legal maximum when the asking rent exceeds it.
    if prop.monthly_rent is None:
        out.missing.append("monthly_rent")
        return out
    rent = prop.monthly_rent
    if rent >= calculators.MAX_MONTHLY_RENT:
        # "10.200 € al mes" for a 140.000 € flat is a yearly figure or a typo: computing with it
        # gives a yield above 80 % that the auditor would accept, since a tool produced it.
        out.missing.append(
            f"monthly_rent: {rent:g} EUR per month looks like a yearly figure or a typo; "
            "ask the user (what_if with overrides can show both readings)"
        )
        return out
    out.set("asking_rent", rent)
    needs_index = stressed and (large_holder or (prop.previous_rent is None and caps_unrented))
    if needs_index and prop.index_upper_eur_m2 is None:
        out.missing.append("index_upper_eur_m2 (SERPAVI upper value: the legal cap depends on it)")
        out.warnings.append("legal_cap_unknown: se usa la renta pedida")
    elif stressed:
        cap = rules.legal_rent_cap(
            market_rent=rent,
            stressed_zone=True,
            large_holder=large_holder,
            previous_rent_updated=prop.previous_rent,
            ten_percent_exception=prop.rehabilitation_last_2y,
            index_upper_eur_m2=prop.index_upper_eur_m2 or 0.0,
            area_m2=prop.area_m2 or 1.0,
            declaration_caps_unrented=caps_unrented,
        )
        out.set("legal_max_rent", cap.max_rent)
        out.rules["legal_rent"] = cap.rule
        if cap.max_rent < rent:
            out.warnings.append(
                f"rent_above_legal_cap: {rent:g} €/mes pedidos, máximo legal {cap.max_rent:g}"
            )
            rent = cap.max_rent
    out.set("effective_rent", rent)

    # 3. Operating yield, before tax and financing.
    noi = rules.net_yield(
        monthly_rent=rent,
        vacant_months=prop.vacant_months,
        ibi=prop.ibi,
        community_monthly=prop.community_monthly,
        insurance=prop.insurance,
        maintenance_pct=prop.maintenance_pct / 100,
        management_pct=prop.management_pct / 100,
        total_investment=investment,
    )
    out.set("collected_rent", noi.collected_rent)
    out.set("operating_costs", noi.operating_costs)
    out.set("net_income", noi.net_income)
    out.set("gross_yield_pct", 100 * 12 * rent / investment)
    out.set("net_yield_pct", noi.net_yield_pct)

    # 4. Financing.
    interest = 0.0
    if profile.financing:
        down = profile.down_payment_pct
        if down is None:
            down = out.assume("down_payment_pct", DEFAULT_DOWN_PAYMENT_PCT, "entrada habitual")
        years = profile.loan_years or out.assume("loan_years", DEFAULT_LOAN_YEARS, "plazo habitual")
        if profile.interest_rate_pct is None:
            out.missing.append("interest_rate_pct (get_market_rates gives the Euribor)")
        else:
            loan = prop.price * (1 - down / 100)
            coc = rules.cash_on_cash(
                total_investment=investment,
                loan=loan,
                annual_rate=profile.interest_rate_pct / 100,
                years=years,
                annual_net_operating_income=noi.net_income,
            )
            out.set("loan", loan)
            out.set("monthly_payment", coc.monthly_payment)
            out.set("annual_cash_flow", coc.annual_cash_flow)
            out.set("cash_on_cash_pct", coc.cash_on_cash_pct)
            interest = _first_year_interest(loan, profile.interest_rate_pct, years)

    # 5. IRPF: depreciation, deductible costs and the reduction of the contract's date.
    if prop.cadastral_value is None or prop.land_share_pct is None:
        out.missing.append("cadastral_value and land_share_pct (IBI receipt) for the IRPF")
        return out
    contract = prop.contract_date
    if contract is None:
        contract = out.assume(
            "contract_date", today or date.today(), "fecha de firma no indicada: hoy"
        )
    try:
        tax = calculators.rental_income_tax.fn(
            annual_rent=noi.collected_rent,
            acquisition_cost_total=investment,
            cadastral_value=prop.cadastral_value,
            contract_date=contract,
            land_share_pct=prop.land_share_pct,
            ibi=prop.ibi,
            community_annual=12 * prop.community_monthly,
            insurance=prop.insurance,
            interest=interest,
            repairs=noi.collected_rent * prop.maintenance_pct / 100,
            stressed_zone=stressed,
            previously_rented=(
                prop.previously_rented
                if prop.previously_rented is not None
                else prop.previous_rent is not None
            ),
            monthly_rent=rent,
            previous_rent=prop.previous_rent,
            index_max_rent=(prop.index_upper_eur_m2 or 0) * (prop.area_m2 or 0) or None,
            large_holder=large_holder,
            tenant_age=prop.tenant_age,
            rehabilitation_last_2y=prop.rehabilitation_last_2y,
        )
    except ValueError as exc:
        out.missing.append(f"IRPF: {exc}")
        return out
    out.set("irpf_depreciation", tax["depreciation"])
    out.set("irpf_net_income", tax["net_income"])
    out.set("irpf_reduction_pct", tax["reduction_pct"])
    out.set("irpf_reduced_net_income", tax["reduced_net_income"])
    out.rules["irpf_reduction"] = tax["reduction_rule"]
    out.warnings.extend(w for w in tax["warnings"] if "variación" not in w)
    marginal = profile.marginal_tax_rate_pct
    if marginal is None:
        marginal = out.assume(
            "marginal_tax_rate_pct", DEFAULT_MARGINAL_TAX_PCT, "tipo marginal medio de IRPF"
        )
    # A negative net rental income lowers the rest of the general tax base: a saving.
    income_tax = tax["reduced_net_income"] * marginal / 100
    out.set("income_tax", income_tax)
    out.set("after_tax_income", noi.net_income - income_tax)
    out.set("after_tax_yield_pct", 100 * (noi.net_income - income_tax) / investment)
    return out
