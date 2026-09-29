"""Phase 1 evaluation: pass@1 of base vs SFT vs GRPO on a held-out set, plus training curves.

Run::

    uv run python -m rlm.evaluate --data rlm/data/test.jsonl \
        --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora

    uv run python -m rlm.evaluate --data rlm/data/test_ood.jsonl --out reports/phase1_ood.json \
        --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora

It writes ``reports/phase1_eval.json`` with per-example verdicts (so you can do the failure
analysis), pass@1 overall and per family, and ``reports/phase1_pass1.png`` with the bar chart.
``--history`` plots the reward and length curves from the ``trainer_state.json`` that TRL
saves in every output and checkpoint folder.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from rlm.generation import Generator, batched
from rlm.realestate_rewards import breakdown_reward, verify_row
from rlm.rewards import has_valid_format, thinking_length


def evaluate_model(
    base_model: str,
    adapter: str | None,
    rows: list[dict],
    max_new_tokens: int,
    batch_size: int = 16,
) -> list[dict]:
    """Greedy generation for every example, one verdict each.

    Returns one dict per example with ``question``, ``family``, ``expected``, ``raw``,
    ``predicted``, ``is_correct``, ``has_valid_format``, ``n_tokens``, ``think_words``,
    ``truncated`` and ``breakdown`` (our third reward, to see if it moves in evaluation too).
    """
    # Same chat template as training and /reasoning (Qwen3 default): the model opens <think>.
    generator = Generator(base_model, adapter_path=adapter).load()
    results = []
    for chunk in batched(rows, batch_size):
        outputs = generator.generate([r["question"] for r in chunk], max_new_tokens=max_new_tokens)
        for row, [(raw, n_tokens, truncated)] in zip(chunk, outputs, strict=True):
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
            results.append(
                {
                    "question": row["question"],
                    "family": row.get("family", "control"),
                    "expected": str(row["answer"]),
                    "raw": raw,
                    "predicted": predicted,
                    "is_correct": correct,
                    "has_valid_format": has_valid_format(raw),
                    "n_tokens": n_tokens,
                    "think_words": thinking_length(raw),
                    "truncated": truncated,
                    "breakdown": breakdown,
                }
            )
    return results


def pass_at_1(rows: list[dict]) -> float:
    return sum(r["is_correct"] for r in rows) / max(len(rows), 1)


def summarize(rows: list[dict]) -> dict:
    """pass@1, format rate and mean length, overall and per family."""
    by_family: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)

    def stats(group: list[dict]) -> dict:
        n = max(len(group), 1)
        return {
            "n": len(group),
            "pass@1": pass_at_1(group),
            "format_rate": sum(r["has_valid_format"] for r in group) / n,
            "truncated_rate": sum(r["truncated"] for r in group) / n,
            "mean_tokens": sum(r["n_tokens"] for r in group) / n,
            "mean_breakdown": sum(r["breakdown"] for r in group) / n,
        }

    return {
        "overall": stats(rows),
        "per_family": {f: stats(g) for f, g in sorted(by_family.items())},
    }


def plot_pass1(results: dict, path: Path) -> None:
    """Grouped bars: pass@1 per family for each model."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(results)
    families = list(results[names[0]]["summary"]["per_family"])
    width = 0.8 / len(names)
    fig, ax = plt.subplots(figsize=(max(6, 1.4 * len(families)), 4))
    for i, name in enumerate(names):
        values = [results[name]["summary"]["per_family"][f]["pass@1"] for f in families]
        ax.bar([x + i * width for x in range(len(families))], values, width, label=name)
    ax.set_xticks([x + width * (len(names) - 1) / 2 for x in range(len(families))])
    ax.set_xticklabels(families, rotation=20, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("pass@1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def plot_history(trainer_state: Path, path: Path) -> None:
    """Reward components and completion length along GRPO training, from ``trainer_state.json``."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    history = json.loads(trainer_state.read_text())["log_history"]
    steps = [h["step"] for h in history if "reward" in h]
    reward_keys = sorted(
        {k for h in history for k in h if k.startswith("rewards/") and k.endswith("/mean")}
    )
    fig, (ax_r, ax_l) = plt.subplots(1, 2, figsize=(11, 4))
    for key in ["reward", *reward_keys]:
        ax_r.plot(steps, [h.get(key) for h in history if "reward" in h], label=key)
    ax_r.set_xlabel("step")
    ax_r.set_title("recompensas")
    ax_r.legend(fontsize=7)
    length_key = next(
        (
            k
            for k in ("completions/mean_length", "completion_length")
            if any(k in h for h in history)
        ),
        None,
    )
    if length_key:
        ax_l.plot(steps, [h.get(length_key) for h in history if "reward" in h])
    ax_l.set_xlabel("step")
    ax_l.set_title("longitud media de la respuesta (tokens)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", default="rlm/data/test.jsonl", help="test JSONL")
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument(
        "--adapters",
        nargs="+",
        default=["base=none"],
        help="name=path pairs; use 'none' for the bare base model",
    )
    parser.add_argument("--n-examples", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--out", default="reports/phase1_eval.json")
    parser.add_argument("--history", default=None, help="trainer_state.json to plot")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.history:
        target = out.with_name(Path(args.history).parent.name + "_curves.png")
        plot_history(Path(args.history), target)
        print(f"curves -> {target}")
        return

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines()]
    if args.n_examples:
        rows = rows[: args.n_examples]
    results = {}
    for pair in args.adapters:
        name, path = pair.split("=", 1)
        evaluated = evaluate_model(
            args.model,
            None if path == "none" else path,
            rows,
            args.max_new_tokens,
            args.batch_size,
        )
        results[name] = {"summary": summarize(evaluated), "rows": evaluated}
        print(
            f"{name:>8}: pass@1 = {results[name]['summary']['overall']['pass@1']:.3f} "
            f"on {len(evaluated)} problems"
        )

    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    plot_pass1(results, out.with_suffix(".png"))
    print(f"details -> {out}\nchart -> {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
