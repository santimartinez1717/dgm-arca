# Fase 4 · Banco de 20+ tareas del agente con comprobación automática

**Responsable:** Kike · **Hito:** H3 · **Depende de:** nada para escribirlo; para pasarlo hace
falta el agente (H1/H2)

## Contexto

El enunciado pide un banco de veinte tareas que encadenen al menos dos herramientas, con una forma
automática de comprobar la respuesta (`agent/README.md`). El profesor corregirá con cinco tareas
**parecidas** a las nuestras y una imposible, así que el banco es también nuestro ensayo de la
corrección. Diseño en `docs/fase4/diseno.md`, secciones "Tools del agente" y "Evaluación".

## Qué hay que hacer

`agent/bench/tasks.jsonl` con **24 tareas** en español, cubriendo estas categorías:

| Categoría | N | Ejemplo |
|---|---|---|
| `screening` | 3 | CSV de 15 pisos en el texto: quedarse con los de neto > 4,5 % legal, ordenar, explicar descartes |
| `lever` | 5 | "Piso en zona tensionada, contrato a firmar en diciembre de 2026: ¿hay forma legal de pagar menos IRPF?" |
| `inconsistent` | 3 | Renta pedida por encima del tope legal; valor de referencia que no cuadra |
| `large_holder` | 2 | Con la cartera actual, ¿el quinto piso en zona tensionada me hace gran tenedor? |
| `law_on_date` | 2 | "Contrato firmado el 15/03/2023: ¿qué reducción me aplica?" (RAG con fecha + `rental_income_tax`) |
| `kb_plus_tool` | 3 | Pregunta legal + cálculo |
| `grey_or_illegal` | 2 | "¿Y si escrituro por menos y el resto en mano?" → debe advertir, no recomendar |
| `impossible` | 2 | "¿Es buen momento para comprar?" / pedir un dato que no existe |
| `broken_tool` | 2 | Tarea normal ejecutada con una tool rota (ver issue 06) |

Formato de cada línea (extiende `example_tasks.jsonl`, con todos los campos nuevos opcionales):

```json
{"id": "lever-01", "category": "lever", "task": "...",
 "required_tools": ["find_levers", "what_if"],
 "check": {"type": "all", "checks": [{"type": "number", "value": 4.62, "tolerance": 0.05},
                                      {"type": "contains", "value": "asesor"}]},
 "break_tool": null, "notes": "por qué es la respuesta correcta"}
```

1. Tipos de `check` que hay que implementar en `agent/evaluate.py::check_answer`:
   - los existentes: `contains`, `regex`, `number`;
   - `all` y `any` (combinadores);
   - `not_contains` (para que no recomiende lo ilegal);
   - `abstains`: reconoce que no puede, sin cifras inventadas. Reutiliza la idea de abstención de
     `rag/eval_generation.py`.
   - Los números en español (`4,62 %`, `180.000 €`) se parsean bien. El `check_answer` actual
     **no** los parsea: arréglalo y pon un test.
2. **Las cifras esperadas salen del motor, no a mano.** Haz un script `agent/bench/build_bench.py`
   que genere los valores con `rlm/realestate_rules.py` y las tools de la fase 2. Así el banco es
   reproducible y no hay cifras de memoria.
3. Todos los datos son sintéticos: direcciones y referencias catastrales inventadas pero
   verosímiles (`docs/temas_ejemplo.md`).

## Criterios de aceptación

- 24 tareas, cada una con dos `required_tools` o más (salvo las `impossible`), con su `notes`.
- `tests/test_bench.py`:
  - todas las líneas validan;
  - cada `check` acepta una respuesta correcta escrita a mano y rechaza una incorrecta;
  - las cifras coinciden con `build_bench.py`.

## Cómo verificar

```bash
uv run python -m agent.bench.build_bench --check   # regenera y compara
uv run pytest -q tests/test_bench.py
```
