"""Phase 4 evaluation: success, steps and tokens per brain and configuration, on the bench.

Each line of the benchmark (``agent/bench/tasks.jsonl``, built by ``agent/bench/build_bench.py``)
has a task, the tools that must be involved and a ``check`` of the final answer. Every task
runs in isolation: a fresh case file and portfolio (seeded from ``setup.portfolio``) and, for
``broken_tool`` tasks, one tool replaced by a version that fails or hangs. Run on the GPU::

    uv run python -m agent.evaluate --bench agent/bench/tasks.jsonl --brains base rlm thinking \
        --configs full no_auditor no_playbook flat_memory

Configurations (the ablations of docs/fase4/diseno.md, "Evaluación"):

* ``full``: everything on;
* ``no_auditor``: ``audit=False``, the answer is delivered without the deterministic audit;
* ``no_playbook``: no ``find_levers`` nor ``what_if`` in the registry;
* ``flat_memory``: ``anchor_case_file=False``, no case file pinned at the top of the context.

Outputs: ``reports/fase4/phase4_eval.json`` (every trace), ``phase4_eval.md`` (the tables for
the report, with Wilson intervals and McNemar between brains) and five selected traces in
``reports/fase4/trazas/``. One log line per task, so a run on the DGX can be followed.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import math
import os
import re
import tempfile
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from rag.eval_generation import ABSTAIN as RAG_ABSTAIN

# A number as people write it: "4,62", "180.000", "1.234,5", "1,234.5", "-3". A digit glued to
# a letter is part of an id ("P07", "BOE-A-2026") and not a figure.
NUMBER_TOKEN = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+)*")

# What an agent says when it cannot answer, on top of phase 3's wording for passages. English
# too: abstaining is what the check measures, the language of the answer is measured apart
# (the thinking brain abstained in English on impossible-01, EXPERIMENTS.md, issue 20).
AGENT_ABSTAIN = re.compile(
    r"no (?:es posible|se puede|puedo|podemos|sabría) (?:\w+ ){0,2}"
    r"(?:saber|predecir|prever|anticipar|garantizar|determinar|asegurar|calcular|responder)"
    r"|no (?:tengo|dispongo de|hay) (?:\w+ ){0,2}(?:forma|manera|modo|datos|información)"
    r"|nadie (?:puede|sabe)"
    r"|no existe (?:\w+ ){0,3}(?:dato|información|registro|forma)"
    r"|(?:imposible|no se puede) (?:de )?(?:saber|predecir|prever)"
    r"|(?:can ?not|can't|cannot|unable to|no (?:\w+ )?(?:one|tool|tools|model) can|nobody can)"
    r" (?:\w+ ){0,2}(?:predict|forecast|know|tell|determine|guarantee)"
    r"|(?:impossible|not possible) to (?:predict|forecast|know|tell|determine)",
    re.IGNORECASE,
)
# A figure with a unit: what an abstention must not invent.
FIGURE = re.compile(r"\d[\d.,]*\s*(?:%|€|euros?\b|EUR\b)", re.IGNORECASE)


def _fold(text: str) -> str:
    """Lower case without accents, so 'Asesor' matches 'asesor' and 'tributación' 'tributacion'."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_numbers(text: str) -> list[float]:
    """Every value the numbers of ``text`` can mean, in Spanish or English notation.

    "4,62 %" is 4.62 and "180.000 €" is 180000. A lone separator followed by exactly three
    digits ("1.234", "1,234") is ambiguous, so both readings are returned; with both
    separators, the last one is the decimal mark.
    """
    values: list[float] = []
    for raw in NUMBER_TOKEN.findall(text):
        sign = -1.0 if raw[0] in "-−" else 1.0
        raw = raw.lstrip("-−")
        if "," in raw and "." in raw:
            decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
            thousands = "." if decimal == "," else ","
            readings = [raw.replace(thousands, "").replace(decimal, ".")]
        elif "," in raw or "." in raw:
            sep = "," if "," in raw else "."
            groups = raw.split(sep)
            if len(groups) > 2:  # 12.000.000 or 1,234,567
                readings = [raw.replace(sep, "")]
            elif len(groups[1]) == 3:  # 1.234 / 1,234: thousands or decimals
                readings = [raw.replace(sep, ""), raw.replace(sep, ".")]
            else:
                readings = [raw.replace(sep, ".")]
        else:
            readings = [raw]
        values.extend(sign * float(r) for r in readings)
    return values


def abstains(answer: str, no_figures: bool = False) -> bool:
    """The answer says it cannot know; with ``no_figures``, it also gives no € or % figure."""
    said = bool(AGENT_ABSTAIN.search(answer) or RAG_ABSTAIN.search(answer))
    return said and not (no_figures and FIGURE.search(answer))


def run_check(check: dict, answer: str) -> bool:
    """Evaluate one ``check`` (see ``agent/bench/schema.py``) against an answer."""
    kind, value = check.get("type"), check.get("value")
    if kind == "all":
        return all(run_check(c, answer) for c in check["checks"])
    if kind == "any":
        return any(run_check(c, answer) for c in check["checks"])
    if kind == "contains":
        return _fold(str(value)) in _fold(answer)
    if kind == "not_contains":
        values = value if isinstance(value, list) else [value]
        return not any(_fold(str(v)) in _fold(answer) for v in values)
    if kind == "regex":
        return re.search(value, answer, re.IGNORECASE) is not None
    if kind == "number":
        tolerance = check.get("tolerance", 0)
        return any(abs(n - float(value)) <= tolerance + 1e-9 for n in parse_numbers(answer))
    if kind == "abstains":
        return abstains(answer, no_figures=check.get("no_figures", False))
    return False


def check_answer(task: dict, final_answer: str) -> bool:
    """Automatic check of the final answer, according to the task's ``check`` field."""
    return run_check(task.get("check", {}), final_answer or "")


def tools_used(steps: list[dict]) -> set[str]:
    return {s["action"]["name"] for s in steps if s.get("action")}


# --------------------------------------------------------------------------- configurations

# Attributes set on the agent and tools removed from its registry, per configuration. The
# names are the ones the loop exposes (docs/fase4/issues/11-bucle-react.md).
CONFIGS: dict[str, dict[str, Any]] = {
    "full": {"attrs": {}, "drop_tools": []},
    "no_auditor": {"attrs": {"audit": False}, "drop_tools": []},
    "no_playbook": {"attrs": {}, "drop_tools": ["find_levers", "what_if"]},
    "flat_memory": {"attrs": {"anchor_case_file": False}, "drop_tools": []},
}


def configure(agent: Any, config: str) -> Any:
    """Apply a configuration to a freshly built agent; refuse a switch the agent lacks."""
    spec = CONFIGS[config]
    for name, value in spec["attrs"].items():
        if not hasattr(agent, name):
            raise AttributeError(f"config {config!r} needs ReActAgent.{name} (issue 11)")
        setattr(agent, name, value)
    if spec["drop_tools"] and hasattr(agent, "use_playbook"):
        agent.use_playbook = False  # the loop's own switch: it hides the tools from the model
    else:
        for name in spec["drop_tools"]:
            agent.registry.tools.pop(name, None)
    return agent


# --------------------------------------------------------------------------- isolation


@contextlib.contextmanager
def isolated(task: dict) -> Iterator[Path]:
    """A fresh case file and portfolio for one task, seeded from ``task["setup"]``."""
    keys = ("ARCA_CASE_DB", "ARCA_PORTFOLIO_DB")
    saved = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory(prefix="arca-eval-") as tmp:
        os.environ["ARCA_CASE_DB"] = str(Path(tmp) / "cases.sqlite")
        os.environ["ARCA_PORTFOLIO_DB"] = str(Path(tmp) / "portfolio.sqlite")
        try:
            rows = ((task.get("setup") or {}).get("portfolio")) or []
            if rows:
                from tool_use.portfolio import save_to_portfolio

                for row in rows:
                    save_to_portfolio.fn(**row)
            yield Path(tmp)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class SimulatedOutage(RuntimeError):
    """What a broken tool raises: the agent sees it as the observation."""


def hang_seconds() -> float:
    """Longer than the agent's tool timeout, so a hanging tool always trips it."""
    return float(os.environ.get("ARCA_AGENT_TOOL_TIMEOUT", "30")) + 5


@contextlib.contextmanager
def broken(agent: Any, task: dict, hang_s: float | None = None) -> Iterator[None]:
    """Replace ``task["break_tool"]`` by a version that fails (``error``) or hangs (``timeout``)."""
    name, mode = task.get("break_tool"), task.get("break_mode")
    tools = agent.registry.tools
    if not name or name not in tools:
        yield
        return
    original = tools[name]
    delay = hang_seconds() if hang_s is None else hang_s

    def failing(**_: Any) -> Any:
        if mode == "timeout":
            time.sleep(delay)
            raise SimulatedOutage(f"{name} did not answer in {delay:g} s (simulated)")
        raise SimulatedOutage(f"{name} is unavailable: 503 Service Unavailable (simulated)")

    tools[name] = dataclasses.replace(original, fn=failing)
    try:
        yield
    finally:
        tools[name] = original


# --------------------------------------------------------------------------- statistics


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval of a proportion; (0, 0) for no data."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar(only_a: int, only_b: int) -> float:
    """Exact two-sided McNemar p-value on the discordant pairs (as in rlm/eval_mlx.py)."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1))
    return min(1.0, 2 * tail / 2**n)


# --------------------------------------------------------------------------- running


def run_task(agent: Any, task: dict, brain: str, max_steps: int, hang_s: float | None) -> dict:
    """One task, isolated, with its broken tool if any. Never raises: a crash is a row."""
    started = time.perf_counter()
    with isolated(task), broken(agent, task, hang_s):
        try:
            response = agent.run(task["task"], max_steps=max_steps, brain=brain)
            response = response.model_dump() if hasattr(response, "model_dump") else response
            crash = None
        except Exception as exc:  # noqa: BLE001 - one crashing task must not stop the run
            response = {
                "final_answer": "",
                "steps": [],
                "n_steps": 0,
                "succeeded": False,
                "tokens_used": 0,
            }
            crash = f"{type(exc).__name__}: {exc}"
    used = tools_used(response.get("steps", []))
    # A code agent calls tools from inside its Python: those calls count as used too.
    used |= {c["name"] for c in response.get("tool_calls", [])}
    passes = check_answer(task, response.get("final_answer", ""))
    audit = response.get("audit") or None
    return {
        "id": task.get("id"),
        "category": task.get("category"),
        "brain": brain,
        "task": task["task"],
        "final_answer": response.get("final_answer", ""),
        "steps": response.get("steps", []),
        "n_steps": response.get("n_steps", 0),
        "tokens_used": response.get("tokens_used", 0),
        "succeeded": bool(response.get("succeeded", False)),
        "check": passes,
        "correct": bool(response.get("succeeded", False)) and passes,
        "tools_used": sorted(used),
        "required_tools_used": set(task.get("required_tools", [])) <= used,
        "audit": audit,
        "audit_rejections": int((audit or {}).get("rejections", 0)),
        "open_questions": response.get("open_questions", []),
        # optional fields of /agent (issue 21): what the traces and the viewer show
        "levers": response.get("levers", []),
        "scenarios": response.get("scenarios", []),
        "case_file": response.get("case_file"),
        "crash": crash,
        "code_errors": response.get("code_errors"),
        "seconds": round(time.perf_counter() - started, 2),
    }


def summarise(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    k = sum(r["correct"] for r in rows)
    audited = [r for r in rows if r["audit"] is not None]
    impossible = [r for r in rows if r["category"] == "impossible"]

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    low, high = wilson(k, n)
    return {
        "n": n,
        "correct": k,
        "success_rate": mean([r["correct"] for r in rows]),
        "wilson_95": [round(low, 3), round(high, 3)],
        "mean_steps": mean([r["n_steps"] for r in rows]),
        "mean_tokens": mean([r["tokens_used"] for r in rows]),
        "required_tools_rate": mean([r["required_tools_used"] for r in rows]),
        "audit_rejection_rate": mean([r["audit_rejections"] > 0 for r in audited]),
        "abstention_rate": mean([r["check"] for r in impossible]),
        "crashes": sum(r["crash"] is not None for r in rows),
        "mean_code_errors": mean(
            [r["code_errors"] for r in rows if r.get("code_errors") is not None]
        ),
    }


def evaluate(
    tasks: list[dict],
    make_agent: Callable[[], Any],
    brains: list[str],
    configs: list[str],
    max_steps: int = 10,
    hang_s: float | None = None,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    """Every task under every (configuration, brain). ``make_agent`` builds a fresh agent.

    With ``checkpoint``, every row is appended to that JSONL as soon as it finishes, and the
    rows already in it are reused: a run cut by the end of a DGX session resumes where it was.
    """
    results: dict[str, Any] = {"runs": {}}
    total = len(configs) * len(brains) * len(tasks)
    done_rows = load_checkpoint(checkpoint) if checkpoint else {}
    done = 0
    for config in configs:
        agent = None  # built lazily: a fully resumed configuration loads nothing
        for brain in brains:
            rows = []
            for task in tasks:
                key = (config, brain, task.get("id"))
                if key in done_rows:
                    row = done_rows[key]
                    tag = "(reanudada) "
                else:
                    if agent is None:
                        agent = configure(make_agent(), config)
                    row = run_task(agent, task, brain, max_steps, hang_s)
                    row["config"] = config
                    tag = ""
                    if checkpoint:
                        with checkpoint.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(row, ensure_ascii=False, default=list) + "\n")
                rows.append(row)
                done += 1
                mark = "ok " if row["correct"] else ("ERR" if row["crash"] else "no ")
                log(
                    f"[{done}/{total}] {tag}{config}/{brain} {row['id']}: {mark} "
                    f"steps={row['n_steps']} tokens={row['tokens_used']} {row['seconds']}s"
                )
            by_category = defaultdict(list)
            for r in rows:
                by_category[r["category"]].append(r)
            results["runs"][f"{config}/{brain}"] = {
                "config": config,
                "brain": brain,
                **summarise(rows),
                "by_category": {c: summarise(rs) for c, rs in sorted(by_category.items())},
                "rows": rows,
            }
    results["mcnemar"] = compare_brains(results["runs"], configs, brains)
    return results


def load_checkpoint(path: Path) -> dict[tuple, dict]:
    """Rows already evaluated, by (config, brain, task id). A torn last line is ignored."""
    rows: dict[tuple, dict] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # the process died while writing it: that task runs again
        rows[(row["config"], row["brain"], row["id"])] = row
    return rows


def compare_brains(runs: dict, configs: list[str], brains: list[str]) -> list[dict]:
    """McNemar between every pair of brains, within each configuration, on the same tasks."""
    out = []
    for config in configs:
        for i, a in enumerate(brains):
            for b in brains[i + 1 :]:
                ra = {r["id"]: r["correct"] for r in runs[f"{config}/{a}"]["rows"]}
                rb = {r["id"]: r["correct"] for r in runs[f"{config}/{b}"]["rows"]}
                only_a = sum(ra[t] and not rb[t] for t in ra)
                only_b = sum(rb[t] and not ra[t] for t in ra)
                out.append(
                    {
                        "config": config,
                        "a": a,
                        "b": b,
                        "only_a": only_a,
                        "only_b": only_b,
                        "p": round(mcnemar(only_a, only_b), 4),
                    }
                )
    return out


# --------------------------------------------------------------------------- reports


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f} %"


def _num(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def markdown(results: dict[str, Any]) -> str:
    """Tables ready for the report: brains × configurations, categories, McNemar."""
    runs = results["runs"]
    lines = [
        f"# Fase 4 · Evaluación del agente ({results.get('agent', 'json')})",
        "",
        "## Cerebros × configuraciones",
        "",
        "| Config. | Cerebro | Éxito | IC 95 % (Wilson) | Pasos | Tokens | Tools requeridas "
        "| Rechazo auditor | Abstención (imposibles) | Caídas | Errores de código |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs.values():
        low, high = run["wilson_95"]
        lines.append(
            f"| {run['config']} | {run['brain']} | {run['correct']}/{run['n']} "
            f"({_pct(run['success_rate'])}) | {100 * low:.0f}–{100 * high:.0f} % "
            f"| {_num(run['mean_steps'])} | {_num(run['mean_tokens'], 0)} "
            f"| {_pct(run['required_tools_rate'])} | {_pct(run['audit_rejection_rate'])} "
            f"| {_pct(run['abstention_rate'])} | {run['crashes']} "
            f"| {_num(run.get('mean_code_errors'))} |"
        )
    categories = sorted({c for run in runs.values() for c in run["by_category"]})
    lines += [
        "",
        "## Éxito por categoría",
        "",
        "| Config. | Cerebro | " + " | ".join(categories) + " |",
        "|---|---|" + "---|" * len(categories),
    ]
    for run in runs.values():
        cells = []
        for c in categories:
            s = run["by_category"].get(c)
            cells.append(f"{s['correct']}/{s['n']}" if s else "—")
        lines.append(f"| {run['config']} | {run['brain']} | " + " | ".join(cells) + " |")
    if results.get("mcnemar"):
        lines += [
            "",
            "## McNemar entre cerebros (exacto, pares discordantes)",
            "",
            "| Config. | A | B | Solo A | Solo B | p |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {m['config']} | {m['a']} | {m['b']} | {m['only_a']} | {m['only_b']} "
            f"| {m['p']:.3f} |"
            for m in results["mcnemar"]
        ]
    return "\n".join(lines) + "\n"


def trace_markdown(row: dict, label: str) -> str:
    """One trace as the cards of the viewer: thought, action, observation."""
    lines = [
        f"# {label}: {row['id']} ({row['config']}/{row['brain']})",
        "",
        f"- Categoría: `{row['category']}` · correcta: **{row['correct']}** · pasos: "
        f"{row['n_steps']} · tokens: {row['tokens_used']}",
        f"- Tools usadas: {', '.join(row['tools_used']) or 'ninguna'}",
    ]
    if row.get("crash"):
        lines.append(f"- Caída: `{row['crash']}`")
    lines += ["", "## Tarea", "", row["task"], ""]
    for i, step in enumerate(row["steps"], 1):
        lines += [f"## Paso {i}", "", f"**Pensamiento:** {step.get('thought') or '—'}", ""]
        if step.get("action"):
            args = json.dumps(step["action"].get("arguments", {}), ensure_ascii=False)
            lines += [f"**Acción:** `{step['action']['name']}` `{args}`", ""]
        if step.get("observation") is not None:
            lines += ["**Observación:**", "", "```", str(step["observation"])[:2000], "```", ""]
    if row.get("levers"):
        lines += ["## Palancas (find_levers)", ""]
        lines += [
            f"- `{lv.get('id')}` ({lv.get('level')}): {lv.get('title', '')} · "
            f"{lv.get('source', '')}"
            for lv in row["levers"]
        ]
        lines.append("")
    if row.get("scenarios"):
        lines += ["## Escenarios (what_if)", "", "```json"]
        lines += [json.dumps(s, ensure_ascii=False) for s in row["scenarios"]]
        lines += ["```", ""]
    if row.get("audit"):
        lines += [
            "## Auditor",
            "",
            "```json",
            json.dumps(row["audit"], ensure_ascii=False),
            "```",
            "",
        ]
    lines += ["## Respuesta final", "", row["final_answer"] or "—", ""]
    if row.get("case_file"):
        lines += ["## Expediente al final", "", "```", row["case_file"], "```", ""]
    return "\n".join(lines)


def select_traces(rows: list[dict]) -> list[tuple[str, dict]]:
    """Two good, two bad and one broken-tool trace, preferring varied categories."""

    def pick(candidates: list[dict], k: int) -> list[dict]:
        chosen, seen = [], set()
        for r in sorted(candidates, key=lambda r: -r["n_steps"]):
            if r["category"] not in seen:
                chosen.append(r)
                seen.add(r["category"])
            if len(chosen) == k:
                break
        return chosen

    normal = [r for r in rows if r["category"] != "broken_tool"]
    out = [("buena", r) for r in pick([r for r in normal if r["correct"]], 2)]
    out += [("mala", r) for r in pick([r for r in normal if not r["correct"]], 2)]
    out += [("tool_rota", r) for r in [r for r in rows if r["category"] == "broken_tool"][:1]]
    return out


def write_reports(results: dict[str, Any], out: Path, traces_dir: Path) -> list[Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=list))
    md = out.with_suffix(".md")
    md.write_text(markdown(results), encoding="utf-8")
    first = next(iter(results["runs"].values()), None)
    written = [out, md]
    if first:
        traces_dir.mkdir(parents=True, exist_ok=True)
        for label, row in select_traces(first["rows"]):
            path = traces_dir / f"{label}-{row['id']}-{row['config']}-{row['brain']}.md"
            path.write_text(trace_markdown(row, label), encoding="utf-8")
            written.append(path)
    return written


def load_tasks(path: Path, ids: list[str] | None = None, limit: int | None = None) -> list[dict]:
    tasks = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if ids:
        tasks = [t for t in tasks if t.get("id") in ids]
    return tasks[:limit] if limit else tasks


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bench", default="agent/bench/tasks.jsonl")
    parser.add_argument(
        "--agent",
        choices=["json", "code"],
        default="json",
        help="json: our ReAct agent; code: smolagents' CodeAgent with the same tools (issue 16)",
    )
    parser.add_argument("--brains", nargs="+", default=["rlm"])
    parser.add_argument("--configs", nargs="+", default=["full"], choices=sorted(CONFIGS))
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--ids", nargs="+", help="only these task ids")
    parser.add_argument("--limit", type=int, help="only the first N tasks (smoke test)")
    parser.add_argument("--out", default="reports/fase4/phase4_eval.json")
    parser.add_argument("--traces-dir", default="reports/fase4/trazas")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse the rows of <out>.partial.jsonl from a run that was cut and go on",
    )
    args = parser.parse_args()

    if args.agent == "code":
        from agent.code_agent import CodeAgentRunner as Agent
    else:
        from agent.react_agent import ReActAgent as Agent

    tasks = load_tasks(Path(args.bench), args.ids, args.limit)
    out = Path(args.out)
    checkpoint = out.with_suffix(".partial.jsonl")
    if checkpoint.exists() and not args.resume:
        raise SystemExit(f"{checkpoint} exists from an earlier run: pass --resume or move it")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    results = evaluate(
        tasks, Agent.from_env, args.brains, args.configs, args.max_steps, checkpoint=checkpoint
    )
    results["agent"] = args.agent
    for path in write_reports(results, Path(args.out), Path(args.traces_dir)):
        print(f"wrote {path}", flush=True)
    for run in results["runs"].values():
        print(
            f"{run['config']:>12}/{run['brain']:<9} success {run['correct']}/{run['n']} "
            f"· steps {_num(run['mean_steps'])} · tokens {_num(run['mean_tokens'], 0)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
