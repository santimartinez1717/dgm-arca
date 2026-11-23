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


def version_relevance(gold_item: dict, chunks, on: str, static_relevant: set[str]) -> set[str]:
    """Relevant ids for a normal gold question when the BOE laws come as article versions.

    Non-BOE evidence keeps its chunks of the normal index (they are shared). BOE evidence
    (``boe/<law>.md``, section ``Artículo N``) maps to the chunks of that article's version in
    force on ``on`` that hold the quote, or a 20+ character half of it when it is split.
    """
    from rag.gold import normalise

    relevant = {cid for cid in static_relevant}
    for e in gold_item["evidence"]:
        if not e["source"].startswith("boe/"):
            continue
        law = e["source"].removeprefix("boe/").removesuffix(".md")
        quote = normalise(e["quote"])
        halves = [h for h in (quote[: len(quote) // 2], quote[len(quote) // 2 :]) if len(h) >= 20]
        section = (e.get("section") or "") + "."
        article = [
            c for c in chunks
            if c.doc_id.startswith(f"{law}-") and c.in_force(on)
            and c.text.split("\n", 1)[0].split(" — ", 1)[-1].startswith(section)
        ]  # fmt: skip
        version_text = normalise(" ".join(c.text for c in article))
        if quote in version_text:
            relevant |= {
                c.id for c in article if any(h in normalise(c.text) for h in [quote, *halves])
            }
    return relevant


def compare_on_normal_gold(out: Path) -> None:
    """The 51 normal questions: normal index, routed (dated ones to versions), all to versions."""
    from rag.download_corpus import AS_OF
    from rag.evaluate import load_gold, reciprocal_rank
    from rag.generate import RagConfig, RagPipeline
    from rag.gold import resolve
    from rag.ingest import load_corpus
    from rag.temporal import question_date

    pipeline = RagPipeline(RagConfig(temporal=True))
    pipeline.load(generator=False)
    gold = resolve(load_gold("rag/gold/gold.jsonl"), load_corpus(), pipeline.chunks)
    temporal = pipeline.temporal
    rows = []
    for g in gold:
        q = g["question"]
        normal_rel = set(g["relevant_chunk_ids"])
        static_rel = {cid for cid in normal_rel if cid in {c.id for c in temporal.static}}
        on = question_date(q) or AS_OF
        forced_rel = version_relevance(g, temporal.versions, on, static_rel)
        normal = [h.chunk.id for h in pipeline.retrievers["hybrid"].search(q, 10)]
        routed_hits, routed_on = pipeline.retrieve_dated(q, 10, "hybrid")
        routed = [h.chunk.id for h in routed_hits]
        forced = [h.chunk.id for h in temporal.search(q, 10, "hybrid", on=on)]
        rows.append(
            {
                "id": g["id"],
                "routed_to_versions": routed_on is not None,
                "versions_have_answer": bool(forced_rel),
                "normal": reciprocal_rank(normal, normal_rel),
                "routed": reciprocal_rank(routed, forced_rel if routed_on else normal_rel),
                "forced": reciprocal_rank(forced, forced_rel),
                "normal_hit5": bool(set(normal[:5]) & normal_rel),
                "routed_hit5": bool(set(routed[:5]) & (forced_rel if routed_on else normal_rel)),
                "forced_hit5": bool(set(forced[:5]) & forced_rel),
            }
        )
    summary = {
        v: {
            "hit@5": float(np.mean([r[f"{v}_hit5"] for r in rows])),
            "mrr": float(np.mean([r[v] for r in rows])),
        }
        for v in ("normal", "routed", "forced")
    }
    summary["routed_questions"] = [r["id"] for r in rows if r["routed_to_versions"]]
    summary["unresolvable_in_versions"] = [r["id"] for r in rows if not r["versions_have_answer"]]
    out.write_text(
        json.dumps({"summary": summary, "per_question": rows}, ensure_ascii=False, indent=1)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"report: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gold", default="rag/gold/temporal.jsonl")
    parser.add_argument("--out", default="reports/fase3/phase3_temporal.json")
    parser.add_argument("--weight-bm25", type=float, default=0.2)
    parser.add_argument(
        "--normal-gold",
        action="store_true",
        help="compare normal / routed / all-versions on the 51 normal gold questions",
    )
    args = parser.parse_args()
    if args.normal_gold:
        compare_on_normal_gold(Path("reports/fase3/phase3_temporal_routing.json"))
        return

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
