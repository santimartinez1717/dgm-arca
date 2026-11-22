"""Upload the phase 1 LoRA adapters to Hugging Face Hub (the DGX has no backups).

Only the final adapter files go up (weights, config, tokenizer, chat template), not the
intermediate checkpoints, logged completions or training data. Each repo gets a short model
card. Needs ``HF_TOKEN`` with write access in ``.env`` (loaded by ``smoke/dgx_env.sh``).

Run::

    source smoke/dgx_env.sh
    uv run python -m rlm.upload_hub --private
"""

from __future__ import annotations

import argparse
from pathlib import Path

ADAPTERS = {
    "umbral-qwen3-1.7b-grpo2-lora": {
        "path": "rlm/weights/grpo2_lora",
        "title": "GRPO 2 (modelo final de la fase 1)",
        "how": "GRPO de 400 pasos desde el SFT 3: 2048 tokens, recompensa de formato, exactitud "
        "y recompensa por pasos (0,5 / 2,0 / 0,5), learning rate 2e-5 constante, pistas en "
        "irpf_rental y cash_on_cash los 250 primeros pasos.",
        "score": "47,3 %",
    },
    "umbral-qwen3-1.7b-sft3-lora": {
        "path": "rlm/weights/sft3_lora",
        "title": "SFT 3 (punto de partida del GRPO 2)",
        "how": "SFT sobre 857 trazas verificadas de Qwen3-4B (con hoja de reglas, y con la clave "
        "del motor de reglas reescrita sin mencionarla en los problemas que no resolvía).",
        "score": "40,3 %",
    },
    "umbral-qwen3-1.7b-grpo1-lora": {
        "path": "rlm/weights/final_rlm_lora",
        "title": "GRPO 1 (primera ronda)",
        "how": "GRPO de 400 pasos desde el SFT 1: 1536 tokens, recompensa de desglose, "
        "learning rate 5e-6.",
        "score": "38,3 %",
    },
}
FILES = [
    "adapter_config.json",
    "adapter_model.safetensors",
    "chat_template.jinja",
    "tokenizer.json",
    "tokenizer_config.json",
]


def model_card(name: str, info: dict) -> str:
    return f"""---
base_model: Qwen/Qwen3-1.7B
library_name: peft
language: [es]
tags: [lora, grpo, real-estate, reasoning]
---

# {name}

{info["title"]}. Adaptador LoRA (r=16, todas las capas lineales) sobre **Qwen/Qwen3-1.7B**,
del equipo Umbral (práctica ARCA, MGD · ICAI 2026-2027): analista de inversión inmobiliaria
para alquilar en España (coste de adquisición, rentabilidad neta, renta máxima legal, IRPF del
alquiler, flujo de caja sobre capital propio y precio máximo).

**Entrenamiento.** {info["how"]}

**Resultado.** pass@1 en el test propio (300 problemas, 6 familias, 2048 tokens nuevos):
**{info["score"]}**. Detalle en el EXPERIMENTS.md del repositorio del equipo.

Formato de respuesta: `<think>…</think><answer>…</answer>`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="repo names to upload")
    args = parser.parse_args()

    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi()
    user = api.whoami()["name"]
    for name, info in ADAPTERS.items():
        if args.only and name not in args.only:
            continue
        folder = Path(info["path"])
        repo = f"{user}/{name}"
        api.create_repo(repo, private=args.private, exist_ok=True)
        ops = [
            CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(folder / f))
            for f in FILES
            if (folder / f).exists()
        ]
        ops.append(
            CommitOperationAdd(
                path_in_repo="README.md", path_or_fileobj=model_card(name, info).encode()
            )
        )
        api.create_commit(repo, operations=ops, commit_message=f"Adaptador {info['title']}")
        print(f"{repo}: {len(ops)} files -> https://huggingface.co/{repo}", flush=True)


if __name__ == "__main__":
    main()
