"""SFT of a LoRA on the agent's accepted traces (issue 18, "cerrar el círculo").

Input: ``agent.collect_traces`` output, one example per generation, with the prompt already
rendered by the model's chat template (system prompt, tool definitions, anchored case file,
conversation) and the agent's raw output as the completion. TRL computes the loss on the
completion only. ``rlm/train_sft.py`` is not reused: it builds single-turn prompts for the
phase-1 ``<think>/<answer>`` format, and here every example is one turn of a tool-using loop.

An example longer than ``--max-length`` is dropped, not truncated: TRL cuts from the end, which
would remove the completion the loss is computed on. The memory settings are the ones that fit
the 17 GB MIG for Qwen3-1.7B (CLAUDE.md): batch 1, gradient accumulation 8, checkpointing::

    uv run python -m agent.train_traces --data outputs/agent_traces/sft.jsonl \\
        --output rlm/weights/agent_sft_lora
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path


def load_examples(path: Path, tokenizer, max_length: int, seed: int = 0) -> tuple[list, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    kept, lengths = [], []
    for r in rows:
        n = len(tokenizer(r["prompt"] + r["completion"], add_special_tokens=False)["input_ids"])
        lengths.append(n)
        if n <= max_length:
            # TRL appends the EOS token itself: drop the one collect_traces wrote.
            completion = r["completion"]
            if tokenizer.eos_token and completion.endswith(tokenizer.eos_token):
                completion = completion[: -len(tokenizer.eos_token)]
            kept.append({"prompt": r["prompt"], "completion": completion})
    random.Random(seed).shuffle(kept)
    stats = {
        "examples": len(rows),
        "kept": len(kept),
        "dropped_too_long": len(rows) - len(kept),
        "max_tokens": max(lengths) if lengths else 0,
        "mean_tokens": round(sum(lengths) / len(lengths)) if lengths else 0,
        "runs": len({r["id"] for r in rows}),
        "per_category": dict(Counter(r["category"] for r in rows)),
    }
    return kept, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default="outputs/agent_traces/sft.jsonl")
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--output", default="rlm/weights/agent_sft_lora")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--lora-rank", type=int, default=16)
    args = parser.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    examples, stats = load_examples(Path(args.data), tokenizer, args.max_length)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    if not examples:
        raise SystemExit("no examples fit in --max-length")
    if torch.cuda.is_available():
        torch.backends.cuda.enable_cudnn_sdp(False)  # CLAUDE.md: cuDNN attention runs out of memory
    config = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        max_length=args.max_length,
        completion_only_loss=True,
        bf16=torch.cuda.is_available(),
        use_cpu=not torch.cuda.is_available(),
        gradient_checkpointing=True,
        logging_steps=5,
        save_strategy="epoch",
        report_to="none",
        model_init_kwargs={"dtype": torch.bfloat16 if torch.cuda.is_available() else torch.float32},
    )
    trainer = SFTTrainer(
        model=args.model,
        args=config,
        train_dataset=Dataset.from_list(examples),
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=args.lora_rank,
            lora_alpha=2 * args.lora_rank,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
    )
    trainer.train()
    trainer.save_model(args.output)
    if torch.cuda.is_available():
        print(f"PEAK_GPU_GB {torch.cuda.max_memory_reserved() / 2**30:.1f}", flush=True)
    Path(args.output, "data_stats.json").write_text(json.dumps(stats, indent=1), "utf-8")
    print(f"adapter saved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
