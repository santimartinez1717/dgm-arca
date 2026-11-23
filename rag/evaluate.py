"""Phase 3 evaluation: Recall@k and MRR of each retriever on the gold set.

The gold set (``rag/gold/gold.jsonl``, format in ``rag/gold/README.md``) stores document,
section and a literal quote per question; ``rag/gold.py`` turns it into chunk ids for each
chunking, so the same questions evaluate every strategy.

What this script measures, in order:

1. **Chunking.** Recursive (800/100) and semantic at several distance thresholds (percentiles
   of the distance between consecutive sentences), with the plot of those distances.
2. **Three retrievers** on each chunking: BM25, dense (Qwen3-Embedding) and hybrid.
3. **λ sweep** of the hybrid, chosen by repeated 2-fold cross-validation so that the λ we
   report was not picked on the same questions it is scored on.
4. **Query instruction** of the dense retriever: none, the default one, one written for our
   domain and a deliberately wrong one.
5. **Unanswerable questions**: top similarity for answerable vs unanswerable questions.

Metrics: ``hit@k`` (the answer is in the top k: any relevant chunk, since every question
asks for one fact and a quote can sit whole in two overlapping chunks), the class metric
``recall@k`` (fraction of relevant chunks in the top k) and ``mrr`` (first relevant chunk,
cut at 10).

Run on the GPU (embeds ~20k sentences and ~20k chunks the first time, cached in
``rag/index/``)::

    uv run python -m rag.evaluate
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from rag.embed import DEFAULT_QUERY_INSTRUCTION

CUTOFF = 10  # ranks considered for every metric
LAMBDAS = [round(0.1 * i, 1) for i in range(11)]
PERCENTILES = (70, 80, 90, 95)
INSTRUCTIONS = {
    "none": None,
    "default": DEFAULT_QUERY_INSTRUCTION,
    "generic_es": "Recupera el pasaje que responde a la pregunta.",
    "domain_es": (
        "Dada la pregunta de alguien que compra una vivienda para alquilarla en España, "
        "recupera el artículo de ley, la norma o el pasaje oficial que la responde."
    ),
    "domain_en": (
        "Given a question from someone buying a home in Spain to rent it out, retrieve the "
        "article of law, the regulation or the official passage that answers it."
    ),
    "wrong": "Given a text, retrieve passages written in the same informal style.",
}


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of relevant chunks that appear in the top k."""
    if not relevant_ids:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    """1 / position of the first relevant chunk (0 when none is retrieved)."""
    for position, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / position
    return 0.0


def hit_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """1 if any relevant chunk is in the top k: the answer was retrieved."""
    return float(bool(set(ranked_ids[:k]) & relevant_ids))


def evaluate_retriever(retriever, gold: list[dict], k: int) -> dict[str, float]:
    ranked = [[h.chunk.id for h in retriever.search(g["question"], top_k=CUTOFF)] for g in gold]
    return score_rankings(ranked, gold, ks=(k,))


def score_rankings(rankings: list[list[str]], gold: list[dict], ks=(1, 5, 10)) -> dict:
    """Mean metrics of one ranking per gold question (``relevant_chunk_ids`` resolved)."""
    out: dict[str, float] = {}
    relevant = [set(g["relevant_chunk_ids"]) for g in gold]
    for k in ks:
        out[f"hit@{k}"] = float(
            np.mean([hit_at_k(r, s, k) for r, s in zip(rankings, relevant, strict=True)])
        )
        out[f"recall@{k}"] = float(
            np.mean([recall_at_k(r, s, k) for r, s in zip(rankings, relevant, strict=True)])
        )
    out["mrr"] = float(
        np.mean([reciprocal_rank(r[:CUTOFF], s) for r, s in zip(rankings, relevant, strict=True)])
    )
    out["n_questions"] = len(gold)
    return out


def first_rank(ranked: list[str], relevant: set[str]) -> int | None:
    return next((i for i, c in enumerate(ranked[:CUTOFF], 1) if c in relevant), None)


def load_gold(path: str | Path) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ----------------------------------------------------------------------------- pieces


def rank_lists(retriever_hits: list[list]) -> list[list[str]]:
    return [[h.chunk.id for h in hits] for hits in retriever_hits]


def lambda_cross_validation(
    pools: tuple[list, list], gold: list[dict], repeats: int = 200, seed: int = 0
) -> dict:
    """Repeated 2-fold CV: pick λ by MRR on one half, score it on the other half."""
    from rag.retriever import fuse

    bm25_pools, dense_pools = pools
    per_lambda = {}
    for lam in LAMBDAS:
        rankings = [
            [h.chunk.id for h in fuse(b, d, lam, CUTOFF)]
            for b, d in zip(bm25_pools, dense_pools, strict=True)
        ]
        per_lambda[lam] = [
            reciprocal_rank(r, set(g["relevant_chunk_ids"]))
            for r, g in zip(rankings, gold, strict=True)
        ]
    rng = random.Random(seed)
    idx = list(range(len(gold)))
    chosen, held_out = [], []
    for _ in range(repeats):
        rng.shuffle(idx)
        half = len(idx) // 2
        for train, test in ((idx[:half], idx[half:]), (idx[half:], idx[:half])):
            best = max(LAMBDAS, key=lambda lam: np.mean([per_lambda[lam][i] for i in train]))
            chosen.append(best)
            held_out.append(float(np.mean([per_lambda[best][i] for i in test])))
    counts = {lam: chosen.count(lam) for lam in LAMBDAS if chosen.count(lam)}
    return {
        "mrr_by_lambda": {lam: float(np.mean(v)) for lam, v in per_lambda.items()},
        "chosen_lambda_counts": counts,
        "most_chosen_lambda": max(counts, key=counts.get),
        "held_out_mrr_mean": float(np.mean(held_out)),
        "held_out_mrr_std": float(np.std(held_out)),
    }


def plot_distances(cache, doc_id: str, title: str, thresholds: dict, path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from rag.chunking import consecutive_distances

    distances = consecutive_distances(cache(cache.per_doc[doc_id]))[:150]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(range(1, len(distances) + 1), distances, lw=1, color="#3b6ea8")
    for (name, value), color in zip(
        thresholds.items(), ["#999", "#c77", "#a33", "#600"], strict=False
    ):
        ax.axhline(value, ls="--", lw=1, color=color, label=f"{name} = {value:.3f}")
    ax.set_xlabel("pair of consecutive sentences")
    ax.set_ylabel("cosine distance")
    ax.set_title(title)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_lambda(curves: dict[str, dict], path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 3.5))
    for name, curve in curves.items():
        ax.plot(list(curve), list(curve.values()), marker="o", ms=3, label=name)
    ax.set_xlabel("λ (weight of BM25)")
    ax.set_ylabel("MRR@10")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--gold", default="rag/gold/gold.jsonl")
    parser.add_argument("--unanswerable", default="rag/gold/unanswerable.jsonl")
    parser.add_argument("--out", default="reports/phase3_eval.json")
    parser.add_argument("--index-dir", default="rag/index")
    parser.add_argument("--max-chunk-chars", type=int, default=1500)
    parser.add_argument("--embedding-model", default=None, help="default: rag.embed")
    args = parser.parse_args()

    from rag.chunking import SentenceCache, describe, recursive_chunks, semantic_chunks
    from rag.embed import DEFAULT_MODEL, Embedder
    from rag.gold import resolve
    from rag.ingest import load_corpus
    from rag.retriever import BM25Retriever, DenseRetriever, fuse

    t0 = time.time()
    out_path, index_dir = Path(args.out), Path(args.index_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    documents = load_corpus()
    gold = load_gold(args.gold)
    unanswerable = load_gold(args.unanswerable)
    questions = [g["question"] for g in gold]
    print(f"{len(documents)} documents, {len(gold)} gold questions", flush=True)

    embedder = Embedder(args.embedding_model or DEFAULT_MODEL)
    cache = SentenceCache(documents, embedder, args.max_chunk_chars, index_dir)
    distances = cache.all_distances()
    thresholds = {f"p{p}": float(np.percentile(distances, p)) for p in PERCENTILES}
    report: dict = {
        "embedding_model": embedder.model_id,
        "sentence_distances": {
            "n": int(len(distances)),
            "mean": float(distances.mean()),
            **{k: round(v, 4) for k, v in thresholds.items()},
        },
        "chunkings": {},
    }
    lau = next(d for d in documents if d.source == "boe/lau.md")
    plot_distances(
        cache,
        lau.id,
        "LAU: distance between consecutive sentences (first 150)",
        thresholds,
        out_path.with_name("phase3_semantic_distances.png"),
    )

    chunkings = {"recursive_800_100": recursive_chunks(documents, 800, 100)}
    for name, value in thresholds.items():
        chunkings[f"semantic_{name}"] = semantic_chunks(
            documents, cache, value, args.max_chunk_chars
        )

    lambda_curves, per_question = {}, {}
    for name, chunks in chunkings.items():
        print(f"\n== {name}: {describe(chunks)}", flush=True)
        resolved = resolve(gold, documents, chunks)
        bm25 = BM25Retriever(chunks)
        dense = DenseRetriever(chunks, embedder, index_dir)
        bm25_pools = [bm25.search(q, 20) for q in questions]
        dense_pools = dense.search_many(questions, 20)
        results = {
            "bm25": score_rankings(rank_lists(bm25_pools), resolved),
            "dense": score_rankings(rank_lists(dense_pools), resolved),
        }
        cv = lambda_cross_validation((bm25_pools, dense_pools), resolved)
        lam = cv["most_chosen_lambda"]
        hybrid = [fuse(b, d, lam, CUTOFF) for b, d in zip(bm25_pools, dense_pools, strict=True)]
        results["hybrid"] = score_rankings(rank_lists(hybrid), resolved) | {"lambda": lam}
        lambda_curves[name] = cv["mrr_by_lambda"]
        relevant_counts = [len(g["relevant_chunk_ids"]) for g in resolved]
        report["chunkings"][name] = {
            "stats": describe(chunks),
            "relevant_chunks_per_question": float(np.mean(relevant_counts)),
            "retrievers": results,
            "lambda_cv": cv,
        }
        per_question[name] = {
            g["id"]: {
                "bm25": first_rank(rank_lists([b])[0], set(g["relevant_chunk_ids"])),
                "dense": first_rank(rank_lists([d])[0], set(g["relevant_chunk_ids"])),
                "hybrid": first_rank(rank_lists([h])[0], set(g["relevant_chunk_ids"])),
            }
            for g, b, d, h in zip(resolved, bm25_pools, dense_pools, hybrid, strict=True)
        }
        for retriever, metrics in results.items():
            print(
                f"{retriever:<7} hit@1 {metrics['hit@1']:.3f}  hit@5 {metrics['hit@5']:.3f}  "
                f"hit@10 {metrics['hit@10']:.3f}  recall@5 {metrics['recall@5']:.3f}  "
                f"mrr {metrics['mrr']:.3f}" + (f"  λ={lam}" if retriever == "hybrid" else ""),
                flush=True,
            )
        print(
            f"λ CV: chosen {cv['chosen_lambda_counts']}, held-out MRR "
            f"{cv['held_out_mrr_mean']:.3f} ± {cv['held_out_mrr_std']:.3f}",
            flush=True,
        )
    report["per_question_first_rank"] = per_question
    plot_lambda(lambda_curves, out_path.with_name("phase3_lambda.png"))

    # instruction ablation, on the chunking with the best dense MRR
    best = max(chunkings, key=lambda n: report["chunkings"][n]["retrievers"]["dense"]["mrr"])
    chunks = chunkings[best]
    resolved = resolve(gold, documents, chunks)
    report["instruction_ablation"] = {"chunking": best}
    print(f"\n== query instruction (dense, {best})", flush=True)
    only_boe = [all(e["source"].startswith("boe/") for e in g["evidence"]) for g in resolved]
    for name, instruction in INSTRUCTIONS.items():
        dense = DenseRetriever(chunks, embedder, index_dir, instruction=instruction)
        rankings = rank_lists(dense.search_many(questions, CUTOFF))
        metrics = score_rankings(rankings, resolved)
        rr = [
            reciprocal_rank(r, set(g["relevant_chunk_ids"]))
            for r, g in zip(rankings, resolved, strict=True)
        ]
        metrics["mrr_answer_in_boe"] = float(
            np.mean([x for x, b in zip(rr, only_boe, strict=True) if b])
        )
        metrics["mrr_answer_elsewhere"] = float(
            np.mean([x for x, b in zip(rr, only_boe, strict=True) if not b])
        )
        by_id = {c.id: c.source.split("/")[0] for c in chunks}
        metrics["top5_folders"] = {
            f: sum(by_id[c] == f for r in rankings for c in r[:5])
            for f in sorted(set(by_id.values()))
        }
        report["instruction_ablation"][name] = {"instruction": instruction, **metrics}
        print(
            f"{name:<10} hit@5 {metrics['hit@5']:.3f}  mrr {metrics['mrr']:.3f}  "
            f"(BOE {metrics['mrr_answer_in_boe']:.3f}, rest {metrics['mrr_answer_elsewhere']:.3f})"
            f"  top5 {metrics['top5_folders']}",
            flush=True,
        )

    # unanswerable questions: is the top similarity lower than for answerable ones?
    dense = DenseRetriever(chunks, embedder, index_dir)
    top_answerable = [h[0].score for h in dense.search_many(questions, 1)]
    top_none = [h[0].score for h in dense.search_many([u["question"] for u in unanswerable], 1)]
    report["unanswerable_top_dense_score"] = {
        "answerable": {
            "mean": float(np.mean(top_answerable)),
            "min": float(np.min(top_answerable)),
        },
        "unanswerable": {"mean": float(np.mean(top_none)), "max": float(np.max(top_none))},
        "unanswerable_scores": [round(s, 4) for s in top_none],
    }
    print(
        f"\ntop dense score: answerable mean {np.mean(top_answerable):.3f} "
        f"(min {np.min(top_answerable):.3f}); unanswerable {np.round(top_none, 3)}",
        flush=True,
    )

    report["elapsed_s"] = round(time.time() - t0, 1)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\nreport: {out_path} ({report['elapsed_s']} s)")


if __name__ == "__main__":
    main()
