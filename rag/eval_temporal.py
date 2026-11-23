"""Option 1: does filtering article versions by the question's date retrieve the right law?

Same chunks (every version of every BOE article, ``rag/temporal.py``), same retrievers, three
ways of choosing which versions can be retrieved:

* ``hoy``: only the versions in force today, what a normal RAG over the current text sees;
* ``todas``: every version, no filter (the history is there, nothing says which applies);
* ``fecha``: the versions in force on the date read from the question (today if none).

On ``rag/gold/temporal.jsonl`` (17 questions, 7 of them controls whose answer has not
changed). Metrics: ``hit@k`` of a chunk of the *right version*, MRR, and ``wrong_version@1``:
the first chunk is the right article in a version that did not apply on that date.

    uv run python -m rag.eval_temporal
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

VARIANTS = ("hoy", "todas", "fecha")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gold", default="rag/gold/temporal.jsonl")
    parser.add_argument("--out", default="reports/phase3_temporal.json")
    parser.add_argument("--weight-bm25", type=float, default=0.2)
    args = parser.parse_args()

    from rag.download_corpus import AS_OF
    from rag.embed import Embedder
    from rag.evaluate import first_rank, load_gold, reciprocal_rank
    from rag.retriever import BM25Retriever, DenseRetriever, Hit, fuse
    from rag.temporal import load_versions, question_date, resolve_temporal, version_chunks

    t0 = time.time()
    chunks = version_chunks(load_versions())
    gold = resolve_temporal(load_gold(args.gold), chunks, AS_OF)
    questions = [g["question"] for g in gold]
    dates = {
        "hoy": [AS_OF] * len(gold),
        "todas": [None] * len(gold),
        "fecha": [question_date(q) or AS_OF for q in questions],
    }
    parsed_ok = sum(d == g["on"] for d, g in zip(dates["fecha"], gold, strict=True))
    print(f"{len(chunks)} version chunks, {len(gold)} questions, dates read right: {parsed_ok}")

    dense = DenseRetriever(chunks, Embedder())
    query_vectors = np.asarray(dense.embedder.embed_queries(questions, dense.instruction))
    scores = query_vectors @ dense.matrix.T
    bm25_cache: dict[str | None, tuple[BM25Retriever, set[str]]] = {}

    def bm25_for(on: str | None):
        if on not in bm25_cache:
            subset = [c for c in chunks if on is None or c.in_force(on)]
            bm25_cache[on] = (BM25Retriever(subset), {c.id for c in subset})
        return bm25_cache[on][0]

    report: dict = {"as_of": AS_OF, "dates_read_right": parsed_ok, "variants": {}}
    for variant in VARIANTS:
        rankings: dict[str, list[list[Hit]]] = {"bm25": [], "dense": [], "hybrid": []}
        for i, (question, on) in enumerate(zip(questions, dates[variant], strict=True)):
            mask = np.array([on is None or c.in_force(on) for c in chunks])
            row = np.where(mask, scores[i], -np.inf)
            order = np.argsort(-row)[:20]
            dense_hits = [Hit(chunks[j], float(row[j])) for j in order]
            bm25_hits = bm25_for(on).search(question, 20)
            rankings["dense"].append(dense_hits)
            rankings["bm25"].append(bm25_hits)
            rankings["hybrid"].append(fuse(bm25_hits, dense_hits, args.weight_bm25, 20))
        results = {}
        for retriever, per_question in rankings.items():
            rows = []
            for g, hits in zip(gold, per_question, strict=True):
                ids = [h.chunk.id for h in hits[:10]]
                relevant = set(g["relevant_chunk_ids"])
                top = hits[0].chunk.doc_id
                right_article = any(
                    top.startswith(f"{e['law']}-{e['block_id']}-v") for e in g["evidence"]
                )
                rows.append(
                    {
                        "id": g["id"],
                        "control": g["control"],
                        "rank": first_rank(ids, relevant),
                        "rr": reciprocal_rank(ids, relevant),
                        "wrong_version_top1": right_article and ids[0] not in relevant,
                        "top1": hits[0].chunk.id,
                    }
                )

            def summary(sel):
                return {
                    "n": len(sel),
                    "hit@1": float(np.mean([r["rank"] == 1 for r in sel])),
                    "hit@5": float(np.mean([bool(r["rank"]) and r["rank"] <= 5 for r in sel])),
                    "mrr": float(np.mean([r["rr"] for r in sel])),
                    "wrong_version@1": float(np.mean([r["wrong_version_top1"] for r in sel])),
                }

            results[retriever] = {
                "all": summary(rows),
                "changed": summary([r for r in rows if not r["control"]]),
                "control": summary([r for r in rows if r["control"]]),
                "per_question": rows,
            }
            s = results[retriever]
            print(
                f"{variant:<6} {retriever:<7} "
                f"changed hit@1 {s['changed']['hit@1']:.2f} hit@5 {s['changed']['hit@5']:.2f} "
                f"wrong@1 {s['changed']['wrong_version@1']:.2f} | "
                f"control hit@1 {s['control']['hit@1']:.2f} hit@5 {s['control']['hit@5']:.2f}",
                flush=True,
            )
        report["variants"][variant] = results
    report["elapsed_s"] = round(time.time() - t0, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"report: {out} ({report['elapsed_s']} s)")


if __name__ == "__main__":
    main()
