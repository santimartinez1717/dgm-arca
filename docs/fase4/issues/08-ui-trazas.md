# Fase 4 · UI de trazas: palancas, escenarios y auditor, más el GIF de la demo

**Responsable:** Kike · **Hito:** H3 · **Depende de:** los campos opcionales de `AgentResponse`
(núcleo, H1/H2)

## Contexto

`agent/ui.py` (Gradio) pinta la traza como tarjetas de colores. Es la herramienta de depuración y lo
que se enseña en los tres minutos de demo en vivo de la defensa. Nuestro agente devuelve más cosas
que una traza ReAct normal, y la UI tiene que enseñar justo lo que lo diferencia.

## Qué hay que hacer

1. Leer los campos opcionales de la respuesta de `POST /agent`. El núcleo los añade a
   `api/schemas.py` sin romper el contrato:
   - `session_id`;
   - `levers`: id, nivel, diferencia de neto, cita;
   - `scenarios`: dato dudoso, valores, resultado;
   - `open_questions`;
   - `audit`: aprobado o rechazos con su motivo;
   - `case_file`: el expediente renderizado.
2. Tarjetas nuevas:
   - **palanca**: verde si es legal, ámbar si es gris, rojo si es `illegal_warning`, con su cita;
   - **auditor**: rechazos en rojo, con la cifra que no cuadraba;
   - **escenarios**: tabla "si X / si Y".
   - Un panel lateral con el expediente.
3. Modo conversación: el `session_id` se mantiene entre envíos y se pueden contestar las
   `open_questions`. Selector de cerebro y una casilla para confirmar las tools con efecto
   (`confirm`).
4. Grabar un **GIF de la demo** para el README con la tarea del CSV de 15 pisos y una palanca.

## Criterios de aceptación

- `uv run python -m agent.ui` funciona contra la API local.
- Sin los campos opcionales (por ejemplo con otra versión de la API), la UI sigue funcionando.
- Hay un test de `render_trace` con una respuesta de ejemplo que incluye todos los campos nuevos.
- El GIF está en `docs/fase4/demo.gif` y enlazado desde el README.

## Cómo verificar

```bash
uv run pytest -q tests/test_agent_ui.py
uv run arca-api &   uv run python -m agent.ui
```
