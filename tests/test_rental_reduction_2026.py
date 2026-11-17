"""Art. 23.2 LIRPF as worded by RDL 29/2026 (BOE-A-2026-20823), contracts from 01/12/2026.

Each case quotes the letter of the article it checks.
"""

from __future__ import annotations

import pytest

from rlm.realestate_rules import rental_reduction_pct_2026


def reduction(**overrides) -> int:
    facts = dict(
        large_holder=False,
        previously_rented=True,
        rent_change_pct=0.0,
        same_tenant_after_term=False,
        below_index=False,
        stressed_zone=False,
        tenant_age=40,
        public_or_social_tenant=False,
        rehabilitation_last_2y=False,
    )
    facts.update(overrides)
    return rental_reduction_pct_2026(**facts)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # a) 1.º a´): rent cut > 5 % and same tenant after the term, or below the index
        ({"rent_change_pct": -6, "same_tenant_after_term": True}, 100),
        ({"rent_change_pct": -6, "below_index": True}, 100),
        # a) 1.º b´) to e´)
        ({"rent_change_pct": -6, "stressed_zone": True, "tenant_age": 30}, 95),
        ({"rent_change_pct": -6, "stressed_zone": True}, 90),
        ({"rent_change_pct": -6, "tenant_age": 35}, 85),
        ({"rent_change_pct": -6}, 70),
        # a) 2.º: not above the previous rent (a 5 % cut is not "more than 5 %")
        ({"rent_change_pct": -5}, 50),
        ({"rent_change_pct": 0}, 50),
        # a) 3.º: increases, by bracket
        ({"rent_change_pct": 5}, 40),
        ({"rent_change_pct": 7}, 30),
        ({"rent_change_pct": 15}, 25),
        ({"rent_change_pct": 20}, 20),
        ({"rent_change_pct": 25}, 15),
        # b) first rental
        ({"previously_rented": False, "below_index": True}, 100),
        ({"previously_rented": False, "stressed_zone": True, "tenant_age": 25}, 95),
        ({"previously_rented": False, "stressed_zone": True}, 90),
        ({"previously_rented": False, "tenant_age": 18}, 85),
        ({"previously_rented": False}, 50),
        # large holder: neither a) nor b); only c) and d) remain
        ({"large_holder": True, "rent_change_pct": -10, "below_index": True}, 0),
        ({"large_holder": True, "public_or_social_tenant": True}, 70),
        ({"large_holder": True, "rehabilitation_last_2y": True}, 60),
        # the highest applicable reduction wins
        ({"rent_change_pct": 25, "rehabilitation_last_2y": True}, 60),
        ({"rent_change_pct": 25, "public_or_social_tenant": True}, 70),
    ],
)
def test_reduction_by_case(overrides, expected):
    assert reduction(**overrides) == expected
