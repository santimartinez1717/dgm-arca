"""Batched generation shared by distillation (``distill.py``) and evaluation (``evaluate.py``).

Generating one prompt at a time wastes the GPU: most of the time goes to reading the weights,
not to arithmetic. Batching several prompts (left-padded, as decoder-only models need) is the
single biggest speed-up available without adding vLLM to the project.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from rlm.data import R1_ZERO_SYSTEM_PROMPT, build_prompt


@dataclass
class Generator:
    """A causal LM (optionally with a LoRA adapter) ready for batched chat generation."""

    model_name: str
    adapter_path: str | None = None
    enable_thinking: bool | None = None
    system_prompt: str = R1_ZERO_SYSTEM_PROMPT

    def load(self) -> Generator:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, padding_side="left")
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            self.model_name, dtype=dtype, device_map=device
        )
        if self.adapter_path:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.adapter_path)
        self.model = model.eval()
        return self

    def _chat_text(self, question: str) -> str:
        kwargs = {}
        if self.enable_thinking is not None:
            # Qwen3 templates accept this switch; other templates ignore unknown kwargs.
            kwargs["enable_thinking"] = self.enable_thinking
        return self.tokenizer.apply_chat_template(
            build_prompt(question, self.system_prompt),
            tokenize=False,
            add_generation_prompt=True,
            **kwargs,
        )

    def generate(
        self,
        questions: Sequence[str],
        num_return_sequences: int = 1,
        max_new_tokens: int = 1024,
        temperature: float = 0.0,
        top_p: float = 0.95,
    ) -> list[list[tuple[str, int, bool]]]:
        """For each question, ``num_return_sequences`` tuples ``(text, n_tokens, truncated)``.

        ``temperature=0`` means greedy decoding (what pass@1 evaluation uses).
        """
        import torch

        texts = [self._chat_text(q) for q in questions]
        inputs = self.tokenizer(texts, return_tensors="pt", padding=True).to(self.model.device)
        sampling = temperature > 0
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=sampling,
                temperature=temperature if sampling else None,
                top_p=top_p if sampling else None,
                num_return_sequences=num_return_sequences,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        new_tokens = out[:, inputs["input_ids"].shape[1] :]
        results: list[list[tuple[str, int, bool]]] = [[] for _ in questions]
        eos = self.tokenizer.eos_token_id
        pad = self.tokenizer.pad_token_id
        for row, tokens in enumerate(new_tokens):
            n = int(((tokens != pad) & (tokens != eos)).sum())
            truncated = bool(tokens[-1] not in (pad, eos))
            text = self.tokenizer.decode(tokens, skip_special_tokens=True)
            results[row // num_return_sequences].append((text, n, truncated))
        return results


def batched(items: Sequence, size: int) -> Iterator[Sequence]:
    """Consecutive slices of ``items`` of length ``size`` (the last one may be shorter)."""
    for start in range(0, len(items), size):
        yield items[start : start + size]
