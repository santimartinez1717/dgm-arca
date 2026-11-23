#!/usr/bin/env bash
# Fase 3, segunda tanda en la GPU (corpus definitivo, tras la corrección de versiones sin fecha):
#   1. recuperación: troceados, retrievers, λ e instrucción          (~10 min)
#   2. opción 1, recuperación: versiones de hoy / todas / por fecha  (~5 min)
#   3. generación base sobre el corpus definitivo                   (~11 min)
#   4. opción 1, generación: las 17 preguntas con fecha, RAG normal y RAG por fecha (~8 min)
# Uso (espera a que acabe el proceso de la GPU que se le pase):
#   source smoke/dgx_env.sh
#   PYTHONUNBUFFERED=1 nohup bash scripts/fase3/rag_round2.sh <PID que esperar> > logs/fase3/rag_round2.log 2>&1 &
set -euo pipefail
if [ -n "${1:-}" ]; then
    echo "waiting for PID $1 $(date +%H:%M)"
    while kill -0 "$1" 2>/dev/null; do sleep 30; done
fi

echo "== evaluate $(date +%H:%M)"
uv run python -m rag.evaluate

echo "== eval_temporal $(date +%H:%M)"
uv run python -m rag.eval_temporal

echo "== generation base $(date +%H:%M)"
uv run python -m rag.eval_generation --name base

echo "== generation temporal_hoy $(date +%H:%M)"
uv run python -m rag.eval_generation --name temporal_hoy --gold rag/gold/temporal.jsonl --unanswerable ""

echo "== generation temporal_fecha $(date +%H:%M)"
ARCA_RAG_TEMPORAL=1 uv run python -m rag.eval_generation \
    --name temporal_fecha --gold rag/gold/temporal.jsonl --unanswerable ""

echo "== done $(date +%H:%M)"
