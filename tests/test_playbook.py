"""The lever playbook: valid, unique ids, risks where due, no figures, quotes in the corpus."""

from __future__ import annotations

from collections import Counter

import pytest
import yaml

from agent.playbook.schema import FIGURE, PLAYBOOK_PATH, load_levers, parse_levers
from rag.gold import locate
from rag.ingest import CORPUS_DIR, load_corpus

LEVERS = load_levers()


def test_playbook_validates_and_is_large_enough():
    assert len(LEVERS) >= 15
    levels = Counter(lever.level for lever in LEVERS)
    assert levels["grey"] >= 3 and levels["illegal_warning"] >= 3


def test_ids_are_unique():
    ids = [lever.id for lever in LEVERS]
    assert len(ids) == len(set(ids))
    # parse_levers is what rejects duplicates when the file is loaded
    raw = yaml.safe_load(PLAYBOOK_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="duplicated"):
        parse_levers(raw + raw[:1])


def test_grey_and_illegal_levers_say_their_risk():
    for lever in LEVERS:
        if lever.level != "legal":
            assert lever.risk and lever.risk.strip(), lever.id


def test_illegal_levers_are_never_simulated():
    assert all(lever.engine is None for lever in LEVERS if lever.level == "illegal_warning")


def test_explanations_carry_no_figures():
    for lever in LEVERS:
        assert not FIGURE.search(lever.explanation), lever.id


def test_the_issue_levers_are_there():
    quantified = {lever.id for lever in LEVERS if lever.quantified}
    assert {
        "contract_date_before_rdl_29_2026",
        "young_tenant_stressed_zone",
        "rent_cut_over_5pct",
        "rehabilitation_before_contract",
        "cheapest_itp_region",
        "reference_value_above_price",
        "new_build_instead_of_second_hand",
        "finance_with_deductible_interest",
        "ten_percent_rent_cap_exception",
        "stay_below_large_holder",
        "offer_at_max_price",
    } <= quantified


@pytest.fixture(scope="module")
def corpus():
    if not any(CORPUS_DIR.rglob("*.md")):
        pytest.skip("rag/corpus is empty: run `uv run python -m rag.download_corpus`")
    return {doc.source: doc for doc in load_corpus()}


@pytest.mark.parametrize("lever", LEVERS, ids=lambda lever: lever.id)
def test_every_quote_is_found_in_the_corpus(lever, corpus):
    locate(lever.evidence.model_dump(), corpus)
