"""Phase 4 evaluation: success rate, steps and tokens on multi-tool tasks, per brain.

Each line of the benchmark (``agent/bench/example_tasks.jsonl``) has a task, the tools that
must be involved, and a way to check the final answer automatically (a number, a substring,
a regex). Twenty tasks that need at least two tools is the minimum. Run every brain::

    uv run python -m agent.evaluate --bench agent/bench/tasks.jsonl --brains base rlm thinking

and put the resulting table in your report next to the JSON-vs-code-agent comparison.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from rag.eval_generation import ABSTAIN as RAG_ABSTAIN

# A number as people write it: "4,62", "180.000", "1.234,5", "1,234.5", "-3". A digit glued to
# a letter is part of an id ("P07", "BOE-A-2026") and not a figure.
NUMBER_TOKEN = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+)*")

# What an agent says when it cannot answer, on top of phase 3's wording for passages.
AGENT_ABSTAIN = re.compile(
    r"no (?:es posible|se puede|puedo|podemos|sabría) (?:\w+ ){0,2}"
    r"(?:saber|predecir|prever|anticipar|garantizar|determinar|asegurar|calcular|responder)"
    r"|no (?:tengo|dispongo de|hay) (?:\w+ ){0,2}(?:forma|manera|modo|datos|información)"
    r"|nadie (?:puede|sabe)"
    r"|no existe (?:\w+ ){0,3}(?:dato|información|registro|forma)"
    r"|(?:imposible|no se puede) (?:de )?(?:saber|predecir|prever)",
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bench", default="agent/bench/example_tasks.jsonl")
    parser.add_argument("--brains", nargs="+", default=["rlm"])
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--out", default="reports/fase4/phase4_eval.json")
    args = parser.parse_args()

    from agent.react_agent import ReActAgent

    tasks = [
        json.loads(line)
        for line in Path(args.bench).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    agent = ReActAgent.from_env()
    results = {}
    for brain in args.brains:
        rows = []
        for task in tasks:
            response = agent.run(task["task"], max_steps=args.max_steps, brain=brain).model_dump()
            ok = response["succeeded"] and check_answer(task, response["final_answer"])
            used = tools_used(response["steps"])
            rows.append(
                {
                    **task,
                    **response,
                    "correct": ok,
                    "tools_used": sorted(used),
                    "required_tools_used": set(task.get("required_tools", [])) <= used,
                }
            )
        n = max(len(rows), 1)
        results[brain] = {
            "success_rate": sum(r["correct"] for r in rows) / n,
            "mean_steps": sum(r["n_steps"] for r in rows) / n,
            "mean_tokens": sum(r["tokens_used"] for r in rows) / n,
            "rows": rows,
        }
        print(
            f"{brain:>9}: success {results[brain]['success_rate']:.2f} "
            f"· steps {results[brain]['mean_steps']:.1f}"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=list))


if __name__ == "__main__":
    main()
