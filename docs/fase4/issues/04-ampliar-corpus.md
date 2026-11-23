# Fase 4 · Ampliar el corpus con las fuentes que piden las palancas

**Responsable:** Bernardo · **Hito:** H2 · **Depende de:** la issue 01, que dice qué palancas se
quedan sin cita

## Contexto

Cada palanca del playbook tiene que apoyarse en una cita literal del corpus de la fase 3. Hoy el
corpus (`rag/CORPUS.md`) tiene normativa estatal, el manual de la AEAT, SERPAVI y las zonas
tensionadas. **No tiene normativa autonómica**: bonificaciones y tipos reducidos del ITP (jóvenes,
familia numerosa, VPO), deducciones autonómicas por alquiler ni el régimen del alquiler de
temporada en la jurisprudencia. Sin esas fuentes, las palancas no tienen fundamento citable.

## Qué hay que hacer

1. Elegir las fuentes **oficiales** que faltan:
   - textos refundidos autonómicos del ITP, al menos las comunidades con más peso en el banco:
     Madrid, Cataluña, Andalucía y Comunitat Valenciana;
   - lo que pida la issue 01.
   - Nada de blogs ni portales: BOE, boletines autonómicos, AEAT.
2. Añadirlas a `rag/download_corpus.py`, que debe seguir siendo reproducible y fijado a la versión
   vigente en una fecha, y documentarlas en `rag/CORPUS.md` con su fuente y licencia.
3. Reingestar y reindexar.
4. Volver a correr `rag/evaluate.py` sobre el conjunto dorado para comprobar que los documentos
   nuevos **no empeoran** el Recall@5 y el MRR de las 51 preguntas actuales.
5. Añadir 5 preguntas doradas o más sobre los documentos nuevos.
6. Registrar el resultado en EXPERIMENTS.md con la skill `registrar-experimento`.

## Criterios de aceptación

- `uv run python -m rag.download_corpus` descarga también los documentos nuevos.
- La tabla de antes y después de Recall@5 y MRR está en EXPERIMENTS.md, con la explicación de
  cualquier cambio.
- Las palancas de la issue 01 que estaban sin cita pasan a tenerla.

## Cómo verificar

```bash
uv run python -m rag.download_corpus
uv run python -m rag.evaluate          # en la DGX, con la skill lanzar-dgx si tarda
uv run pytest -q tests/test_playbook.py tests/test_gold.py
```
