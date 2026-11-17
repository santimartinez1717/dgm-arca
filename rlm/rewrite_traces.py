"""Second pass of privileged distillation: rewrite the traces as if the key had never existed.

A teacher in thinking mode verbalises everything it sees. With the solution key in its prompt
it reasons correctly, but it also writes "which matches the private key's value" or "but the
key says 3,673…" and reasons from there (pilot of 2026-11-17: 3 of the first 4 correct traces).
Deleting those sentences leaves the reasoning around them dangling, so instead the same
teacher, without thinking mode, rewrites each correct trace as one expert working the problem
out alone. The rewritten trace is verified again from scratch: right answer, every
intermediate value computed, no mention of the key or the rule sheet.

Run::

    PYTHONUNBUFFERED=1 uv run python -m rlm.rewrite_traces \
        --input rlm/data/sft_traces_priv_irpf_pilot.jsonl \
        --output rlm/data/sft_traces_priv_irpf_pilot.rewritten.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from rlm.distill import (
    ANSWER,
    RULES_LEAK,
    THINK,
    acceptance_report,
    derived_share,
    read_traces,
    recapitalize,
)
from rlm.generation import Generator, batched
from rlm.realestate_rewards import verify_row
from rlm.rewards import has_valid_format

# The student's other traces are in English; 6 of 59 rewrites in the pilot came out in Spanish.
SPANISH_WORDS = re.compile(r"\b(el|la|los|las|que|del|por|es|una|para|con|se)\b", re.IGNORECASE)

REWRITE_SYSTEM_PROMPT = "You edit worked solutions so that they read as an expert's own reasoning."
REWRITE_REQUEST = """\
Below is a problem and a worked solution to it. The solver had a private answer key and \
sometimes refers to it. Rewrite the reasoning so that it reads as one expert working the \
problem out alone, from the statement only:
- remove every mention of a key, of values known in advance, of checking against expected \
values, and any detour or doubt that only came from comparing with them;
- keep every calculation with its numbers, written as "expression = result";
- keep the legal and financial justification of each step;
- write in English even though the problem is in Spanish, in the first person, with no \
headings; be concise.
Output only the rewritten reasoning: no tags, no final answer line.

Problem:
{question}

Worked solution:
{thinking}"""


def rewrite(
    traces: list[dict],
    rows: dict[str, dict],
    teacher: str,
    batch_size: int,
    max_new_tokens: int,
    min_think_words: int,
    limit: int | None = None,
) -> Iterator[list[dict]]:
    """Rewrite every correct, finished trace; yield the rewritten traces of each batch, verified
    again, with ``rejected`` naming the first check that failed (None when kept)."""
    candidates = [t for t in traces if t["trace"].startswith("<think>") and not t["truncated"]]
    candidates = [t for t in candidates if verify_row(t["trace"], rows[t["question"]])[0]]
    candidates = candidates[:limit] if limit else candidates
    print(f"{len(candidates)} correct finished traces of {len(traces)} to rewrite", flush=True)
    editor = Generator(teacher, enable_thinking=False, system_prompt=REWRITE_SYSTEM_PROMPT).load()
    kept = done = 0
    for chunk in batched(candidates, batch_size):
        prompts = [
            REWRITE_REQUEST.format(
                question=t["question"], thinking=THINK.search(t["trace"]).group("think").strip()
            )
            for t in chunk
        ]
        outputs = editor.generate(prompts, max_new_tokens=max_new_tokens, temperature=0.3)
        batch = []
        for t, [(text, n_tokens, truncated)] in zip(chunk, outputs, strict=True):
            answer = ANSWER.search(t["trace"]).group("answer").strip()
            thinking = recapitalize(text.replace("<think>", "").replace("</think>", "").strip())
            trace = f"<think>\n{thinking}\n</think>\n<answer>{answer}</answer>"
            row = rows[t["question"]]
            mentions = bool(RULES_LEAK.search(thinking))
            derived = derived_share(thinking, row)
            checks = [
                ("truncated", not truncated),
                ("format", has_valid_format(trace)),
                ("wrong answer", verify_row(trace, row)[0]),
                ("too short", len(thinking.split()) >= min_think_words),
                (
                    "not English",
                    len(SPANISH_WORDS.findall(thinking)) <= 0.08 * len(thinking.split()),
                ),
                ("mentions key or sheet", not mentions),
                ("value not computed", derived == 1.0),
            ]
            rejected = next((name for name, passed in checks if not passed), None)
            batch.append(
                {
                    **t,
                    "trace": trace,
                    "verified": rejected is None,
                    "rejected": rejected,
                    "truncated": truncated,
                    "mentions_rules": mentions,
                    "derived": derived,
                    "rewritten": True,
                    "n_tokens": n_tokens,
                }
            )
        done += len(batch)
        kept += sum(t["verified"] for t in batch)
        reasons = Counter(t["rejected"] for t in batch if t["rejected"])
        print(f"{done} rewritten, {kept} verified · rejected now: {dict(reasons)}", flush=True)
        yield batch


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", required=True, help="privileged traces from rlm.distill")
    parser.add_argument("--data", default="rlm/data/train.jsonl", help="the problems")
    parser.add_argument("--teacher", default="Qwen/Qwen3-4B")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=1536)
    parser.add_argument("--min-think-words", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None, help="only the first N traces")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = {
        r["question"]: r
        for r in (json.loads(line) for line in Path(args.data).read_text().splitlines())
    }
    traces = read_traces(Path(args.input))
    out = []
    with Path(args.output).open("w", encoding="utf-8") as handle:
        for batch in rewrite(
            traces,
            rows,
            args.teacher,
            args.batch_size,
            args.max_new_tokens,
            args.min_think_words,
            args.limit,
        ):
            handle.write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in batch))
            handle.flush()
            out.extend(batch)
    report = acceptance_report(out)
    print(f"acceptance {100 * report['overall']:.1f}% -> {args.output}")


if __name__ == "__main__":
    main()
