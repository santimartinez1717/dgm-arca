"""Phase 2 evaluation: does the model pick the right tool with the right arguments?

The benchmark (``tool_use/bench/cases.jsonl``) has one case per line::

    {"id": "acq-01", "category": "single", "query": "...", "needs_tool": true,
     "expected_tool": "acquisition_cost",
     "expected_arguments": {"price": 185000, "region": "andalucia"}}

Chained and parallel cases add the whole expected sequence, with ``"turn"`` when calls must
go out together::

    "expected_calls": [{"tool": "rental_returns", "arguments": {...}, "turn": 1}, ...]

Metrics, overall and by category:

* ``tool_selection_accuracy``: the first call names the expected tool, or there is no call
  when ``needs_tool`` is false;
* ``argument_accuracy``: the first call also has the expected arguments and passed
  validation. Only the keys in the case are compared (numbers within 0.5 %, text without
  case or accents, ``"*"`` matches anything, a place is compared by its community); extra
  keys are allowed only if they change nothing (the default, or 0 where the default is
  None), so a model that invents an IBI is wrong;
* ``sequence_accuracy`` (chained and parallel cases): every expected call appears, in order,
  with its arguments, and calls marked with the same turn went out in the same generation;
* ``false_call_rate``: share of no-tool cases where the model called a tool anyway.

Run::

    uv run python -m tool_use.evaluate --out reports/phase2_bench.json
    uv run python -m tool_use.evaluate --adapter rlm/weights/final_rlm_lora --out ...
    uv run python -m tool_use.evaluate --rescore reports/phase2_bench_*.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from tool_use.build_data import normalise_name
from tool_use.regions import resolve_region

NUMERIC_TOLERANCE = 0.005


def load_bench(path: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def values_match(expected: Any, actual: Any) -> bool:
    """Tolerant comparison of one argument value."""
    if expected == "*":
        return actual is not None
    if isinstance(expected, bool) or isinstance(actual, bool):  # True == 1 in Python
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, int | float):
        try:
            actual = float(actual)
        except (TypeError, ValueError):
            return False
        return abs(actual - expected) <= max(0.01, NUMERIC_TOLERANCE * abs(expected))
    if isinstance(expected, str) and isinstance(actual, str | int | float):
        a, b = normalise_name(expected), normalise_name(str(actual))
        return a == b or (a.isdigit() and b.isdigit() and int(a) == int(b))
    return expected == actual


def arguments_match(
    expected: dict[str, Any], actual: dict[str, Any], defaults: dict[str, Any]
) -> bool:
    for key, value in expected.items():
        if key not in actual:
            return False
        if key == "region" and value != "*":  # "Sevilla" is as good as "andalucia"
            if _region(actual[key]) != value:
                return False
        elif not values_match(value, actual[key]):
            return False
    for key, value in actual.items():  # extra keys must be harmless defaults
        if key not in expected and not _harmless(value, key, defaults):
            return False
    return True


def _region(value: Any) -> str | None:
    try:
        return resolve_region(str(value))
    except ValueError:
        return None


def _harmless(value: Any, key: str, defaults: dict[str, Any]) -> bool:
    """An extra argument that changes nothing: the default, or 0/False where it is None
    (the tools read an empty value and a missing one the same way)."""
    if value is None:
        return True
    if key not in defaults:
        return False
    default = defaults[key]
    if default is None:
        return value in (0, False, "")
    return values_match(default, value)


def tool_defaults(registry) -> dict[str, dict[str, Any]]:
    """Default value of every optional argument of every tool."""
    out = {}
    for name, tool in registry.tools.items():
        out[name] = {
            k: f.default for k, f in tool.args_model.model_fields.items() if not f.is_required()
        }
    return out


def expected_calls(case: dict[str, Any]) -> list[dict[str, Any]]:
    if "expected_calls" in case:
        return case["expected_calls"]
    if case.get("needs_tool", True):
        return [{"tool": case["expected_tool"], "arguments": case.get("expected_arguments", {})}]
    return []


def score_case(
    case: dict[str, Any],
    calls: list[dict[str, Any]],
    turns: list[int] | None = None,
    defaults: dict[str, dict[str, Any]] | None = None,
) -> dict[str, bool]:
    """Compare the calls the model made against the expectation for one benchmark case."""
    defaults = defaults or {}
    turns = turns or list(range(1, len(calls) + 1))
    if not case.get("needs_tool", True):
        ok = not calls
        return {"selection_ok": ok, "arguments_ok": ok, "sequence_ok": ok}

    wanted = expected_calls(case)
    first = calls[0] if calls else None
    selection_ok = first is not None and first["name"] == case["expected_tool"]
    # In a parallel case the first call may be any of the first turn's expected calls.
    candidates = [c for c in wanted if c.get("turn") == 1] or wanted[:1]
    arguments_ok = (
        selection_ok
        and first.get("ok", True)
        and any(
            c["tool"] == first["name"]
            and arguments_match(c["arguments"], first["arguments"], defaults.get(c["tool"], {}))
            for c in candidates
        )
    )

    # Match expected calls in order; calls with the same expected turn may come in any order.
    used: set[int] = set()
    matched_turns: dict[int, set[int]] = {}
    position = 0
    sequence_ok = True
    for want in wanted:
        found = None
        start = 0 if want.get("turn") else position
        for i in range(start, len(calls)):
            if i in used or calls[i]["name"] != want["tool"] or not calls[i].get("ok", True):
                continue
            if arguments_match(
                want["arguments"], calls[i]["arguments"], defaults.get(want["tool"], {})
            ):
                found = i
                break
        if found is None:
            sequence_ok = False
            break
        used.add(found)
        position = max(position, found + 1)
        if want.get("turn"):
            matched_turns.setdefault(want["turn"], set()).add(turns[found])
    if sequence_ok and any(len(t) > 1 for t in matched_turns.values()):
        sequence_ok = False  # calls meant to be parallel went out in different turns
    return {"selection_ok": selection_ok, "arguments_ok": arguments_ok, "sequence_ok": sequence_ok}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(items, key):
        return round(sum(r[key] for r in items) / len(items), 3) if items else None

    no_tool = [r for r in rows if not r.get("needs_tool", True)]
    multi = [r for r in rows if r.get("category") in ("chain", "parallel")]
    summary: dict[str, Any] = {
        "n_cases": len(rows),
        "tool_selection_accuracy": rate(rows, "selection_ok"),
        "argument_accuracy": rate(rows, "arguments_ok"),
        "sequence_accuracy": rate(multi, "sequence_ok"),
        "false_call_rate": round(sum(bool(r["tool_calls"]) for r in no_tool) / len(no_tool), 3)
        if no_tool
        else None,
        "mean_turns": round(sum(r["turns"] for r in rows) / len(rows), 2) if rows else None,
        "by_category": {},
    }
    for category in sorted({r.get("category", "single") for r in rows}):
        items = [r for r in rows if r.get("category", "single") == category]
        summary["by_category"][category] = {
            "n": len(items),
            "selection": rate(items, "selection_ok"),
            "arguments": rate(items, "arguments_ok"),
            "sequence": rate(items, "sequence_ok"),
        }
    return summary


def rescore(report: str | Path, bench: str | Path) -> dict[str, Any]:
    """Score a saved report again with the current bench and scorer, without generating.

    The report keeps every call the model made, so a fix to a case or to the scorer applies
    to past runs too and they stay comparable.
    """
    from tool_use.tools import default_registry

    data = json.loads(Path(report).read_text())
    cases = {c["id"]: c for c in load_bench(bench)}
    defaults = tool_defaults(default_registry())
    rows = []
    for row in data["rows"]:
        case = cases[row["id"]]
        scores = score_case(case, row["tool_calls"], row["call_turns"], defaults)
        rows.append({**row, **case, **scores})
    data["rows"] = rows
    data["summary"] = summarise(rows)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bench", default="tool_use/bench/cases.jsonl")
    parser.add_argument("--out", default="reports/phase2_bench.json")
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--adapter", default=None, help="LoRA adapter, e.g. the phase 1 one")
    parser.add_argument("--thinking", action="store_true", help="let Qwen3 think each turn")
    parser.add_argument("--prompt-style", choices=["native", "course"], default="native")
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", nargs="*", help="only these case ids")
    parser.add_argument(
        "--rescore", nargs="+", metavar="REPORT", help="score saved reports again, in place"
    )
    args = parser.parse_args()

    if args.rescore:
        for report in args.rescore:
            data = rescore(report, args.bench)
            Path(report).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            print(
                report, json.dumps({k: v for k, v in data["summary"].items() if k != "by_category"})
            )
        return

    # A fresh portfolio per run, so save_to_portfolio cases do not leak between runs.
    os.environ["ARCA_PORTFOLIO_DB"] = str(Path(tempfile.mkdtemp()) / "portfolio.sqlite")

    from tool_use.executor import HFChatModel, ToolLoop
    from tool_use.tools import default_registry

    cases = load_bench(args.bench)
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]
    cases = cases[: args.limit]
    model = HFChatModel(
        model_id=args.model,
        adapter_path=args.adapter,
        enable_thinking=args.thinking,
        max_new_tokens=args.max_new_tokens,
    ).load()
    loop = ToolLoop(model=model, prompt_style=args.prompt_style)
    defaults = tool_defaults(default_registry())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, case in enumerate(cases, 1):
        response = loop.run(case["query"], max_turns=args.max_turns)
        calls = [c.model_dump() for c in response.tool_calls]
        scores = score_case(case, calls, loop.call_turns, defaults)
        rows.append(
            {
                **case,
                "tool_calls": calls,
                "call_turns": loop.call_turns,
                "turns": response.turns,
                "answer": response.answer,
                "raw_outputs": loop.raw_outputs,
                **scores,
            }
        )
        mark = "✓" if scores["arguments_ok"] and scores["sequence_ok"] else "✗"
        names = ", ".join(c["name"] for c in calls) or "-"
        print(f"[{i}/{len(cases)}] {mark} {case['id']:9s} {names}", flush=True)
        summary = summarise(rows)  # saved after every case: a cut session keeps its results
        config = {k: v for k, v in vars(args).items() if k not in ("ids", "limit")}
        out.write_text(
            json.dumps(
                {"config": config, "model": model.name, "summary": summary, "rows": rows},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    print(json.dumps(summarise(rows), indent=2))


if __name__ == "__main__":
    main()
