# Corpus de la fase 3

Normativa y guías oficiales sobre comprar una vivienda para alquilarla en España. El corpus no
está en git (`rag/corpus/*` está en `.gitignore`); se regenera con:

```bash
uv run python -m rag.download_corpus          # ~2 min; salta lo que ya existe (--force para rehacer)
uv run python -m rag.ingest                   # comprobar: 58 documentos, ~3,4 M caracteres
```

El script escribe `rag/corpus/manifest.json` con la URL, la licencia, la fecha de la versión y
el sha256 de cada fichero. También guarda en `rag/corpus/versions/<ley>.jsonl` cada versión de
cada artículo del BOE con sus fechas de vigencia (2.985 versiones), para la recuperación por
fecha de `rag/temporal.py`. `rag/ingest.py` no lee esos ficheros.

## Fuentes

| Carpeta | Qué | Cuántos | Cómo se descarga |
|---|---|---|---|
| `boe/` | Leyes consolidadas: LAU, Ley 12/2023 de vivienda, RDL 29/2026, LIRPF y su reglamento, TRLITPAJD, TRL del Catastro, Ley 5/2019 de crédito inmobiliario, Ley de Propiedad Horizontal, TRLRHL (solo arts. 60-77, IBI, y 104-110, plusvalía) y LIVA (solo arts. 20, 90 y 91). Desde la issue #13, también los textos de tributos cedidos de Madrid, Cataluña, Andalucía y la Comunitat Valenciana, la Ley del Impuesto sobre Sociedades (solo art. 29) y la LEC (solo arts. 643-675, subastas) | 17 | API de datos abiertos del BOE, XML por artículos → Markdown con un `### Artículo N` por artículo |
| `boe_diario/` | Resoluciones del sistema de índices de precios de referencia (SERPAVI, 2024 y 2026) y las ocho relaciones trimestrales de zonas tensionadas (mar. 2024 – jul. 2026) con su corrección de erratas | 11 | `diario_boe/xml.php` → Markdown |
| `aeat/` | Manual práctico de Renta 2025: capítulo 4 (rendimientos del capital inmobiliario) y régimen de imputación de rentas inmobiliarias del capítulo 10 | 28 | HTML de la sede, solo el `<main>` → Markdown, una página por fichero |
| `pdf/` | Metodología del IRAV (INE, dic. 2024) y folleto del Banco de España sobre préstamos hipotecarios | 2 | PDF tal cual; `rag/ingest.py` lo lee con pypdf |

## Licencias

- **BOE** (`boe/`, `boe_diario/`): reutilización libre citando la fuente y sin desnaturalizar
  el contenido (Ley 37/2007 de reutilización de la información del sector público, RD
  1495/2011 y aviso legal del BOE). Los textos consolidados no tienen valor jurídico oficial.
  Las cuatro normas autonómicas salen de su boletín (BOCM, DOGC, BOJA, DOGV); las tomamos de
  la consolidación que publica el BOE, con su misma licencia.
- **AEAT** (`aeat/`): reutilización con cita de la fuente según el aviso legal de la sede
  electrónica (Ley 37/2007).
- **INE** (`pdf/ine-irav-metodologia.pdf`): reutilización con cita de la fuente según el
  aviso legal del INE.
- **Banco de España** (`pdf/bde-guia-prestamo-hipotecario.pdf`): reproducción permitida
  citando la fuente.

Cada documento empieza por su título y una línea `Fuente: <url>`, así que la cita viaja con el
texto hasta los fragmentos.

## Decisiones

- **Versión fijada.** Los textos consolidados cambian (la LAU tiene versión del 13/11/2026).
  Cada artículo se toma en la versión vigente el `--as-of` (por defecto 2026-11-22), no en la
  última, para que dos descargas en días distintos den el mismo corpus y el conjunto dorado
  no se quede apuntando a un texto que ya no existe.
- **Versiones sin fecha fuera.** Una versión sin `fecha_vigencia` no se toma por vigente (le
  pasa al art. 6 bis del reglamento del IRPF). Hasta el 23/11 sí se tomaba, y por eso el
  corpus de ese día cambió ligeramente (EXPERIMENTS.md).
- **Sin notas de modificación.** Se quitan los «Se modifica por el art. X de…» y las notas al
  pie: duplican referencias a otras leyes y meterían ruido en BM25.
- **Leyes enteras salvo dos.** LIRPF y su reglamento van completos aunque gran parte no trate
  de alquileres: son distractores realistas para medir la recuperación. TRLRHL y LIVA se
  recortan porque son enormes y solo nos importan el IBI, la plusvalía y el IVA de la vivienda.
- **Ley 11/2021 fuera.** Es una ley que modifica otras; el valor de referencia vive en el
  TRL del Catastro y el TRLITPAJD, que ya están.
- **Nada derogado.** El RDL 26/2026 (septiembre) no se convalidó y está derogado. Lo
  sustituyó el RDL 29/2026 de 6 de octubre, que es el que entra. El script se niega a
  descargar una ley con `estatus_derogacion = S`, y quita la «nota inicial» del BOE.
- **Sin interfaz de la AEAT.** El diálogo «Generar PDF… Cancelar» que la sede mete dentro de
  `<main>` se recorta: aparecía igual en las 28 páginas.
- **Metodología del SERPAVI fuera.** El PDF del ministerio devuelve 403 al descargarlo con un
  script; entran las resoluciones del BOE que lo determinan.
- **Normativa autonómica (issue #13).** Entran los textos de tributos cedidos de las cuatro
  comunidades con más peso en el banco: Madrid (DLeg 1/2010, `BOCM-m-2010-90068`), Cataluña
  (libro sexto del Código tributario, DLeg 1/2024), Andalucía (Ley 5/2021) y Comunitat
  Valenciana (Ley 13/1997). Los cuatro están consolidados en la misma API del BOE, así que se
  descargan igual que las leyes estatales y quedan fijados a la misma fecha. Van enteros:
  traen los tipos y reducciones del ITP y las deducciones autonómicas por alquiler, pero
  también sucesiones, juego e hidrocarburos, que hacen de distractores. El corpus crece un
  33 % (de ~2,6 a ~3,4 M caracteres). El resto de comunidades queda fuera por ahora.
- **Solo lo que piden las palancas.** De la Ley del Impuesto sobre Sociedades entra el art. 29
  (tipo de gravamen, palanca `buy_through_company`) y de la LEC los arts. 643-675, la subasta
  de bienes (palanca `boe_auction`). Enteras serían el doble del corpus y casi todo ruido.
