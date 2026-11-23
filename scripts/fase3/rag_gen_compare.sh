#!/usr/bin/env bash
# Fase 3: generación con citas en las 57 preguntas (51 + 6 sin respuesta), tres generadores.
# Recuperación fija: troceado semántico p90, híbrido λ=0,2, top-5 (rag/generate.py).
#   base        Qwen3-1.7B sin pensamiento, 512 tokens
#   base_think  Qwen3-1.7B con pensamiento, 1536 tokens
#   rlm_think   modelo de la fase 1 (GRPO 2) con pensamiento, 1536 tokens
# Unos 27 + 60 + 60 minutos en la MIG. Uso:
#   source smoke/dgx_env.sh
#   PYTHONUNBUFFERED=1 nohup bash scripts/fase3/rag_gen_compare.sh > logs/fase3/rag_gen_compare.log 2>&1 &
set -euo pipefail
RLM_ADAPTER=${RLM_ADAPTER:-/home/202201278/clusters/dgx/dgm-arca/rlm/weights/grpo2_lora}

echo "== base $(date +%H:%M)"
uv run python -m rag.eval_generation --name base

echo "== base_think $(date +%H:%M)"
ARCA_RAG_THINKING=1 ARCA_RAG_MAX_NEW_TOKENS=1536 \
    uv run python -m rag.eval_generation --name base_think

echo "== rlm_think $(date +%H:%M)"
ARCA_RAG_GENERATOR_ADAPTER=$RLM_ADAPTER ARCA_RAG_THINKING=1 ARCA_RAG_MAX_NEW_TOKENS=1536 \
    uv run python -m rag.eval_generation --name rlm_think

echo "== done $(date +%H:%M)"
