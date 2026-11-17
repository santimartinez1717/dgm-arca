# EXPERIMENTS.md — cuaderno de experimentos de Umbral

Una entrada cada vez que lanzamos algo o tomamos una decisión, con fecha y de la más antigua a
la más reciente. Formato en [`docs/EXPERIMENTS_plantilla.md`](docs/EXPERIMENTS_plantilla.md).

---

### 2026-09-29 · Fase 1 · Primera versión del dataset verificable

**Qué queríamos saber.** Si el generador cubre todas las ramas de las reglas con una
frecuencia razonable, y si hay fugas de la respuesta en el enunciado o solapamiento entre
particiones.

**Qué hicimos.** `uv run python -m rlm.realestate_problems --out-dir rlm/data` (semilla 0):
- 400 problemas por familia en train y 50 por familia en test, sobre seis familias;
- 75 por familia fuera de distribución, sobre dos composiciones de reglas;
- deduplicación por huella de parámetros, compartida entre las tres particiones.

**Qué pasó.** 2.400 / 300 / 150 problemas, sin solapamiento (hay un test que lo comprueba).
Cobertura de ramas en train (`rlm/data/dataset_stats.json`):

| Familia | Rama | Reparto |
|---|---|---|
| `acquisition_cost` | base imponible | precio 203 · valor de referencia 197 |
| `acquisition_cost` | tipo de vivienda | usada 319 · obra nueva 81 |
| `legal_rent` | regla que limita | renta anterior 126 · sin zona 74 · índice 79 · zona sin tope 61 · mercado por debajo 60 |
| `legal_rent` | gran tenedor | sí 99 · no 301 |
| `irpf_rental` | reducción | 50 %: 143 · 70 %: 51 · 90 %: 41 · 60 %: 39 · rendimiento negativo (sin reducción): 126 |
| `irpf_rental` | límite intereses + reparaciones activo | 33 |
| `cash_on_cash` | flujo de caja negativo | 115 |
| `net_yield` | con meses vacíos | 268 |

Una fuga en train y otra en test. La primera comprobación, que buscaba el número sin unidad,
daba cinco; eran coincidencias de enteros como "2" o "5" que aparecen en cualquier enunciado.
Ahora buscamos la cifra con su unidad, tal como la escribiría el enunciado (`2,45 %`).

**Qué concluimos.**
- Ninguna rama pasa del 36 % de su familia. La reducción del 90 % salía en el 6,5 % de los
  problemas y subimos la probabilidad de "renta rebajada más de un 5 %" de 0,35 a 0,55; ahora
  sale en el 10 %.
- **Pendiente:** solo hay 2-3 plantillas por familia. Antes de destilar haremos una pasada de
  paráfrasis con el profesor, para que el modelo no aprenda la plantilla en vez de la tarea.
- Auditoría manual: 50 problemas de test repartidos por familias en
  `rlm/data/test_audit.csv`. Cada uno lo firma quien lo revisa.

---

### 2026-09-29 · Fase 1 · Prueba de todo el pipeline en CPU

**Qué queríamos saber.** Si generación, destilación, SFT, GRPO con las tres recompensas y
evaluación funcionan juntos antes de gastar horas de GPU.

**Qué hicimos.** Con `HuggingFaceTB/SmolLM2-135M-Instruct` en un Mac, sobre 3 problemas:
- `distill` con 2 muestras y 16 tokens;
- `train_sft`, 1 época;
- `train_grpo`, 1 paso con 2 generaciones y un 30 % de control GSM8K;
- `evaluate` y `evaluate --history`.

**Qué pasó.** Todo termina y guarda sus salidas. Las tres recompensas aparecen en el registro
de TRL (`rewards/format_reward`, `rewards/euro_accuracy_reward`, `rewards/domain_reward`). La
exactitud es 0, lo esperable con 135M parámetros y 16 tokens.

Encontramos un fallo solo de Mac: sin CUDA, `accelerate` elegía la GPU de Apple (MPS) y la
generación de TRL mezclaba tensores de MPS y CPU. Lo arreglamos con `use_cpu` cuando no hay
CUDA. En la DGX no aplica.

**Qué concluimos.** El código está listo para la DGX. Lo siguiente es el smoke test y la
destilación con Qwen3-4B.

---

### 2026-09-29 · Fase 1 · Smoke test en la DGX (GRPO sobre GSM8K)

**Qué queríamos saber.** Si el bucle de GRPO con TRL funciona en la partición MIG de la DGX
(H200 1g.18gb, 17,2 GB), cuánto tarda y cuánta memoria usa, antes de lanzar nada del dominio.

**Qué hicimos.** `nohup uv run arca-smoke > smoke.log 2>&1 &`: Qwen3-0.6B con LoRA de rango
16 (10,1 M parámetros entrenables, un 1,67 %), 40 pasos, grupo de 8 generaciones, 384 tokens
como máximo, lr 1e-5, 256 problemas de GSM8K, semilla 0.

**Qué pasó.** Termina sin errores en 11,9 min (~18 s por paso), con un pico de 7,3 GB de GPU.
Adaptador guardado en `rlm/weights/smoke_lora/`. Cada paso usa un único problema, así que la
recompensa por paso es muy ruidosa; comparamos medias de 10 pasos:

| Métrica (recompensa máx. 2) | Pasos 1-10 | Pasos 31-40 |
|---|---|---|
| Recompensa total | 0,29 | 0,69 |
| Formato | 0,08 | 0,41 |
| Exactitud | 0,21 | 0,28 |
| Fracción truncada a 384 tokens | 0,76 | 0,59 |

**Qué concluimos.**
- El bucle funciona: sube sobre todo la recompensa de formato, y lo hace a la vez que baja
  la fracción truncada. Casi todo el formato perdido viene de respuestas cortadas antes de
  `</think>`, no de que el modelo ignore las etiquetas.
- La tabla "first step / last step" del resumen del smoke engaña, porque compara dos pasos de
  un solo problema cada uno. En nuestros informes usaremos medias móviles.
- Consecuencia para el dominio: la longitud máxima es el hiperparámetro crítico. Qwen3 en
  modo thinking se extiende mucho; en la línea base mediremos la fracción truncada junto al
  pass@1, y por eso GRPO usará 1024 tokens y un arranque en frío con trazas compactas.
- Margen de memoria: 7,3 de 17,2 GB con 0,6B y 384 tokens. Con 1,7B y 1024 tokens no
  cabe dar nada por hecho: se medirá con una prueba corta antes de lanzarlo.
- Aviso en el log: no hay `HF_TOKEN` (no existe `.env`). Hará falta para subir adaptadores
  al Hub.

### 2026-09-29 · Fase 1 · Sonda de evaluación de Qwen3-0.6B base sobre el dominio

**Qué queríamos saber.** Si `rlm.evaluate` funciona de principio a fin en la DGX con nuestro
test, y una primera idea de dónde parte el modelo base antes de la línea base completa.

**Qué hicimos.** `rlm.evaluate` con `Qwen/Qwen3-0.6B`, sin adaptador (`base=none`), sobre
32 problemas de `rlm/data/test.jsonl`, con los valores por defecto (1024 tokens nuevos como
máximo, lotes de 16). El comando exacto no quedó en `eval_probe.log`; fue el equivalente a
`--n-examples 32 --out reports/eval_base_06b_probe.json`. Tardó 510 s.

**Qué pasó.** Detalle en `reports/eval_base_06b_probe.json` y gráfico en
`reports/eval_base_06b_probe.png`.

| Familia | n | pass@1 | Formato válido | Cortadas a 1024 |
|---|---|---|---|---|
| **Global** | 32 | **0 %** | **15,6 %** | **46,9 %** |
| `acquisition_cost` | 6 | 0 % | 16,7 % | 33,3 % |
| `cash_on_cash` | 6 | 0 % | 16,7 % | 50 % |
| `irpf_rental` | 4 | 0 % | 25 % | 50 % |
| `legal_rent` | 4 | 0 % | 25 % | 50 % |
| `max_price` | 8 | 0 % | 0 % | 50 % |
| `net_yield` | 4 | 0 % | 25 % | 50 % |

De media 812 tokens por respuesta (mediana 854,5). No todo es longitud: en el primer
problema de `cash_on_cash` el formato es correcto y no se corta, pero el modelo divide el
flujo entre la inversión total en vez de entre el capital propio y da 4,92 % (lo esperado
es 1,36 %). Además ignora la cuota de la hipoteca.

**Qué concluimos.**
- El pipeline de evaluación funciona en la DGX.
- La 0,6B base parte de cero en el dominio: casi la mitad de las respuestas se cortan, y las
  que terminan aplican mal las fórmulas. Con 32 problemas el reparto por familia es solo
  orientativo.
- Siguiente paso: la línea base completa (300 problemas) para 0,6B y 1,7B, que decide qué
  modelo será el alumno.

---

### 2026-10-06 · Fase 1 · Línea base de Qwen3-0.6B y Qwen3-1.7B: elección del alumno

**Qué queríamos saber.** De dónde parten los dos candidatos a alumno sin entrenar, y cuál
de los dos usamos (regla de `docs/fase1_plan.md`: si el de 1,7B pasa del 60 %, el dominio es
demasiado fácil).

**Qué hicimos.** Las dos órdenes del paso 1 de `docs/fase1_plan.md`, encadenadas con `nohup`
(salida en `baseline.log`): `rlm.evaluate` sobre los 300 problemas de `rlm/data/test.jsonl`,
sin adaptador, con 1024 tokens nuevos como máximo. 0,6B: de 08:50 a 09:18 (~28 min).
1,7B: de 09:18 a 09:49 (~31 min).

**Qué pasó.** Detalle en `reports/eval_base_06b.json` y `reports/eval_base_17b.json`, con
sus gráficos `.png`.

| | Qwen3-0.6B | Qwen3-1.7B |
|---|---|---|
| **pass@1** | **1,7 %** (5/300) | **3,3 %** (10/300) |
| Formato válido | 16,7 % | 0,7 % |
| Cortadas a 1024 tokens | 52 % | 81,3 % |
| Tokens por respuesta (media) | 840 | 983 |
| Aciertos entre las que no se cortan | 5/144 (3,5 %) | 10/56 (17,9 %) |

pass@1 / formato válido / cortadas, por familia (50 problemas cada una):

| Familia | Qwen3-0.6B | Qwen3-1.7B |
|---|---|---|
| `acquisition_cost` | 6 % / 28 % / 20 % | 10 % / 0 % / 54 % |
| `cash_on_cash` | 0 % / 36 % / 24 % | 0 % / 4 % / 68 % |
| `irpf_rental` | 0 % / 14 % / 68 % | 0 % / 0 % / 100 % |
| `legal_rent` | 4 % / 16 % / 54 % | 8 % / 0 % / 84 % |
| `max_price` | 0 % / 2 % / 76 % | 0 % / 0 % / 90 % |
| `net_yield` | 0 % / 4 % / 70 % | 2 % / 0 % / 92 % |

Ninguna respuesta cortada acierta, en ninguno de los dos modelos. El formato válido del 1,7B
es casi nulo aunque escriba `<answer>`: después de `</think>` añade una explicación en prosa
antes de la etiqueta, y `has_valid_format` no lo acepta. El verificador sí extrae el número,
y por eso hay aciertos con formato inválido.

**Qué concluimos.**
- **Alumno: Qwen3-1.7B.** Estamos muy lejos del umbral del 60 %, así que hay margen de sobra.
  La diferencia de pass@1 por sí sola no es significativa (10 frente a 5 de 300; Fisher
  bilateral, p ≈ 0,30). Lo que decide es que, cuando termina, el 1,7B acierta cinco veces más
  (17,9 % frente a 3,5 %; p ≈ 0,001). Su límite es la longitud, no el razonamiento, y eso es
  justo lo que atacan el arranque en frío con trazas compactas y la recompensa de formato.
- El cuello de botella de los dos es la longitud: con 1024 tokens el 1,7B se corta en 4 de
  cada 5 problemas (en todos los de `irpf_rental`). En la destilación filtraremos las trazas
  del profesor por longitud.
- `max_price` e `irpf_rental` dan 0 % en los dos modelos: son las familias que hay que
  vigilar en la tasa de aceptación de la destilación.
- **Pendiente antes de GRPO:** una prueba corta de memoria con 1,7B y 1024 tokens. La del
  smoke test (7,3 GB con 0,6B y 384 tokens) no sirve para extrapolar.
- Siguiente paso: destilación con Qwen3-4B, empezando por `--limit 20` para medir la
  velocidad.

---

### 2026-10-06 · Fase 1 · Pruebas de destilación con Qwen3-4B: sin y con hoja de reglas

**Qué queríamos saber.** Cuánto tarda y cuánta memoria usa destilar en la MIG 1g.18gb, y qué
parte de las trazas del profesor pasa el verificador, antes de lanzar la destilación grande.

**Qué hicimos.** Dos pruebas sobre los mismos 20 problemas de `rlm/data/train.jsonl`
(`--limit 20`, semilla 0), con 4 muestras por problema y temperatura 0,6:

1. **Sin hoja de reglas**: 3072 tokens nuevos, lotes de 2. Un primer intento a las 11:21
   murió con el fin de la sesión de Slurm (12:02) sin guardar nada, porque `distill.py`
   escribía solo al final. Lo repetimos a las 12:17.
2. **Con hoja de reglas** (`TEACHER_RULES` en el prompt de sistema del profesor, commit
   `12bafcf`): 1536 tokens nuevos. Con lotes de 4 se quedó sin memoria en el primer lote
   (15,8 GB en uso); repetido con lotes de 2 y `expandable_segments`:
   `PYTHONUNBUFFERED=1 uv run python -m rlm.distill --data rlm/data/train.jsonl
   --teacher Qwen/Qwen3-4B --limit 20 --batch-size 2 --output
   rlm/data/sft_traces_probe20_rules.jsonl`.

**Qué pasó.**

| | Sin hoja (3072 tokens) | Con hoja (1536 tokens) |
|---|---|---|
| **Aceptación** | **18,8 %** (15/80) | **37,5 %** (30/80) |
| Cortadas | 32,5 % (26) | 42,5 % (34) |
| Citan la hoja (descartadas) | — | 25 % (20) |
| Duración | 71,7 min (7,2 min/lote) | 45,4 min (3,4–3,8 min/lote*) |
| Memoria pico | 15,6 GB | 11,6 GB |

\* El primer lote marcó 13,7 min porque el cronómetro incluye la carga del modelo.

Aceptación por familia:

| Familia | Sin hoja | Con hoja | Cortadas con hoja |
|---|---|---|---|
| `acquisition_cost` | 31 % | **81 %** | 0 % |
| `net_yield` | 75 % | **100 %** | 0 % |
| `max_price` | 0 % (todas cortadas) | **62 %** | 0 % |
| `legal_rent` | 35 % | 35 % | 55 % |
| `irpf_rental` | 0 % | 8 % | 50 % |
| `cash_on_cash` | 0 % | 0 % | **85 %** |

Sin hoja, el profesor fallaba igual en las cuatro muestras de un problema: no conoce las
reglas implícitas. En obra nueva olvidaba el IVA del 10 % (176.306 € frente a 189.106 €) y
en cash-on-cash no restaba la cuota de la hipoteca (22,55 % frente a −1,35 %).

Con hoja, las 80 trazas se reparten así: 30 aceptadas, 34 cortadas, 11 terminadas pero
citando la hoja ("following the rules provided"), de las que 5 eran correctas, y solo **5
respuestas equivocadas**. Las trazas aceptadas tienen una mediana de 799 tokens.

**Qué concluimos.**
- La hoja de reglas resuelve los errores de conocimiento: el profesor ya casi no se equivoca.
  Lo que queda se pierde por longitud y por citar la hoja.
- `cash_on_cash` se corta casi siempre: calcular a mano la cuota (con (1+i)^−240) no cabe en
  1536 tokens. Subiremos el tope a 2048.
- La instrucción de no citar la hoja está en español y el profesor razona en inglés. La
  reescribiremos en inglés y más tajante.
- Al 37,5 %, 400 problemas darían unas 600 trazas, por debajo de las 1.000–2.000
  recomendadas. Con los dos arreglos esperamos más; si no basta, destilaremos 800 problemas.
- La destilación grande se hará en una sesión de 24 h con 71 GiB, que admite lotes más
  grandes y permite probar Qwen3-8B como profesor. Antes, prueba de 20 problemas con los
  arreglos.

---

### 2026-10-06 · Fase 1 · Destilación principal con Qwen3-4B (206 de 400 problemas)

**Qué queríamos saber.** Cuántas trazas verificadas da el profesor con la hoja de reglas y
2048 tokens sobre una muestra al azar de train, y cómo se reparten por familia.

**Qué hicimos.** `PYTHONUNBUFFERED=1 uv run python -m rlm.distill --data rlm/data/train.jsonl
--teacher Qwen/Qwen3-4B --limit 400 --batch-size 2 --resume --output
rlm/data/sft_traces.jsonl` (commit `884136c`: instrucción anti-cita en inglés, 2048 tokens).
De 15:45 a 23:41, en la MIG de 17 GB; el fin de la sesión la cortó en el lote 103 de 200.
Unos 5 min por lote; el primero tarda unos 15 más porque incluye la carga del modelo.

**Qué pasó.** 469 de 824 trazas aceptadas (**56,9 %**), 206 problemas; mediana de 790
tokens en las aceptadas.

| Familia | Aceptación | Cortadas | Citan la hoja | Problemas con traza |
|---|---|---|---|---|
| `acquisition_cost` | 99 % | 0 % | 1 | 35/35 |
| `max_price` | 89 % | 2 % | 5 | 32/32 |
| `net_yield` | 81 % | 2 % | 1 | 33/33 |
| `legal_rent` | 38 % | 30 % | 3 | 26/40 |
| `irpf_rental` | 25 % | 29 % | 42 | 18/31 |
| `cash_on_cash` | 14 % | 65 % | 1 | 12/35 |

Cada familia difícil falla por una razón distinta:
- `cash_on_cash`: se corta calculando la cuota a mano ((1+i)^−240, unas 20 potencias por
  traza), y las que terminan fallan por centésimas de aproximación (−1,41 frente a −1,35).
- `irpf_rental`: una cuarta parte cita la hoja ("the rules provided"); esas trazas además
  suelen estar mal. El resto se corta dudando o falla por unos euros en la amortización.
- `legal_rent`: error sistemático. Aplica el tope del índice cuando el enunciado dice que la
  resolución **no** lo extiende (27.820,80 € frente a 27.960 €, en las cuatro muestras).

**Qué concluimos.** No seguir con los 194 problemas restantes: dos tercios serían de las
familias fáciles, que ya tienen de sobra. En su lugar, una pasada solo con las difíciles
(entrada siguiente).

---

### 2026-10-08 · Fase 1 · Pasada extra de destilación para las familias difíciles

**Qué queríamos saber.** Si arreglos dirigidos a la causa de cada fallo suben la aceptación
de `legal_rent`, `irpf_rental` y `cash_on_cash`.

**Qué hicimos.** `distill_hard.sh` (commit `dde430d`), con problemas nuevos de train
(`--families`, `--exclude rlm/data/sft_traces.jsonl`):
1. `legal_rent` + `irpf_rental`, 100 problemas, 2048 tokens. La hoja explica el caso de
   `legal_rent` que fallaba siempre, presenta las reducciones del IRPF como art. 23.2 y pide
   cuentas con céntimos; las citas a la hoja se reescriben como "the rules" antes de
   verificar. 4,5 h, pico de 12,8 GB.
2. `cash_on_cash`, 30 problemas, **3072 tokens**. 2,8 h (~9,3 min por lote), pico de 14,1 GB.

**Qué pasó.**

| Familia | Principal | Pasada extra | Cortadas (antes → ahora) |
|---|---|---|---|
| `legal_rent` | 38 % | **67 %** | 30 % → 16 % |
| `irpf_rental` | 25 % | 32 % | 29 % → 42 % |
| `cash_on_cash` | 14 % | **32 %** | 65 % → 27 % |

En `irpf_rental` las citas en trazas terminadas desaparecen, pero la aceptación apenas se
mueve: las que citaban estaban casi siempre mal, y ahora se cortan o fallan igual.

Total de trazas verificadas, sumando las tres tandas: **698**.

| Familia | Trazas | Problemas distintos |
|---|---|---|
| `legal_rent` | 180 | 65 |
| `acquisition_cost` | 138 | 35 |
| `max_price` | 114 | 32 |
| `net_yield` | 107 | 33 |
| `irpf_rental` | 101 | 52 |
| `cash_on_cash` | 58 | 33 |

**Qué concluimos.**
- El error de reglas de `legal_rent` se arregla explicando el caso en la hoja. Lo de
  `cash_on_cash` es longitud: con 3072 tokens se cortan la mitad que antes.
- `irpf_rental` es larga y numéricamente delicada para el 4B; las citas no eran la causa.
  Queda una tanda con 3072 tokens y un orden fijo de cálculo (`distill_irpf.sh`, commit
  `0ef55ae`), que no cupo en la sesión.
- Las familias que más le cuestan al profesor son las de más pasos encadenados: es de esperar
  lo mismo en el alumno, y es donde una herramienta de cálculo (fase 2) aportaría más.
- Siguiente paso: SFT con las tres tandas y `--max-per-problem 3 --max-per-family 150`.

---

### 2026-10-15 · Fase 1 · SFT de Qwen3-1.7B sobre las trazas destiladas, y su evaluación

**Qué queríamos saber.** Si el arranque en frío con las trazas del profesor enseña al alumno
el formato y a resolver los problemas, y cuánto de lo que falla es falta de espacio.

**Qué hicimos.** SFT con LoRA (rango 16, 2 épocas, lr 2e-4, lote efectivo 16) sobre las
cuatro tandas de destilación, con `--max-per-problem 3 --max-per-family 150`: 596 trazas de
252 problemas (`legal_rent` 150, `acquisition_cost` 105, `irpf_rental` 102, `max_price` 92,
`net_yield` 91, `cash_on_cash` 56). `--max-length 3328`: con el valor por defecto (2048)
se habrían recortado antes de `</answer>` cerca de la mitad de las trazas de
`cash_on_cash` (mediana de 1.862 tokens). 76 pasos en 23,6 min, pico de 5,3 GB en la prueba.
Evaluación con `eval_sft.sh` sobre los 300 problemas de test, en modo greedy.

**Qué pasó.** La loss baja de 0,52 a 0,28 (acierto por token del 85 al 90 %) sin caer a
cero.

| | Base, 1.024 | Base, 2.048 | SFT, 1.024 | **SFT, 2.048** |
|---|---|---|---|---|
| **pass@1** | 3,3 % | 10,3 % | 32,0 % | **37,7 %** |
| Formato válido | 0,7 % | 3,3 % | 47,3 % | 69,0 % |
| Cortadas | 81,3 % | 35,0 % | 52,7 % | 31,0 % |
| `acquisition_cost` | 10 % | 16 % | 74 % | 72 % |
| `net_yield` | 2 % | 26 % | 64 % | 68 % |
| `max_price` | 0 % | 0 % | 36 % | 56 % |
| `legal_rent` | 8 % | 20 % | 18 % | 30 % |
| `irpf_rental` | 0 % | 0 % | 0 % | 0 % |
| `cash_on_cash` | 0 % | 0 % | 0 % | 0 % |

Detalle en `reports/eval_sft_17b.json`, `reports/eval_sft_17b_2048.json` y
`reports/eval_base_17b_2048.json`. Con 2.048 tokens, el 55 % de las respuestas que terminan
son correctas.

En `cash_on_cash` e `irpf_rental` más espacio no basta: terminan más respuestas (cortadas
del 98 al 62 % y del 80 al 52 %) pero siguen al 0 %, y fallan por mucho, no por céntimos.
En `cash_on_cash` da por ejemplo 13,17 % frente a 5,36 %, o 7,17 % frente a −3,03 %, como
si no restara la cuota de la hipoteca: el mismo error del profesor sin la hoja de reglas.

**Qué concluimos.**
- El SFT multiplica el pass@1 por 10 con el mismo presupuesto que la línea base (1.024
  tokens) y por 3,7 con 2.048. La mejora no viene solo de tener más espacio.
- En las familias de trazas cortas el alumno aprende la tarea; en `max_price` y `legal_rent`
  le falta espacio; en `cash_on_cash` e `irpf_rental`, 56 y 102 trazas no le bastan para
  aprender la regla.
- GRPO con 1.536 tokens por respuesta, desde este adaptador. `cash_on_cash` e `irpf_rental`
  van al análisis de fallos y son el caso para la herramienta de cálculo de la fase 2.

---

### 2026-10-18 · Fase 1 · GRPO desde el adaptador del SFT

**Qué queríamos saber.** Si GRPO con las tres recompensas mejora al alumno tras el SFT, y
qué aporta la recompensa del dominio.

**Qué hicimos.** `rlm.train_grpo` con Qwen3-1.7B, `--init-adapter rlm/weights/sft_lora`,
400 pasos (un problema por paso, 8 respuestas), `--max-completion-length 1536`, lr 5e-6,
sin KL, pesos 0,5 / 2,0 / 0,5 (formato / exactitud / dominio), 10 % de control GSM8K. En la
MIG de 17 GB hizo falta desactivar la atención de cuDNN (falla en el primer forward de
entrenamiento) y procesar las respuestas en micro-lotes de 2 (commit `0ed5df0`): 10,6 GB de
pico, ~50 s por paso, 5 h 21 min en total.

Hubo dos ejecuciones:
1. **15/10, 215 pasos, recompensa del dominio rota** (`rlm/weights/grpo_sin_dominio_lora`,
   `grpo_sin_dominio.log`). Se quedó en 0,01-0,05: exigía la unidad dentro de `<answer>`,
   y la hoja del profesor pedía el número sin unidades; y leía "240,700" como 240,7. La
   cortó el fin de la sesión.
2. **18/10, 400 pasos, recompensa arreglada** (commit `310f048`; `rlm/weights/final_rlm_lora`,
   `grpo.log`). Con las respuestas del SFT, 0,99 de media en aciertos y 0,25 en fallos.

**Qué pasó.** Curvas de la ejecución 2, medias de 100 pasos:

| Pasos | Formato | Exactitud | Dominio | Cortadas | Longitud |
|---|---|---|---|---|---|
| 1-100 | 0,61 | 0,31 | 0,38 | 39 % | 1.112 |
| 101-200 | 0,73 | 0,32 | 0,41 | 27 % | 1.022 |
| 201-300 | 0,82 | 0,36 | 0,48 | 18 % | 938 |
| 301-400 | 0,83 | 0,34 | 0,49 | 17 % | 899 |

Hasta el paso 215, las dos ejecuciones van igual en formato, exactitud, cortadas y longitud
(los problemas salen en el mismo orden): lo único que cambia es la recompensa del dominio.

Evaluación en test, 300 problemas, 1.024 tokens (`reports/eval_grpo_17b.json`):

| | Base | SFT | **GRPO** |
|---|---|---|---|
| **pass@1** | 3,3 % | 32,0 % | **36,3 %** |
| Formato válido | 0,7 % | 47,3 % | 76,7 % |
| Cortadas | 81,3 % | 52,7 % | 23,3 % |
| Tokens medios | 983 | 866 | 718 |
| `acquisition_cost` | 10 % | 74 % | 78 % |
| `net_yield` | 2 % | 64 % | 56 % |
| `max_price` | 0 % | 36 % | 36 % |
| `legal_rent` | 8 % | 18 % | **46 %** |
| `irpf_rental` | 0 % | 0 % | 2 % |
| `cash_on_cash` | 0 % | 0 % | 0 % |

GRPO acierta 31 problemas que el SFT fallaba y falla 18 que el SFT acertaba (96 frente a 109
aciertos; McNemar exacto, p = 0,085).

**Qué concluimos.**
- Lo que más aprende GRPO es a ser compacto: un 20 % menos de longitud y la mitad de
  cortadas sin premiarlo directamente, solo porque una respuesta cortada no puntúa. Con el
  mismo presupuesto, más respuestas llegan a la cifra final.
- `legal_rent` lo muestra mejor: tras el SFT sabía resolverla pero no le daba tiempo (30 %
  con 2.048 tokens, 18 % con 1.024); tras GRPO saca un 46 % con 1.024.
- La mejora global es probable pero no concluyente con 300 problemas.
- `cash_on_cash` e `irpf_rental` siguen en 0: terminan más respuestas, pero mal. Sin
  aciertos en el grupo, GRPO no tiene señal en esas familias.
- Con 2.048 tokens (`reports/eval_grpo_17b_2048.json`), donde el espacio no limita:

  | | Base | SFT | **GRPO** |
  |---|---|---|---|
  | **pass@1** | 10,3 % | 37,7 % | **38,3 %** |
  | Formato válido | 3,3 % | 69,0 % | 92,0 % |
  | Cortadas | 35,0 % | 31,0 % | 8,0 % |
  | Tokens medios | 1.578 | 1.255 | 857 |

  GRPO acierta lo mismo que el SFT (22 problemas solo el SFT, 24 solo GRPO; McNemar p =
  0,88), con un tercio menos de tokens. Gana en `legal_rent` (30 → 46 %) y pierde en
  `max_price` (56 → 42 %).
- **En resumen: con 400 pasos, GRPO no enseña a resolver más problemas, sino a resolver los
  que ya sabía en menos tokens.** Por eso mejora con 1.024 y no con 2.048.
- Ablación de la recompensa del dominio: entrada siguiente.

---

### 2026-10-27 · Fase 1 · Ablación de la recompensa del dominio, curvas y análisis de fallos

**Qué queríamos saber.** Si la tercera recompensa ("desglose trazable": unidad junto a la
cifra final y cifras intermedias en el razonamiento) aporta algo frente a entrenar solo con
formato y exactitud.

**Qué hicimos.** Comparamos el `checkpoint-200` de las dos ejecuciones de GRPO, que salen del
mismo adaptador del SFT con la misma semilla y los problemas en el mismo orden. La única
diferencia es la recompensa del dominio: arreglada en una (`final_rlm_lora`) y prácticamente
nula en la otra (`grpo_sin_dominio_lora`, 0,01-0,05 durante todo el entrenamiento). Test de
300 problemas, 1.024 tokens, greedy.

**Qué pasó.**

| Paso 200, 1.024 tokens | Con recompensa del dominio | Sin ella |
|---|---|---|
| **pass@1** | 33,0 % | **35,7 %** |
| Formato válido | 65,3 % | 72,7 % |
| Cortadas | 34,7 % | 27,3 % |
| Tokens medios | 781 | 743 |
| Unidad junto a la cifra final | 194 / 300 | 218 / 300 |
| `legal_rent` | 32 % | 42 % |
| `max_price` | 26 % | 38 % |
| `net_yield` | 66 % | 60 % |

Cada versión acierta problemas que la otra falla (21 y 29); McNemar exacto, p = 0,32.
Detalle en `reports/eval_grpo200_dominio.json` y `reports/eval_grpo200_sin_dominio.json`.
Curvas de las dos ejecuciones en `reports/grpo_curvas.png`.

**Qué concluimos.**
- **No hay evidencia de que la recompensa del dominio ayude.** La versión sin ella sale
  ligeramente mejor, pero la diferencia no es significativa con 300 problemas. Tampoco aumenta
  lo que premia: la unidad junto a la cifra final aparece más sin ella (218 frente a 194).
- Una hipótesis, sin medir: la mitad de la recompensa premia escribir cifras intermedias, lo
  que alarga el razonamiento (781 frente a 743 tokens) y hace que se corten más respuestas con
  1.024 tokens (35 % frente a 27 %).
- En los aciertos, la recompensa vale casi siempre 1 (0,99 de media con las respuestas del
  SFT): el alumno ya escribe las cifras intermedias, así que apenas distingue entre respuestas
  correctas. Para que aporte haría falta que discriminara más, por ejemplo puntuando solo las
  cifras que el enunciado no da.
- Análisis de cinco fallos del modelo final en `docs/analisis_fallos_fase1.md`: obra nueva sin
  IVA (0 de 11), cash-on-cash sin cuota, IRPF sin amortización, divisiones mal hechas en
  `max_price` y bucles de repetición. Además, el alumno escribe "From the background knowledge"
  en 80 de 300 respuestas: la frase de la hoja del profesor se coló en 143 de las 703 trazas.

---

### 2026-11-17 · Fase 1 · Piloto de destilación con información privilegiada (`irpf_rental`)

**Qué queríamos saber.** Si darle al profesor la solución del motor de reglas le permite
resolver los problemas que no resolvía solo, sin que las trazas citen esa ayuda ni se
vuelvan repetitivas.

**Qué hicimos.** 20 problemas de `irpf_rental` en los que el profesor sin ayuda no consiguió
ninguna traza verificada (0 de 4 en cada uno). Al prompt del profesor (Qwen3-4B, con la hoja
de reglas) se añade una clave privada: los valores intermedios del motor con nombre y en
orden aleatorio, la reducción que aplica y la respuesta (`--privileged --only-unsolved`,
commit `4fe8f38` y siguientes). 4 muestras por problema, 2.048 tokens. Después,
`rlm/rewrite_traces.py`: el mismo profesor, sin modo de pensamiento, reescribe cada traza
correcta como si no hubiera visto la clave, y la traza se verifica de nuevo (respuesta,
valores intermedios calculados tras "=" o una operación, ninguna cita, en inglés).
70 min de destilación (pico de 13,2 GB) y unos 20 min de reescritura.

**Qué pasó.**

| | Sin clave (antes) | Con clave | Con clave y reescritas |
|---|---|---|---|
| Problemas con alguna traza correcta | 0 / 20 | 19 / 20 | — |
| Trazas correctas (de las terminadas) | — | 59 / 59 | — |
| Cortadas a 2.048 tokens | — | 21 / 80 | — |
| Citan la clave | — | 53 de las 59 correctas | 0 |
| **Trazas verificadas** | 0 | 6 | **42** (19 problemas) |
| Palabras del razonamiento (mediana) | 728* | — | 171 |

\* Trazas verificadas de `irpf_rental` sin clave, de otros problemas.

Rechazos en la reescritura: 15 por perder algún valor intermedio y 2 por estar en español.
Al revisar los primeros rechazos encontramos tres fallos del filtro, ya corregidos: no
reconocía "multiplied by 0.4055 gives 3,673.94", el signo "−" ni la frase "the key says…".

Repetición, con una traza por problema (similitud media de 4-gramas entre trazas de
problemas distintos, con los números sustituidos):

| | Sin clave | Con clave, reescritas |
|---|---|---|
| Similitud media | 0,071 | 0,075 |
| Aperturas distintas | 3 / 54 | 13 / 19 |

**Qué concluimos.**
- La clave resuelve lo que faltaba: el profesor ya sabía razonar estos problemas, le faltaba
  dar con la amortización y la reducción correctas.
- Sin la reescritura, la clave casi no sirve: casi todas las trazas correctas la citan
  ("which matches the private key's value", "but the key says 3,673…") y razonan a partir de
  ella. Pedirle en el prompt que no la mencione no basta.
- Las trazas reescritas no son más repetitivas que las del profesor sin ayuda, y empiezan de
  formas más variadas. Son mucho más cortas (171 frente a 728 palabras): soluciones limpias,
  sin las dudas y comprobaciones del modo de pensamiento. Conviene mezclarlas con las
  naturales, no sustituirlas.
- Siguiente paso: lo mismo en el resto de problemas sin resolver de `irpf_rental`,
  `cash_on_cash` y `legal_rent`, y más trazas de obra nueva.

---

### 2026-11-17 · Fase 1 · Ronda 2 de datos (clave en irpf y legal, obra nueva) y SFT 2

**Qué queríamos saber.** Si con trazas de los problemas que el profesor no resolvía solo
(`irpf_rental`, `legal_rent`) y de obra nueva, el alumno empieza a acertar esas familias, y si
así GRPO tendrá señal en ellas.

**Qué hicimos.** `distill_priv.sh` (Qwen3-4B, lotes de 2, `--privileged --only-unsolved`, cada
tanda seguida de `rlm.rewrite_traces`) y después `sft2.sh`:

| Tanda | Trazas | Verificadas | Problemas cubiertos | Tras reescribir |
|---|---|---|---|---|
| `irpf_rental` con clave (2048 tokens) | 64 | 17 (26,6 %) | 10/16 | 30 de 46 (13 problemas) |
| Obra nueva, sin clave | — | 141 | 40/40 | — |
| `legal_rent` con clave (2048 tokens) | 80 | 29 (36,2 %) | 17/20 | **63 de 63** (20 problemas) |

`cash_on_cash` con clave quedó para la próxima sesión (`relevo.sh` paró la cadena a las 14:46
para que el SFT 2 cupiera). La reescritura de `legal_rent` acepta más trazas que las
verificadas porque reescribe las que aciertan aunque se salten un cálculo intermedio, y al
reescribirlas el profesor los escribe todos.

SFT 2: Qwen3-1.7B desde el modelo base, mismo LoRA y mismos hiperparámetros que el SFT 1
(`--max-per-problem 3 --max-per-family 150 --max-length 3328`, 2 épocas, 86 pasos, 34 min,
loss final 0,35). 974 trazas verificadas, 688 tras el tope: acquisition_cost 150, legal_rent
150, irpf_rental 150, max_price 92, net_yield 91, cash_on_cash 55. Evaluación en test con
1024 tokens (`reports/eval_sft2_17b.json`).

**Qué pasó.**

| Familia (n=50) | SFT 1 | SFT 2 | Truncadas SFT 1 → 2 |
|---|---|---|---|
| acquisition_cost | 74 % | 76 % | 6 → 8 % |
| — de ellas obra nueva (n=11) | **1/11** | **9/11** | |
| cash_on_cash | 0 % | 0 % | 98 → 98 % |
| irpf_rental | 0 % | 2 % | **80 → 42 %** |
| legal_rent | 18 % | 18 % | 72 → 80 % |
| max_price | 36 % | 26 % | 44 → 38 % |
| net_yield | 64 % | 58 % | 16 → 18 % |
| **Total (300)** | **32,0 %** | **30,0 %** | 53 → 47 % |

- Obra nueva: de 1/11 a 9/11 (Fisher p = 0,002). El modelo ya suma el IVA del 10 %.
- El total baja 2 puntos, pero no es significativo: 31 problemas los acierta solo el SFT 1 y
  25 solo el SFT 2 (McNemar exacto p = 0,50). La bajada de max_price (18 → 13 de 50) tampoco
  lo es (Fisher p = 0,39).
- `irpf_rental`: ahora termina el 58 % de las veces (antes el 20 %), pero acierta 1 de 50. De
  las 29 respuestas terminadas, solo 7 mencionan la amortización y casi todas dan una cifra muy
  por encima de la esperada (4.886 frente a 3.912; 6.544 frente a 2.274): sigue sin restar la
  amortización ni aplicar bien la reducción.
- `legal_rent` y `cash_on_cash` siguen cortándose en 1024 tokens (80 % y 98 %).

Defecto encontrado en los datos: 48 de las 63 trazas reescritas de `legal_rent` y 21 de las 30
de `irpf_rental` están escritas enteras en minúsculas (manía del profesor al reescribir; las
cuentas están bien). Entraron así en el SFT 2.

**Qué concluimos.**
- Las trazas de obra nueva funcionan: es la única mejora clara del SFT 2.
- En `irpf_rental` las trazas con clave le enseñan a terminar, no a calcular bien. Antes de
  GRPO hay que ver con `sample_check` si con 8 muestras acierta alguna vez; si no, GRPO
  seguirá sin señal y harán falta pistas.
- `legal_rent` y `cash_on_cash` necesitan más tokens que 1024 o razonamientos más cortos.
- Para la próxima tanda, `rewrite_traces` debe rechazar las trazas en minúsculas.
- Pendiente: `cash_on_cash` con clave (`bash distill_priv.sh` continúa), `sample_check` del
  SFT 2 si no termina hoy, y GRPO 2.

---

### 2026-11-18 · Fase 1 · Decisión: el límite de 1024 tokens no cuadra con las trazas

**Qué queríamos saber.** Por qué `legal_rent` y `cash_on_cash` se cortan tanto en test y si
`irpf_rental` falla por longitud o por razonar mal.

**Qué hicimos.** Medir con el tokenizador de Qwen3 las trazas verificadas que entraron en el
SFT 2 y, en las evaluaciones guardadas, contar los aciertos solo entre las respuestas que
terminan.

**Qué pasó.**

| Trazas de entrenamiento | Mediana de tokens | Más largas que 1024 |
|---|---|---|
| cash_on_cash | 1.870 | 93 % |
| irpf_rental (profesor sin clave) | 1.437 | 90 % |
| legal_rent (profesor sin clave) | 1.053 | 52 % |
| irpf_rental / legal_rent reescritas | 383 / 190 | 0 % |
| acquisition_cost | 645 | 3 % |

En el SFT no se cortó ninguna (la más larga, ~3.100 tokens con la pregunta; límite 3328).
El corte está solo en la evaluación (`rlm/evaluate.py`, 1024 por defecto, heredado del
`--max-completion-length 1024` del plan para GRPO).

| Familia | Evaluación | Terminadas | Aciertos entre terminadas |
|---|---|---|---|
| legal_rent | SFT 1, 2048 | 23 | 15 |
| legal_rent | SFT 2, 1024 | 10 | 9 |
| irpf_rental | SFT 1, 2048 | 24 | 0 |
| irpf_rental | SFT 2, 1024 | 29 | 1 |
| cash_on_cash | SFT 1, 2048 | 19 | 0 |

**Qué concluimos.**
- Error nuestro: subimos el límite del profesor (2048, 3072) para que terminara, sin controlar
  la longitud, y evaluamos al alumno con 1024. Hay que elegir: o el alumno tiene el mismo
  presupuesto que las trazas, o las trazas caben en el del alumno.
- `legal_rent` es solo longitud: cuando termina, acierta casi siempre.
- `irpf_rental` y `cash_on_cash` razonan mal aunque terminen: no es cuestión de tokens.
- La cifra principal pasa a ser la de 2048 tokens (`eval_sft2_2048.sh`, en cola) y el GRPO 2
  usará al menos 1536.

---

### 2026-11-18 · Fase 1 · Muestreo del SFT 2, `cash_on_cash` con clave y pistas para GRPO

**Qué queríamos saber.** Si el SFT 2 acierta alguna vez las familias difíciles con 8 intentos
(si no, GRPO no tiene señal en ellas) y si la destilación con clave funciona en `cash_on_cash`.

**Qué hicimos.** `sesion3.sh`: `rlm.sample_check` sobre el SFT 2 (8 problemas de train por
familia, 8 respuestas a temperatura 1,0, 1536 tokens; obra nueva con 6 problemas), y después
`cash_on_cash` con clave (3072 tokens, `--only-unsolved`) y su reescritura.

**Qué pasó.** Muestreo (`reports/sample_check_sft2*.json`):

| Familia | pass@8 | Problemas útiles | Respuestas correctas | Cortadas |
|---|---|---|---|---|
| legal_rent | 7/8 | 7/8 | 53 % | 16 % |
| obra nueva | 6/6 | 6/6 | 62 % | 4 % |
| irpf_rental | **0/8** | 0/8 | 0 de 64 | 22 % |
| cash_on_cash | **0/8** | 0/8 | 0 de 64 | 62 % |

La recompensa por pasos media de las respuestas fallidas de irpf es 0,07: el error está al
principio (la amortización), no hay crédito parcial que aprovechar.

`cash_on_cash` con clave: 32 problemas que el profesor nunca resolvió, 128 trazas, las 128 con
la respuesta correcta pero 36 de las primeras 48 citan la clave ("The answer provided in the
key is 1.31%"). Tras la reescritura, 51 verificadas de 26 problemas; 76 rechazadas por
saltarse algún valor intermedio. Las que pasan calculan la cuota con la fórmula, pero la
potencia (1+i)^-300 la dan como "aproximadamente 0,4666" sin desarrollarla.

**Qué concluimos.**
- `legal_rent` y obra nueva ya tienen señal para GRPO.
- `irpf_rental` y `cash_on_cash` no: hacen falta pistas. `rlm/hints.py` añade copias de esos
  problemas con una pista al final del enunciado (nivel 1: el método; nivel 2: además el
  primer valor intermedio), dejando también los originales (`--hint-families` en
  `train_grpo`, `--hint-level` en `sample_check`). Idea de Scaf-GRPO / Guide-GRPO.
- Cambio de orden: en vez de evaluar el SFT 2 a 2048 y muestrear con pistas sobre él, SFT 3
  desde el modelo base con todas las trazas (incluidas las 51 de cash) y tope de 200 por
  familia, y las pruebas sobre el SFT 3, que será el punto de partida del GRPO 2.
- La potencia de la cuota sigue siendo aritmética que el 1,7B tiene que memorizar: en
  `cash_on_cash` la solución de fondo es la calculadora de la fase 2.
