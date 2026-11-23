#!/usr/bin/env bash
# Sirve la API en la GPU de la DGX con el modelo final de la fase 1 (GRPO 2, base + LoRA, el
# mismo que da el 47,3 % del test) y la deja calentada: llama una vez a cada endpoint
# (scripts/calentar_api.py), así que el arranque en frío no lo sufre el primero que llame.
#
#     bash scripts/serve_dgx.sh          # en una terminal de code-server; ngrok en otra
#
# Mientras corre ocupa unos 4-5 GB de la GPU: no lanzar a la vez evaluaciones ni entrenamientos.
# Se para con Ctrl+C. Log en logs/serve_dgx.log.
set -euo pipefail
cd "$(dirname "$0")/.."
# The port asked for when launching (ARCA_API_PORT=8001 bash scripts/serve_dgx.sh) wins over
# the one in .env, which dgx_env.sh loads.
REQUESTED_PORT="${ARCA_API_PORT:-}"
source smoke/dgx_env.sh >/dev/null

if pgrep -af "python -m (rlm|tool_use|rag|agent)" >/dev/null; then
    echo "Ojo: hay otro proceso del proyecto usando la GPU:"
    pgrep -af "python -m (rlm|tool_use|rag|agent)"
    echo "Con los dos a la vez la MIG de 17 GB se puede quedar corta."
fi

export ARCA_RLM_ADAPTER="${ARCA_RLM_ADAPTER:-rlm/weights/grpo2_lora}"
PORT="${REQUESTED_PORT:-${ARCA_API_PORT:-8000}}"
export ARCA_API_PORT="$PORT"

# Several sessions of the team can share a DGX node: an API of someone else on this port would
# get our warm-up calls and, through ngrok, the grader's.
if curl -s -m 3 "http://localhost:$PORT/health" >/dev/null; then
    echo "El puerto $PORT ya tiene una API (quizá la de otro compañero en este nodo)."
    echo "Usa otro: ARCA_API_PORT=8001 bash scripts/serve_dgx.sh, y ngrok http 8001."
    exit 1
fi

# Lo que no está en git y sin lo que /reasoning o /rag fallan en clase.
if [ ! -f "$ARCA_RLM_ADAPTER/adapter_config.json" ] || [ ! -f "$ARCA_RLM_ADAPTER/adapter_model.safetensors" ]; then
    echo "FALTA el adaptador GRPO 2 en $ARCA_RLM_ADAPTER: hacen falta adapter_config.json y"
    echo "adapter_model.safetensors (te los pasa Santiago, docs/servir_api.md)."
    echo "Sin él, /reasoning no arranca y /agent con brain=rlm responde con el modelo base."
fi
if [ -z "$(ls rag/corpus/boe 2>/dev/null)" ]; then
    echo "FALTA el corpus: uv run python -m rag.download_corpus (y la primera carga indexa, ~5 min)."
fi
mkdir -p logs

uv run --env-file .env arca-api > >(tee logs/serve_dgx.log) 2>&1 &
API=$!
trap 'kill $API 2>/dev/null' EXIT

echo "Esperando a que la API responda en el puerto $PORT..."
until curl -s "http://localhost:$PORT/health" >/dev/null; do sleep 2; done
echo "Calentando y comprobando todos los endpoints (la primera llamada carga cada modelo)..."
if ! uv run python scripts/calentar_api.py --url "http://localhost:$PORT" --thinking; then
    echo "Algún endpoint falla: mira logs/serve_dgx.log antes de abrir ngrok."
fi
echo
echo "API lista en http://localhost:$PORT. Ahora, en otra terminal, ngrok (ver docs/servir_api.md)."
wait $API
