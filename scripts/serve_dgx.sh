#!/usr/bin/env bash
# Sirve la API en la GPU de la DGX con el modelo final de la fase 1 (GRPO 2, base + LoRA, el
# mismo que da el 47,3 % del test) y la deja calentada: la primera petición carga el modelo,
# así que la hacemos aquí y no la sufre el primero que llame.
#
#     bash scripts/serve_dgx.sh          # en una terminal de code-server; ngrok en otra
#
# Mientras corre ocupa unos 4-5 GB de la GPU: no lanzar a la vez evaluaciones ni entrenamientos.
# Se para con Ctrl+C. Log en logs/serve_dgx.log.
set -euo pipefail
cd "$(dirname "$0")/.."
source smoke/dgx_env.sh >/dev/null

if pgrep -af "python -m (rlm|tool_use|rag|agent)" >/dev/null; then
    echo "Ojo: hay otro proceso del proyecto usando la GPU:"
    pgrep -af "python -m (rlm|tool_use|rag|agent)"
    echo "Con los dos a la vez la MIG de 17 GB se puede quedar corta."
fi

export ARCA_RLM_ADAPTER="${ARCA_RLM_ADAPTER:-rlm/weights/grpo2_lora}"
PORT="${ARCA_API_PORT:-8000}"
mkdir -p logs

uv run --env-file .env arca-api > >(tee logs/serve_dgx.log) 2>&1 &
API=$!
trap 'kill $API 2>/dev/null' EXIT

echo "Esperando a que la API responda en el puerto $PORT..."
until curl -s "http://localhost:$PORT/health" >/dev/null; do sleep 2; done
echo "Calentando el modelo con una pregunta corta (carga el GRPO 2 en la GPU)..."
curl -sS -X POST "http://localhost:$PORT/reasoning" -H "Content-Type: application/json" \
    -d '{"question": "Un piso de segunda mano cuesta 100.000 €. El ITP es del 10 % y la notaría 1.000 €. ¿Cuál es el desembolso total? Da el resultado en euros, con dos decimales.", "expected_answer": "111000.00"}' \
    | python3 -c "import json,sys; r=json.load(sys.stdin); print('respuesta', r['answer'], '· correcta:', r['verifier']['is_correct'], '·', r['tokens_generated'], 'tokens')"
echo
echo "API lista en http://localhost:$PORT. Ahora, en otra terminal, ngrok (ver docs/servir_api.md)."
wait $API
