"""Semantic chunking, dense index and hybrid fusion, with a fake bag-of-words embedder (CPU)."""

import re

import numpy as np
import pytest

from rag.chunking import Chunk, semantic_chunks, split_long
from rag.evaluate import hit_at_k, score_rankings
from rag.ingest import Document
from rag.retriever import BM25Retriever, DenseRetriever, Hit, fuse, minmax

VOCAB = ["fianza", "renta", "hipoteca", "banco", "impuesto", "iva", "gato", "perro"]


class FakeEmbedder:
    """One dimension per vocabulary word; counts passages and query calls."""

    model_id = "fake/bow"

    def __init__(self):
        self.passage_calls = 0
        self.instructions = []

    def _vec(self, text):
        words = re.findall(r"\w+", text.lower())
        v = np.array([words.count(w) for w in VOCAB], dtype=np.float32) + 1e-3
        return v / np.linalg.norm(v)

    def embed_passages(self, texts):
        self.passage_calls += 1
        return np.stack([self._vec(t) for t in texts])

    def embed_queries(self, texts, instruction=None):
        self.instructions.append(instruction)
        return np.stack([self._vec(t) for t in texts])


def test_semantic_chunks_split_where_the_topic_changes():
    text = (
        "La fianza es una renta. La renta y la fianza. El banco da la hipoteca. Hipoteca del banco."
    )
    doc = Document(id="d", source="d.md", text=text)
    chunks = semantic_chunks([doc], FakeEmbedder().embed_passages, distance_threshold=0.5)
    assert [c.text for c in chunks] == [
        "La fianza es una renta. La renta y la fianza.",
        "El banco da la hipoteca. Hipoteca del banco.",
    ]
    assert [c.id for c in chunks] == ["d-0000", "d-0001"]


def test_semantic_chunks_respect_the_size_limit():
    doc = Document(id="d", source="d.md", text=" ".join(["La fianza y la renta."] * 30))
    chunks = semantic_chunks([doc], FakeEmbedder().embed_passages, 0.9, max_chunk_chars=100)
    assert len(chunks) > 1 and all(len(c.text) <= 100 for c in chunks)


def test_split_long_cuts_at_spaces():
    pieces = split_long(["a" * 10 + " " + "b" * 10 + " " + "c" * 10], max_chars=15)
    assert pieces == ["a" * 10, "b" * 10, "c" * 10]


CHUNKS = [
    Chunk("d-0000", "d", "d.md", "La fianza es de una mensualidad de renta.", 0),
    Chunk("d-0001", "d", "d.md", "El banco concede la hipoteca.", 1),
    Chunk("d-0002", "d", "d.md", "El iva de la vivienda nueva es un impuesto.", 2),
]


def test_dense_index_is_persisted_and_reused(tmp_path):
    first = FakeEmbedder()
    dense = DenseRetriever(CHUNKS, first, tmp_path, instruction="x")
    assert first.passage_calls == 1 and len(list(tmp_path.glob("*.npy"))) == 1
    assert dense.search("¿qué fianza pido?", top_k=1)[0].chunk.id == "d-0000"
    assert first.instructions == ["x"]
    second = FakeEmbedder()
    DenseRetriever(CHUNKS, second, tmp_path)
    assert second.passage_calls == 0  # loaded from disk
    third = FakeEmbedder()
    DenseRetriever(CHUNKS[:2], third, tmp_path)  # another chunking, another file
    assert third.passage_calls == 1 and len(list(tmp_path.glob("*.npy"))) == 2


def test_minmax_and_fuse():
    a, b, c = CHUNKS
    bm25 = [Hit(a, 9.0), Hit(b, 3.0)]
    dense = [Hit(c, 0.8), Hit(a, 0.6), Hit(b, 0.4)]
    assert minmax(bm25) == {"d-0000": 1.0, "d-0001": 0.0}
    assert [h.chunk.id for h in fuse(bm25, dense, 1.0, 3)][0] == "d-0000"
    assert [h.chunk.id for h in fuse(bm25, dense, 0.0, 3)][0] == "d-0002"
    mixed = fuse(bm25, dense, 0.5, 3)  # a: .5*1 + .5*.5 = .75; c: .5*1 = .5
    assert [h.chunk.id for h in mixed] == ["d-0000", "d-0002", "d-0001"]
    assert mixed[0].score == pytest.approx(0.75)


def test_hybrid_end_to_end(tmp_path):
    from rag.retriever import HybridRetriever

    hybrid = HybridRetriever(
        BM25Retriever(CHUNKS), DenseRetriever(CHUNKS, FakeEmbedder(), tmp_path)
    )
    assert hybrid.search("hipoteca del banco", top_k=2)[0].chunk.id == "d-0001"


def test_hit_counts_any_relevant_chunk_and_recall_counts_all():
    gold = [{"relevant_chunk_ids": ["a", "b"]}]
    assert hit_at_k(["x", "a"], {"a", "b"}, 2) == 1.0
    scores = score_rankings([["x", "a", "y"]], gold, ks=(2,))
    assert scores["hit@2"] == 1.0 and scores["recall@2"] == 0.5 and scores["mrr"] == 0.5


def test_generation_checks():
    from rag.eval_generation import abstains, numbers

    assert numbers("1.500 m², un 0,30 y el 10 % de 2.35") == {"1500", "0.3", "10", "2.35"}
    assert numbers("0,30") == numbers("0.30") == {"0.3"}
    assert numbers("cuatro meses y treinta y un días") == {"4", "31"}
    assert abstains("La información disponible no es suficiente.")
    assert abstains("La información proporcionada no es suficiente para responder.")
    assert abstains("No encuentro datos sobre Madrid en los pasajes.")
    assert not abstains("Sí, la fianza es de una mensualidad [d-0001].")


def test_numbered_citations_become_chunk_ids():
    from rag.generate import extract_citations, number_to_id

    hits = [Hit(c, 1.0) for c in CHUNKS]
    answer = number_to_id("La fianza es una mensualidad [1]. Ver [2, 3] y [9].", hits)
    assert answer == "La fianza es una mensualidad [d-0000]. Ver [d-0001][d-0002] y [9]."
    assert extract_citations(answer, {c.id for c in CHUNKS}) == ["d-0000", "d-0001", "d-0002"]


def test_abstention_is_read_in_the_first_sentence():
    from rag.eval_generation import abstains

    assert not abstains("Sí, se actualiza con el IPC [d-0001]. No hay un pacto expreso.")
    assert not abstains("La información indica que si no se especifica un índice, se usa el IRAV.")
    assert abstains("No se menciona en ningún pasaje. Por tanto no lo sé.")
    assert abstains("No se encuentra información en los pasajes sobre el precio en Madrid.")
    assert abstains("No hay pasaje que responda directamente a la pregunta.")
    assert abstains("No se proporciona información específica sobre el valor del IRAV.")


def test_pipeline_answer_with_a_fake_generator():
    from rag.generate import RagConfig, RagPipeline

    class FakeGenerator:
        def generate(self, prompts, max_new_tokens):
            assert "[1] (de d.md)" in prompts[0] and "Pregunta: ¿fianza?" in prompts[0]
            return [[("<think></think>Una mensualidad [1].", 5, False)] for _ in prompts]

    pipeline = RagPipeline(RagConfig())
    pipeline.retrievers = {"bm25": BM25Retriever(CHUNKS)}
    pipeline.temporal = None
    pipeline.generator = FakeGenerator()
    response = pipeline.answer("¿fianza?", top_k=2, retriever="bm25")
    assert response.answer == "Una mensualidad [d-0000]."
    assert response.citations == ["d-0000"] and response.law_date is None
    assert response.chunks[0].id == "d-0000"


def test_pipeline_routes_only_dated_questions_to_the_law_versions():
    from rag.generate import RagConfig, RagPipeline

    class FakeTemporal:
        def __init__(self):
            self.calls = []

        def search(self, question, top_k, mode, on):
            self.calls.append(on)
            return [Hit(CHUNKS[2], 1.0)]

    pipeline = RagPipeline(RagConfig())
    pipeline.retrievers = {"bm25": BM25Retriever(CHUNKS)}
    pipeline.temporal = FakeTemporal()
    hits, on = pipeline.retrieve_dated("¿fianza de un contrato de 2017?", 2, "bm25")
    assert on == "2017-07-01" and hits[0].chunk.id == "d-0002"
    hits, on = pipeline.retrieve_dated("¿fianza?", 2, "bm25")
    assert on is None and hits[0].chunk.id == "d-0000"  # normal index
    assert pipeline.temporal.calls == ["2017-07-01"]
    pipeline.temporal = None  # ARCA_RAG_TEMPORAL=0
    assert pipeline.retrieve_dated("¿fianza en 2017?", 2, "bm25")[1] is None
