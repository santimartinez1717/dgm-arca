"""Versions of BOE articles, their validity spans and the date of a question."""

import pytest

from rag.temporal import (
    FAR_FUTURE,
    article_versions,
    question_date,
    validity,
    version_chunks,
)


def test_validity_in_document_order():
    assert validity(["19950101", "20130606", "20190306"]) == [
        [("1995-01-01", "2013-06-06")],
        [("2013-06-06", "2019-03-06")],
        [("2019-03-06", FAR_FUTURE)],
    ]


def test_validity_with_a_repealed_decree_and_a_future_version():
    # LIRPF art. 85: 2015 text; RDL 26/2026 changes it from 2027; repealed on 2/10/2026
    # (restores the text, version dated 20261002); RDL 29/2026 changes it again from 2027.
    spans = validity(["20070101", "20150101", "20270101", "20261002", "20270101"])
    assert spans[0] == [("2007-01-01", "2015-01-01")]
    assert spans[1] == [("2015-01-01", "2026-10-02")]
    assert spans[2] == []  # never in force: overtaken by later entries in the list
    assert spans[3] == [("2026-10-02", "2027-01-01")]
    assert spans[4] == [("2027-01-01", FAR_FUTURE)]


def test_validity_skips_versions_without_date():
    spans = validity(["20190306", "", "20261113"])
    assert spans == [[("2019-03-06", "2026-11-13")], [], [("2026-11-13", FAR_FUTURE)]]


XML = """<response><data><texto>
<bloque id="a9" tipo="precepto" titulo="Artículo 9">
  <version fecha_vigencia="20130606" id_norma="BOE-A-2013-5941">
    <p class="articulo">Artículo 9. Plazo mínimo.</p><p class="parrafo">Tres años.</p>
  </version>
  <version fecha_vigencia="20190306" id_norma="BOE-A-2019-3108">
    <p class="articulo">Artículo 9. Plazo mínimo.</p><p class="parrafo">Cinco años.</p>
    <blockquote><p>Se modifica por el RDL 7/2019.</p></blockquote>
  </version>
</bloque>
<bloque id="ti" tipo="encabezado">
  <version fecha_vigencia="19950101"><p>TÍTULO I</p></version>
</bloque>
</texto></data></response>"""


def test_article_versions_and_their_chunks():
    versions = article_versions(XML, "lau", "Ley 29/1994")
    assert [v.id for v in versions] == ["lau-a9-v0", "lau-a9-v1"]
    old, new = versions
    assert old.in_force("2017-07-01") and not new.in_force("2017-07-01")
    assert new.in_force("2026-11-23") and "Se modifica" not in new.text
    chunks = version_chunks(versions)
    assert chunks[0].text == "Ley 29/1994 — Artículo 9. Plazo mínimo.\nTres años."
    assert chunks[1].source == "boe/lau.md#a9@2019-03-06"
    assert [c.in_force("2020-01-01") for c in chunks] == [False, True]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Firmé el contrato el 3 de marzo de 2022, ¿qué plazo tengo?", "2022-03-03"),
        ("Contrato firmado el 3/3/2022", "2022-03-03"),
        ("Alquilé en marzo de 2019 a un particular", "2019-03-15"),
        ("Si alquilé en 2017, ¿cuánto duraba?", "2017-07-01"),
        ("Un contrato firmado antes de mayo de 2023", "2023-04-30"),
        ("Contratos firmados antes del 26 de mayo de 2023", "2023-05-25"),
        ("¿Cuánta fianza debo pedir?", None),
        ("Tengo 2 pisos y 1.500 m²", None),
    ],
)
def test_question_date(question, expected):
    assert question_date(question) == expected


XML_3 = XML.replace(
    '</bloque>\n<bloque id="ti"',
    """<version fecha_vigencia="20261008" id_norma="BOE-A-2026-20823">
    <p class="articulo">Artículo 9. Plazo mínimo.</p><p class="parrafo">Cinco años.</p>
    <p class="parrafo">Nuevo apartado.</p>
  </version>
</bloque>
<bloque id="ti\"""",
    1,
)


def test_resolve_temporal_is_by_content_not_by_version_id():
    from rag.temporal import resolve_temporal

    chunks = version_chunks(article_versions(XML_3, "lau", "Ley 29/1994"))
    assert [c.doc_id for c in chunks] == ["lau-a9-v0", "lau-a9-v1", "lau-a9-v2"]
    five = [{"law": "lau", "block_id": "a9", "quote": "Cinco años."}]
    gold = [
        {"id": "old", "date": "2017-07-01",
         "evidence": [{"law": "lau", "block_id": "a9", "quote": "Tres años."}]},
        {"id": "2021", "date": "2021-07-01", "evidence": five},
        {"id": "excluding", "date": "2021-07-01",
         "evidence": [five[0] | {"absent": ["Nuevo apartado"]}]},
    ]  # fmt: skip
    old, same_text, excluding = resolve_temporal(gold, chunks, today="2026-11-23")
    assert old["relevant_chunk_ids"] == ["lau-a9-v0-00"]
    # the 2021 answer is also in today's version, which changed another paragraph
    assert same_text["relevant_chunk_ids"] == ["lau-a9-v1-00", "lau-a9-v2-00"]
    assert excluding["relevant_chunk_ids"] == ["lau-a9-v1-00"]
    with pytest.raises(ValueError, match="quote not in"):
        resolve_temporal(
            [{"id": "x", "date": "2017-07-01", "evidence": five}], chunks, "2026-11-23"
        )


def test_date_filtered_retriever_reads_the_date(tmp_path):
    from rag.chunking import Chunk
    from rag.retriever import DenseRetriever
    from rag.temporal import DateFilteredRetriever
    from tests.test_rag_retrieval import FakeEmbedder

    versions = version_chunks(article_versions(XML, "lau", "Ley 29/1994"))
    static = [Chunk("g-0000", "g", "aeat/guia.md", "La fianza y la renta.", 0)]
    embedder = FakeEmbedder()
    retriever = DateFilteredRetriever(
        static,
        DenseRetriever(static, embedder, tmp_path),
        DenseRetriever(versions, embedder, tmp_path),
        today="2026-11-23",
        weight_bm25=0.2,
    )
    ids = [h.chunk.id for h in retriever.search("plazo de un contrato de 2017", 5, "dense")]
    assert "lau-a9-v0-00" in ids and "lau-a9-v1-00" not in ids and "g-0000" in ids
    assert retriever.last_date == "2017-07-01"
    ids = [h.chunk.id for h in retriever.search("plazo de un contrato", 5, "hybrid")]
    assert "lau-a9-v1-00" in ids and retriever.last_date == "2026-11-23"
