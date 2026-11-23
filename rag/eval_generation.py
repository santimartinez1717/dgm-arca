"""Phase 3 generation check: citations, abstention and key figures on the gold set.

For every gold question (and every unanswerable one) it runs the full ``/rag`` pipeline and
measures, automatically:

* ``cites_any``: the answer cites at least one retrieved chunk;
* ``invented_ids``: bracketed ids in the answer that are *not* among the retrieved chunks
  (the automatic check that citations exist; ``to_response`` already drops them);
* ``cites_relevant``: among the questions whose relevant chunk was retrieved, the answer
  cites it;
* ``figures_match``: every number in the reference answer appears in the generated one, a
  cheap proxy for correctness that misses paraphrases (read the answers too);
* ``abstains``: the answer says the information is not enough. Wanted on the
  unanswerable questions, unwanted on the answerable ones.

All answers are saved so they can be read. Run on the GPU::

    uv run python -m rag.eval_generation --name base
    ARCA_RAG_GENERATOR_ADAPTER=rlm/weights/grpo2_lora \
        uv run python -m rag.eval_generation --name rlm
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ABSTAIN = re.compile(
    r"(?:información|datos) (?:proporcionad[ao]s? |disponibles? )?"
    r"(?:no (?:es|son) suficientes?|(?:es|son) insuficientes?)"
    r"|no (?:tengo|dispongo de|hay|encuentro) (?:suficiente )?(?:información|datos)"
    r"|no (?:es posible|se puede|puedo) (?:responder|determinar|saber)"
    r"|no se (?:menciona|especifica|indica|encuentra)\w* en (?:los|ningún|ninguno de los) pasajes?"
    r"|no se (?:encuentra|proporciona|ofrece|incluye|recoge|dispone de) (?:\w+ )?"
    r"(?:información|datos)"
    r"|no hay (?:ningún )?pasaje"
    r"|not enough information",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
BRACKETED = re.compile(r"\[([A-Za-z0-9_-]+)\]")


WORDS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20,
    "treinta": 30, "treinta y uno": 31, "treinta y un": 31, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100,
}  # fmt: skip
WORD_NUMBER = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)) + r")\b", re.I
)


def numbers(text: str) -> set[str]:
    """Numbers in a canonical form: '1.500' = '1500', '0,30' = '0.3', 'cinco' = '5'.

    "una mensualidad" also yields 1: harmless, since the check is that the reference's
    numbers are a subset of the answer's.
    """
    out = {str(WORDS[w.lower()]) for w in WORD_NUMBER.findall(text)}
    for raw in NUMBER.findall(text):
        if "," in raw:  # Spanish decimal comma, dots are thousands
            value = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):  # 1.500 / 12.000.000
            value = raw.replace(".", "")
        else:  # integer or a decimal point
            value = raw
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        out.add(value)
    return out


def abstains(answer: str) -> bool:
    """The answer *opens* by saying the information is not enough (later hedges don't count)."""
    first = re.split(r"(?<=[.!?])\s", answer.strip(), maxsplit=1)[0]
    return bool(ABSTAIN.search(first))


def score(items: list[dict]) -> dict:
    answerable = [i for i in items if not i["unanswerable"]]
    unanswerable = [i for i in items if i["unanswerable"]]
    retrieved = [i for i in answerable if i["relevant_retrieved"]]

    def mean(values):
        values = list(values)
        return round(sum(values) / len(values), 3) if values else None

    return {
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "cites_any": mean(bool(i["citations"]) for i in answerable),
        "answers_with_invented_ids": mean(bool(i["invented_ids"]) for i in items),
        "relevant_retrieved": mean(i["relevant_retrieved"] for i in answerable),
        "cites_relevant_when_retrieved": mean(i["cites_relevant"] for i in retrieved),
        "figures_match": mean(
            i["figures_match"] for i in answerable if i["figures_match"] is not None
        ),
        "figures_match_when_retrieved": mean(
            i["figures_match"] for i in retrieved if i["figures_match"] is not None
        ),
        "abstains_answerable": mean(i["abstains"] for i in answerable),
        # abstaining is right when the passage with the answer was not retrieved
        "abstains_when_retrieved": mean(i["abstains"] for i in retrieved),
        "abstains_when_not_retrieved": mean(
            i["abstains"] for i in answerable if not i["relevant_retrieved"]
        ),
        "abstains_unanswerable": mean(i["abstains"] for i in unanswerable),
    }


def rescore(path: Path) -> None:
    """Re-apply ``abstains`` and ``figures_match`` to the saved answers (detectors improve)."""
    report = json.loads(path.read_text())
    for item in report["items"]:
        item["abstains"] = abstains(item["answer"])
        reference = numbers(item.get("reference") or "")
        item["figures_match"] = reference <= numbers(item["answer"]) if reference else None
    report["metrics"] = score(report["items"])
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(path, json.dumps(report["metrics"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", help="suffix of the report file")
    parser.add_argument(
        "--rescore", nargs="+", metavar="REPORT", help="recompute checks and metrics of reports"
    )
    parser.add_argument("--retriever", default="hybrid", choices=["bm25", "dense", "hybrid"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="first N questions (smoke test)")
    parser.add_argument("--gold", default="rag/gold/gold.jsonl")
    parser.add_argument("--unanswerable", default="rag/gold/unanswerable.jsonl", help="'' = none")
    args = parser.parse_args()
    if args.rescore:
        for path in args.rescore:
            rescore(Path(path))
        return
    if not args.name:
        parser.error("--name is required")

    from rag.evaluate import load_gold
    from rag.generate import RagPipeline
    from rag.gold import resolve
    from rag.ingest import load_corpus

    t0 = time.time()
    out = Path(f"reports/phase3_generation_{args.name}.json")
    if out.exists():
        raise SystemExit(f"{out} already exists: choose another --name")
    pipeline = RagPipeline()
    pipeline.load()
    gold = load_gold(args.gold)
    if all("source" in e for g in gold for e in g["evidence"]):
        gold = resolve(gold, load_corpus(), pipeline.chunks)
    else:  # dated questions (rag/gold/temporal.jsonl): judged on the answer, not on chunk ids
        gold = [g | {"relevant_chunk_ids": []} for g in gold]
    none = (
        [g | {"relevant_chunk_ids": []} for g in load_gold(args.unanswerable)]
        if args.unanswerable
        else []
    )
    questions = (gold + none)[: args.limit] if args.limit else gold + none
    print(f"{len(questions)} questions, generator {pipeline.model_name}, {pipeline.config}")

    items = []
    for start in range(0, len(questions), args.batch_size):
        batch = questions[start : start + args.batch_size]
        responses = pipeline.answer_many([q["question"] for q in batch], args.top_k, args.retriever)
        for q, r in zip(batch, responses, strict=True):
            returned = {c.id for c in r.chunks}
            relevant = set(q["relevant_chunk_ids"])
            reference = numbers(q.get("answer", ""))
            items.append(
                {
                    "id": q["id"],
                    "unanswerable": q["id"].startswith("none-"),
                    "question": q["question"],
                    "reference": q.get("answer"),
                    "answer": r.answer,
                    "citations": r.citations,
                    "invented_ids": sorted(set(BRACKETED.findall(r.answer)) - returned),
                    "relevant_retrieved": bool(relevant & returned),
                    "cites_relevant": bool(relevant & set(r.citations)),
                    "figures_match": reference <= numbers(r.answer) if reference else None,
                    "abstains": abstains(r.answer),
                    "chunks": [(c.id, c.source, round(c.score, 4)) for c in r.chunks],
                    "law_date": r.law_date,
                    "control": q.get("control"),
                }
            )
        print(f"{len(items)}/{len(questions)} answered ({time.time() - t0:.0f} s)", flush=True)

    report = {
        "generator": pipeline.model_name,
        "config": vars(pipeline.config),
        "retriever": args.retriever,
        "top_k": args.top_k,
        "metrics": score(items),
        "elapsed_s": round(time.time() - t0, 1),
        "items": items,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["metrics"], indent=1))
    print(f"report: {out}")


if __name__ == "__main__":
    main()
