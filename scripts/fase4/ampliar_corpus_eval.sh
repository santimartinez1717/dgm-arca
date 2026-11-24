#!/usr/bin/env bash
# Issue #13: retrieval before/after the corpus extension, then rebuild the /rag index.
# Run from the repo root after `source smoke/dgx_env.sh`. The "before" run is the same
# rag.evaluate on the corpus without the new documents (reports/fase4/corpus_antes_eval.json).
set -euo pipefail
export PYTHONUNBUFFERED=1
mkdir -p reports/fase4 logs
gold51=$(mktemp) && git show 9b1c9ad:rag/gold/gold.jsonl > "$gold51"
none6=$(mktemp) && git show 9b1c9ad:rag/gold/unanswerable.jsonl > "$none6"
# 1. the 51 phase-3 questions (and the 6 unanswerable ones) on the extended corpus
uv run python -m rag.evaluate --gold "$gold51" --unanswerable "$none6" \
    --out reports/fase4/corpus_despues_eval.json
# 2. the 59 questions (8 new) and 5 unanswerable; embeddings are cached by step 1
uv run python -m rag.evaluate --out reports/fase4/corpus_despues_eval_59.json
# 3. reindex what /rag and search_knowledge_base load (fixed threshold, law versions)
uv run python -c "from rag.generate import RagPipeline; p = RagPipeline(); p.load(generator=False); print('index ready:', len(p.chunks), 'chunks')"
echo ELAPSED_S $SECONDS
