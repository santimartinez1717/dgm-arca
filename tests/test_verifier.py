"""Tests for the verifiers. Add one class of tests per domain verifier you write."""

from rlm.verifier import ExactMatchVerifier, NumericVerifier


def test_numeric_verifier_exact():
    v = NumericVerifier()
    assert v.is_correct("42", "42")
    assert v.is_correct("$42.00", "42")
    assert not v.is_correct("41", "42")
    assert not v.is_correct(None, "42")
    assert not v.is_correct("forty-two", "42")


def test_numeric_verifier_with_tolerance():
    v = NumericVerifier(tolerance=0.05)
    assert v.is_correct("3.14", "3.1416")
    assert not v.is_correct("3.0", "3.1416")


def test_verify_extracts_from_full_completion():
    result = NumericVerifier().verify("<think>...</think><answer>18</answer>", "18")
    assert result.is_correct and result.predicted == "18"
    missing = NumericVerifier().verify("no tags at all", "18")
    assert not missing.is_correct and "no <answer>" in missing.detail


def test_exact_match_ignores_case_and_spacing():
    v = ExactMatchVerifier()
    assert v.is_correct("  Madrid ", "madrid")
    assert not v.is_correct("Barcelona", "Madrid")


# --------------------------------------------------------------------------- domain verifier

from rlm.verifier import EuroVerifier, parse_amount  # noqa: E402


def test_parse_amount_spanish_and_english_conventions():
    assert parse_amount("208.850,00") == 208850.0
    assert parse_amount("208,850.00") == 208850.0
    assert parse_amount("1.050") == 1050.0  # Spanish thousands, not one point zero five
    assert parse_amount("4,37") == 4.37
    assert parse_amount("4.37") == 4.37
    assert parse_amount("0.375") == 0.375  # leading zero: a decimal, not 375
    assert parse_amount("1,050,000") == 1050000.0
    assert parse_amount("-1.234,56") == -1234.56
    assert parse_amount("12.") == 12.0  # full stop at the end of a sentence


def test_euro_verifier_accepts_units_and_words():
    v = EuroVerifier()
    assert v.is_correct("208.850,00 €", "208850.00")
    assert v.is_correct("Necesitas 208850 euros", "208850.00")
    assert v.is_correct("4,37 %", "4.37")
    assert not v.is_correct("207.800,00 €", "208850.00")


def test_euro_verifier_rejects_hedging_and_missing_numbers():
    v = EuroVerifier()
    assert not v.is_correct("entre 4,2 y 4,4 %", "4.3")
    assert not v.is_correct("no lo sé", "4.3")
    assert not v.is_correct(None, "4.3")
    # The same number written twice is not hedging.
    assert v.is_correct("648 € (648,00 €)", "648.00")


def test_euro_verifier_tolerance_is_absolute_plus_relative():
    v = EuroVerifier(tolerance_abs=0.01, tolerance_rel=0.0005)
    assert v.is_correct("208.900,00", "208850.00")  # 50 € off on 208.850: within 0.05 %
    assert not v.is_correct("209.000,00", "208850.00")
    percent = EuroVerifier(tolerance_abs=0.01, tolerance_rel=0.0)
    assert percent.is_correct("4,38 %", "4.37")  # one hundredth of a point: rounding drift
    assert not percent.is_correct("4,39 %", "4.37")
