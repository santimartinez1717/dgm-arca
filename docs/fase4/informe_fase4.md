# Informe · Sección 6. Fase 4: el agente (borrador)

> Borrador para `docs/informe_plantilla.md`, sección 6 (página y media). Las cifras marcadas
> **⟦pendiente⟧** salen de `reports/fase4/phase4_eval.md` cuando se ejecute
> `agent.evaluate` en la DGX. No se rellenan a mano: cada una necesita su entrada en
> EXPERIMENTS.md. Diagrama en [`arquitectura.md`](arquitectura.md).

## 6.1 El bucle y sus decisiones

Umbral es un analista de inversión en vivienda para alquilar. El agente recibe la tarea, a
menudo con una tabla de pisos pegada, y responde con las cifras, las palancas legales que
mejoran la rentabilidad y sus citas. Hay un solo bucle ReAct (`agent/react_agent.py`) y dos
etapas en código, antes y después:

- **Ingesta determinista** (`agent/ingest.py`). El CSV de la tarea se lee en código y pasa al
  expediente. Con un modelo de 1,7B, copiar 15 pisos con `record_property` serían 15 pasos y
  15 ocasiones de equivocarse. En el contexto, la tabla se queda en una línea («15 pisos
  cargados en el expediente: P01…P15»).
- **Expediente anclado** (`agent/case_file.py`). Los pisos, el perfil del inversor, cada cifra
  que calculó una tool y las preguntas abiertas van siempre al principio del contexto y no se
  resumen. Lo que se resume al acercarse al presupuesto de tokens son las observaciones
  antiguas, que ya están en el expediente.
- **Auditor determinista** (`agent/auditor.py`). Cada cifra de la respuesta tiene que salir de
  una observación del motor, y cada cita de un pasaje recuperado en esa ejecución. Si no, la
  respuesta vuelve al bucle como observación, como mucho dos veces. Así el cerebro no puede
  inventar un número, y el modelo de la fase 1 nunca es la fuente de una cifra.
- **Guardarraíles.**
  - Timeout por tool, y el error de una tool vuelve como observación para que el agente decida.
  - Aviso a la segunda llamada idéntica y respuesta forzada a la tercera.
  - Presupuesto de tokens.
  - Las tools con efecto (guardar en la cartera, el informe) solo se ejecutan con
    `confirm=true`.

El cerebro no calcula ni recuerda la ley. **Busca palancas**: cambios legales que mejoran el
caso, como la fecha de firma frente al RDL 29/2026, una rebaja de la renta de más del 5 %, la
excepción del 10 % por rehabilitación o el precio máximo de oferta. Salen de un playbook curado
(`agent/playbook/levers.yaml`). `what_if` recalcula cada una con el motor, y las trampas
(`illegal_warning`) solo se reconocen para advertir de ellas.

## 6.2 El banco

`agent/bench/tasks.jsonl` tiene 24 tareas en español, cada una con al menos dos tools
requeridas y un `check` automático:

| Categoría | N | Qué mide |
|---|---|---|
| `screening` | 3 | CSV de 15 pisos; quedarse con los que pasan con la renta **legal**. Dos pasan solo con la renta pedida, que supera el tope |
| `lever` | 5 | Palancas con cifra: fecha de firma, rebaja de renta, excepción del 10 %, obra nueva frente a segunda mano, precio máximo |
| `inconsistent` | 3 | Renta por encima del tope, valor de referencia dudoso (bifurcar), renta mensual que es anual |
| `large_holder` | 2 | Mismo quinto piso: gran tenedor en Santiago, cuya declaración baja el umbral, y no en A Coruña |
| `law_on_date` | 2 | Reducción del IRPF según la fecha del contrato |
| `kb_plus_tool` | 3 | Pregunta legal + cálculo |
| `grey_or_illegal` | 2 | Pagar parte en negro y temporada fraudulenta: advertir, no calcular |
| `impossible` | 2 | Precios de 2027 y Euríbor de 2030: abstenerse sin cifras |
| `broken_tool` | 2 | Una tool que falla (error) o que se cuelga (timeout) |

**Ninguna cifra esperada está escrita a mano.** `agent/bench/build_bench.py` las calcula con
`agent.analysis.analyze`, el mismo camino que `analyze_property`, y un test comprueba que el
fichero coincide. El `check` lee los números en formato español: el original quitaba la coma,
y «4,62 %» se leía como 462.

## 6.3 Resultados por cerebro

`agent.evaluate --brains base rlm thinking --configs full no_auditor no_playbook flat_memory`.
Cada tarea se ejecuta aislada, con un expediente y una cartera nuevos. Intervalos de Wilson al
95 % y McNemar exacto entre cerebros.

| Cerebro | Éxito | IC 95 % | Pasos | Tokens | Tools requeridas | Abstención |
|---|---|---|---|---|---|---|
| base | ⟦pendiente⟧ | | | | | |
| rlm (GRPO 2) | ⟦pendiente⟧ | | | | | |
| thinking | ⟦pendiente⟧ | | | | | |

**Qué esperamos ver**, a falta de medirlo:

- **`thinking` debería ganar en las palancas y en `kb_plus_tool`.** En la fase 3, pensar subió
  el porcentaje de veces que se cita el pasaje correcto del 50 % al 70 %.
- **`rlm` no tiene ventaja en las cifras,** porque el auditor las bloquea. Su riesgo es el
  formato de tool call: en la fase 2, el adaptador bajó la selección de tool de 39/40 a 27/40.

La pregunta «¿ayuda haber entrenado?» se responde con la selección de tools y argumentos, los
pasos y el éxito.

## 6.4 Ablaciones

| Configuración | Qué se quita | Éxito (base) |
|---|---|---|
| `full` | nada | ⟦pendiente⟧ |
| `no_auditor` | la auditoría de cifras y citas | ⟦pendiente⟧ |
| `no_playbook` | `find_levers` y `what_if` | ⟦pendiente⟧ |
| `flat_memory` | el expediente anclado (solo historial) | ⟦pendiente⟧ |

## 6.5 JSON frente a código (CodeAct)

`agent/code_agent.py` pone el `CodeAgent` de smolagents en las mismas condiciones que el agente
JSON: las mismas tools a través del mismo registro, el mismo modelo compartido, el mismo
expediente y los mismos `max_steps` y timeout. Solo cambia el formato de la acción.

- **En la prueba con un modelo guionizado,** el cribado de 15 pisos cabe en **un paso de
  código**, con un `for` y 15 llamadas a `analyze_property`. El agente JSON necesita una tool
  call por paso.
- **La pregunta es si un 1,7B escribe ese Python bien.**

| Agente | Cerebro | Éxito | Pasos | Tokens | Errores de código |
|---|---|---|---|---|---|
| JSON | base / thinking | ⟦pendiente⟧ | | | — |
| Código | base / thinking | ⟦pendiente⟧ | | | |

## 6.6 Trazas

`agent.evaluate` guarda cinco trazas en `reports/fase4/trazas/`: dos buenas, dos malas y una
con la tool rota, como tarjetas de pensamiento, acción y observación. Es el mismo formato que
`agent/ui.py`. Aquí van dos buenas y dos malas, comentadas: ⟦pendiente⟧.

---

## Para la sección 1: un ejemplo de principio a fin

La tarea `lever-01` del banco, con las cifras del motor:

> *Compro un piso de segunda mano de 70 m² en Madrid por 200.000 €, al contado. El inquilino
> anterior pagaba 1.000 € al mes y al nuevo le voy a cobrar 1.030 €. Pensaba firmar el
> 15/12/2026. […] ¿Hay alguna forma legal de pagar menos IRPF por el alquiler?*

1. `analyze_property(P1)`: el contrato, firmado desde el 01/12/2026 y con la renta un 3 % por
   encima de la anterior, tiene una reducción del 40 % (RDL 29/2026). Tributan 4.346,40 €.
2. `find_levers(P1)`: aplica la palanca de la fecha de firma frente al RDL 29/2026, con su
   cita del BOE. Todavía no está en el playbook semilla; la añade el issue #1.
3. `what_if(P1, overrides={"contract_date": "2026-11-30"})`: firmando el 30/11/2026 rige la
   Ley 12/2023 con un 50 %, y tributan 3.622 €.
4. `final_answer`: las dos cifras, la palanca con su cita y la remisión a un asesor. El
   auditor la aprueba porque cada cifra sale de un paso anterior.

La traza real la pondremos cuando el bucle la produzca: ⟦pendiente⟧.
