# Relevo para el siguiente Claude (sesión de Kike, 23-24/11/2026)

Hola. Trabajas con **Kike** (Enrique Rodríguez, GitHub `enriquerodriguezcamacho`, le gusta que
le llames Kike, habla en español) en `santimartinez1717/dgm-arca`, la práctica ARCA del equipo
**Umbral** (Bernardo Ordás `@berordas`, Santiago Martínez `@santimartinez1717`, Kike). Esta
conversación no se puede recuperar: lo que importa está aquí.

## Cómo trabajamos

- **Una rama por issue**, con el nombre `kike/issue-N-…`; `fase4/…` no se puede crear porque
  ya existe una rama `fase4`. PR contra `fase4`, nunca push directo a `fase4` ni a `main`.
- **Para hablar con Santi o Bernardo, menciónalos en el PR o el issue.** Sus Claude Code están
  conectados al repo y responden ahí.
- Commits con la identidad `enriquerodriguezcamacho <202213390@alu.comillas.edu>`
  (`git config user.name/user.email` en el repo), en español, terminados en
  `Co-Authored-By: Claude …`. Lee `CLAUDE.md`: código y comentarios en inglés, documentación en
  español, `uv run ruff check && uv run ruff format && uv run pytest -q` antes de cada commit.
- Cada resultado lleva su entrada en EXPERIMENTS.md (skill `registrar-experimento`). Para los
  procesos largos en la DGX, usa la skill `lanzar-dgx`.
- `gh` está en `~/.local/bin/gh` (no está en el PATH), con la sesión de Kike iniciada. En una
  máquina nueva: `gh auth login` y `gh auth setup-git`.

## Qué es de Kike y en qué estado está

| Issue | Estado |
|---|---|
| #14 banco de 24 tareas · #15 `agent/evaluate.py` · #21 API e ingesta CSV | Cerrados (fusionados) |
| #16 contraste con CodeAgent (`agent/code_agent.py`) | Código fusionado. Falta **medirlo** y escribir la tabla JSON frente a código en EXPERIMENTS.md |
| #17 visor de trazas (`agent/ui.py`) | Código fusionado. Falta el **GIF** `docs/fase4/demo.gif` (con la API levantada) |
| #19 informe y README | Borrador fusionado (`docs/fase4/informe_fase4.md`, `docs/README_portfolio.md`). Falta rellenar los **⟦pendiente⟧** con los resultados |

También son de Kike y están fusionados: la ingesta en prosa (#35), los checks del banco (#34), el
evaluador reanudable (#37) y la marca de cerebro sustituido (#41).

## La evaluación de la fase 4: dónde se quedó

Rama **`kike/eval-dgx-resultados`** (sin PR todavía). Contiene:

- `scripts/fase4/eval_agent.sh` con `ARCA_EVAL_BRAINS` y `ARCA_EVAL_CONFIGS` para lanzar por
  partes;
- `scripts/fase4/tablas_informe.py`, que saca de los JSON las tablas 6.3, 6.4 y 6.5 del informe
  y un diagnóstico de fallos (datos, copia, auditor, pasos);
- **`reports/fase4/phase4_eval.partial.jsonl`**: el checkpoint con 36 filas ya hechas. Son
  `full/base` 24/24 tareas (4 correctas) y `full/thinking` 12/24 (2 correctas). Se paró a
  propósito al cambiar de servidor;
- la prueba de humo (`reports/fase4/smoke_eval*`).

**Para seguir**, en el servidor nuevo:

```bash
git checkout kike/eval-dgx-resultados
mkdir -p ~/clusters/dgx && source smoke/dgx_env.sh   # cachés de uv/HF; copia ~/.gitconfig a ~/clusters/dgx/.gitconfig o gh no podrá hacer push
uv sync --extra train --extra agent --extra rag        # unos minutos
uv run python -m rag.download_corpus                   # 58 ficheros; ESPERA a que acabe antes de evaluar
# el índice del RAG se construye solo al arrancar el agente la primera vez (~5 min)
```

Después, en este orden de prioridad (cada línea reanuda del checkpoint, con `nohup`, como dice
la skill `lanzar-dgx`):

```bash
ARCA_EVAL_BRAINS="base thinking" ARCA_EVAL_CONFIGS="full" bash scripts/fase4/eval_agent.sh json      # termina thinking (12 tareas)
ARCA_EVAL_BRAINS="base" ARCA_EVAL_CONFIGS="no_auditor no_playbook flat_memory" bash scripts/fase4/eval_agent.sh json
ARCA_EVAL_BRAINS="base thinking" bash scripts/fase4/eval_agent.sh code
ARCA_EVAL_BRAINS="thinking" ARCA_EVAL_CONFIGS="no_auditor no_playbook flat_memory" bash scripts/fase4/eval_agent.sh json
ARCA_EVAL_BRAINS="base thinking" bash scripts/fase4/eval_agent.sh json    # todo reanudado: escribe el informe completo
uv run python scripts/fase4/tablas_informe.py                             # tablas para el informe
```

- **Tiempos medidos** en una MIG 1g.18gb: `base` unos 28 s por tarea; `thinking` de 55 a 120 s.
- **Un proceso ocupa unos 7,6 GB de GPU.** En la MIG de 17 GB no se paralelizó: Kike pidió no
  hacerlo si no es seguro.
- **Con una GPU más grande**, `json` y `code` escriben en ficheros distintos
  (`phase4_eval*.partial.jsonl` frente a `phase4_eval_code*.partial.jsonl`), así que se pueden
  lanzar a la vez **solo si `nvidia-smi` muestra memoria de sobra para dos procesos con margen**
  (más de 2 × 9 GB). No lances dos procesos sobre el mismo `--out`: los dos añadirían filas al
  mismo checkpoint.
- **Sigue con `ARCA_AGENT_TOKEN_BUDGET=100000`** en la evaluación, aunque corte tareas (ver más
  abajo), para que todas las configuraciones sean comparables.
- **`rlm` no se puede medir sin el adaptador GRPO 2** de Santi en `rlm/weights/grpo2_lora`; no
  está en git ni en un repositorio público de Hugging Face. Si aparece, añade `rlm` a
  `ARCA_EVAL_BRAINS`. El evaluador marca las filas en que el cerebro no cargó y respondió `base`.
- **Cuidado con `pkill -f`**: el patrón coincide con tu propia orden y la mata. Para vigilar o
  parar un proceso, usa el PID de `ps`.

## Lo que ya sabemos (está en EXPERIMENTS.md o en el #20)

- **Presupuesto de tokens.** Un paso cuesta unos 15.000 tokens de prompt, así que
  `ARCA_AGENT_TOKEN_BUDGET=100000` corta las tareas hacia el paso 7. En `lever-01` el agente hizo
  el camino perfecto y se quedó sin presupuesto antes de `final_answer`. Para **servir** la API
  se recomendó 200.000 (#20).
- **Con `full`/`base`**, de las 24 tareas 4 son correctas y ninguna se cae; 6 terminan sin
  `final_answer` (3 por repetir la misma llamada, 1 por el presupuesto, 2 por agotar los pasos).
- **`impossible-01`**: el modelo se inventa un piso en lugar de abstenerse. El auditor bloquea las
  cifras y la respuesta acaba en «No he podido terminar».
- **Fallos de «copia».** En `screening-01`, `screen_properties` dio los 10 pisos correctos y la
  respuesta solo recogió 6. Unas 4 de cada 24 respuestas salen en inglés.
- **Limitación del banco, para contarla en el informe sin cambiarlo a mitad de la evaluación.**
  `get_rent_reference` figura como tool requerida en screening, inconsistent-01/03,
  kb_plus_tool-02 y broken_tool-01, pero desde que `analyze_property` consulta las zonas por su
  cuenta ya no hace falta. Por eso la métrica «tools requeridas» sale baja, y `broken_tool-01`
  apenas pone a prueba la recuperación.

## Pendiente fuera de lo de Kike

- **Pedir a Santi el adaptador GRPO 2** y avisarle de que todo se fusionó sin su revisión. Esto
  lo tiene que hacer Kike o Bernardo.
- **`fase4` no está fusionada en `main`** (57 commits por delante). Lo decide Santi.
- **Bernardo** tiene aplazados el #18 (cerrar el círculo) y el recorte del #13; sus pasos están
  escritos en cada issue.

## Cuando termines

1. Abre el PR de `kike/eval-dgx-resultados` con los JSON y los Markdown de `reports/fase4/`.
2. Rellena los ⟦pendiente⟧ del informe y del README y escribe las entradas de EXPERIMENTS.md.
3. Cierra el #16 y el #19, y el #17 cuando esté el GIF.
