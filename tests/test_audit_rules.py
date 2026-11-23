"""The audit flags engine rules whose legal text changed or disappeared."""

import pytest

from rag import audit_rules
from rag.temporal import FAR_FUTURE, ArticleVersion


def version(index, text, start, end, norm="BOE-X"):
    return ArticleVersion(
        law="lirpf", law_title="LIRPF", block_id="a23", heading="Artículo 23. Gastos",
        index=index, amended_by=norm, text=text, valid=[(start, end)],
    )  # fmt: skip


def test_audit_finds_broken_changed_and_future(monkeypatch):
    monkeypatch.setattr(
        audit_rules,
        "RULES",
        [
            audit_rules.Rule("tres por ciento", "lirpf", "a23", ("el 3 por ciento",)),
            audit_rules.Rule("noventa", "lirpf", "a23", ("En un 90 por ciento",)),
        ],
    )
    versions = [
        version(0, "el 3 por ciento. En un 90 por ciento.", "2024-01-01", "2026-10-08"),
        version(1, "el 3 por ciento. En un 95 por ciento.", "2026-10-08", "2027-01-01", "RDL"),
        version(2, "el 3 por ciento. Otra.", "2027-01-01", FAR_FUTURE, "LEY"),
    ]
    three, ninety = audit_rules.audit(versions, today="2026-11-22", engine_date="2026-09-15")
    assert three["status"] == "revisar" and three["changed_by"] == "RDL"
    assert ninety["status"] == "ROTA" and ninety["missing_now"] == ["En un 90 por ciento"]
    assert three["future_changes"] == [("2027-01-01", "LEY")]


def test_audit_refuses_quotes_that_were_never_in_the_law(monkeypatch):
    monkeypatch.setattr(
        audit_rules, "RULES", [audit_rules.Rule("x", "lirpf", "a23", ("no existe",))]
    )
    versions = [version(0, "el 3 por ciento", "2024-01-01", FAR_FUTURE)]
    with pytest.raises(ValueError, match="quote not in"):
        audit_rules.audit(versions, today="2026-11-22")
