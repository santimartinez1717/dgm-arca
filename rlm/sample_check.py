"""Will GRPO have a signal? Sample k answers per problem and count the problems with a hit.

GRPO learns only from groups where some answers are right and some wrong. In the run of
2026-10-18 not one of 552 sampled irpf_rental answers was right, so that family taught
nothing. Before a long GRPO run, this samples ``k`` answers per problem at GRPO's temperature
and reports, per family: pass@k (problems with at least one right answer), the share of
"useful" problems (some right, some wrong) and the mean process reward of the wrong answers.

Run::

    PYTHONUNBUFFERED=1 uv run python -m rlm.sample_check --adapter rlm/weights/sft_lora \
        --families irpf_rental cash_on_cash legal_rent acquisition_cost --n-per-family 15
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from rlm.generation import Generator, batched
from rlm.realestate_rewards import process_reward, verify_row


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", default="rlm/data/train.jsonl")
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--families", nargs="+", required=True)
    parser.add_argument("--branch", nargs="*", default=[], help="e.g. new_build=True")
    parser.add_argument("--n-per-family", type=int, default=15)
    parser.add_argument("--k", type=int, default=8, help="answers per problem, as in GRPO")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=2, help="problems per batch")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", default="reports/sample_check.json")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines()]
    for condition in args.branch:
        key, value = condition.split("=", 1)
        rows = [r for r in rows if (r.get("branches") or {}).get(key) == value]
    rng = random.Random(args.seed)
    chosen = []
    for family in args.families:
        pool = [r for r in rows if r["family"] == family]
        chosen += rng.sample(pool, min(args.n_per_family, len(pool)))

    generator = Generator(args.model, adapter_path=args.adapter).load()
    per_problem = []
    for chunk in batched(chosen, args.batch_size):
        outputs = generator.generate(
            [r["question"] for r in chunk],
            num_return_sequences=args.k,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
        )
        for row, completions in zip(chunk, outputs, strict=True):
            texts = [text for text, _, _ in completions]
            hits = [verify_row(text, row)[0] for text in texts]
            prompt = [{"role": "user", "content": row["question"]}]
            steps = process_reward(
                [prompt] * len(texts),
                texts,
                [str(row["answer"])] * len(texts),
                unit=[row["unit"]] * len(texts),
                checkpoints=[row["checkpoints"]] * len(texts),
            )
            per_problem.append(
                {
                    "question": row["question"],
                    "family": row["family"],
                    "hits": sum(hits),
                    "truncated": sum(t for _, _, t in completions),
                    "process_wrong": [s for s, h in zip(steps, hits, strict=True) if not h],
                }
            )
        print(f"{len(per_problem)}/{len(chosen)} problems sampled", flush=True)

    summary = {}
    by_family = defaultdict(list)
    for p in per_problem:
        by_family[p["family"]].append(p)
    for family, problems in by_family.items():
        wrong = [s for p in problems for s in p["process_wrong"]]
        summary[family] = {
            "problems": len(problems),
            f"pass@{args.k}": sum(p["hits"] > 0 for p in problems) / len(problems),
            "useful (some right, some wrong)": sum(0 < p["hits"] < args.k for p in problems)
            / len(problems),
            "right answers": sum(p["hits"] for p in problems) / (args.k * len(problems)),
            "truncated": sum(p["truncated"] for p in problems) / (args.k * len(problems)),
            "process reward of wrong answers": sum(wrong) / len(wrong) if wrong else None,
        }
        print(family, json.dumps(summary[family]), flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"args": vars(args), "summary": summary, "problems": per_problem},
            indent=1,
            ensure_ascii=False,
        )
    )
    print(f"-> {out}")


if __name__ == "__main__":
    main()
