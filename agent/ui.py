"""Trace viewer: send a task to the running API and see every step, lever and audit as a card.

    uv run arca-api &
    uv run python -m agent.ui            # expects the API at ARCA_API_URL (localhost:8000)

Same idea as the coloured trace of the class notebook (purple thoughts, orange actions, green
observations), plus what makes Umbral different from a plain ReAct trace:

* **levers** from ``find_levers``: green if legal, amber if grey, red if ``illegal_warning``,
  each with its source;
* **scenarios** of ``what_if``: an "if X / if Y" table with the change of each figure;
* the **auditor**: approved, or the rejected figures and citations in red;
* the **case file** in a side panel, and the **open questions** to answer in the next turn.

The conversation keeps its ``session_id`` between sends, so an open question can be answered
and the case file grows. Every optional field may be missing (another version of the API):
the viewer then shows the plain trace.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any

import httpx

API_URL = os.environ.get("ARCA_API_URL", "http://localhost:8000")

COLORS = {
    "thought": ("#ede9fe", "#4c1d95"),
    "action": ("#ffedd5", "#9a3412"),
    "observation": ("#dcfce7", "#166534"),
    "error": ("#fee2e2", "#991b1b"),
    "final": ("#ccfbf1", "#115e59"),
    "legal": ("#dcfce7", "#166534"),
    "grey": ("#fef3c7", "#92400e"),
    "illegal_warning": ("#fee2e2", "#991b1b"),
    "audit_ok": ("#dcfce7", "#166534"),
    "audit_rejected": ("#fee2e2", "#991b1b"),
    "question": ("#e0f2fe", "#075985"),
    "case": ("#f1f5f9", "#0f172a"),
}
LEVEL_LABEL = {"legal": "legal", "grey": "zona gris", "illegal_warning": "ilegal: solo aviso"}

# Figures of a what_if scenario, in the order and with the names the user reads.
SCENARIO_COLUMNS = {
    "effective_rent": "Renta (€/mes)",
    "total_investment": "Inversión (€)",
    "net_yield_pct": "Neto (%)",
    "cash_on_cash_pct": "Cash-on-cash (%)",
    "irpf_reduction_pct": "Reducción IRPF (%)",
    "income_tax": "IRPF (€)",
    "after_tax_yield_pct": "Neto tras IRPF (%)",
}


def _e(text: Any) -> str:
    return html.escape(str(text))


def card(title: str, body: str, kind: str, raw_html: bool = False) -> str:
    """A coloured card. ``body`` is escaped unless ``raw_html`` (for tables we build)."""
    bg, fg = COLORS[kind]
    content = (
        body
        if raw_html
        else f'<pre style="white-space:pre-wrap;margin:8px 0 0;color:{fg}">{_e(body)}</pre>'
    )
    return (
        f'<div class="arca-card arca-{kind}" style="background:{bg};color:{fg};'
        f'border-left:6px solid {fg};padding:10px 14px;margin:8px 0;border-radius:8px">'
        f"<b>{_e(title)}</b>{content}</div>"
    )


def _is_error(observation: str) -> bool:
    head = observation.lstrip()[:80].lower()
    return head.startswith(("error", "tool error")) or "timeout" in head or "timed out" in head


def render_steps(steps: list[dict]) -> list[str]:
    blocks = []
    for i, step in enumerate(steps, start=1):
        if step.get("thought"):
            blocks.append(card(f"PASO {i} · Pensamiento", step["thought"], "thought"))
        action = step.get("action")
        if action:
            args = json.dumps(action.get("arguments", {}), ensure_ascii=False, indent=2)
            blocks.append(card(f"PASO {i} · Acción: {action.get('name')}", args, "action"))
        observation = step.get("observation")
        if observation is not None:
            observation = str(observation)
            kind = "error" if _is_error(observation) else "observation"
            blocks.append(card(f"PASO {i} · Observación", observation, kind))
    return blocks


def render_levers(levers: list[dict]) -> list[str]:
    blocks = []
    for lever in levers:
        level = lever.get("level", "legal")
        kind = level if level in LEVEL_LABEL else "legal"
        title = (
            f"PALANCA · {lever.get('title') or lever.get('id')} ({LEVEL_LABEL.get(level, level)})"
        )
        lines = [f"id: {lever.get('id')}"]
        for key, label in (("net_yield_pct_change", "Δ neto (puntos)"), ("delta", "Δ")):
            if key in lever:
                lines.append(f"{label}: {lever[key]:+}")
        if lever.get("needs"):
            lines.append("falta saber: " + ", ".join(lever["needs"]))
        if lever.get("risk"):
            lines.append(f"riesgo: {lever['risk']}")
        if lever.get("source"):
            lines.append(f"cita: {lever['source']}")
        blocks.append(card(title, "\n".join(lines), kind))
    return blocks


def _cell(scenario: dict, key: str) -> str:
    if key not in scenario:
        return "—"
    value = scenario[key]
    change = scenario.get(f"{key}_change")
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if change is not None:
        sign = "+" if change > 0 else ""
        text += f" <small>({sign}{change:g})</small>"
    return text


def render_scenarios(scenarios: list[dict]) -> list[str]:
    """One table with a row per scenario: "si palanca X / si dato = Y"."""
    if not scenarios:
        return []
    rows, notes = [], []
    columns = [k for k in SCENARIO_COLUMNS if any(k in s for s in scenarios)]
    for s in scenarios:
        name = s.get("scenario") or s.get("lever") or json.dumps(s.get("override", {}))
        if any(k in s for k in ("error", "refused", "qualitative")):
            notes.append(f"{name}: {s.get('error') or s.get('refused') or s.get('qualitative')}")
            continue
        cells = "".join(f"<td>{_cell(s, k)}</td>" for k in columns)
        rows.append(f"<tr><td><b>si {_e(name)}</b></td>{cells}</tr>")
        if s.get("irpf_rule"):
            notes.append(f"{name}: {s['irpf_rule']}")
    head = "".join(f"<th>{_e(SCENARIO_COLUMNS[k])}</th>" for k in columns)
    table = (
        '<table style="border-collapse:collapse;margin-top:8px" cellpadding="4">'
        f"<tr><th>Escenario</th>{head}</tr>{''.join(rows)}</table>"
    )
    if notes:
        table += "<ul>" + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul>"
    return [card("ESCENARIOS (what_if)", table, "case", raw_html=True)]


def render_audit(audit: dict | None) -> list[str]:
    """The auditor's verdict, in the shape the loop returns (``agent/react_agent.py``):
    ``{enabled, rejections, ok, unsupported_numbers, unknown_citations, disclaimer_added}``,
    plus an optional ``history`` of the rejected answers."""
    if not audit:
        return []
    rejections = int(audit.get("rejections", 0))
    history = audit.get("history") or []
    lines = [f"rechazo {i}: " + _audit_reasons(r) for i, r in enumerate(history, 1)]
    passed = audit.get("ok", True) and not audit.get("unsupported_numbers")
    if audit.get("enabled") is False:  # the no_auditor ablation: what it would have said
        verdict = (
            "la habría aprobado" if passed else "la habría rechazado: " + _audit_reasons(audit)
        )
        return [card("AUDITOR · desactivado (ablación)", verdict, "case")]
    if passed:
        title = "AUDITOR · aprobada" + (f" tras {rejections} rechazo(s)" if rejections else "")
        if audit.get("disclaimer_added"):
            lines.append("se añadió el aviso y la remisión a un asesor")
        return [
            card(title, "\n".join(lines) or "cada cifra y cada cita salen de una tool", "audit_ok")
        ]
    lines.append(_audit_reasons(audit))
    title = f"AUDITOR · rechazada ({rejections} rechazo(s)); se entrega sin aprobar"
    return [card(title, "\n".join(lines), "audit_rejected")]


def _audit_reasons(result: dict) -> str:
    parts = []
    if result.get("unsupported_numbers"):
        parts.append(
            "cifras sin origen en una tool: " + ", ".join(map(str, result["unsupported_numbers"]))
        )
    if result.get("unknown_citations"):
        parts.append("citas no recuperadas: " + ", ".join(map(str, result["unknown_citations"])))
    return "; ".join(parts) or "sin detalle"


def render_open_questions(questions: list[str]) -> list[str]:
    if not questions:
        return []
    body = "\n".join(f"• {q}" for q in questions)
    return [card("PREGUNTAS ABIERTAS (contéstalas en el siguiente mensaje)", body, "question")]


def render_trace(response: dict) -> str:
    """The whole response as cards; every optional field may be missing."""
    blocks = render_steps(response.get("steps") or [])
    blocks += render_levers(response.get("levers") or [])
    blocks += render_scenarios(response.get("scenarios") or [])
    blocks += render_audit(response.get("audit"))
    blocks.append(card("RESPUESTA FINAL", response.get("final_answer", ""), "final"))
    blocks += render_open_questions(response.get("open_questions") or [])
    summary = f"{response.get('n_steps', len(response.get('steps') or []))} pasos"
    if response.get("tokens_used"):
        summary += f" · {response['tokens_used']} tokens"
    if response.get("succeeded") is False:
        summary += " · sin terminar (max_steps agotado o error)"
    blocks.insert(0, f'<p style="color:#475569">{_e(summary)}</p>')
    return "\n".join(blocks)


def render_case_file(response: dict) -> str:
    case_file = response.get("case_file")
    if not case_file:
        return '<p style="color:#64748b">La API no devuelve el expediente.</p>'
    session = response.get("session_id")
    title = f"EXPEDIENTE · sesión {session}" if session else "EXPEDIENTE"
    return card(title, case_file, "case")


def call_api(
    task: str,
    brain: str,
    max_steps: int,
    confirm: bool = False,
    session_id: str | None = None,
) -> dict:
    """POST /agent. The optional fields go only when set, so an older API keeps working."""
    payload: dict[str, Any] = {"task": task, "brain": brain, "max_steps": int(max_steps)}
    if session_id:
        payload["session_id"] = session_id
    if confirm:
        payload["confirm"] = True
    reply = httpx.post(f"{API_URL}/agent", json=payload, timeout=900)
    if reply.status_code != 200:
        raise RuntimeError(f"API error {reply.status_code}: {reply.text}")
    return reply.json()


def run(
    task: str,
    brain: str,
    max_steps: int,
    confirm: bool,
    session_id: str | None,
) -> tuple[str, str, str, str | None]:
    """One send of the conversation: (answer, trace, case file, session id to keep)."""
    try:
        body = call_api(task, brain, max_steps, confirm, session_id)
    except (RuntimeError, httpx.HTTPError) as exc:
        message = str(exc)
        return message, card("ERROR", message, "error"), "", session_id
    return (
        body.get("final_answer", ""),
        render_trace(body),
        render_case_file(body),
        body.get("session_id") or session_id,
    )


def main() -> None:
    import gradio as gr

    with gr.Blocks(title="Umbral · traza del agente") as demo:
        gr.Markdown(
            "# Umbral · traza del agente\n"
            "Pensamiento, acción y observación, con palancas, escenarios y auditor."
        )
        session = gr.State(None)
        with gr.Row():
            with gr.Column(scale=3):
                task = gr.Textbox(label="Tarea (o la respuesta a una pregunta abierta)", lines=6)
                with gr.Row():
                    brain = gr.Dropdown(["base", "rlm", "thinking"], value="rlm", label="Cerebro")
                    max_steps = gr.Slider(1, 30, value=10, step=1, label="Máx. pasos")
                    confirm = gr.Checkbox(label="Confirmar tools con efecto (guardar, informe)")
                with gr.Row():
                    send = gr.Button("Enviar", variant="primary")
                    reset = gr.Button("Nueva sesión")
                session_label = gr.Markdown("Sesión nueva")
                answer = gr.Textbox(label="Respuesta final", lines=5, interactive=False)
                trace = gr.HTML(label="Traza")
            with gr.Column(scale=2):
                case_file = gr.HTML(label="Expediente")

        def send_fn(text, brain_value, steps, confirm_value, session_id):
            out = run(text, brain_value, steps, confirm_value, session_id)
            label = f"Sesión `{out[3]}`" if out[3] else "Sesión nueva"
            return (*out, label)

        send.click(
            send_fn,
            inputs=[task, brain, max_steps, confirm, session],
            outputs=[answer, trace, case_file, session, session_label],
        )
        reset.click(
            lambda: (None, "Sesión nueva", "", "", ""),
            outputs=[session, session_label, answer, trace, case_file],
        )
    demo.launch()


if __name__ == "__main__":
    main()
