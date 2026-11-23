"""With vs without tools, on the phase 1 test set: what do the tools fix?

The same model, the same problems (``rlm/data/test.jsonl``) and the same verifier as phase 1
(``EuroVerifier`` with each problem's tolerance), in three variants:

* ``none``: no tools; the model must apply the rules and do the arithmetic itself;
* ``arithmetic``: only a generic calculator; arithmetic is fixed, the rules are still the
  model's job;
* ``domain``: the full registry, whose calculators apply the rules.

Phase 1 failed both on rules (VAT on new builds, depreciation in IRPF) and on arithmetic
(divisions, the French mortgage). The gap between ``none`` and ``arithmetic`` measures the
arithmetic part, the gap between ``arithmetic`` and ``domain`` the rules part.

Every problem gets the same instruction to end with the figure inside <answer></answer>,
because the verifier accepts exactly one number there.

Run::

    uv run python -m tool_use.phase1_compare --variants none arithmetic domain \\
        --per-family 10 --out reports/fase2/phase2_vs_phase1.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ANSWER_INSTRUCTION = (
    "\n\nCuando tengas el resultado, termina con la cifra final, sin unidades, entre "
    "<answer> y </answer>."
)


def registry_for(variant: str):
    from tool_use.registry import ToolRegistry
    from tool_use.tools import arithmetic_registry, default_registry

    return {"none": ToolRegistry, "arithmetic": arithmetic_registry, "domain": default_registry}[
        variant
    ]()


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, Any] = {}
    for variant in sorted({r["variant"] for r in rows}):
        items = [r for r in rows if r["variant"] == variant]
        families: dict[str, list[bool]] = defaultdict(list)
        for r in items:
            families[r["family"]].append(r["correct"])
        by_variant[variant] = {
            "n": len(items),
            "pass_at_1": round(sum(r["correct"] for r in items) / len(items), 3),
            "used_a_tool": round(sum(bool(r["tool_calls"]) for r in items) / len(items), 3),
            "failed_calls": sum(sum(not c["ok"] for c in r["tool_calls"]) for r in items),
            "by_family": {f: round(sum(v) / len(v), 3) for f, v in sorted(families.items())},
        }
    return by_variant


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", default="rlm/data/test.jsonl")
    parser.add_argument("--variants", nargs="+", default=["none", "arithmetic", "domain"])
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--limit", type=int, default=None, help="first N problems")
    parser.add_argument(
        "--per-family", type=int, default=None, help="first N problems of each family"
    )
    parser.add_argument(
        "--skip-per-family",
        type=int,
        default=0,
        help="skip the first N of each family (a fresh sample after tuning on the first ones)",
    )
    parser.add_argument(
        "--resume", action="store_true", help="keep the rows already in --out and skip them"
    )
    parser.add_argument("--out", default="reports/fase2/phase2_vs_phase1.json")
    args = parser.parse_args()

    os.environ["ARCA_PORTFOLIO_DB"] = str(Path(tempfile.mkdtemp()) / "portfolio.sqlite")
    from rlm.verifier import EuroVerifier
    from tool_use.executor import HFChatModel, ToolLoop

    problems = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line]
    if args.per_family:
        seen: dict[str, int] = defaultdict(int)
        kept = []
        for problem in problems:
            rank = seen[problem["family"]]
            seen[problem["family"]] += 1
            if args.skip_per_family <= rank < args.skip_per_family + args.per_family:
                kept.append(problem)
        problems = kept
    problems = problems[: args.limit]
    model = HFChatModel(
        model_id=args.model,
        adapter_path=args.adapter,
        enable_thinking=args.thinking,
        max_new_tokens=args.max_new_tokens,
    ).load()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if args.resume and out.exists():  # a session cut mid-run: keep what was done
        rows = json.loads(out.read_text())["rows"]
        print(f"resuming with {len(rows)} rows already done", flush=True)
    done = {(r["variant"], r["question"]) for r in rows}
    for variant in args.variants:
        loop = ToolLoop(model=model, registry=registry_for(variant), use_tools=variant != "none")
        for i, problem in enumerate(problems, 1):
            if (variant, problem["question"]) in done:
                continue
            response = loop.run(problem["question"] + ANSWER_INSTRUCTION, max_turns=args.max_turns)
            verifier = EuroVerifier(
                problem.get("tolerance_abs", 0.01), problem.get("tolerance_rel", 0.0)
            )
            result = verifier.verify(response.answer, problem["answer"])
            rows.append(
                {
                    "variant": variant,
                    "family": problem["family"],
                    "question": problem["question"],
                    "expected": problem["answer"],
                    "predicted": result.predicted,
                    "correct": result.is_correct,
                    "tool_calls": [c.model_dump() for c in response.tool_calls],
                    "turns": response.turns,
                    "answer": response.answer,
                }
            )
            mark = "✓" if result.is_correct else "✗"
            names = ",".join(c.name for c in response.tool_calls) or "-"
            print(
                f"[{variant} {i}/{len(problems)}] {mark} {problem['family']:16s} {names}",
                flush=True,
            )
            out.write_text(
                json.dumps(
                    {
                        "config": vars(args),
                        "model": model.name,
                        "summary": summarise(rows),
                        "rows": rows,
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
    print(json.dumps(summarise(rows), indent=2))


if __name__ == "__main__":
    main()
