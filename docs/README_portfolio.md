# Umbral · analista de inversión en vivienda para alquilar

**Umbral** responde a la pregunta que se hace quien compra un piso para alquilarlo en España:
*¿me sale a cuenta, y qué puedo hacer legalmente para que me salga mejor?* Le pegas una lista de
pisos y te dice:

- la rentabilidad neta de cada uno con la renta que **la ley** te deja cobrar, no con la que
  pide el anuncio;
- el ITP de tu comunidad y el IRPF del alquiler;
- si te conviertes en gran tenedor;
- qué palancas legales tienes (la fecha de firma frente al RDL 29/2026, una rebaja de la renta
  que multiplica la reducción del IRPF, la excepción del 10 % por rehabilitación, cuánto
  ofrecer), cada una con su cifra y su cita del BOE;
- qué cosas parecen un atajo y son fraude, para advertirte de ellas.

Es para pequeños inversores y para quien les asesora. Hoy esto se hace con una hoja de cálculo
propia, leyendo el BOE y preguntando en foros. La reducción del IRPF del alquiler tiene tres regímenes distintos desde 2023,
y cuál se aplica depende de la fecha del contrato.

Práctica final de *Modelos Generativos Profundos* (Máster en IA, ICAI, 2026-2027), de Bernardo
Ordás, Enrique Rodríguez y Santiago Martínez Díe.

![Demo](fase4/demo.gif)

> ⟦pendiente⟧: el GIF se graba con el agente funcionando (issue #17): la tarea de los 15 pisos
> y una palanca.

## Cómo funciona

**El modelo decide qué mirar y lo explica; el motor pone todos los números; el corpus
justifica.**

Un Qwen3-1.7B, cargado una sola vez, mueve un bucle ReAct con herramientas. Ninguna cifra sale
del modelo: un auditor determinista rechaza la respuesta que trae un número que no haya
calculado una herramienta, o una cita que no se haya recuperado.

Diagrama completo y decisiones en [`fase4/arquitectura.md`](fase4/arquitectura.md).

| Fase | Pieza | Endpoint |
|---|---|---|
| 1 · Razonamiento | Qwen3-1.7B + LoRA: destilación de Qwen3-4B, SFT y GRPO sobre problemas que verifica un motor de reglas | `POST /reasoning` |
| 2 · Herramientas | El motor como tools, más datos públicos (zonas tensionadas del BOE, rentas del SERPAVI, Euríbor, Catastro) y una cartera en SQLite | `POST /tools` |
| 3 · Conocimiento | Corpus del BOE y la AEAT con troceado semántico, retriever híbrido y la ley vigente en cada fecha | `POST /rag` |
| 4 · Agente | Bucle ReAct con expediente, playbook de palancas, auditor y tres cerebros | `POST /agent` |

## Resultados

Todas las cifras salen de [`EXPERIMENTS.md`](../EXPERIMENTS.md), donde está cómo se midió cada
una.

| Fase | Qué se mide | Resultado |
|---|---|---|
| 1 | pass@1 en el test de 300 problemas del dominio (2.048 tokens) | base 10,3 % → SFT 37,7 % → GRPO 38,3 % → **GRPO 2 47,3 %** (McNemar frente al SFT 3, p = 0,026) |
| 2 | 60 problemas del test de la fase 1 con el modelo base | sin herramientas 1/60 · con una calculadora genérica 1/60 · **con las del dominio 20/60** |
| 2 | Banco de 40 casos de `/tools` (v13) | selección de herramienta 40/40 · argumentos 33/40 · respuestas en español 29/32 |
| 3 | Recuperación en 51 preguntas anotadas (semántico p90, híbrido λ = 0,2) | acierto@5 58,8 % · MRR 0,425; el troceado importa más que el retriever (recursivo: MRR 0,29) |
| 3 | Generación con citas (cita el pasaje relevante cuando se recuperó) | base 50 % · **base con pensamiento 70 %** · modelo de la fase 1 46,7 %; 6/6 abstenciones correctas |
| 3 | Ley vigente en una fecha, preguntas cuya respuesta cambió (10) | acierto@5: solo la ley de hoy 0 % → **versiones vigentes en la fecha 60 %** |
| 4 | Banco de 24 tareas, tres cerebros y cuatro configuraciones | ⟦pendiente⟧ (`reports/fase4/phase4_eval.md`) |
| 4 | Agente JSON frente a `CodeAgent` | ⟦pendiente⟧ |

**Dos hallazgos que guían el diseño:**

- **En las cifras, las herramientas ganan al entrenamiento.** El modelo base con herramientas
  (20/60) empata con el SFT de la fase 1 en esos 60 problemas, y el GRPO 2 sin herramientas
  saca 24/60, sin diferencia significativa (p = 0,54).
- **El modelo entrenado para hacer cuentas lee y cita peor** que el base con pensamiento.

## Levantarlo

```bash
cp .env.example .env          # rellena HF_TOKEN si hace falta
docker compose build
docker compose up api         # http://localhost:8000/docs
```

Sin Docker: `uv sync --extra agent && uv run arca-api`.

El visor de trazas (pensamiento, acciones, palancas, escenarios, auditor y expediente):

```bash
uv run python -m agent.ui     # contra ARCA_API_URL, por defecto http://localhost:8000
```

Ejemplo de llamada al agente:

```bash
curl -s localhost:8000/agent -H 'content-type: application/json' -d '{
  "task": "Piso de segunda mano en Pamplona por 180.000 €. El último inquilino pagaba 950 € y quiero pedir 1.100 €. ¿Cuánto puedo cobrar y qué neto saco?",
  "brain": "base", "max_steps": 8}'
```

Para reproducir cada resultado, mira los comandos de su entrada en EXPERIMENTS.md y los
scripts de `scripts/faseN/`.

*Análisis orientativo, no asesoramiento fiscal.*
