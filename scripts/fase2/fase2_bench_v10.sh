# Bench v10: save_to_portfolio with area_m2 optional and after price and rent (the model filled
# 180 m2 from a 180,000 EUR price). Base model, same 40 cases as v9.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\.|arca-api"; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Banco: Qwen3-1.7B base, sin thinking, $(git log --oneline -1 | cut -c1-7) + cambios sin commitear ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/fase2/phase2_bench_base_v10.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
