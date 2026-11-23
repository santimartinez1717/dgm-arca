"""Tables for the phase 4 report (docs/fase4/informe_fase4.md, sections 6.3-6.5) and a failure
diagnosis, from the JSON that agent/evaluate.py writes.

    uv run python scripts/fase4/tablas_informe.py \
        --json reports/fase4/phase4_eval.json --code reports/fase4/phase4_eval_code.json

Prints Markdown. Every figure comes from the files, so it can be pasted into the report and
EXPERIMENTS.md as is. The diagnosis says, for each failed task, which of four reasons applies:

* ``datos``: the model did not pass to record_property a fact the task gives (needs
  agent.ingest.extract_prose to know what the task gives);
* ``copia``: a tool returned the figure the check needs, but the answer does not have it;
* ``auditor``: the answer was delivered unapproved (rejected and out of retries);
* ``pasos``: the loop ended without final_answer (steps, tokens or a repeated call).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from agent.bench.schema import load_bench
from agent.evaluate import parse_numbers


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f} %"


def num(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def brains_table(runs: dict, config: str = "full") -> list[str]:
    lines = [
        "| Cerebro | Éxito | IC 95 % | Pasos | Tokens | Tools requeridas | Abstención | Caídas |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for run in runs.values():
        if run["config"] != config:
            continue
        low, high = run["wilson_95"]
        lines.append(
            f"| {run['brain']} | {run['correct']}/{run['n']} ({pct(run['success_rate'])}) "
            f"| {100 * low:.0f}–{100 * high:.0f} % | {num(run['mean_steps'])} "
            f"| {num(run['mean_tokens'], 0)} | {pct(run['required_tools_rate'])} "
            f"| {pct(run['abstention_rate'])} | {run['crashes']} |"
        )
    return lines


def ablation_table(runs: dict) -> list[str]:
    brains = sorted({r["brain"] for r in runs.values()})
    lines = ["| Configuración | " + " | ".join(brains) + " |", "|---|" + "---|" * len(brains)]
    for config in ("full", "no_auditor", "no_playbook", "flat_memory"):
        cells = []
        for brain in brains:
            run = runs.get(f"{config}/{brain}")
            cells.append(f"{run['correct']}/{run['n']}" if run else "—")
        lines.append(f"| `{config}` | " + " | ".join(cells) + " |")
    return lines


def category_table(runs: dict) -> list[str]:
    categories = sorted({c for run in runs.values() for c in run["by_category"]})
    lines = [
        "| Config./cerebro | " + " | ".join(categories) + " |",
        "|---|" + "---|" * len(categories),
    ]
    for key, run in runs.items():
        cells = [
            f"{run['by_category'][c]['correct']}/{run['by_category'][c]['n']}"
            if c in run["by_category"]
            else "—"
            for c in categories
        ]
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    return lines


def code_table(json_runs: dict, code_runs: dict) -> list[str]:
    lines = [
        "| Agente | Cerebro | Éxito | Pasos | Tokens | Errores de código | screening |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, runs in (("JSON", json_runs), ("Código", code_runs)):
        for run in runs.values():
            if run["config"] != "full":
                continue
            scr = run["by_category"].get("screening")
            lines.append(
                f"| {label} | {run['brain']} | {run['correct']}/{run['n']} "
                f"| {num(run['mean_steps'])} | {num(run['mean_tokens'], 0)} "
                f"| {num(run.get('mean_code_errors'))} "
                f"| {scr['correct']}/{scr['n'] if scr else '—'} |"
            )
    return lines


def _needed_numbers(check: dict) -> list[float]:
    if check.get("type") == "number":
        return [float(check["value"])]
    return [n for c in check.get("checks", []) for n in _needed_numbers(c)]


def diagnose(row: dict, task) -> list[str]:
    reasons = []
    try:
        from agent.ingest import extract_prose

        stated = extract_prose(task.task)
        if stated.property is not None:
            recs = [
                s["action"]["arguments"]
                for s in row["steps"]
                if s.get("action") and s["action"]["name"] == "record_property"
            ]
            passed = set().union(*map(set, recs)) if recs else set()
            missing = set(stated.fields) - {"municipality"} - passed
            # Since PR #35 the flat is ingested before the loop: only a missing case counts.
            if recs and missing:
                reasons.append("datos")
    except ImportError:
        pass
    observed = " ".join(str(s.get("observation") or "") for s in row["steps"])
    seen = set(parse_numbers(observed))
    answer = set(parse_numbers(row["final_answer"]))
    needed = _needed_numbers(task.check.model_dump())
    if any(
        any(abs(n - v) < 0.06 for v in seen) and not any(abs(n - v) < 0.06 for v in answer)
        for n in needed
    ):
        reasons.append("copia")
    audit = row.get("audit") or {}
    if audit.get("enabled") and audit.get("ok") is False:
        reasons.append("auditor")
    if "No he podido terminar el análisis" in row["final_answer"]:
        reasons.append("pasos")
    return reasons or ["otro"]


def failures(runs: dict) -> list[str]:
    bench = {t.id: t for t in load_bench()}
    lines = [
        "| Config./cerebro | Fallos | datos | copia | auditor | pasos | otro |",
        "|---|---|---|---|---|---|---|",
    ]
    detail = []
    for key, run in runs.items():
        counts: Counter = Counter()
        failed = [r for r in run["rows"] if not r["correct"]]
        for row in failed:
            why = diagnose(row, bench[row["id"]])
            counts.update(why)
            detail.append(f"- {key} · `{row['id']}`: {', '.join(why)}")
        lines.append(
            f"| {key} | {len(failed)} | "
            + " | ".join(str(counts[k]) for k in ("datos", "copia", "auditor", "pasos", "otro"))
            + " |"
        )
    return lines + ["", *detail]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", default="reports/fase4/phase4_eval.json")
    parser.add_argument("--code", default="reports/fase4/phase4_eval_code.json")
    args = parser.parse_args()
    runs = json.loads(Path(args.json).read_text())["runs"]
    out = ["## 6.3 Cerebros (configuración full)", "", *brains_table(runs)]
    out += ["", "## 6.4 Ablaciones (éxito)", "", *ablation_table(runs)]
    out += ["", "## Éxito por categoría", "", *category_table(runs)]
    code = Path(args.code)
    if code.exists():
        code_runs = json.loads(code.read_text())["runs"]
        out += ["", "## 6.5 JSON frente a código (full)", "", *code_table(runs, code_runs)]
        out += ["", "## Diagnóstico de fallos (código)", "", *failures(code_runs)]
    out += ["", "## Diagnóstico de fallos (JSON)", "", *failures(runs)]
    print("\n".join(out))


if __name__ == "__main__":
    main()
