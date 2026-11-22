"""Converters of the corpus downloader, on small offline samples of BOE and AEAT markup."""

from rag.download_corpus import (
    aeat_page_to_markdown,
    all_sources,
    boe_consolidated_to_markdown,
    boe_diario_to_markdown,
)

CONSOLIDATED = """<?xml version="1.0" encoding="utf-8"?>
<response><data><texto>
  <bloque id="preambulo" tipo="preambulo">
    <version fecha_vigencia="19950101"><p class="parrafo">Exposición de motivos.</p></version>
  </bloque>
  <bloque id="ti" tipo="encabezado" titulo="TÍTULO I">
    <version fecha_vigencia="19950101">
      <p class="titulo_num">TÍTULO I</p><p class="titulo_tit">Ámbito de la ley</p>
    </version>
  </bloque>
  <bloque id="a17" tipo="precepto" titulo="Artículo 17">
    <version fecha_vigencia="19950101">
      <p class="articulo">Artículo 17. Determinación de la renta.</p>
      <p class="parrafo">3. El pago se efectuará en metálico.</p>
    </version>
    <version fecha_vigencia="20230526">
      <p class="articulo">Artículo 17. Determinación de la renta.</p>
      <p class="parrafo">3. El pago se efectuará a través de medios electrónicos.</p>
      <table><tr><th>Zona</th><th>Límite</th></tr><tr><td>Tensionada</td><td>IRAV</td></tr></table>
      <p class="nota_pie">Téngase en cuenta la disposición transitoria.</p>
      <blockquote><p>Se modifica el apartado 3 por la Ley 12/2023.</p></blockquote>
    </version>
  </bloque>
  <bloque id="a17-2" tipo="precepto" titulo="Artículo 17 bis">
    <version fecha_vigencia="20990101"><p class="articulo">Artículo 17 bis. Futuro.</p></version>
  </bloque>
  <bloque id="a18" tipo="precepto" titulo="Artículo 18">
    <version fecha_vigencia="19950101"><p class="articulo">Artículo 18. Actualización.</p></version>
  </bloque>
  <bloque id="fi" tipo="firma">
    <version fecha_vigencia="19950101"><p>JUAN CARLOS R.</p></version>
  </bloque>
</texto></data></response>"""


def test_consolidated_takes_the_version_in_force_on_the_cutoff_date():
    new, latest = boe_consolidated_to_markdown(CONSOLIDATED, "LAU", "u", "2026-11-22")
    old, _ = boe_consolidated_to_markdown(CONSOLIDATED, "LAU", "u", "2020-01-01")
    assert "medios electrónicos" in new and "metálico" not in new
    assert "metálico" in old and "medios electrónicos" not in old
    assert latest == "2023-05-26"


def test_consolidated_drops_amendment_notes_signature_and_future_articles():
    md, _ = boe_consolidated_to_markdown(CONSOLIDATED, "LAU", "u", "2026-11-22")
    assert "Se modifica" not in md and "Téngase" not in md and "JUAN CARLOS" not in md
    assert "Futuro" not in md


def test_consolidated_structure_headings_and_tables():
    md, _ = boe_consolidated_to_markdown(CONSOLIDATED, "LAU", "https://boe/lau", "2026-11-22")
    assert md.startswith("# LAU\n\nFuente: https://boe/lau\n")
    assert "## Preámbulo" in md
    assert "## TÍTULO I. Ámbito de la ley" in md
    assert "### Artículo 17. Determinación de la renta.\n\n3. El pago" in md
    assert "| Zona | Límite |\n| Tensionada | IRAV |" in md


def test_consolidated_article_filter_keeps_only_those_articles():
    md, _ = boe_consolidated_to_markdown(CONSOLIDATED, "LAU", "u", "2026-11-22", ((18, 18),))
    assert "### Artículo 18. Actualización." in md
    assert "Artículo 17" not in md and "Preámbulo" not in md and "TÍTULO" not in md


def test_diario_document():
    xml = """<documento><metadatos><titulo>Resolución de zonas tensionadas</titulo></metadatos>
    <texto><p class="parrafo">Primero. Se declara zona tensionada Barcelona.</p></texto>
    </documento>"""
    md, title = boe_diario_to_markdown(xml, "https://boe/x")
    assert title == "Resolución de zonas tensionadas"
    assert "Se declara zona tensionada Barcelona." in md


def test_aeat_page_keeps_main_only_and_unescapes():
    page = """<html><body><nav>Menú</nav><main id="acc-main">
    <h1>Rendimiento neto</h1><p>Diferencia entre ingresos &iacute;ntegros y gastos.</p>
    <ul><li>Intereses</li><li><p>Gastos de conservaci&oacute;n</p></li></ul>
    <table><tr><th>Año</th><th>Reducción</th></tr><tr><td>2024</td><td>50 %</td></tr></table>
    </main><footer>Pie</footer></body></html>"""
    md, title = aeat_page_to_markdown(page, "https://aeat/x")
    assert title == "Rendimiento neto"
    assert md.startswith("# Rendimiento neto\n\nFuente: https://aeat/x\n")
    assert "ingresos íntegros" in md
    assert "- Intereses" in md and "- Gastos de conservación" in md
    assert "| Año | Reducción |\n| 2024 | 50 % |" in md
    assert "Menú" not in md and "Pie" not in md


def test_every_source_has_a_licence_and_a_unique_file_name():
    sources = all_sources()
    assert all(s.license for s in sources)
    assert len({s.slug for s in sources}) == len(sources)
