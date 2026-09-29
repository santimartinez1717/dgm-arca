"""Domain rewards: Spanish-format accuracy and the traceable-breakdown reward."""

from rlm.realestate_rewards import (
    breakdown_reward,
    checkpoint_coverage,
    euro_accuracy_reward,
    unit_ok,
)

ROW = dict(
    unit=["eur"], checkpoints=[[195000.0, 13650.0]], tolerance_abs=[0.01], tolerance_rel=[0.0005]
)
FULL = "<think>Base 195.000 €, ITP 13.650 €, total...</think><answer>208.850,00 €</answer>"
BARE = "<think>Sumo todo.</think><answer>208.850,00 €</answer>"
WRONG = "<think>Base 195.000 €, ITP 13.650 €...</think><answer>207.800,00 €</answer>"


def test_accuracy_reads_spanish_format():
    assert euro_accuracy_reward([None], [FULL], ["208850.00"], **ROW) == [1.0]
    assert euro_accuracy_reward([None], [WRONG], ["208850.00"], **ROW) == [0.0]


def test_control_rows_use_the_generic_check():
    gsm = "<think>...</think><answer>1,234</answer>"
    control = dict(unit=[None], checkpoints=[None], tolerance_abs=[None], tolerance_rel=[None])
    assert euro_accuracy_reward([None], [gsm], ["1234"], **control) == [1.0]
    assert breakdown_reward([None], [gsm], ["1234"], **control) == [0.0]


def test_breakdown_rewards_unit_and_intermediate_values():
    assert breakdown_reward([None], [FULL], ["208850.00"], **ROW) == [1.0]
    assert breakdown_reward([None], [BARE], ["208850.00"], **ROW) == [0.5]


def test_breakdown_is_gated_on_a_correct_answer():
    assert breakdown_reward([None], [WRONG], ["208850.00"], **ROW) == [0.5]
    ungated = breakdown_reward([None], [WRONG], ["208850.00"], gate_on_correct=False, **ROW)
    assert ungated == [1.0]


def test_unit_and_coverage_helpers():
    assert unit_ok("4,37 %", "pct") and not unit_ok("4,37 €", "pct")
    assert unit_ok("648 euros", "eur") and not unit_ok("648", "eur")
    assert checkpoint_coverage("3.420 y luego 2.160", [3420.0, 2160.0, 648.0]) == 2 / 3
