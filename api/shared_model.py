"""One copy of each base model for every phase of the API, with its LoRA adapters on top.

Phase 1 (Qwen3-1.7B + the GRPO 2 adapter) and phase 2 (Qwen3-1.7B as is) used to load a model
each. On a 6 GB laptop GPU the two do not fit, and ``/health`` loads every phase. Here the base
model is loaded once and each request picks its adapter, or none:

- with an adapter, the output is the base model plus that adapter's LoRA update, exactly how
  ``rlm/evaluate.py`` measured pass@1 (unmerged PEFT model);
- with ``adapter=None``, PEFT's ``disable_adapter()`` skips every LoRA branch and the forward
  pass is the base model's.

Every call that touches a model runs on one thread. Switching adapters is global state, two
generations at once do not fit on a laptop GPU anyway, and on Apple GPUs (MPS) a model loaded
in one thread can hang when another thread generates with it.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_THREAD_NAME = "arca-model"
_MODEL_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix=_THREAD_NAME)
_MODELS: dict[str, SharedModel] = {}


def on_model_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run ``fn`` on the model thread and wait for it (directly if already there)."""
    if threading.current_thread().name.startswith(_THREAD_NAME):
        return fn(*args, **kwargs)
    return _MODEL_THREAD.submit(fn, *args, **kwargs).result()


@dataclass
class SharedModel:
    model_id: str
    tokenizer: Any
    model: Any  # the base model, or a PeftModel around it once an adapter is added
    device: str
    adapters: dict[str, str] = field(default_factory=dict)  # resolved path -> adapter name

    def add_adapter(self, path: str) -> str:
        """Load a LoRA adapter (once) on top of the base model; return its name."""
        return on_model_thread(self._add_adapter, path)

    def _add_adapter(self, path: str) -> str:
        key = str(Path(path).resolve())
        if key in self.adapters:
            return self.adapters[key]
        from peft import PeftModel

        name = f"adapter{len(self.adapters)}"
        if isinstance(self.model, PeftModel):
            self.model.load_adapter(path, adapter_name=name)
        else:
            self.model = PeftModel.from_pretrained(self.model, path, adapter_name=name)
        self.model.eval()
        self.adapters[key] = name
        print(f"{self.model_id}: adapter {path} loaded as {name}", file=sys.stderr, flush=True)
        return name

    def generate(self, adapter: str | None, **kwargs: Any) -> Any:
        """``model.generate(**kwargs)`` with that adapter active, or the bare base model."""
        return on_model_thread(self._generate, adapter, kwargs)

    def _generate(self, adapter: str | None, kwargs: dict) -> Any:
        import contextlib

        import torch
        from peft import PeftModel

        if not isinstance(self.model, PeftModel):
            if adapter is not None:
                raise ValueError(f"{self.model_id} has no adapter {adapter}")
            context = contextlib.nullcontext()
        elif adapter is None:
            context = self.model.disable_adapter()
        else:
            self.model.set_adapter(adapter)
            context = contextlib.nullcontext()
        with context, torch.no_grad():
            return self.model.generate(**kwargs)


def get_model(model_id: str) -> SharedModel:
    """The shared copy of ``model_id``, loaded the first time it is asked for."""
    return on_model_thread(_get_model, model_id)


def _get_model(model_id: str) -> SharedModel:
    if model_id in _MODELS:
        return _MODELS[model_id]
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    print(f"loading {model_id} on {device} in {dtype}", file=sys.stderr, flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype, device_map=device)
    _MODELS[model_id] = SharedModel(model_id, tokenizer, model.eval(), device)
    return _MODELS[model_id]
