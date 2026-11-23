"""Evaluate an MLX model (merged and quantized with mlx_lm) on the test, like rlm/evaluate.py.

The API serves the quantized model on a Mac, so the reported pass@1 has to be checked on that
model, not only on the PyTorch adapter. Same prompts, greedy decoding and 2048 new tokens as
``rlm/evaluate.py``; the output has the same format and is compared problem by problem with the
PyTorch evaluation.

On a Mac, with the ``mac`` extra (``uv sync --extra train --extra mac``)::

    uv run python -m rlm.eval_mlx --model rlm/weights/grpo2_mlx_8bit --n-examples 30 \
        --batch-size 4 --compare reports/eval_grpo2_17b_2048.json \
        --out reports/eval_grpo2_mlx8_2048.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rlm.data import build_prompt
from rlm.evaluate import summarize
from rlm.generation import batched
from rlm.realestate_rewards import breakdown_reward, verify_row
from rlm.rewards import has_valid_format, thinking_length


def score(row: dict, raw: str, n_tokens: int, max_new_tokens: int) -> dict:
    """The same fields as rlm.evaluate.evaluate_model."""
    correct, predicted = verify_row(raw, row)
    breakdown = breakdown_reward(
        [None],
        [raw],
        [str(row["answer"])],
        unit=[row.get("unit")],
        checkpoints=[row.get("checkpoints") or []],
        tolerance_abs=[row.get("tolerance_abs", 0.01)],
        tolerance_rel=[row.get("tolerance_rel", 0.0)],
    )[0]
    return {
        "question": row["question"],
        "family": row.get("family", "control"),
        "expected": str(row["answer"]),
        "raw": raw,
        "predicted": predicted,
        "is_correct": correct,
        "has_valid_format": has_valid_format(raw),
        "n_tokens": n_tokens,
        "think_words": thinking_length(raw),
        "truncated": n_tokens >= max_new_tokens,
        "breakdown": breakdown,
    }


def compare(rows: list[dict], reference: Path, name: str) -> None:
    """Agreement with the PyTorch evaluation and exact McNemar test on the discordant pairs."""
    from math import comb

    ref = json.loads(reference.read_text())
    ref_rows = {r["question"]: r for r in next(iter(ref.values()))["rows"]}
    both = only_ref = only_new = 0
    for row in rows:
        old = ref_rows[row["question"]]["is_correct"]
        both += old and row["is_correct"]
        only_ref += old and not row["is_correct"]
        only_new += row["is_correct"] and not old
    n = only_ref + only_new
    p = min(1.0, 2 * sum(comb(n, k) for k in range(min(only_ref, only_new) + 1)) / 2**n)
    print(
        f"vs {reference.name}: both right {both}, only PyTorch {only_ref}, only {name} "
        f"{only_new} (McNemar p = {p:.3f})",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", required=True, help="MLX model folder")
    parser.add_argument("--data", default="rlm/data/test.jsonl")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--n-examples", type=int, default=None)
    parser.add_argument("--name", default="mlx8")
    parser.add_argument("--compare", default=None, help="rlm.evaluate JSON to compare with")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from mlx_lm import batch_generate, load

    model, tokenizer = load(args.model)
    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines()]
    rows = rows[: args.n_examples] if args.n_examples else rows
    evaluated, started = [], time.perf_counter()
    for chunk in batched(rows, args.batch_size):
        prompts = [
            tokenizer.apply_chat_template(
                build_prompt(r["question"]), tokenize=True, add_generation_prompt=True
            )
            for r in chunk
        ]
        response = batch_generate(
            model, tokenizer, prompts, max_tokens=args.max_new_tokens, return_token_ids=True
        )
        for row, raw, ids in zip(chunk, response.texts, response.token_ids, strict=True):
            evaluated.append(score(row, raw, len(ids), args.max_new_tokens))
        right = sum(r["is_correct"] for r in evaluated)
        print(
            f"{len(evaluated)}/{len(rows)} done, {right} right, "
            f"{time.perf_counter() - started:.0f}s",
            flush=True,
        )

    summary = summarize(evaluated)
    out = Path(args.out)
    out.write_text(
        json.dumps(
            {args.name: {"summary": summary, "rows": evaluated}}, indent=2, ensure_ascii=False
        )
    )
    print(f"{args.name}: pass@1 = {summary['overall']['pass@1']:.3f} -> {out}", flush=True)
    if args.compare:
        compare(evaluated, Path(args.compare), args.name)


if __name__ == "__main__":
    main()
