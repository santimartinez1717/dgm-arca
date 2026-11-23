# Bench v12: answer "in the language they wrote in (Spanish if...)" (CHAIN_HINT) and stressed_zone looked up by
# save_to_portfolio when the user does not say. Base model, same 40 cases.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\.|arca-api"; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Banco: Qwen3-1.7B base, sin thinking, $(git log --oneline -1 | cut -c1-7) + cambios sin commitear ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/fase2/phase2_bench_base_v12.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
