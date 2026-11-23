# Fase 4 · Campos opcionales de `/agent` e ingesta determinista de CSV

**Responsable:** Kike · **Hito:** H1 · **Depende de:** nada para la ingesta; el bucle (issue 11)
la usa

## Contexto

El profesor corrige llamando a `POST /agent`. El contrato de `api/schemas.py` no se puede romper,
pero sí se pueden añadir campos opcionales (`enunciado.tex`). Nuestro agente necesita una sesión
para la memoria multiturno y una confirmación para las tools con efecto, y devuelve más cosas que
una traza: palancas, escenarios, auditoría y expediente. La interfaz (issue 08) y la evaluación
(issue 06) leen esos campos.

La tarea estrella trae 15 pisos en un CSV pegado en el texto. Que un 1,7B los copie uno a uno
con `record_property` serían 15 pasos y 15 ocasiones de equivocarse. Por eso se parsean de forma
determinista **antes** del bucle.

## Qué hay que hacer

1. **`api/schemas.py`**, solo campos opcionales con valor por defecto:
   - `AgentRequest`: `session_id: str | None = None` y `confirm: bool = False`.
   - `AgentResponse`:
     - `session_id: str | None`;
     - `case_file: str | None` (el `render()`);
     - `levers: list[dict] = []` (lo que devolvió `find_levers`);
     - `scenarios: list[dict] = []` (los `scenarios` de cada `what_if`);
     - `open_questions: list[str] = []`;
     - `audit: dict | None` (el `AuditResult` y el número de rechazos).
   - Ajustar `api/app.py` para pasar `session_id` y `confirm` al agente.
   - Test de que un cliente con el contrato antiguo sigue funcionando.
2. **`agent/ingest.py`** con `extract_properties(task: str) -> tuple[list[Property], str]`:
   - Detecta bloques CSV en el texto: separador `,` o `;`, con cabecera, o dentro de bloques de
     código.
   - Mapea las columnas en español e inglés a los campos de `Property`: precio/price,
     municipio/ciudad/municipality, renta/alquiler/monthly_rent, m2/superficie/area_m2, valor de
     referencia, valor catastral, % suelo, obra nueva, renta anterior, IBI, comunidad,
     fecha_contrato…
   - Ids: los de la columna `id`, o `P1`…`Pn` si no hay.
   - Números en formato español: `180.000`, `4,5`.
   - Devuelve los pisos y el texto de la tarea con el CSV sustituido por "[15 pisos cargados en
     el expediente: P1…P15]", para no gastar contexto.
   - Las columnas desconocidas se ignoran y se reportan.
3. **Tests** `tests/test_ingest.py`:
   - CSV con `,` y con `;`;
   - cabeceras en español e inglés;
   - números en formato español;
   - celdas vacías;
   - un texto sin CSV no se toca;
   - un CSV de 15 pisos del banco (issue 05).

## Criterios de aceptación

- `uv run pytest -q tests/test_ingest.py tests/test_api.py` en verde.
- El contrato antiguo de `/agent` sigue funcionando sin cambios en el cliente.
