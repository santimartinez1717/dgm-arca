# Fase 4 · Tool `write_investment_report`: informe con cifras del expediente

**Responsable:** Bernardo · **Hito:** H2 · **Depende de:** `agent/case_file.py` (núcleo, H1)

## Contexto

La propuesta promete un informe final. Es una tool **con efecto observable**: escribe un fichero.
Por eso pide confirmación, igual que `save_to_portfolio`. La regla del diseño es que los números
los pone el motor, así que el informe **no recibe cifras del modelo**: las lee del expediente.
Diseño en `docs/fase4/diseno.md`.

## Qué hay que hacer

`agent/tools/report.py` con:

```python
@tool(requires_confirmation=True)
def write_investment_report(property_ids: list[str], title: str | None = None) -> dict[str, Any]:
    """Write a Markdown investment report for these properties to outputs/reports/..."""
```

1. La tool lee del expediente activo (`agent.case_file.current()`):
   - el perfil;
   - los pisos pedidos;
   - sus `figures`, en el escenario base y por palanca;
   - los supuestos (`assumptions`);
   - las preguntas abiertas.
2. Escribe `outputs/reports/<session_id>-<slug>.md` con estas secciones:
   - resumen;
   - tabla por piso;
   - palancas evaluadas (cuantificadas con su diferencia, cualitativas con su riesgo);
   - supuestos;
   - preguntas abiertas;
   - el **aviso obligatorio**: "Análisis orientativo con datos sintéticos; consulta a un asesor
     fiscal" (`docs/temas_ejemplo.md`).
3. Devuelve `{"path": ..., "n_properties": ..., "sections": [...]}`. No devuelve el texto
   completo, para no llenar el contexto.
4. Un id que no existe da un error claro con los ids disponibles. El error vuelve al modelo como
   observación.

## Criterios de aceptación

- Hay un test que comprueba que **toda cifra del informe** está en `case.figures`. Es la misma
  idea que el auditor del núcleo.
- Hay un test de que el aviso está siempre.
- `outputs/` sigue fuera de git.

## Cómo verificar

```bash
uv run pytest -q tests/test_report.py
uv run ruff check && uv run ruff format
```
