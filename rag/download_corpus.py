"""Download the phase 3 corpus into ``rag/corpus/`` (Spanish rental-investment law and guides).

Sources (licences in ``rag/CORPUS.md``):

* **BOE consolidated legislation** through the open-data API, one Markdown file per law with
  one ``### Artículo N`` section per article. Each article is taken in the version in force
  on ``--as-of`` (fixed by default), so two runs on different days give the same text.
* **BOE daily-gazette documents** (stressed-zone declarations, SERPAVI resolutions) through
  ``diario_boe/xml.php``.
* **AEAT Renta 2025 practical manual**, chapter 4 (rental income) and the imputed-income
  regime, one Markdown file per page.
* **PDFs** (INE IRAV methodology, Banco de España mortgage guide), saved as they are;
  ``rag/ingest.py`` reads them with pypdf.

Files that already exist are skipped unless ``--force``. A ``manifest.json`` with url,
licence, version date and sha256 of every file is written next to the corpus.

    uv run python -m rag.download_corpus            # everything
    uv run python -m rag.download_corpus --only boe --force
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

CORPUS_DIR = Path(__file__).parent / "corpus"
AS_OF = "2026-11-22"  # versions of the consolidated texts in force on this date

BOE_API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/{part}"
BOE_DIARIO = "https://www.boe.es/diario_boe/xml.php?id={id}"
BOE_HTML = "https://www.boe.es/buscar/act.php?id={id}"
AEAT_BASE = "https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/"

LICENSE_BOE = (
    "BOE: reutilización libre citando la fuente (Ley 37/2007, RD 1495/2011, aviso legal del BOE)"
)
LICENSE_AEAT = (
    "AEAT: reutilización citando la fuente (Ley 37/2007, aviso legal de la sede electrónica)"
)
LICENSE_INE = "INE: reutilización citando la fuente (Ley 37/2007, aviso legal del INE)"
LICENSE_BDE = "Banco de España: reproducción permitida citando la fuente"

USER_AGENT = "arca-rag-corpus/0.1 (university coursework; polite crawler)"
PAUSE_S = 0.5


@dataclass
class Source:
    kind: str  # boe | diario | aeat | pdf
    id: str  # BOE id, AEAT page path or PDF url
    slug: str  # output file name without extension
    license: str
    title: str = ""
    articles: tuple[tuple[int, int], ...] = ()  # boe only: keep these article ranges
    tags: list[str] = field(default_factory=list)


# fmt: off
BOE_LAWS = [  # (id, file name, article ranges to keep; empty = whole law)
    ("BOE-A-1994-26003", "lau", ()),  # Ley 29/1994, LAU
    ("BOE-A-2023-12203", "ley-vivienda", ()),  # Ley 12/2023
    ("BOE-A-2026-20823", "rdl-29-2026", ()),  # RDL 29/2026 (replaces the repealed 26/2026)
    ("BOE-A-2006-20764", "lirpf", ()),  # Ley 35/2006, IRPF
    ("BOE-A-2007-6820", "rirpf", ()),  # RD 439/2007, Reglamento IRPF
    ("BOE-A-1993-25359", "trlitpajd", ()),  # RDLeg 1/1993, ITP y AJD
    ("BOE-A-2004-4163", "trlci", ()),  # RDLeg 1/2004, Catastro
    ("BOE-A-2019-3814", "ley-credito-inmobiliario", ()),  # Ley 5/2019
    ("BOE-A-1960-10906", "lph", ()),  # Ley 49/1960, propiedad horizontal
    ("BOE-A-2004-4214", "trlrhl-ibi-plusvalia", ((60, 77), (104, 110))),  # RDLeg 2/2004
    ("BOE-A-1992-28740", "liva-vivienda", ((20, 20), (90, 91))),  # Ley 37/1992
]

BOE_DIARIO_DOCS = [
    ("BOE-A-2024-5213",  "serpavi-2024"),          # sistema de índices de precios de referencia
    ("BOE-A-2026-8691",  "serpavi-2026"),          # actualización del sistema
    ("BOE-A-2024-5214",  "zonas-tensionadas-2024-03"),
    ("BOE-A-2024-20576", "zonas-tensionadas-2024-10"),
    ("BOE-A-2025-1721",  "zonas-tensionadas-2025-01"),
    ("BOE-A-2025-15728", "zonas-tensionadas-2025-07"),
    ("BOE-A-2025-20246", "zonas-tensionadas-2025-07-erratas"),
    ("BOE-A-2025-21901", "zonas-tensionadas-2025-10"),
    ("BOE-A-2026-2448",  "zonas-tensionadas-2026-01"),
    ("BOE-A-2026-9175",  "zonas-tensionadas-2026-04"),
    ("BOE-A-2026-16532", "zonas-tensionadas-2026-07"),
]

AEAT_PAGES = [
    "c04-rendimientos-capital-inmobiliario/rendimientos-capital-inmobiliario/introduccion-rendimientos-capital",
    "c04-rendimientos-capital-inmobiliario/rendimientos-capital-inmobiliario/concepto-rendimientos-capital-inmobiliario",
    "c04-rendimientos-capital-inmobiliario/rendimientos-integros",
    "c04-rendimientos-capital-inmobiliario/gastos-deducibles",
    "c04-rendimientos-capital-inmobiliario/gastos-deducibles/intereses-demas-gastos-financiacion-inmueble",
    "c04-rendimientos-capital-inmobiliario/gastos-deducibles/otros-gastos-necesarios-obtencion-rendimientos",
    "c04-rendimientos-capital-inmobiliario/gastos-deducibles/cantidades-destinadas-amortizacion",
    "c04-rendimientos-capital-inmobiliario/gastos-deducibles/compensacion-contratos-arrendamiento-anteriores-9-1985",
    "c04-rendimientos-capital-inmobiliario/gastos-no-deducibles",
    "c04-rendimientos-capital-inmobiliario/rendimiento-neto",
    "c04-rendimientos-capital-inmobiliario/reducciones-rendimiento-neto",
    "c04-rendimientos-capital-inmobiliario/reducciones-rendimiento-neto/arrendamiento-inmuebles-destinados-vivienda",
    "c04-rendimientos-capital-inmobiliario/reducciones-rendimiento-neto/arrendamiento-inmuebles-destinados-vivienda/cuadro-reducciones-arrendamiento",
    "c04-rendimientos-capital-inmobiliario/reducciones-rendimiento-neto/rendimientos-periodo-generacion-superior-dos-anos",
    "c04-rendimientos-capital-inmobiliario/rendimiento-neto-reducido",
    "c04-rendimientos-capital-inmobiliario/rendimiento-minimo-computable-caso-parentesco",
    "c04-rendimientos-capital-inmobiliario/rendimientos-capital-inmobiliario-estimados-operaciones-vinculadas",
    "c04-rendimientos-capital-inmobiliario/individualizacion-rendimientos-capital-inmobiliario",
    "c04-rendimientos-capital-inmobiliario/imputacion-temporal-rendimientos-capital-inmobiliario",
    "c04-rendimientos-capital-inmobiliario/declaracion-bienes-inmuebles/consideraciones-generales",
    "c04-rendimientos-capital-inmobiliario/declaracion-bienes-inmuebles/datos-particulares-inmueble/general",
    "c04-rendimientos-capital-inmobiliario/declaracion-bienes-inmuebles/datos-particulares-inmueble/particular",
    "c04-rendimientos-capital-inmobiliario/caso-practico",
    "c10-regimenes-especiales-imputacion-atribucion-rentas/regimen-imputacion-rentas-inmobiliarias/concepto-requisitos",
    "c10-regimenes-especiales-imputacion-atribucion-rentas/regimen-imputacion-rentas-inmobiliarias/determinacion-importe-renta-imputable",
    "c10-regimenes-especiales-imputacion-atribucion-rentas/regimen-imputacion-rentas-inmobiliarias/individualizacion-rentas-inmobiliarias",
    "c10-regimenes-especiales-imputacion-atribucion-rentas/regimen-imputacion-rentas-inmobiliarias/declaracion-rentas-inmobiliarias-imputadas",
    "c10-regimenes-especiales-imputacion-atribucion-rentas/regimen-imputacion-rentas-inmobiliarias/ejemplo-imputacion-rentas-inmobiliarias",
]

PDFS = [
    ("https://ine.es/daco/daco42/irav/meto_IRAV.pdf", "ine-irav-metodologia", LICENSE_INE),
    ("https://www.bde.es/f/webbde/Secciones/Publicaciones/Folletos/Guia%20de%20acceso%20al%20prestamo%20hipotecario/folletoGuiaHipotecaria_BDE_02.pdf",
     "bde-guia-prestamo-hipotecario", LICENSE_BDE),
]
# fmt: on


def all_sources() -> list[Source]:
    sources = [Source("boe", i, s, LICENSE_BOE, articles=a) for i, s, a in BOE_LAWS]
    sources += [Source("diario", i, s, LICENSE_BOE) for i, s in BOE_DIARIO_DOCS]
    sources += [
        Source("aeat", p, f"irpf2025-{p[:3]}-{p.rsplit('/', 1)[-1]}", LICENSE_AEAT)
        for p in AEAT_PAGES
    ]
    sources += [Source("pdf", u, s, lic) for u, s, lic in PDFS]
    return sources


# ----------------------------------------------------------------------------- converters


def _text(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _render_xml_blocks(parent: ET.Element) -> list[str]:
    """Paragraphs and tables of a BOE ``<version>`` or ``<texto>``; amendment notes dropped."""
    lines = []
    for el in parent:
        if el.tag == "blockquote" or (el.get("class") or "").startswith("nota_pie"):
            continue  # "Se modifica por el art. 3 del Real Decreto-ley..." and footnotes
        if el.tag == "table":
            for row in el.iter("tr"):
                cells = [_text(c) for c in row if c.tag in ("td", "th")]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
            continue
        text = _text(el)
        if text:
            lines.append(text)
    return lines


def _article_number(block_id: str) -> int | None:
    m = re.fullmatch(r"a(\d+)(-\d+)?", block_id)
    return int(m.group(1)) if m else None


def _in_ranges(n: int | None, ranges: tuple[tuple[int, int], ...]) -> bool:
    return n is not None and any(lo <= n <= hi for lo, hi in ranges)


def boe_consolidated_to_markdown(
    xml_text: str, title: str, url: str, as_of: str, articles: tuple[tuple[int, int], ...] = ()
) -> tuple[str, str]:
    """Markdown of a consolidated law in force on ``as_of`` (YYYY-MM-DD), and its version date.

    Every ``<bloque>`` has one ``<version>`` per amendment; we keep the last one already in
    force on ``as_of``. Blocks not yet in force are dropped. With ``articles``, only those
    article ranges are kept (no preamble, no headings).
    """
    cutoff = as_of.replace("-", "")
    root = ET.fromstring(xml_text)
    out = [f"# {title}", "", f"Fuente: {url}", ""]
    latest = ""
    for block in root.iter("bloque"):
        kind, block_id = block.get("tipo"), block.get("id", "")
        if kind in ("firma", "nota_inicial"):
            continue
        if articles and not (
            kind == "precepto" and _in_ranges(_article_number(block_id), articles)
        ):
            continue
        # a version with no date is not known to be in force: skip it
        versions = [
            v for v in block.findall("version") if "" < v.get("fecha_vigencia", "") <= cutoff
        ]
        if not versions:
            continue
        version = versions[-1]
        latest = max(latest, version.get("fecha_vigencia", ""))
        lines = _render_xml_blocks(version)
        if not lines:
            continue
        if kind == "encabezado":
            out += [f"## {'. '.join(lines)}", ""]
        elif kind == "preambulo":
            out += ["## Preámbulo", "", *_paragraphs(lines)]
        else:
            first = version.find("p")
            heading = (
                lines.pop(0) if first is not None and first.get("class") == "articulo" else None
            )
            out += [f"### {heading or block.get('titulo', block_id)}", "", *_paragraphs(lines)]
    date = f"{latest[:4]}-{latest[4:6]}-{latest[6:]}" if latest else ""
    return "\n".join(out).strip() + "\n", date


def boe_diario_to_markdown(xml_text: str, url: str) -> tuple[str, str]:
    """Markdown of a BOE daily-gazette document (``diario_boe/xml.php``) and its title."""
    root = ET.fromstring(xml_text)
    title = _text(root.find("metadatos/titulo"))
    body = root.find("texto")
    lines = _render_xml_blocks(body) if body is not None else []
    return "\n".join(
        [f"# {title}", "", f"Fuente: {url}", "", *_paragraphs(lines)]
    ).strip() + "\n", title


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank line between paragraphs, but keep table rows together."""
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not (line.startswith("|") and nxt.startswith("|")):
            out.append("")
    return out


class _MainContent(HTMLParser):
    """Text of ``<main>`` as Markdown-ish lines: headings, paragraphs, list items, table rows."""

    BLOCK = {"p", "div", "ul", "ol", "table", "tr", "br", "section", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0  # >0 while inside <main>
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.prefix = ""
        self.skip = 0

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if text:
            self.lines.append(self.prefix + text)
            self.prefix = ""
        self.buf = []  # an empty flush keeps the prefix: <li><p>text</p></li> stays a list item

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth += 1
            return
        if not self.depth:
            return
        if tag in ("script", "style", "nav"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self._flush()
            self.prefix = "- "
        elif tag in ("td", "th"):
            self.buf.append(" | ")
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "main" and self.depth:
            self._flush()
            self.depth -= 1
        elif self.depth and tag in ("script", "style", "nav"):
            self.skip = max(self.skip - 1, 0)
        elif self.depth and (
            tag in self.BLOCK or tag in ("li", "h1", "h2", "h3", "h4", "h5", "h6")
        ):
            self._flush()

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.buf.append(data)


def aeat_page_to_markdown(page_html: str, url: str) -> tuple[str, str]:
    """Markdown of one AEAT manual page (only ``<main>``) and its title (the ``<h1>``)."""
    parser = _MainContent()
    parser.feed(page_html)
    parser.close()
    # table rows come out as "| a | b" (each cell opens with " | "): close them
    lines = [html.unescape(ln + " |" if ln.startswith("| ") else ln) for ln in parser.lines]
    title = next((ln[2:] for ln in lines if ln.startswith("# ")), url.rsplit("/", 1)[-1])
    if "Generar PDF" in lines:  # the "export to PDF" dialog sits inside <main>: drop it
        lines = lines[: lines.index("Generar PDF")]
    body = [ln for ln in lines if not ln.startswith("# ")]
    return "\n".join(
        [f"# {title}", "", f"Fuente: {url}", "", *_paragraphs(body)]
    ).strip() + "\n", title


# ----------------------------------------------------------------------------- download


def _get(client: httpx.Client, url: str, accept: str | None = None) -> httpx.Response:
    headers = {"Accept": accept} if accept else {}
    for attempt in range(3):
        try:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            time.sleep(PAUSE_S)
            return response
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch(client: httpx.Client, source: Source, as_of: str) -> tuple[Path, dict]:
    """Download one source, write it under ``CORPUS_DIR`` and return its manifest entry."""
    entry = {"kind": source.kind, "id": source.id, "license": source.license}
    if source.kind == "boe":
        meta = _get(client, BOE_API.format(id=source.id, part="metadatos"), "application/xml")
        metadata = ET.fromstring(meta.text).find("data/metadatos")
        title = _text(metadata.find("titulo"))
        if _text(metadata.find("estatus_derogacion")) == "S":
            raise ValueError(f"{source.id} ({title}) is repealed: drop it from BOE_LAWS")
        url = BOE_HTML.format(id=source.id)
        xml = _get(client, BOE_API.format(id=source.id, part="texto"), "application/xml")
        text, version = boe_consolidated_to_markdown(xml.text, title, url, as_of, source.articles)
        if source.articles:
            ranges = ", ".join(f"{lo}-{hi}" if lo != hi else str(lo) for lo, hi in source.articles)
            text = text.replace(
                f"Fuente: {url}\n", f"Fuente: {url}\n\nSolo los artículos {ranges}.\n", 1
            )
        entry |= {"title": title, "url": url, "as_of": as_of, "latest_version_in_force": version}
        path = CORPUS_DIR / "boe" / f"{source.slug}.md"
    elif source.kind == "diario":
        url = BOE_DIARIO.format(id=source.id)
        xml = _get(client, url)
        text, title = boe_diario_to_markdown(
            xml.text, f"https://www.boe.es/diario_boe/txt.php?id={source.id}"
        )
        entry |= {"title": title, "url": url}
        path = CORPUS_DIR / "boe_diario" / f"{source.slug}.md"
    elif source.kind == "aeat":
        url = AEAT_BASE + source.id + ".html"
        page = _get(client, url)
        text, title = aeat_page_to_markdown(page.text, url)
        entry |= {"title": f"Manual práctico de Renta 2025. {title}", "url": url}
        path = CORPUS_DIR / "aeat" / f"{source.slug}.md"
    elif source.kind == "pdf":
        response = _get(client, source.id)
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"{source.id} did not return a PDF")
        path = CORPUS_DIR / "pdf" / f"{source.slug}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        entry |= {"title": source.slug, "url": source.id}
        return path, entry
    else:
        raise ValueError(f"unknown source kind {source.kind!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--as-of", default=AS_OF, help="version date of the consolidated laws")
    parser.add_argument("--only", choices=["boe", "diario", "aeat", "pdf"], help="one kind only")
    parser.add_argument("--force", action="store_true", help="download files that already exist")
    args = parser.parse_args(argv)

    manifest_path = CORPUS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    sources = [s for s in all_sources() if args.only in (None, s.kind)]
    failures = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    ) as client:
        for n, source in enumerate(sources, 1):
            existing = [
                p for p in CORPUS_DIR.glob(f"*/{source.slug}.*") if p.suffix in (".md", ".pdf")
            ]
            if existing and not args.force:
                print(f"[{n:>2}/{len(sources)}] skip  {existing[0].relative_to(CORPUS_DIR)}")
                continue
            try:
                path, entry = fetch(client, source, args.as_of)
            except Exception as exc:  # keep going: one broken source should not stop the rest
                failures.append(source.slug)
                print(f"[{n:>2}/{len(sources)}] FAIL  {source.slug}: {exc}", file=sys.stderr)
                continue
            data = path.read_bytes()
            relative = str(path.relative_to(CORPUS_DIR))
            manifest[relative] = entry | {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            print(f"[{n:>2}/{len(sources)}] ok    {relative}  ({len(data):,} bytes)")
    manifest_path.write_text(
        json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=1)
    )
    print(f"{len(manifest)} files in {manifest_path}; {len(failures)} failures {failures or ''}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
