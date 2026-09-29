"""Phase 1, step 1b: generate reasoning traces with a teacher model and keep the verified ones.

This is what Sky-T1, OpenThoughts and DeepSeek's cold start have in common: a strong
model writes solutions with visible reasoning, a verifier throws away the wrong ones,
and what survives becomes SFT data. Our teacher is Qwen3 in thinking mode.

Run (on the DGX; a subset is enough, SFT needs 1-2k verified traces)::

    uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B \
        --samples 4 --limit 800 --output rlm/data/sft_traces.jsonl

Output: one JSON line per generated trace with ``question``, ``answer``, ``family``,
``trace`` (canonical ``<think>…</think><answer>…</answer>``), ``verified``, ``truncated``
and ``teacher``. The acceptance rate, overall and per family, is printed and saved next to
the output: it is the first measurement of how hard each family is, and goes to
EXPERIMENTS.md.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

from rlm.generation import Generator, batched
from rlm.realestate_rewards import verify_row
from rlm.rewards import has_valid_format

THINK = re.compile(r"<think>(?P<think>.*?)</think>", re.DOTALL)
ANSWER = re.compile(r"<answer>(?P<answer>.*?)</answer>", re.DOTALL)


def canonicalize(raw: str) -> str | None:
    """Rewrite a teacher completion into ``<think>…</think><answer>…</answer>``.

    Qwen3 in thinking mode opens ``<think>`` inside the chat template, so the decoded text
    often starts mid-thought and only shows the closing tag. After ``</think>`` it may or may
    not use ``<answer>``; when it does not, the last non-empty line is taken as the answer.
    Returns None when there is no reasoning at all.
    """
    if "</think>" not in raw:
        return None
    thinking, after = raw.split("</think>", 1)
    thinking = thinking.replace("<think>", "").strip()
    if not thinking:
        return None
    match = ANSWER.search(after)
    if match:
        answer = match.group("answer").strip()
    else:
        lines = [line.strip() for line in after.strip().splitlines() if line.strip()]
        if not lines:
            return None
        answer = lines[-1]
    return f"<think>\n{thinking}\n</think>\n<answer>{answer}</answer>"


def generate_traces(
    rows: list[dict],
    teacher: str,
    samples: int,
    max_new_tokens: int,
    batch_size: int,
    temperature: float,
    min_think_words: int,
) -> list[dict]:
    """For each problem, sample ``samples`` teacher completions, canonicalise and verify them.

    A trace is kept as ``verified`` only if it has valid format, the answer passes the domain
    verifier, it was not truncated, and the reasoning has at least ``min_think_words`` words
    (a cheap filter against answers that are right by luck with no reasoning).
    """
    generator = Generator(teacher, enable_thinking=True).load()
    traces: list[dict] = []
    for chunk in batched(rows, batch_size):
        outputs = generator.generate(
            [row["question"] for row in chunk],
            num_return_sequences=samples,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        for row, completions in zip(chunk, outputs, strict=True):
            for raw, n_tokens, truncated in completions:
                trace = canonicalize(raw)
                ok = False
                if trace is not None and not truncated and has_valid_format(trace):
                    correct, _ = verify_row(trace, row)
                    think_words = len(THINK.search(trace).group("think").split())
                    ok = correct and think_words >= min_think_words
                traces.append(
                    {
                        "question": row["question"],
                        "answer": row["answer"],
                        "family": row.get("family", "control"),
                        "trace": trace or raw,
                        "verified": ok,
                        "truncated": truncated,
                        "n_tokens": n_tokens,
                        "teacher": teacher,
                    }
                )
        kept = sum(t["verified"] for t in traces)
        print(f"{len(traces)} traces, {kept} verified ({100 * kept / len(traces):.1f}%)")
    return traces


def acceptance_report(traces: list[dict]) -> dict:
    """Acceptance rate overall and per family, plus truncation, for EXPERIMENTS.md."""
    total = Counter(t["family"] for t in traces)
    kept = Counter(t["family"] for t in traces if t["verified"])
    truncated = Counter(t["family"] for t in traces if t["truncated"])
    solved = {}
    for t in traces:
        solved.setdefault((t["family"], t["question"]), False)
        solved[(t["family"], t["question"])] |= t["verified"]
    problems = Counter(f for f, _ in solved)
    problems_solved = Counter(f for (f, _), ok in solved.items() if ok)
    return {
        "overall": sum(kept.values()) / max(len(traces), 1),
        "per_family": {
            f: {
                "traces": total[f],
                "acceptance": kept[f] / total[f],
                "truncated": truncated[f] / total[f],
                "problems_with_a_verified_trace": problems_solved[f] / problems[f],
            }
            for f in sorted(total)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", required=True, help="domain JSONL with question / answer")
    parser.add_argument("--teacher", default="Qwen/Qwen3-4B")
    parser.add_argument("--samples", type=int, default=4, help="traces per problem")
    parser.add_argument("--limit", type=int, default=None, help="random subset of problems")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="problems per batch; x samples sequences share the KV cache (16 GB GPU: 2)",
    )
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--max-new-tokens", type=int, default=3072)
    parser.add_argument("--min-think-words", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", default="rlm/data/sft_traces.jsonl")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines()]
    if args.limit:
        rows = random.Random(args.seed).sample(rows, min(args.limit, len(rows)))
    traces = generate_traces(
        rows,
        args.teacher,
        args.samples,
        args.max_new_tokens,
        args.batch_size,
        args.temperature,
        args.min_think_words,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in traces:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = acceptance_report(traces)
    report_path = out.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"acceptance {100 * report['overall']:.1f}% -> {out}\nper family -> {report_path}")


if __name__ == "__main__":
    main()
