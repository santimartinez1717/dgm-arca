# Conjunto dorado de la fase 3

- `gold.jsonl`: 59 preguntas con respuesta en el corpus. Las 51 primeras son las de la fase 3;
  las 8 últimas (`ccaa-*`, `lis-01`, `lec-*`) preguntan por los documentos que añadió la
  issue #13 (tributos cedidos de cuatro comunidades, tipo del Impuesto sobre Sociedades y
  subastas de la LEC).
- `unanswerable.jsonl`: 5 preguntas que el corpus **no** responde, para comprobar que
  `/rag` dice «no lo sé». `none-02` (el ITP de la Comunidad de Madrid) pasó a `gold.jsonl`
  como `ccaa-01` cuando entró el texto refundido madrileño.
- `temporal.jsonl`: 17 preguntas con fecha para el derecho aplicable en una fecha
  ([`docs/fase3/fase3.md`](../../docs/fase3/fase3.md), sección 8). Cada una anota ley, artículo (`block_id`
  del BOE) y cita, y se resuelve a la versión vigente en su `date`; `control` marca las que
  tienen la misma respuesta hoy.

## Formato: por artículo y cita, no por id de fragmento

Los ids de fragmento (`<doc_id>-<índice>`) cambian con cada troceado y con cada parámetro.
Por eso cada pregunta guarda **dónde** está la respuesta, y `rag/gold.py` la traduce a ids para
el troceado que se esté evaluando:

```json
{"id": "lau-04",
 "question": "¿Cuánta fianza debo pedir al firmar un alquiler de vivienda?",
 "answer": "Una mensualidad de renta en metálico (dos en uso distinto de vivienda).",
 "evidence": [{"source": "boe/lau.md", "section": "Artículo 36",
               "quote": "fianza en metálico en cantidad equivalente a una mensualidad de renta en el arrendamiento de viviendas"}],
 "notes": "opcional"}
```

- `source`: ruta dentro de `rag/corpus/`.
- `section`: encabezado bajo el que está la cita (`Artículo 36` casa con
  `### Artículo 36. Fianza.`, no con `Artículo 36 bis`). Se omite en documentos sin artículos.
- `quote`: copiada **literal** del Markdown (los espacios se normalizan). Tiene que ser única
  dentro de la sección.
- Varias entradas en `evidence` significan sitios **igual de válidos**: cada uno responde por sí
  solo. Pasa con la amortización del 3 % (ley, reglamento y manual de la AEAT) y en otras
  seis preguntas.

Un fragmento es relevante si contiene al menos la mitad de alguna cita. Con solape, una cita
corta suele caber entera en dos fragmentos seguidos, y cualquiera de los dos responde. Una
pregunta se considera acertada a k si **alguno** de sus fragmentos relevantes está entre los k
primeros.

```bash
uv run python -m rag.gold -v       # comprueba todas las citas y cuántos fragmentos tocan
```

## Cómo se escribió

Leyendo el corpus, artículo a artículo, con la pregunta que haría alguien que compra para
alquilar. Las preguntas **no copian** el texto de la norma («¿puedo cobrarle los honorarios de
la agencia?» frente a «gastos de gestión inmobiliaria»). Con preguntas copiadas, BM25 lo tendría
demasiado fácil.

| Bloque | Preguntas |
|---|---|
| LAU | 12 |
| Ley 12/2023 y RDL 29/2026 | 6 |
| IRPF (ley, reglamento y Manual de Renta 2025) | 12 |
| ITP, IVA, IBI, plusvalía, Catastro | 9 |
| Hipoteca (Ley 5/2019 y folleto del BdE) | 5 |
| Propiedad horizontal | 1 |
| Zonas tensionadas, SERPAVI, IRAV | 6 |

## Preguntas con trampa (anotadas en `notes`)

- **Conflictos entre fuentes.** El Manual de Renta 2025 da porcentajes de reducción de una
  redacción anterior del art. 23.2 LIRPF (`aeat-03` frente a `irpf-04`). El folleto del BdE,
  anterior a 2019, habla de 14 días de oferta vinculante; la Ley 5/2019 exige 10 días naturales
  (`hip-03`). El tope del 2 % del RDL 29/2026 convive con la regla general del IRAV (`rdl-01`).
- **Respuesta repartida.** En `lau-08` el 10 % y la lista de supuestos están en párrafos
  distintos. En `iva-01` el 10 % está en la cabecera del apartado y no en la cita. Con
  fragmentos pequeños, el fragmento relevante no basta para responder del todo.
- **Tablas.** `aeat-03`, `rdl-02`, `zon-01` y `zon-03` tienen la respuesta en una fila de tabla.
