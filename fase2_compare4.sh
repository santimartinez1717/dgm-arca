# v4 of the domain variant: first on 10 fresh problems per family (11th to 20th, never used to
# tune the tools), then on the same 60 as v1-v3 for the paired comparison.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\."; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== domain v4 ($(git log --oneline -1 | cut -c1-7)), problemas nuevos ($(date +%H:%M))"
uv run python -m tool_use.phase1_compare --variants domain --per-family 10 --skip-per-family 10 \
    --resume --out reports/phase2_vs_phase1_domain_v4_nuevos.json
echo "=== domain v4, los 60 de siempre ($(date +%H:%M))"
uv run python -m tool_use.phase1_compare --variants domain --per-family 10 --resume \
    --out reports/phase2_vs_phase1_domain_v4.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
