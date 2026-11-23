# Fase 4 · Tool `screen_properties`: cribado en lote con el motor

**Responsable:** Bernardo · **Hito:** H2 · **Depende de:** `agent/case_file.py` y
`agent/analysis.analyze` (núcleo, H1)

## Contexto

La tarea estrella de la propuesta es "Te paso 15 pisos en un CSV. Quédate con los que den más de
un 4,5 % neto después de impuestos cumpliendo la ley, ordénalos, dime por qué descartas el resto".
Con un modelo de 1,7B, ir piso a piso son más de 45 pasos. `screen_properties` hace el cribado
mecánico en **una** llamada, y el agente solo profundiza en los finalistas y en los que casi pasan.
Diseño en `docs/fase4/diseno.md`.

## Qué hay que hacer

`agent/tools/screening.py` con:

```python
@tool
def screen_properties(
    min_net_yield_pct: float | None = None,
    max_price: float | None = None,
    min_cash_on_cash_pct: float | None = None,
    require_legal_rent: bool = True,
    near_miss_pct: float = 0.5,
) -> dict[str, Any]:
    """Screen every property in the case file with the rule engine..."""
```

1. La tool lee los pisos del expediente activo con `agent.case_file.current()`; no recibe la
   lista como argumento.
2. Para cada piso llama a `agent.analysis.analyze(property, profile)`, que da el mismo análisis
   que `analyze_property`.
   - La renta que cuenta es `min(renta pedida, tope legal)` cuando `require_legal_rent`.
   - Si la renta pedida supera el tope, el piso lleva el aviso `rent_above_legal_cap`.
3. Devuelve tres grupos:
   - `passed`: ordenados por neto descendente;
   - `rejected`: cada uno con su `reason` en español y la cifra que falla, por ejemplo
     "neto 3,8 % < 4,5 %";
   - `near_miss`: los que fallan por `near_miss_pct` puntos o menos. Son candidatos para buscar
     palancas.
4. Cada cifra calculada se registra con `case.add_figure(..., tool="screen_properties")`.
5. La salida es compacta, porque va al contexto de un modelo pequeño: una fila por piso con id,
   precio, neto, cash-on-cash (si hay financiación) y motivo.

## Criterios de aceptación

- Los tests en `tests/test_screening.py` usan un expediente sintético de 15 pisos que cubra todos
  los motivos de descarte: neto bajo, precio alto, renta por encima del tope y dato faltante.
  - Un dato que falta no tumba el cribado: el piso va a `rejected` con el motivo "falta X".
- Las cifras coinciden con llamar a `analyze` piso a piso.
- La tool se registra en el agente (`agent/react_agent.py`, junto a las demás).

## Cómo verificar

```bash
uv run pytest -q tests/test_screening.py
uv run ruff check && uv run ruff format
```
