#!/bin/bash
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
uv run python -c "
import runpy, sys, time, torch
sys.argv = ['distill', '--data', 'rlm/data/train.jsonl', '--teacher', 'Qwen/Qwen3-4B',
            '--samples', '4', '--limit', '20', '--batch-size', '2',
            '--output', 'rlm/data/sft_traces_probe20.jsonl']
t = time.time()
runpy.run_module('rlm.distill', run_name='__main__')
print(f'ELAPSED_S={time.time() - t:.0f}')
print(f'PEAK_GPU_GB={torch.cuda.max_memory_reserved() / 2**30:.1f}')
" 2>&1 | awk '{ print strftime("[%H:%M:%S]"), $0; fflush() }'
