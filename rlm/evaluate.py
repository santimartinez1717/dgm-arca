"""Phase 1 evaluation: pass@1 of base vs SFT vs GRPO on a held-out set, plus training curves.

Run::

    uv run python -m rlm.evaluate --data rlm/data/test.jsonl \
        --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora

    uv run python -m rlm.evaluate --data rlm/data/test_ood.jsonl \
        --out reports/fase1/phase1_ood.json \
        --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora

It writes ``reports/fase1/phase1_eval.json`` with per-example verdicts (so you can do the failure
analysis), pass@1 overall and per family, and ``reports/fase1/phase1_pass1.png`` with the bar chart.
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


# Panels of the GRPO curves: (title, log key, scale applied to the value).
HISTORY_PANELS = [
    ("Formato", "rewards/format_reward/mean", 1.0),
    ("Exactitud", "rewards/euro_accuracy_reward/mean", 1.0),
    # The third reward of each run: the breakdown reward (GRPO 1) or the process reward (GRPO 2).
    ("Tercera recompensa", "rewards/domain_reward/mean|rewards/process_reward/mean", 1.0),
    ("Respuestas cortadas (%)", "completions/clipped_ratio", 100.0),
    ("Longitud media (tokens)", "completions/mean_length", 1.0),
]
# First two slots of the reference categorical palette (fixed order, not cycled).
RUN_COLORS = ["#2a78d6", "#eb6834"]


def _rolling(values: list[float], window: int) -> list[float]:
    out = []
    for i in range(len(values)):
        if i < window - 1:  # a partial window is a few problems, i.e. noise
            out.append(float("nan"))
            continue
        chunk = [v for v in values[i - window + 1 : i + 1] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else float("nan"))
    return out


def plot_history(
    trainer_state: Path,
    path: Path,
    compare: dict[str, Path] | None = None,
    window: int = 25,
    name: str = "GRPO con recompensa del dominio",
    mark: int | None = None,
) -> None:
    """GRPO curves from ``trainer_state.json``: one panel per metric, moving averages.

    Each step is a single problem, so per-step values are mostly noise; the curves show a
    ``window``-step moving average. ``compare`` adds other runs (name -> trainer_state.json)
    on the same panels, e.g. an ablation. ``mark`` draws a vertical line at that step (e.g.
    where the hints stop).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs = {name: trainer_state, **(compare or {})}
    fig, axes = plt.subplots(1, len(HISTORY_PANELS), figsize=(17, 3.6), sharex=True)
    for color, (name, state_path) in zip(RUN_COLORS, runs.items(), strict=False):
        log = json.loads(Path(state_path).read_text())["log_history"]
        history = [h for h in log if "reward" in h]
        steps = [h["step"] for h in history]
        for ax, (_, key, scale) in zip(axes, HISTORY_PANELS, strict=True):
            keys = key.split("|")
            raw = [next((h[k] * scale for k in keys if k in h), None) for h in history]
            ax.plot(steps, _rolling(raw, window), color=color, linewidth=2, label=name)
    for ax, (title, _, _) in zip(axes, HISTORY_PANELS, strict=True):
        ax.set_title(title, fontsize=10, loc="left", color="#0b0b0b")
        ax.set_xlabel("paso", color="#52514e")
        ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
        ax.tick_params(colors="#52514e", labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c3c2b7")
        if mark:
            ax.axvline(mark, color="#8a8984", linewidth=1, linestyle="--")
    if len(runs) > 1:
        axes[0].legend(frameon=False, fontsize=8, labelcolor="#0b0b0b")
    fig.suptitle(
        f"GRPO, media móvil de {window} pasos", x=0.01, ha="left", fontsize=11, color="#0b0b0b"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="#fcfcfb")


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
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--out", default="reports/fase1/phase1_eval.json")
    parser.add_argument("--history", default=None, help="trainer_state.json to plot")
    parser.add_argument("--name", default="GRPO con recompensa del dominio", help="--history run")
    parser.add_argument("--mark", type=int, default=None, help="--history: vertical line at step")
    parser.add_argument(
        "--compare",
        nargs="*",
        default=[],
        help="with --history: name=trainer_state.json pairs drawn on the same panels",
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.history:
        target = out.with_name(Path(args.history).parent.name + "_curves.png")
        compare = dict(pair.split("=", 1) for pair in args.compare)
        plot_history(
            Path(args.history),
            target,
            {k: Path(v) for k, v in compare.items()},
            name=args.name,
            mark=args.mark,
        )
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
