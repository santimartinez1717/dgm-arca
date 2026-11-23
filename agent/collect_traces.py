"""Collect the agent's successful traces on the synthetic tasks, as SFT data (issue 18).

The agent runs on ``agent/bench/train_tasks.jsonl`` (never the bench) and every run is kept
in ``--runs``, so a run cut short by the end of the Slurm session resumes where it stopped.
A trace is accepted when it

* passes the task's ``check``,
* passes the auditor at the first attempt (``succeeded`` and no rejection),
* takes no more steps than the median of the runs that pass the check.

The accepted ones become SFT examples in ``--out``: one per generation, with the prompt
rendered exactly as the model saw it (chat template, tool definitions, case file) and the
model's raw output as the completion, so the loss falls only on what the agent wrote::

    uv run python -m agent.collect_traces --tasks agent/bench/train_tasks.jsonl \\
        --brain base --runs reports/fase4/traces_runs.jsonl --out rlm/data/agent_sft.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from agent.evaluate import check_answer, isolated


def run_tasks(
    agent: Any, tasks: list[dict], brain: str, max_steps: int, runs: Path, max_minutes: float | None
) -> None:
    """Run every task not yet in ``runs``, appending one line per run."""
    done = set()
    if runs.exists():
        done = {json.loads(line)["id"] for line in runs.read_text(encoding="utf-8").splitlines()}
    todo = [t for t in tasks if t["id"] not in done]
    started = time.perf_counter()
    runs.parent.mkdir(parents=True, exist_ok=True)
    for i, task in enumerate(todo, 1):
        if max_minutes is not None and time.perf_counter() - started > 60 * max_minutes:
            print(f"time budget of {max_minutes:g} min reached", flush=True)
            break
        t0 = time.perf_counter()
        with isolated(task):
            try:
                response = agent.run(task["task"], max_steps=max_steps, brain=brain).model_dump()
                crash = None
            except Exception as exc:  # noqa: BLE001 - a crash is a rejected run, not the end
                response = {"final_answer": "", "steps": [], "n_steps": 0, "succeeded": False}
                crash = f"{type(exc).__name__}: {exc}"
        audit = response.get("audit") or {}
        row = {
            "id": task["id"],
            "category": task["category"],
            "task": task["task"],
            "check": check_answer(task, response.get("final_answer", "")),
            "succeeded": bool(response.get("succeeded")),
            "rejections": int(audit.get("rejections", 0)),
            "n_steps": response.get("n_steps", 0),
            "tokens_used": response.get("tokens_used", 0),
            "final_answer": response.get("final_answer", ""),
            "crash": crash,
            "seconds": round(time.perf_counter() - t0, 1),
            "generations": [] if crash else agent.last_generations,
        }
        with runs.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        mark = "ok" if row["check"] else "no"
        print(
            f"[{len(done) + i}/{len(tasks)}] {task['id']}: {mark} steps={row['n_steps']} "
            f"rej={row['rejections']} {row['seconds']}s",
            flush=True,
        )


def accept(rows: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    """The accepted runs and the acceptance report (rates per filter and per category)."""
    passing = [r for r in rows if r["check"]]
    median = statistics.median(r["n_steps"] for r in passing) if passing else 0
    clean = [r for r in passing if r["succeeded"] and r["rejections"] == 0]
    kept = [r for r in clean if r["n_steps"] <= median]
    per_category: dict[str, dict[str, int]] = {}
    for r in rows:
        c = per_category.setdefault(r["category"], {"runs": 0, "check": 0, "accepted": 0})
        c["runs"] += 1
        c["check"] += r["check"]
    for r in kept:
        per_category[r["category"]]["accepted"] += 1
    report = {
        "runs": len(rows),
        "pass_check": len(passing),
        "pass_audit_first_time": len(clean),
        "median_steps_of_passing": median,
        "accepted": len(kept),
        "acceptance_rate": round(len(kept) / len(rows), 3) if rows else 0.0,
        "per_category": per_category,
    }
    return kept, report


def to_sft(rows: list[dict], tokenizer: Any, tools: list[dict]) -> list[dict]:
    """One prompt/completion example per generation, rendered with the model's own template."""
    examples = []
    for row in rows:
        for g in row["generations"]:
            prompt = tokenizer.apply_chat_template(
                g["messages"],
                tools=tools,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            examples.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "prompt": prompt,
                    "completion": g["raw"],  # TRL appends the EOS token
                }
            )
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", default="agent/bench/train_tasks.jsonl")
    parser.add_argument("--brain", default="base")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--runs", default="reports/fase4/traces_runs.jsonl")
    parser.add_argument("--out", default="rlm/data/agent_sft.jsonl")
    parser.add_argument("--report", default="reports/fase4/traces_acceptance.json")
    parser.add_argument("--limit", type=int, help="only the first N tasks")
    parser.add_argument("--max-minutes", type=float, help="stop starting new tasks after this")
    parser.add_argument("--only-convert", action="store_true", help="skip running: filter only")
    args = parser.parse_args()

    from agent.react_agent import ReActAgent

    tasks = [json.loads(line) for line in Path(args.tasks).read_text().splitlines()]
    tasks = tasks[: args.limit] if args.limit else tasks
    runs = Path(args.runs)
    agent = ReActAgent.from_env()
    if not args.only_convert:
        run_tasks(agent, tasks, args.brain, args.max_steps, runs, args.max_minutes)
    rows = [json.loads(line) for line in runs.read_text(encoding="utf-8").splitlines()]
    kept, report = accept(rows)
    brain = agent.brains["base"]
    brain.load()
    examples = to_sft(kept, brain.tokenizer, agent.tool_definitions())
    report["sft_examples"] = len(examples)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    Path(args.report).write_text(json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"wrote {len(examples)} SFT examples to {out}", flush=True)


if __name__ == "__main__":
    main()
