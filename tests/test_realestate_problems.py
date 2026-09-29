"""The generator is the dataset and the ground truth: splits, determinism and rendering."""

import json

from rlm import realestate_problems as gen
from rlm.realestate_rewards import verify_row


def build(seed=0):
    seen: set[str] = set()
    train = gen.generate(gen.TRAIN_FAMILIES, 30, f"{seed}-train", seen)
    test = gen.generate(gen.TRAIN_FAMILIES, 10, f"{seed}-test", seen)
    ood = gen.generate(gen.OOD_FAMILIES, 10, f"{seed}-ood", seen)
    return train, test, ood


def test_splits_do_not_share_parameters():
    train, test, ood = build()
    keys = [{gen._fingerprint(p.params) for p in split} for split in (train, test, ood)]
    assert not keys[0] & keys[1] and not keys[0] & keys[2] and not keys[1] & keys[2]


def test_generation_is_deterministic():
    first, _, _ = build(seed=3)
    second, _, _ = build(seed=3)
    assert [p.question for p in first] == [p.question for p in second]


def test_ood_families_never_appear_in_train():
    train, _, ood = build()
    assert {p.family for p in train} == set(gen.TRAIN_FAMILIES)
    assert {p.family for p in ood} == set(gen.OOD_FAMILIES)


def test_answers_verify_against_themselves_in_spanish_format():
    train, _, _ = build()
    for problem in train:
        row = {
            "answer": problem.answer,
            "unit": problem.unit,
            "tolerance_abs": problem.tolerance_abs,
            "tolerance_rel": problem.tolerance_rel,
        }
        value = float(problem.answer)
        spanish = gen.eur(value, 2) if problem.unit == "eur" else gen.pct(value / 100)
        assert verify_row(f"<think>x</think><answer>{spanish}</answer>", row)[0], spanish


def test_statement_asks_for_the_right_unit_and_rows_serialise():
    train, _, _ = build()
    for problem in train:
        asks = gen.PCT_ASKS if problem.unit == "pct" else gen.EUR_ASKS
        assert problem.question.endswith(asks), problem.question
        json.dumps(problem.__dict__, ensure_ascii=False)


def test_spanish_formatting_helpers():
    assert gen.eur(208_850) == "208.850 €"
    assert gen.eur(1_234.5) == "1.234,50 €"
    assert gen.pct(0.075) == "7,5 %"
    assert gen.num(12.5) == "12,5"
