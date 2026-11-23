#!/usr/bin/env bash
# Phase 4 evaluation on the DGX (issues 15 and 16): the bench under every brain and ablation,
# then the CodeAgent contrast. Resumable: if the Slurm session ends, run the same command in
# the next one and it continues from reports/fase4/*.partial.jsonl.
#
#   bash scripts/fase4/eval_agent.sh smoke   # 2 tasks, base, full: memory and time per task
#   bash scripts/fase4/eval_agent.sh json    # 24 tasks × base rlm thinking × 4 configurations
#   bash scripts/fase4/eval_agent.sh code    # 24 tasks × base thinking with the CodeAgent
#
# Launch it with nohup as the lanzar-dgx skill says, e.g.
#   PYTHONUNBUFFERED=1 nohup bash scripts/fase4/eval_agent.sh json > logs/fase4_eval_json.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/../.."
stage="${1:-smoke}"

# One process on the 17 GB MIG at a time (CLAUDE.md): wait until the GPU is free.
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use|agent)\.|arca-api"; do
    echo "GPU busy, waiting ($(date +%H:%M))"
    sleep 60
done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
mkdir -p logs reports/fase4

if [ "$stage" != "smoke" ] && [ -z "${ARCA_RLM_ADAPTER:-}${ARCA_AGENT_RLM_ADAPTER:-}" ]; then
    export ARCA_RLM_ADAPTER=rlm/weights/grpo2_lora
fi
if [ "$stage" = "json" ] && [ ! -d "${ARCA_AGENT_RLM_ADAPTER:-$ARCA_RLM_ADAPTER}" ]; then
    echo "brain=rlm needs the GRPO 2 adapter at ${ARCA_AGENT_RLM_ADAPTER:-$ARCA_RLM_ADAPTER}" >&2
    exit 1
fi

echo "=== Fase 4 · evaluate $stage · $(git log --oneline -1 | cut -c1-7) · $(date +%H:%M)"
echo "    session ends in $(( (${SLURM_JOB_END_TIME:-$(date +%s)} - $(date +%s)) / 60 )) min"
case "$stage" in
    smoke)
        uv run python -m agent.evaluate --brains base --configs full --limit 2 \
            --out reports/fase4/smoke_eval.json --traces-dir reports/fase4/smoke_eval_trazas \
            --resume
        ;;
    json)
        uv run python -m agent.evaluate --brains base rlm thinking \
            --configs full no_auditor no_playbook flat_memory \
            --out reports/fase4/phase4_eval.json --traces-dir reports/fase4/trazas --resume
        ;;
    code)
        uv run python -m agent.evaluate --agent code --brains base thinking --configs full \
            --out reports/fase4/phase4_eval_code.json --traces-dir reports/fase4/trazas_code \
            --resume
        ;;
    *)
        echo "unknown stage $stage: smoke | json | code" >&2
        exit 2
        ;;
esac
echo "=== TODO TERMINADO ($(date +%H:%M))"
