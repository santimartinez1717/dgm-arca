"""Inference for the phase-1 reasoning model, and the object behind ``POST /reasoning``.

``ReasoningModel`` loads a base model plus (optionally) your LoRA adapter, generates
with the R1-Zero system prompt and splits the output into thinking / answer. When the
request carries the expected answer, it also runs the verifier and returns the verdict.

Configuration comes from environment variables so that the same code runs on your
laptop, on the DGX and inside Docker:

* ``ARCA_RLM_BASE_MODEL``  base model id (default ``Qwen/Qwen3-0.6B``)
* ``ARCA_RLM_ADAPTER``     path to your trained LoRA adapter (e.g. ``rlm/weights/final_rlm_lora``)
* ``ARCA_RLM_VERIFIER``    ``numeric`` (default), ``exact_match`` or ``euro`` (our domain)

Try it from the command line::

    ARCA_RLM_ADAPTER=rlm/weights/smoke_lora \\
        uv run python -m rlm.inference "If 5x - 3 = 12, what is 5x + 3?"
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from api.schemas import ReasoningResponse, VerifierVerdict
from rlm.data import build_prompt
from rlm.rewards import extract_answer, has_valid_format
from rlm.verifier import EuroVerifier, ExactMatchVerifier, NumericVerifier, Verifier

VERIFIERS: dict[str, type[Verifier]] = {
    "numeric": NumericVerifier,
    "exact_match": ExactMatchVerifier,
    "euro": EuroVerifier,
}

THINK_PATTERN = re.compile(r"<think>(?P<think>.*?)</think>", re.DOTALL)


def split_thinking(raw: str) -> tuple[str, str]:
    """Return (thinking, answer) from a raw completion, tolerating imperfect formats."""
    match = THINK_PATTERN.search(raw)
    thinking = match.group("think").strip() if match else ""
    answer = extract_answer(raw)
    if answer is None:
        # No <answer> block: fall back to whatever comes after </think>, or the whole text.
        answer = raw.split("</think>")[-1].strip() if match else raw.strip()
    return thinking, answer


def _base_model_from_adapter(adapter: str) -> str:
    """PEFT stores the base model id in adapter_config.json; use it unless overridden."""
    config = Path(adapter) / "adapter_config.json"
    if config.exists():
        base = json.loads(config.read_text()).get("base_model_name_or_path")
        if base:
            return base
    return "Qwen/Qwen3-0.6B"


# Every call that touches the model runs on this one thread. FastAPI serves each request from a
# different worker thread, and on Apple GPUs (MPS) a model loaded in one thread can hang when a
# second thread generates with it: the first request answered and the second never did. One
# worker also queues concurrent requests, which a laptop GPU could not hold in memory anyway.
_MODEL_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase1-model")


@dataclass
class ReasoningModel:
    base_model: str
    adapter_path: str | None = None
    verifier_name: str = "numeric"
    # A merged, quantized model converted with mlx_lm (rlm/weights/grpo2_mlx_8bit): on a Mac,
    # 8 bits fit in 8 GB of shared memory and generate several times faster than PyTorch.
    mlx_path: str | None = None

    @classmethod
    def from_env(cls) -> ReasoningModel:
        mlx_path = os.environ.get("ARCA_RLM_MLX") or None
        if mlx_path:
            if not Path(mlx_path).exists():
                raise FileNotFoundError(f"ARCA_RLM_MLX points to a missing folder: {mlx_path}")
            return cls(
                base_model=mlx_path,
                mlx_path=mlx_path,
                verifier_name=os.environ.get("ARCA_RLM_VERIFIER", "numeric"),
            )
        adapter = os.environ.get("ARCA_RLM_ADAPTER") or None
        if adapter is None:
            raise NotImplementedError(
                "Phase 1 is not wired yet: set ARCA_RLM_ADAPTER to the folder of your trained "
                "LoRA adapter (see rlm/README.md). For a quick check you can point it to the "
                "adapter produced by the smoke test, rlm/weights/smoke_lora."
            )
        if not Path(adapter).exists():
            raise FileNotFoundError(f"ARCA_RLM_ADAPTER points to a missing folder: {adapter}")
        base_model = os.environ.get("ARCA_RLM_BASE_MODEL") or _base_model_from_adapter(adapter)
        return cls(
            base_model=base_model,
            adapter_path=adapter,
            verifier_name=os.environ.get("ARCA_RLM_VERIFIER", "numeric"),
        )

    def load(self) -> None:
        _MODEL_THREAD.submit(self._load).result()

    def _load(self) -> None:
        self.verifier = VERIFIERS[self.verifier_name]()
        if self.mlx_path:
            from mlx_lm import load

            self.model, self.tokenizer = load(self.mlx_path)
            print(f"phase 1 model on MLX from {self.mlx_path}", file=sys.stderr, flush=True)
            return
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # CUDA on the DGX; on a Mac, the Apple GPU (MPS) in bfloat16: half the memory of float32
        # on CPU (~3.5 GB for 1.7B instead of ~7 GB) and much faster.
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        dtype = torch.float32 if device == "cpu" else torch.bfloat16
        print(f"phase 1 model on {device} in {dtype}", file=sys.stderr, flush=True)
        self.tokenizer = AutoTokenizer.from_pretrained(self.base_model)
        model = AutoModelForCausalLM.from_pretrained(
            self.base_model, dtype=dtype, device_map=device
        )
        if self.adapter_path:
            # Merged into the base weights: the API never trains, and the unmerged LoRA adds
            # two small matmuls per linear layer to every generated token.
            model = PeftModel.from_pretrained(model, self.adapter_path).merge_and_unload()
        self.model = model.eval()

    def generate(self, question: str, max_new_tokens: int = 2048) -> tuple[str, int]:
        """Return the raw completion and the number of generated tokens."""
        return _MODEL_THREAD.submit(self._generate, question, max_new_tokens).result()

    def _generate(self, question: str, max_new_tokens: int) -> tuple[str, int]:
        text = self.tokenizer.apply_chat_template(
            build_prompt(question), tokenize=False, add_generation_prompt=True
        )
        if self.mlx_path:
            return self._generate_mlx(text, max_new_tokens)
        import torch

        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        started = time.perf_counter()
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                # Greedy, like rlm/evaluate.py: the API must agree with the reported pass@1.
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
            )
        new_tokens = out[0, inputs["input_ids"].shape[1] :]
        seconds = time.perf_counter() - started
        print(
            f"generated {new_tokens.numel()} tokens in {seconds:.1f}s "
            f"({new_tokens.numel() / seconds:.1f} tokens/s)",
            file=sys.stderr,
            flush=True,
        )
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True), int(new_tokens.numel())

    def _generate_mlx(self, text: str, max_new_tokens: int) -> tuple[str, int]:
        from mlx_lm import stream_generate

        started = time.perf_counter()
        pieces, n_tokens = [], 0
        # No sampler: mlx_lm decodes greedily, like rlm/evaluate.py.
        for response in stream_generate(
            self.model, self.tokenizer, text, max_tokens=max_new_tokens
        ):
            pieces.append(response.text)
            n_tokens = response.generation_tokens
        seconds = time.perf_counter() - started
        print(
            f"generated {n_tokens} tokens in {seconds:.1f}s ({n_tokens / seconds:.1f} tokens/s)",
            file=sys.stderr,
            flush=True,
        )
        return "".join(pieces), n_tokens

    def answer(
        self, question: str, expected_answer: str | None = None, max_new_tokens: int = 2048
    ) -> ReasoningResponse:
        raw, n_tokens = self.generate(question, max_new_tokens)
        thinking, answer = split_thinking(raw)
        verdict = None
        if expected_answer is not None:
            result = self.verifier.verify(raw, expected_answer)
            verdict = VerifierVerdict(
                is_correct=result.is_correct,
                predicted=result.predicted,
                expected=result.expected,
                detail=result.detail,
            )
        return ReasoningResponse(
            thinking=thinking,
            answer=answer,
            raw=raw,
            has_valid_format=has_valid_format(raw),
            verifier=verdict,
            tokens_generated=n_tokens,
            model=f"mlx:{Path(self.mlx_path).name}"
            if self.mlx_path
            else f"{self.base_model}+{Path(self.adapter_path).name}"
            if self.adapter_path
            else self.base_model,
        )


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "If 5x - 3 = 12, what is the value of 5x + 3?"
    rlm = ReasoningModel.from_env()
    rlm.load()
    print(rlm.answer(question, expected_answer=None).model_dump_json(indent=2))
