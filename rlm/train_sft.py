"""Phase 1, step 2: cold-start supervised fine-tuning on verified reasoning traces.

This is the "SFT round 1" box of the DeepSeek pipeline. The input is the JSONL produced
by ``rlm/distill.py``: problems from your domain with a teacher-generated reasoning trace
that *passed your verifier*. The output is a LoRA adapter that already speaks the
``<think>…</think><answer>…</answer>`` format before we ever run GRPO.

Run::

    uv run python -m rlm.train_sft --data rlm/data/sft_traces.jsonl --output rlm/weights/sft_lora

What is decided for you: the trainer (``trl.SFTTrainer``), LoRA, the conversational
format (``prompt`` + ``completion`` columns, so that the loss is computed only on the
assistant turn). What you decide: the data, the base model, epochs, learning rate,
sequence length. Write down in EXPERIMENTS.md why you chose them.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path

from datasets import Dataset

from rlm.data import build_prompt


def cap_traces(
    rows: list[dict], max_per_problem: int | None, max_per_family: int | None, seed: int = 0
) -> list[dict]:
    """Keep at most ``max_per_problem`` traces per question and ``max_per_family`` per family.

    The teacher solves the easy families almost every time, so without a cap they dominate
    the SFT set (~260 traces each against ~90 for irpf_rental). Problems are filled one trace
    at a time, so a family cap keeps as many distinct problems as possible.
    """
    rng = random.Random(seed)
    rows = rows[:]
    rng.shuffle(rows)
    by_problem: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if max_per_problem is None or len(by_problem[row["question"]]) < max_per_problem:
            by_problem[row["question"]].append(row)
    by_family: dict[str, list[list[dict]]] = defaultdict(list)
    for traces in by_problem.values():
        by_family[traces[0].get("family", "control")].append(traces)
    kept = []
    for problems in by_family.values():
        family_kept = []
        for round_ in range(max(len(t) for t in problems)):
            family_kept += [t[round_] for t in problems if round_ < len(t)]
        kept += family_kept[:max_per_family] if max_per_family else family_kept
    rng.shuffle(kept)
    return kept


def load_sft_dataset(
    paths: str | Path | list[str | Path],
    max_per_problem: int | None = None,
    max_per_family: int | None = None,
):
    """Turn distilled traces into TRL's prompt/completion conversational format.

    Expected JSONL fields: ``question``, ``trace`` (the full ``<think>…</think><answer>…</answer>``
    text) and ``answer``. Only traces marked ``verified: true`` are used. Several files (the
    main distillation, targeted passes, rewritten privileged traces) are concatenated; their
    extra fields differ, so only what SFT needs is kept. Mentions of the teacher's rule sheet
    are scrubbed (``distill.scrub_leaks``), all-lowercase traces are recapitalised
    (``distill.recapitalize``) and traces that still cite the sheet are dropped.
    """
    from rlm.distill import RULES_LEAK, read_traces, recapitalize, scrub_leaks

    if not isinstance(paths, list):
        paths = [paths]
    rows, scrubbed, dropped = [], 0, 0
    for path in paths:
        for t in read_traces(Path(path)):
            if not t.get("verified", True):
                continue
            trace = scrub_leaks(t["trace"])
            scrubbed += trace != t["trace"]
            trace = recapitalize(trace)
            if RULES_LEAK.search(trace):
                dropped += 1
                continue
            rows.append(
                {"question": t["question"], "trace": trace, "family": t.get("family", "control")}
            )
    print(
        f"{len(rows)} verified traces; {scrubbed} scrubbed of rule-sheet mentions, {dropped} "
        "dropped because they still cite it"
    )
    if max_per_problem or max_per_family:
        rows = cap_traces(rows, max_per_problem, max_per_family)
        print(f"per family after capping: {dict(Counter(r.get('family') for r in rows))}")
    dataset = Dataset.from_list(rows)
    return dataset.map(
        lambda ex: {
            "prompt": build_prompt(ex["question"]),
            "completion": [{"role": "assistant", "content": ex["trace"]}],
        },
        remove_columns=dataset.column_names,
    )


def train(args: argparse.Namespace) -> None:
    import torch
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    dataset = load_sft_dataset(args.data, args.max_per_problem, args.max_per_family)
    print(f"{len(dataset)} verified traces loaded from {args.data}")

    peft_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=2 * args.lora_rank,
        lora_dropout=0.05,
        target_modules="all-linear",
        task_type="CAUSAL_LM",
    )
    config = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        max_length=args.max_length,
        bf16=torch.cuda.is_available(),
        use_cpu=not torch.cuda.is_available(),
        gradient_checkpointing=True,
        logging_steps=10,
        save_strategy="epoch",
        report_to="none",
        model_init_kwargs={"dtype": torch.bfloat16 if torch.cuda.is_available() else torch.float32},
        # Tu turno: consider `packing=True` for throughput, `assistant_only_loss=True` if your
        # chat template supports it, and a small eval split to watch for over-fitting.
    )
    trainer = SFTTrainer(
        model=args.model,
        args=config,
        train_dataset=dataset,
        peft_config=peft_config,
    )
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(args.output)
    print(f"adapter saved to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data",
        nargs="+",
        required=True,
        help="one or more JSONL files with question / trace / answer / verified",
    )
    parser.add_argument(
        "--max-per-problem", type=int, default=None, help="cap traces of the same question"
    )
    parser.add_argument(
        "--max-per-family", type=int, default=None, help="cap traces of each problem family"
    )
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--output", default="rlm/weights/sft_lora")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--resume-from-checkpoint", default=None, help="checkpoint-XXX folder")
    train(parser.parse_args())


if __name__ == "__main__":
    main()
