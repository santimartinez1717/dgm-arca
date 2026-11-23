"""Retrieval and generation: augment the prompt with the retrieved chunks and answer with citations.

``answer_with_rag`` is what ``POST /rag`` calls. It must:

1. retrieve ``top_k`` chunks with the requested retriever (dense, bm25 or hybrid);
2. build the augmented prompt (``RAG_PROMPT_TEMPLATE`` below is the one from class, with
   chunk ids so the model can cite them);
3. generate the answer with your model;
4. extract the citations and return everything in a ``RagResponse``.

A grader will check that every cited id exists among the returned chunks, and will read
the answers to see whether they actually rest on the retrieved text.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, fields
from pathlib import Path

from api.schemas import RagResponse, RetrievedChunk
from rag.embed import DEFAULT_MODEL as DEFAULT_EMBEDDING_MODEL
from rag.retriever import Hit

RAG_SYSTEM_PROMPT = (
    "Eres un asistente para personas que compran vivienda en España para alquilarla. "
    "Respondes siempre en español y solo con lo que dicen los pasajes que se te dan."
)

# The template from class, in Spanish: with the English one, Qwen3-1.7B answered half of the
# Spanish questions in English, cited articles ("artículo 36") instead of passage ids, and
# opened correct answers with "no se especifica" (see EXPERIMENTS.md, 2026-11-23).
RAG_PROMPT_TEMPLATE = """Responde a la pregunta usando la información actualizada de los pasajes.
- Después de cada afirmación, cita entre corchetes el número del pasaje en que te basas,
  por ejemplo [1] o [2]. Cita el número del pasaje, no el del artículo.
- Si un pasaje responde a la pregunta, da la respuesta directamente, sin rodeos.
- Solo si ningún pasaje trata lo que se pregunta, di que la información disponible no es
  suficiente.

Pasajes recuperados:
{chunks}

Pregunta: {question}
"""

CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]")


def format_chunks(hits: list[Hit]) -> str:
    """Passages numbered [1]..[k]: a 1.7B model copies "[2]" far more reliably than a chunk id."""
    return "\n\n".join(
        f"[{n}] (de {hit.chunk.source})\n{hit.chunk.text}" for n, hit in enumerate(hits, 1)
    )


def build_prompt(question: str, hits: list[Hit], on: str | None = None) -> str:
    """``on``: date whose law the passages reflect (option 1); said to the model if given."""
    prompt = RAG_PROMPT_TEMPLATE.format(chunks=format_chunks(hits), question=question)
    if on:
        prompt = prompt.replace(
            "Pasajes recuperados:",
            f"Los artículos de ley son los que estaban en vigor el {on}.\n\nPasajes recuperados:",
        )
    return prompt


def number_to_id(answer: str, hits: list[Hit]) -> str:
    """Rewrite the citations [n] (also [1, 3] and [1][2]) as the real chunk ids."""

    def one(n: str) -> str:
        i = int(n)
        return f"[{hits[i - 1].chunk.id}]" if 1 <= i <= len(hits) else f"[{n}]"

    def group(match: re.Match) -> str:
        return "".join(one(n) for n in re.findall(r"\d+", match.group(0)))

    return re.sub(r"\[\s*\d+(?:\s*[,;y]\s*\d+)*\s*\]", group, answer)


def extract_citations(answer: str, valid_ids: set[str]) -> list[str]:
    """Ids cited in the answer that actually exist among the retrieved chunks, in order."""
    seen: list[str] = []
    for match in CITATION_PATTERN.findall(answer):
        if match in valid_ids and match not in seen:
            seen.append(match)
    return seen


def to_response(answer: str, hits: list[Hit], retriever: str, model: str = "") -> RagResponse:
    chunks = [
        RetrievedChunk(id=h.chunk.id, source=h.chunk.source, score=h.score, text=h.chunk.text)
        for h in hits
    ]
    return RagResponse(
        answer=answer,
        chunks=chunks,
        citations=extract_citations(answer, {c.id for c in chunks}),
        retriever=retriever,
        model=model,
    )


@dataclass
class RagConfig:
    """What ``POST /rag`` runs; every field can be overridden with an ``ARCA_RAG_*`` variable.

    The chunking and λ come from ``rag/evaluate.py`` (see EXPERIMENTS.md).
    """

    chunking: str = "semantic"  # semantic | recursive
    chunk_size: int = 800  # recursive only
    chunk_overlap: int = 100  # recursive only
    semantic_threshold: float = 0.8215  # p90 of consecutive-sentence distances, Qwen3-Emb-0.6B
    max_chunk_chars: int = 1500
    weight_bm25: float = 0.2  # middle of the MRR plateau (λ 0-0.3) for semantic p90
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    generator_model: str = "Qwen/Qwen3-1.7B"
    generator_adapter: str | None = None  # e.g. rlm/weights/grpo2_lora (phase-1 model)
    temporal: bool = False  # option 1: BOE articles in the version in force on the question's date
    thinking: bool = False  # Qwen3 thinking mode before the answer
    max_new_tokens: int = 512
    index_dir: str = "rag/index"

    @classmethod
    def from_env(cls) -> RagConfig:
        config = cls()
        for f in fields(cls):
            value = os.environ.get(f"ARCA_RAG_{f.name.upper()}")
            if value is not None:
                kind = type(getattr(config, f.name))
                if kind is bool:
                    parsed = value.lower() in ("1", "true", "yes")
                elif kind in (int, float):
                    parsed = kind(value)
                else:
                    parsed = value or None
                setattr(config, f.name, parsed)
        return config


class RagPipeline:
    """Everything ``POST /rag`` needs, built once and reused."""

    def __init__(self, config: RagConfig | None = None):
        self.config = config or RagConfig.from_env()
        self._lock = threading.Lock()

    def load(self, generator: bool = True) -> None:
        """Ingest -> chunk -> BM25, dense (index persisted in ``rag/index/``) and hybrid.

        ``generator=False`` skips the language model (retrieval-only scripts).
        """
        from rag.chunking import SentenceCache, recursive_chunks, semantic_chunks
        from rag.embed import Embedder
        from rag.ingest import load_corpus
        from rag.retriever import BM25Retriever, DenseRetriever, HybridRetriever

        c = self.config
        documents = load_corpus()
        if not documents:
            raise RuntimeError("rag/corpus is empty: run `uv run python -m rag.download_corpus`")
        self.embedder = Embedder(c.embedding_model)
        if c.chunking == "semantic":
            sentences = SentenceCache(documents, self.embedder, c.max_chunk_chars, c.index_dir)
            chunks = semantic_chunks(documents, sentences, c.semantic_threshold, c.max_chunk_chars)
        else:
            chunks = recursive_chunks(documents, c.chunk_size, c.chunk_overlap)
        self.chunks = chunks
        bm25 = BM25Retriever(chunks)
        dense = DenseRetriever(chunks, self.embedder, c.index_dir)
        self.retrievers = {
            "bm25": bm25,
            "dense": dense,
            "hybrid": HybridRetriever(bm25, dense, weight_bm25=c.weight_bm25),
        }
        self.temporal = None
        if c.temporal:
            from rag.download_corpus import AS_OF
            from rag.temporal import DateFilteredRetriever, load_versions, version_chunks

            versions = DenseRetriever(version_chunks(load_versions()), self.embedder, c.index_dir)
            self.temporal = DateFilteredRetriever(chunks, dense, versions, AS_OF, c.weight_bm25)
        self.generator = None
        if generator:
            self.load_generator()

    def load_generator(self):
        """The language model; the API loads it on the first question, not in /health."""
        if self.generator is None:
            from rlm.generation import Generator

            c = self.config
            self.generator = Generator(
                c.generator_model,
                adapter_path=c.generator_adapter,
                enable_thinking=c.thinking,
                system_prompt=RAG_SYSTEM_PROMPT,
            ).load()
        return self.generator

    @property
    def model_name(self) -> str:
        c = self.config
        name = c.generator_model
        return f"{name}+{Path(c.generator_adapter).name}" if c.generator_adapter else name

    def retrieve(self, question: str, top_k: int, retriever: str) -> list[Hit]:
        if retriever not in self.retrievers:
            raise ValueError(f"retriever must be one of {sorted(self.retrievers)}")
        if self.temporal is not None:
            return self.temporal.search(question, top_k, mode=retriever)
        return self.retrievers[retriever].search(question, top_k=top_k)

    def answer(self, question: str, top_k: int = 5, retriever: str = "hybrid") -> RagResponse:
        return self.answer_many([question], top_k, retriever)[0]

    def answer_many(
        self, questions: list[str], top_k: int = 5, retriever: str = "hybrid"
    ) -> list[RagResponse]:
        """Retrieve -> ``build_prompt`` -> generate (one batch) -> ``to_response``."""
        hits, dates = [], []
        for q in questions:
            hits.append(self.retrieve(q, top_k, retriever))
            dates.append(self.temporal.last_date if self.temporal is not None else None)
        prompts = [build_prompt(q, h, on) for q, h, on in zip(questions, hits, dates, strict=True)]
        with self._lock:  # one generation at a time on a small GPU
            generator = self.load_generator()
            outputs = generator.generate(prompts, max_new_tokens=self.config.max_new_tokens)
        # generate() gives, per question, a list of (text, n_tokens, truncated) samples
        responses = []
        for samples, h, on in zip(outputs, hits, dates, strict=True):
            answer = number_to_id(strip_thinking(samples[0][0]), h)
            response = to_response(answer, h, retriever, self.model_name)
            response.law_date = on
            responses.append(response)
        return responses


def strip_thinking(text: str) -> str:
    """Qwen3 with thinking off still emits an empty ``<think></think>``: drop it."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


_pipeline: RagPipeline | None = None


def build_pipeline() -> RagPipeline:
    global _pipeline
    if _pipeline is None:
        pipeline = RagPipeline()
        pipeline.load(generator=False)  # the model comes with the first question
        _pipeline = pipeline
    return _pipeline


def answer_with_rag(question: str, top_k: int = 5, retriever: str = "hybrid") -> RagResponse:
    """Convenience entry point for scripts and the evaluation."""
    return build_pipeline().answer(question, top_k=top_k, retriever=retriever)
