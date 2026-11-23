"""The trace viewer renders every field of /agent, and still works without the optional ones."""

from __future__ import annotations

import httpx

from agent import ui

FULL = {
    "final_answer": "Con la renta legal de 720 € el neto es 4,51 %. Consúltalo con un asesor.",
    "steps": [
        {
            "thought": "Analizo P07 con el motor.",
            "action": {"name": "analyze_property", "arguments": {"property_id": "P07"}},
            "observation": '{"net_yield_pct": 4.51, "effective_rent": 720}',
        },
        {
            "thought": "Consulto la zona.",
            "action": {"name": "get_rent_reference", "arguments": {"municipality": "Santiago"}},
            "observation": "ERROR: get_rent_reference is unavailable (simulated)",
        },
        {"thought": "Respondo.", "action": {"name": "final_answer", "arguments": {}}},
    ],
    "n_steps": 3,
    "succeeded": True,
    "tokens_used": 2140,
    "session_id": "s-42",
    "case_file": "EXPEDIENTE s-42\nP07 · Santiago de Compostela · 155.000 € · renta 950 → 720",
    "levers": [
        {
            "id": "rent_cut_over_5pct",
            "level": "legal",
            "title": "Bajar la renta más de un 5 %",
            "quantified": True,
            "source": "boe/rdl-29-2026.md · Artículo 6",
        },
        {
            "id": "short_term_rental",
            "level": "grey",
            "title": "Alquiler de temporada",
            "quantified": False,
            "risk": "fraude de ley si es vivienda habitual",
            "source": "boe/lau.md · Artículo 3",
        },
        {
            "id": "black_money",
            "level": "illegal_warning",
            "title": "Pagar parte en negro",
            "risk": "fraude fiscal",
            "source": "boe/ley-11-2021.md",
        },
    ],
    "scenarios": [
        {
            "lever": "rent_cut_over_5pct",
            "level": "legal",
            "effective_rent": 676.8,
            "effective_rent_change": -43.2,
            "net_yield_pct": 4.2,
            "net_yield_pct_change": -0.31,
            "irpf_reduction_pct": 90,
            "irpf_reduction_pct_change": 40,
            "irpf_rule": "RDL 29/2026: 90 %",
        },
        {"scenario": "if reference_value=180000", "net_yield_pct": 4.3},
        {"lever": "black_money", "refused": "illegal: only to warn the user"},
    ],
    "open_questions": ["¿Cuál es el valor de referencia de P07?"],
    "audit": {
        "ok": True,
        "rejections": 1,
        "disclaimer_added": True,
        "history": [{"unsupported_numbers": ["4,9 %"], "unknown_citations": ["[K9]"]}],
    },
}

OLD = {  # the contract of the course, without any optional field
    "final_answer": "No puedo saberlo.",
    "steps": [{"thought": "No hay datos.", "action": None, "observation": None}],
    "n_steps": 1,
    "succeeded": True,
    "model": "x",
    "tokens_used": 0,
}


def test_render_trace_with_every_optional_field():
    page = ui.render_trace(FULL)
    # the ReAct cards
    assert "PASO 1 · Pensamiento" in page and "Acción: analyze_property" in page
    assert "arca-observation" in page and "arca-error" in page  # the broken tool is red
    # levers coloured by level, with their source and risk
    assert page.count("arca-legal") == 1 and page.count("arca-grey") == 1
    assert page.count("arca-illegal_warning") == 1
    assert "boe/rdl-29-2026.md · Artículo 6" in page and "fraude de ley" in page
    # scenarios as an "if X" table with the change of each figure
    assert "si rent_cut_over_5pct" in page and "si if reference_value=180000" in page
    assert "676,80" in page and "(-43.2)" in page and "(+40)" in page
    assert "illegal: only to warn the user" in page and "RDL 29/2026: 90 %" in page
    # the auditor, with the figure that did not add up
    assert "AUDITOR · aprobada tras 1 rechazo(s)" in page
    assert "4,9 %" in page and "[K9]" in page and "asesor" in page
    # open questions and the summary line
    assert "¿Cuál es el valor de referencia de P07?" in page
    assert "3 pasos · 2140 tokens" in page


# The shapes the loop of issue 20 returns (agent/react_agent.py::_response).
LOOP_REJECTED = {
    "enabled": True,
    "rejections": 2,
    "ok": False,
    "unsupported_numbers": ["6,9 %"],
    "unknown_citations": [],
    "disclaimer_added": True,
}
LOOP_DISABLED = {**LOOP_REJECTED, "enabled": False, "rejections": 0}


def test_audit_in_the_shape_of_the_loop():
    page = ui.render_trace({**OLD, "audit": LOOP_REJECTED})
    assert "arca-audit_rejected" in page and "6,9 %" in page and "se entrega sin aprobar" in page
    page = ui.render_trace({**OLD, "audit": LOOP_DISABLED})
    assert "desactivado (ablación)" in page and "habría rechazado" in page
    assert "arca-audit_rejected" not in page
    ok = {**LOOP_REJECTED, "ok": True, "unsupported_numbers": [], "rejections": 0}
    assert "habría aprobado" in ui.render_trace({**OLD, "audit": {**ok, "enabled": False}})
    assert "AUDITOR · aprobada" in ui.render_trace({**OLD, "audit": ok})


def test_rejected_audit_is_red():
    page = ui.render_trace(
        {**FULL, "audit": {"ok": False, "rejections": 2, "unsupported_numbers": ["5,1 %"]}}
    )
    assert "arca-audit_rejected" in page and "5,1 %" in page and "2 rechazo(s)" in page


def test_render_trace_without_optional_fields():
    page = ui.render_trace(OLD)
    assert "No puedo saberlo." in page and "PASO 1 · Pensamiento" in page
    for marker in ("PALANCA", "ESCENARIOS", "AUDITOR", "PREGUNTAS ABIERTAS"):
        assert marker not in page
    assert "expediente" in ui.render_case_file(OLD)


def test_text_is_escaped():
    page = ui.render_trace({**OLD, "final_answer": "<script>alert(1)</script>"})
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_case_file_panel():
    panel = ui.render_case_file(FULL)
    assert "sesión s-42" in panel and "renta 950 → 720" in panel


class _Reply:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self.body


def test_conversation_keeps_the_session(monkeypatch):
    sent = []

    def fake_post(url, json, timeout):
        sent.append(json)
        return _Reply({**FULL, "session_id": "s-42"})

    monkeypatch.setattr(httpx, "post", fake_post)
    answer, trace, case_file, session = ui.run("Mira P07", "base", 6, False, None)
    assert session == "s-42" and "4,51 %" in answer and "EXPEDIENTE" in case_file
    ui.run("El valor de referencia es 180.000 €", "base", 6, True, session)
    assert "session_id" not in sent[0] and "confirm" not in sent[0]  # old API compatible
    assert sent[1]["session_id"] == "s-42" and sent[1]["confirm"] is True


def test_api_error_is_shown_and_keeps_the_session(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Reply({"detail": "x"}, status=501))
    answer, trace, case_file, session = ui.run("x", "rlm", 3, False, "s-1")
    assert "501" in answer and "arca-error" in trace and session == "s-1"


def test_old_api_without_session_keeps_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Reply(OLD))
    assert ui.run("x", "rlm", 3, False, None)[3] is None
