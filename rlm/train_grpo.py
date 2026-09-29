"""Phase 1, step 3: reinforcement learning with verifiable rewards using GRPO.

Starting point: the SFT adapter from ``train_sft.py`` (or the base model, if you want to
reproduce the R1-Zero experiment and see what happens without cold start). Output: your
final reasoning model, ``rlm/weights/final_rlm_lora``.

Run::

    uv run python -m rlm.train_grpo --data rlm/data/train.jsonl --init-adapter rlm/weights/sft_lora

The smoke test (``smoke/smoke_grpo.py``) is the minimal version of this script on GSM8K.
Here you add what makes it *yours*:

1. Your domain dataset (``rlm/data.py::load_domain_dataset``) and your verifier.
2. A third, domain-specific reward (``domain_reward`` below). Think about what a good
   answer looks like for your user beyond being correct: language, units, length,
   citing a source, respecting a schema. Justify it in EXPERIMENTS.md and, if you use
   ``reward_weights``, justify those too.
3. The hyper-parameters. Group size, completion length, learning rate and KL
   coefficient all change what the model learns. Change one thing at a time and log it.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from rlm.data import load_gsm8k, load_mixed_dataset
from rlm.realestate_rewards import breakdown_reward, euro_accuracy_reward
from rlm.rewards import accuracy_reward, format_reward

GATE_ON_CORRECT = True


def domain_reward(prompts: Sequence, completions: Sequence, **kwargs) -> list[float]:
    """Our third reward, "desglose trazable" (``rlm/realestate_rewards.py``).

    0.5 for answering with the unit the question asks for (€ or %), plus 0.5 times the share
    of intermediate values of the reference solution (tax base, depreciation, rent cap…)
    that appear in the reasoning, only when the final answer is correct. Justification and
    ablation plan in ``docs/propuesta.md``.
    """
    return breakdown_reward(prompts, completions, gate_on_correct=GATE_ON_CORRECT, **kwargs)


def ungated_domain_reward(prompts: Sequence, completions: Sequence, **kwargs) -> list[float]:
    """Ablation: the checkpoint half also rewards wrong answers (a process reward)."""
    return breakdown_reward(prompts, completions, gate_on_correct=False, **kwargs)


def train(args: argparse.Namespace) -> None:
    import torch
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    if args.data == "gsm8k":
        dataset = load_gsm8k("train", n_examples=args.n_examples, seed=args.seed)
        reward_funcs = [format_reward, accuracy_reward]
    else:
        dataset = load_mixed_dataset(args.data, args.control_fraction, args.seed)
        third = ungated_domain_reward if args.ungated_breakdown else domain_reward
        reward_funcs = [format_reward, euro_accuracy_reward, third]
    print(f"{len(dataset)} training problems")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    config = GRPOConfig(
        output_dir=args.output,
        max_steps=args.steps,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.num_generations,
        gradient_accumulation_steps=args.grad_accum,
        num_generations=args.num_generations,
        max_completion_length=args.max_completion_length,
        temperature=args.temperature,
        beta=args.beta,
        epsilon=0.2,
        bf16=device == "cuda",
        gradient_checkpointing=device == "cuda",
        # Without CUDA, stay on CPU explicitly: on a Mac, accelerate would pick MPS and TRL's
        # generation mixes MPS and CPU tensors.
        use_cpu=device == "cpu",
        logging_steps=1,
        save_steps=args.save_steps,
        save_strategy="steps",
        report_to="none",
        seed=args.seed,
        log_completions=True,
        num_completions_to_print=2,
        model_init_kwargs={"dtype": torch.bfloat16 if device == "cuda" else torch.float32},
        # Accuracy dominates: format is learnt in a few dozen steps and the breakdown reward
        # must never outweigh getting the number right. Justified in EXPERIMENTS.md.
        reward_weights=args.reward_weights[: len(reward_funcs)],
    )

    if args.init_adapter:
        # Continue training the SFT adapter: load base + adapter as a trainable PeftModel.
        from peft import PeftModel
        from transformers import AutoModelForCausalLM

        base = AutoModelForCausalLM.from_pretrained(
            args.model, dtype=torch.bfloat16 if device == "cuda" else torch.float32
        )
        model = PeftModel.from_pretrained(base, args.init_adapter, is_trainable=True)
        peft_config = None
    else:
        model = args.model
        peft_config = LoraConfig(
            r=args.lora_rank,
            lora_alpha=2 * args.lora_rank,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        )

    trainer = GRPOTrainer(
        model=model,
        reward_funcs=reward_funcs,
        args=config,
        train_dataset=dataset,
        peft_config=peft_config,
    )
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(args.output)
    print(f"final adapter saved to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", default="gsm8k", help="'gsm8k' or path to your domain JSONL")
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--init-adapter", default=None, help="SFT adapter to start from")
    parser.add_argument("--output", default="rlm/weights/final_rlm_lora")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--num-generations", type=int, default=8)
    parser.add_argument("--grad-accum", type=int, default=1)
    parser.add_argument("--max-completion-length", type=int, default=768)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--beta", type=float, default=0.0, help="KL coefficient (0 disables it)")
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--n-examples", type=int, default=None)
    parser.add_argument("--save-steps", type=int, default=50)
    parser.add_argument(
        "--resume-from-checkpoint",
        default=None,
        help="path to a checkpoint-XXX folder to continue an interrupted run (24h sessions!)",
    )
    parser.add_argument(
        "--control-fraction", type=float, default=0.1, help="share of GSM8K control problems"
    )
    parser.add_argument(
        "--reward-weights",
        type=float,
        nargs="+",
        default=[0.5, 2.0, 0.5],
        help="format / accuracy / breakdown",
    )
    parser.add_argument(
        "--ungated-breakdown",
        action="store_true",
        help="ablation: breakdown reward also on wrong answers",
    )
    parser.add_argument("--seed", type=int, default=0)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
