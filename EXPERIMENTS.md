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

**Qué hicimos.** `nohup uv run arca-smoke > logs/fase1/smoke.log 2>&1 &`: Qwen3-0.6B con LoRA de rango
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
máximo, lotes de 16). El comando exacto no quedó en `logs/fase1/eval_probe.log`; fue el equivalente a
`--n-examples 32 --out reports/fase1/eval_base_06b_probe.json`. Tardó 510 s.

**Qué pasó.** Detalle en `reports/fase1/eval_base_06b_probe.json` y gráfico en
`reports/fase1/eval_base_06b_probe.png`.

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
(salida en `logs/fase1/baseline.log`): `rlm.evaluate` sobre los 300 problemas de `rlm/data/test.jsonl`,
sin adaptador, con 1024 tokens nuevos como máximo. 0,6B: de 08:50 a 09:18 (~28 min).
1,7B: de 09:18 a 09:49 (~31 min).

**Qué pasó.** Detalle en `reports/fase1/eval_base_06b.json` y `reports/fase1/eval_base_17b.json`, con
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

**Qué hicimos.** `scripts/fase1/distill_hard.sh` (commit `dde430d`), con problemas nuevos de train
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
  Queda una tanda con 3072 tokens y un orden fijo de cálculo (`scripts/fase1/distill_irpf.sh`, commit
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
Evaluación con `scripts/fase1/eval_sft.sh` sobre los 300 problemas de test, en modo greedy.

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

Detalle en `reports/fase1/eval_sft_17b.json`, `reports/fase1/eval_sft_17b_2048.json` y
`reports/fase1/eval_base_17b_2048.json`. Con 2.048 tokens, el 55 % de las respuestas que terminan
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
   `logs/fase1/grpo_sin_dominio.log`). Se quedó en 0,01-0,05: exigía la unidad dentro de `<answer>`,
   y la hoja del profesor pedía el número sin unidades; y leía "240,700" como 240,7. La
   cortó el fin de la sesión.
2. **18/10, 400 pasos, recompensa arreglada** (commit `310f048`; `rlm/weights/final_rlm_lora`,
   `logs/fase1/grpo.log`). Con las respuestas del SFT, 0,99 de media en aciertos y 0,25 en fallos.

**Qué pasó.** Curvas de la ejecución 2, medias de 100 pasos:

| Pasos | Formato | Exactitud | Dominio | Cortadas | Longitud |
|---|---|---|---|---|---|
| 1-100 | 0,61 | 0,31 | 0,38 | 39 % | 1.112 |
| 101-200 | 0,73 | 0,32 | 0,41 | 27 % | 1.022 |
| 201-300 | 0,82 | 0,36 | 0,48 | 18 % | 938 |
| 301-400 | 0,83 | 0,34 | 0,49 | 17 % | 899 |

Hasta el paso 215, las dos ejecuciones van igual en formato, exactitud, cortadas y longitud
(los problemas salen en el mismo orden): lo único que cambia es la recompensa del dominio.

Evaluación en test, 300 problemas, 1.024 tokens (`reports/fase1/eval_grpo_17b.json`):

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
- Con 2.048 tokens (`reports/fase1/eval_grpo_17b_2048.json`), donde el espacio no limita:

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
Detalle en `reports/fase1/eval_grpo200_dominio.json` y `reports/fase1/eval_grpo200_sin_dominio.json`.
Curvas de las dos ejecuciones en `reports/fase1/grpo_curvas.png`.

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
- Análisis de cinco fallos del modelo final en `docs/fase1/analisis_fallos_fase1.md`: obra nueva sin
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

**Qué hicimos.** `scripts/fase1/distill_priv.sh` (Qwen3-4B, lotes de 2, `--privileged --only-unsolved`, cada
tanda seguida de `rlm.rewrite_traces`) y después `scripts/fase1/sft2.sh`:

| Tanda | Trazas | Verificadas | Problemas cubiertos | Tras reescribir |
|---|---|---|---|---|
| `irpf_rental` con clave (2048 tokens) | 64 | 17 (26,6 %) | 10/16 | 30 de 46 (13 problemas) |
| Obra nueva, sin clave | — | 141 | 40/40 | — |
| `legal_rent` con clave (2048 tokens) | 80 | 29 (36,2 %) | 17/20 | **63 de 63** (20 problemas) |

`cash_on_cash` con clave quedó para la próxima sesión (`scripts/fase1/relevo.sh` paró la cadena a las 14:46
para que el SFT 2 cupiera). La reescritura de `legal_rent` acepta más trazas que las
verificadas porque reescribe las que aciertan aunque se salten un cálculo intermedio, y al
reescribirlas el profesor los escribe todos.

SFT 2: Qwen3-1.7B desde el modelo base, mismo LoRA y mismos hiperparámetros que el SFT 1
(`--max-per-problem 3 --max-per-family 150 --max-length 3328`, 2 épocas, 86 pasos, 34 min,
loss final 0,35). 974 trazas verificadas, 688 tras el tope: acquisition_cost 150, legal_rent
150, irpf_rental 150, max_price 92, net_yield 91, cash_on_cash 55. Evaluación en test con
1024 tokens (`reports/fase1/eval_sft2_17b.json`).

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
- Pendiente: `cash_on_cash` con clave (`bash scripts/fase1/distill_priv.sh` continúa), `sample_check` del
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

**Qué hicimos.** `scripts/fase1/sesion3.sh`: `rlm.sample_check` sobre el SFT 2 (8 problemas de train por
familia, 8 respuestas a temperatura 1,0, 1536 tokens; obra nueva con 6 problemas), y después
`cash_on_cash` con clave (3072 tokens, `--only-unsolved`) y su reescritura.

**Qué pasó.** Muestreo (`reports/fase1/sample_check_sft2*.json`):

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

---

### 2026-11-18 · Fase 1 · SFT 3, evaluación a 2048 y muestreo con pistas

**Qué queríamos saber.** Si el SFT con todas las trazas de la ronda 2 (incluidas las 51 de
`cash_on_cash` con clave) mejora al SFT 1 y al GRPO 1 con el presupuesto justo de 2048 tokens,
y si las pistas dan señal para el GRPO 2 en `irpf_rental` y `cash_on_cash`.

**Qué hicimos.** `scripts/fase1/sft3.sh`: SFT desde el modelo base con las nueve tandas de trazas,
`--max-per-problem 3 --max-per-family 200` (857 trazas: acquisition_cost 200, legal_rent 200,
irpf_rental 169, cash_on_cash 105, max_price 92, net_yield 91), 108 pasos, 35 min
(`rlm/weights/sft3_lora`). Evaluación en test con 2048 tokens (80 min) y `sample_check` en irpf
y cash (8 problemas × 8 respuestas, 2048 tokens) sin pista y con pista de nivel 2.

**Qué pasó.** Test, 2048 tokens (`reports/fase1/eval_sft3_17b_2048.json`), aciertos:

| Familia | SFT 1 | GRPO 1 | SFT 3 |
|---|---|---|---|
| acquisition_cost (50) | 36 | 37 | **43** |
| — obra nueva (11) | 0 | 0 | **6** |
| net_yield (50) | 34 | 32 | 35 |
| max_price (50) | **28** | 21 | 23 |
| legal_rent (50) | 15 | **23** | 14 |
| irpf_rental (50) | 0 | 2 | **3** |
| cash_on_cash (50) | 0 | 0 | **3** |
| **Total (300)** | 37,7 % | 38,3 % | **40,3 %** |
| Cortadas | 31 % | 8 % | 23 % |

Ninguna diferencia del total es significativa: frente al SFT 1, 29 problemas solo los acierta
el SFT 3 y 21 solo el SFT 1 (McNemar exacto p = 0,32); frente al GRPO 1, 33 y 27 (p = 0,52).
`legal_rent` sigue cortándose (termina 22 de 50; acierta 14 de esas 22).

Muestreo (`reports/fase1/sample_check_sft3_pista{0,2}.json`):

| | Sin pista: pass@8 | Sin pista: correctas | Pista 2: pass@8 | Pista 2: correctas |
|---|---|---|---|---|
| irpf_rental | 1/8 | 2 % | 1/8 | 3 % |
| cash_on_cash | 1/8 | 2 % | **8/8** | **77 %** |

Con la cuota de la hipoteca dada, `cash_on_cash` sale casi siempre: su único problema es esa
cuenta. En `irpf_rental` dar la amortización no basta. Revisando las 36 respuestas terminadas
de irpf en test: de las 28 con rendimiento positivo, 15 eligen mal la reducción (sobre todo 70 %
en vez de 90 %, y 50 % en vez de 60 %) y 19 calculan mal la amortización, casi siempre por
la parte del suelo (1 − 114.500 / 201.000 escrito como 0,463 en vez de 0,430). Otras 6
respuestas quedan a menos del 0,5 % del valor correcto pero fuera de la tolerancia de 0,05 %:
redondean resultados intermedios.

**Qué concluimos.**
- El SFT 3 es el mejor punto de partida para el GRPO 2 (40,3 %, primeros aciertos en cash).
- `cash_on_cash`: pistas de nivel 2 en el GRPO 2 dan señal de sobra.
- `irpf_rental` falla en dos sitios: la regla de la reducción y la aritmética del suelo. La
  pista de nivel 1 pasa a incluir el orden de las reducciones, y la de nivel 2 también la
  reducción que corresponde; se está midiendo de nuevo.

**Añadido 23:10.** Con la pista nueva (orden de las reducciones y la que corresponde),
`irpf_rental` pasa a pass@8 = 8/8, 8/8 problemas útiles y 23 % de respuestas correctas
(`reports/fase1/sample_check_sft3_pista2_irpf_v2.json`). Prueba de 3 pasos del GRPO 2 a 2048 tokens
desde el SFT 3 con pistas: cabe en la MIG, ~80 s por paso. La prueba enseñó que el learning
rate bajaba en línea recta hasta 0 al final de cada ejecución, lo que rompe una ejecución en
dos etapas: `--lr-scheduler constant`. `scripts/fase1/grpo2.sh` queda listo para la próxima sesión.

---

### 2026-11-18 · Fase 1 · GRPO 2 desde el SFT 3, con pistas y recompensa por pasos

**Qué queríamos saber.** Si el GRPO con las mejoras de la ronda 2 (punto de partida SFT 3,
2048 tokens, recompensa por pasos, learning rate 4 veces mayor y pistas en las familias sin
señal) mejora claramente al SFT 3 y al GRPO 1.

**Qué hicimos.** `scripts/fase1/grpo2.sh` (de 23:55 a 07:14, en una sesión): 400 pasos, un problema y 8
respuestas por paso, `--max-completion-length 2048 --learning-rate 2e-5 --lr-scheduler constant
--third-reward process`, pesos 0,5 / 2,0 / 0,5, 10 % de control GSM8K. Pasos 1–250 con copias
con pista de nivel 2 de los 400 problemas de `irpf_rental` y los 400 de `cash_on_cash`
(`--hint-share 1.0`, 3.556 problemas en total); pasos 251–400 sin pistas, continuando del
checkpoint 250. ~40 s por paso. Evaluación en test con 2048 tokens (69 min).

**Qué pasó.** Entrenamiento, medias de 50 pasos (`rlm/weights/grpo2_lora/checkpoint-400/trainer_state.json`):

| Pasos | Exactitud | Recompensa por pasos | Pasos sin señal | Longitud media | Cortadas |
|---|---|---|---|---|---|
| 1–50 | 0,51 | 0,49 | 11 | 1171 | 21 % |
| 51–100 | 0,46 | 0,64 | 4 | 1074 | 16 % |
| 101–150 | 0,48 | 0,64 | 9 | 918 | 7 % |
| 151–200 | 0,48 | 0,64 | 10 | 888 | 4 % |
| 201–250 | 0,53 | 0,65 | 7 | 898 | 6 % |
| 251–300 (sin pistas) | 0,43 | 0,48 | 9 | 1073 | 11 % |
| 301–350 | 0,42 | 0,54 | 8 | 1040 | 10 % |
| 351–400 | 0,40 | 0,61 | 7 | 1013 | 7 % |

La exactitud cae al quitar las pistas (los problemas pasan a ser más difíciles), no por
olvido: la recompensa por pasos se recupera de 0,48 a 0,61.

Test, 2048 tokens (`reports/fase1/eval_grpo2_17b_2048.json`), aciertos:

| Familia | SFT 1 | GRPO 1 | SFT 3 | **GRPO 2** |
|---|---|---|---|---|
| acquisition_cost (50) | 36 | 37 | 43 | **46** |
| — obra nueva (11) | 0 | 0 | 6 | **8** |
| net_yield (50) | 34 | 32 | 35 | 34 |
| max_price (50) | **28** | 21 | 23 | 22 |
| legal_rent (50) | 15 | 23 | 14 | **30** |
| irpf_rental (50) | 0 | 2 | **3** | 2 |
| cash_on_cash (50) | 0 | 0 | 3 | **8** |
| **Total (300)** | 37,7 % | 38,3 % | 40,3 % | **47,3 %** |
| Cortadas | 31 % | 8 % | 23 % | 6 % |

Por primera vez las mejoras son significativas (McNemar exacto): frente al SFT 3, 51 problemas
solo los acierta el GRPO 2 y 30 solo el SFT 3 (p = 0,026); frente al GRPO 1, 48 y 21
(p = 0,002); frente al SFT 1, 51 y 22 (p = 0,001).

**Qué concluimos.**
- El GRPO 2 es el mejor modelo de la fase 1: 47,3 % en test, +9 puntos sobre el GRPO 1.
- La mayor parte de la mejora es `legal_rent` (14 → 30): GRPO acorta las respuestas (de 1062
  a 896 tokens; cortadas del 23 % al 6 %) y esa familia ya sabía resolverse cuando terminaba.
- `cash_on_cash` sube de 3 a 8 con las pistas; sigue limitada por la potencia de la cuota.
- `irpf_rental` no mejora (3 → 2) pese a acertar el 23 % con pista durante el muestreo: lo
  aprendido con la pista no pasa a los problemas sin ella. Es la familia pendiente.
- max_price sigue por debajo del SFT 1 (28 → 22): pierde algo con cada ronda.

---

### 2026-11-18 · Fase 1 · Por qué fallan irpf, cash y max_price tras el GRPO 2

**Qué queríamos saber.** Por qué `irpf_rental` no mejora con el GRPO 2 pese a las pistas, y
qué limita a `cash_on_cash` y max_price.

**Qué hicimos.** Revisar las respuestas terminadas de test (`reports/fase1/eval_{sft3,grpo2}_17b_2048.json`):
la reducción que aplica el modelo en irpf frente a la correcta, si la amortización coincide con
la del motor, y a qué distancia del valor correcto quedan las respuestas fallidas.

**Qué pasó.**

Reducción elegida en irpf (respuestas terminadas con rendimiento positivo):

| | Bien | Mal | Error más común |
|---|---|---|---|
| SFT 3 | 13 de 28 | 15 | 90 % → 70 % (4) |
| GRPO 2 | **5 de 36** | 31 | **50 % → 70 % (11)** |

Respuestas que quedan cerca del valor correcto (la tolerancia del verificador es 0,05 %):

| Familia, GRPO 2 | Aciertos | A menos del 0,5 % | A menos del 1 % | Terminadas |
|---|---|---|---|---|
| max_price | 22 | 43 | **49** | 49 |
| cash_on_cash | 8 | 9 | 15 | 43 |
| irpf_rental | 2 | 4 | 4 | 46 |

Ejemplo de max_price: plantea bien `1,09·P + 6.000 = 425.333,33` y calcula
`419.333,33 / 1,09 ≈ 385.333,33` (es 384.709,48).

**Qué concluimos.**
- En irpf el GRPO 2 empeoró la elección de la reducción: aplica el 70 % casi por defecto
  ("la renta bajó más de un 5 % → 70 %", cuando esa condición da el 90 % y solo en zona
  tensionada). La pista de nivel 2 le daba la reducción hecha, así que el GRPO premió copiarla
  en vez de deducirla, y sin pista adivina. Si se repite, mejor pista de nivel 1 (solo la regla).
- max_price razona bien casi siempre (49 de 49 a menos del 1 %) y falla la división. Con
  cash_on_cash pasa algo parecido. Son errores de aritmética, no de dominio: es exactamente lo
  que resuelve la calculadora de la fase 2.

---

### 2026-11-18 · Fase 1 · Curvas del GRPO 2, reward hacking y fallos actualizados

**Qué hicimos.** Curvas de entrenamiento del GRPO 2 frente al GRPO 1
(`reports/fase1/grpo2_vs_grpo1_curves.png`, media móvil de 25 pasos, línea en el paso 250 donde se
quitan las pistas; la "tercera recompensa" es la de desglose en el GRPO 1 y la de pasos en el
GRPO 2, no son comparables entre sí). Revisión de las 3.200 respuestas guardadas del GRPO 2
buscando reward hacking, y recuento de los cinco patrones de fallo en el GRPO 2
(`docs/fase1/analisis_fallos_fase1.md`, sección "Ronda 2").

**Qué pasó.** Sin reward hacking: densidad de números estable (13-14 por cada 100 palabras) y
las fallidas con recompensa por pasos completa usan menos cifras distintas que el resto (23,9
frente a 28,5). Patrones: obra nueva 0 → 8 de 11, cash sin cuota 22 → 9 fallos, irpf sin
amortización 34 → 8 fallos, citas a "background knowledge" 80 → 0, bucles 43 → 31.

**Qué concluimos.** El conocimiento del dominio se arregló con datos y la longitud con GRPO; lo
que queda es aritmética (fase 2) y la regla de la reducción del IRPF.

---

### 2026-11-18 · Fase 1 · ¿SFT memoriza, RL generaliza? Evaluación fuera de distribución

**Qué queríamos saber.** Cómo se degradan SFT y GRPO en problemas de dos composiciones de
reglas que no aparecen en entrenamiento (`rlm/data/test_ood.jsonl`: `becomes_large_holder` y
`max_price_capped`, 75 cada una).

**Qué hicimos.** `scripts/fase1/eval_ood.sh`: los cuatro modelos con 2048 tokens y greedy, de 10:11 a 14:00
(`reports/fase1/eval_ood_{sft,grpo,sft3,grpo2}_2048.json`).

**Qué pasó.**

| Modelo | Test | Fuera de distribución | Conserva | large_holder | max_price_capped | Cortadas |
|---|---|---|---|---|---|---|
| SFT 1 | 37,7 % | 6,0 % | 16 % | 7 | 2 | 113 / 150 |
| GRPO 1 | 38,3 % | 18,0 % | 47 % | 21 | 6 | 55 / 150 |
| SFT 3 | 40,3 % | 9,3 % | 23 % | 11 | 3 | 88 / 150 |
| GRPO 2 | 47,3 % | **20,7 %** | 44 % | **28** | 3 | 47 / 150 |

En las dos rondas GRPO generaliza mucho mejor que el SFT del que parte (McNemar exacto):
SFT 1 → GRPO 1, 5 frente a 23 problemas (p = 0,001); SFT 3 → GRPO 2, 1 frente a 18
(p = 0,0001). Entre GRPO 1 y GRPO 2 no hay diferencia fuera de distribución (11 frente a 15,
p = 0,56), aunque en test el GRPO 2 es mejor.

Aciertos solo entre las respuestas que terminan: SFT 1 24 % (9/37), GRPO 1 28 % (27/95),
SFT 3 23 % (14/62), GRPO 2 30 % (31/103).

**Qué concluimos.**
- Se reproduce "SFT memoriza, RL generaliza": los SFT conservan el 16-23 % de su nota fuera de
  distribución; los GRPO, el 44-47 %.
- Pero la mayor parte de la ventaja viene de **terminar**: ante un problema nuevo el SFT se
  enreda y se corta (75 % y 59 % de cortadas), y GRPO aprendió a razonar de forma concisa y
  cerrar. Entre las respuestas que terminan, el GRPO acierta solo algo más (28-30 % frente a
  23-24 %). La generalización que aporta RL aquí es sobre todo de **cómo** razonar (longitud,
  cierre), más que de **qué** reglas aplicar.
- `max_price_capped` (precio máximo con un tope legal) sigue casi a 0 en los cuatro: combina
  dos familias y la aritmética de max_price, que ya fallaba dentro de distribución.
- Lo que la ronda 2 añadió (datos con la clave, pistas) mejora el test pero no la
  generalización: el GRPO 2 y el GRPO 1 están empatados fuera de distribución.

---

### 2026-11-17 · Fase 2 · Qué herramientas construir: investigación del dominio y decisión

**Qué queríamos saber.** Qué herramientas tienen sentido para Umbral. No las que cumplen el
mínimo, sino las que aportan algo que no haga ya otro producto, y que un modelo de 1,7B pueda
usar.

**Qué hicimos.** Investigamos cuatro frentes con búsquedas en la web y pruebas de cada API
desde la DGX:
- qué recomiendan los inversores con experiencia;
- qué palancas legales y fiscales hay;
- qué herramientas existen ya (portales, Invisor, TaxDown, Vivara, apps de ChatGPT);
- qué datos públicos se pueden consultar de verdad.

El informe está en [`docs/fase2/investigacion_fase2.md`](docs/fase2/investigacion_fase2.md).

**Qué pasó.**
- **Ninguna herramienta revisada aplica la norma por el usuario.** Le preguntan justo lo que no
  sabe:
  - el tipo de ITP de su comunidad;
  - si la base es el precio o el valor de referencia;
  - qué reducción del art. 23.2 le toca (TaxDown la pone en un desplegable de 0 a 100 %).
- Ninguna dice si la renta de un piso concreto es legal.
- Esos son también los fallos del alumno de la fase 1: la obra nueva sin IVA, el IRPF sin
  amortización y la cuota del `cash_on_cash`.
- **APIs que responden sin clave:** CartoCiudad, el servicio libre del Catastro, Euríbor del
  BdE e IRAV del INE.
- **Lo que no hay en abierto:** el valor catastral ni el de referencia, una fuente legible por
  máquina de los tipos de ITP o de las zonas tensionadas, ni una API de subastas del BOE (su
  `robots.txt` lo prohíbe todo).
- La cuota de unas 100 llamadas al mes de Idealista no aparece en ninguna fuente primaria.

**Qué concluimos.**
- **10 herramientas:**
  - Consulta: `lookup_property`, `get_market_rates` y `get_rent_reference`.
  - Cálculo, sobre el motor de la fase 1: `acquisition_cost`, `rental_returns`,
    `max_offer_price`, `legal_rent_cap` y `rental_income_tax`.
  - Acción con estado: `save_to_portfolio` y `get_portfolio`.
- Las calculadoras **deducen** lo que la gente suele equivocar en vez de pedirlo:
  - el ITP, a partir de la comunidad;
  - la reducción del IRPF, a partir de la fecha y los datos del contrato.
- Idealista queda como opcional, porque con esa cuota no aguanta el desarrollo, el banco y la
  corrección.
- `calculator`, la calculadora genérica de la plantilla, sale del registro del endpoint. Se
  queda solo para una ablación: con ella, el modelo aún tiene que aplicar las reglas por su
  cuenta.

---

### 2026-11-17 · Fase 2 · El RDL 29/2026, leído en el BOE: la reducción del IRPF tiene tres regímenes

**Qué queríamos saber.** Si lo que decían tres despachos sobre el RDL 29/2026 era cierto, y qué
reglas del motor deja anticuadas.

**Qué hicimos.** Leímos el texto del BOE
([BOE-A-2026-20823](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-20823)), sacado con la
API de sumarios. Nos centramos en el art. 6, que reescribe el art. 23.2 de la LIRPF, y en la
disposición transitoria 38.ª. Resumen en [`docs/investigacion/rdl_29_2026.md`](docs/investigacion/rdl_29_2026.md).

**Qué pasó.**
- **La reducción conserva tres regímenes según la fecha de firma del contrato:**
  - antes del 26/05/2023: 60 %;
  - del 26/05/2023 al 01/12/2026: la escala de la Ley 12/2023;
  - desde el 01/12/2026: una escala nueva.
- **La escala nueva**, solo si el arrendador no es gran tenedor:
  - bajar la renta más de un 5 % da 100/95/90/85/70 %;
  - no subirla da el 50 %;
  - subirla da del 40 % al 15 % según el tramo;
  - el primer alquiler tiene su propia escala, con el 100 % por debajo del índice SERPAVI.
- Al gran tenedor solo le quedan el 70 % (alquiler social) y el 60 % (rehabilitación).
- La fecha del 1 de diciembre que daban los despachos era correcta. El "2 % de subida máxima
  hasta 2027" que también daban **no aparece en el texto**.

**Qué concluimos.**
- La escala nueva va al motor como **función nueva**, `rental_reduction_pct_2026`, con un test
  por cada letra del artículo (23 casos). Las funciones de la fase 1 no cambian, porque su
  dataset es anterior y la escala de 2023 sigue vigente para esos contratos.
- `rental_income_tax` elige el régimen por la fecha y calcula la variación de la renta a
  partir de la renta anterior y la nueva.
- Es el mejor ejemplo de por qué la regla debe vivir en la herramienta y no en los pesos: el
  alumno, entrenado con la escala de 2023, no puede saber la nueva.
- **No están modelados:** el reparto entre varios inquilinos de edades distintas, el 80 % de la
  prórroga tácita y las habitaciones.

---

### 2026-11-17 · Fase 2 · Zonas tensionadas del BOE y rentas del SERPAVI como datos de las herramientas

**Qué queríamos saber.** Si se puede responder "¿es zona tensionada?" y "¿cuánto se paga de
alquiler aquí?" sin que el usuario lo sepa.

**Qué hicimos.** `tool_use/build_data.py` construye dos ficheros:
- **Zonas tensionadas.** Lee las 10 resoluciones trimestrales del Ministerio en el BOE, de
  marzo de 2024 a octubre de 2026.
- **Rentas del SERPAVI.** Usa la hoja de municipios del Excel del SERPAVI (71 MB, no se
  versiona): pisos, último año con datos y solo municipios con al menos 10 contratos.

**Qué pasó.**
- **322 zonas:**
  - por comunidad: Cataluña 272, País Vasco 21, Navarra 21, Asturias 6 y Galicia 2;
  - 8 cubren solo una parte del municipio (un distrito de Galdakao, barrios de Gijón y Avilés,
    núcleos de Llanes…) y la herramienta lo avisa;
  - en 312 la declaración baja el umbral de gran tenedor a 5 viviendas; Bilbao y Asturias no;
  - las 322 aplican el tope del índice a las viviendas sin contrato previo.

  Son justo dos argumentos de `legal_rent_cap` (`zone_lowers_threshold` y
  `declaration_caps_unrented`) que el usuario no suele conocer.
- **SERPAVI:** 2.616 municipios, 2.555 con datos de 2024. Son rentas declaradas a Hacienda de
  contratos en vigor, no precios de anuncio. Madrid da una mediana de 13,97 €/m² y Barcelona
  de 13,68 €/m², muy por debajo de lo que piden los portales.
- **Un error encontrado al montar el banco.** `normalise_name` quitaba como si fuera un
  artículo el principio de cualquier nombre que empezara por "a", "o" o "la": "Olot" quedaba
  en "lot", "Alella" en "lella" y "Lasarte-Oria" en "sarte-oria". **34 de las 322 zonas** no
  se habrían encontrado nunca. Además, el formato del INE "Coruña, A" no cruzaba con
  "A Coruña". Corregido y con test.
- **Detalles del BOE que el parser maneja a mano:**
  - una coma que falta en la lista catalana ("Manresa el Masnou");
  - "Vitoria-Gasteiz, excepto la zona rural…", que se partía por la coma.

**Qué concluimos.**
- `get_rent_reference` combina las dos fuentes. Funciona por nombre (también bilingüe:
  "San Sebastián" encuentra "Donostia / San Sebastián") o por código INE, que es lo que
  devuelve `lookup_property`, así que encadenan sin ambigüedad.
- **Lo que no da** es el índice legal SERPAVI de una vivienda concreta: eso sale del visor
  del Ministerio con su referencia catastral. La herramienta lo dice.
- **Pendiente:**
  - Cataluña amplió la lista a unos 302 municipios en julio de 2026, pero aún no aparece en
    ninguna resolución del BOE;
  - las declaraciones parciales están a nivel de municipio, sin el cruce por sección censal.

---

### 2026-11-17 · Fase 2 · Primera prueba del bucle con un modelo real (Qwen3-0.6B, CPU, un caso)

**Qué queríamos saber.** Si el bucle funciona de principio a fin con un modelo de verdad: el
formato nativo de Qwen3, el parser, la validación y la vuelta del error al modelo.

**Qué hicimos.**
`CUDA_VISIBLE_DEVICES="" uv run python -m tool_use.evaluate --model Qwen/Qwen3-0.6B --ids acq-01 --max-new-tokens 120 --max-turns 2`.

Fue en CPU porque la GPU estaba ocupada con el SFT 2. Es un solo caso, así que no es una
medida: solo comprueba que las piezas encajan.

**Qué pasó.**
- El modelo eligió `acquisition_cost` y copió bien el precio, el valor de referencia y la
  notaría.
- Pero puso `region: "sevilla"`, la ciudad en vez de la comunidad. La validación lo rechazó y
  le devolvió el error, un mensaje largo con las 17 comunidades.
- En el segundo turno no corrigió la llamada: **abandonó y se inventó la respuesta**
  (187.500 €, sin ITP).
- Selección 1/1 y argumentos 0/1.
- Las 10 definiciones ocupan 4.767 tokens con el tokenizador de Qwen3. La más larga es
  `rental_income_tax`, con 1.022.

**Qué concluimos.**
- El bucle funciona de principio a fin con un modelo real.
- Con un 0,6B no sacamos conclusiones. Pero el fallo apunta a una decisión de diseño que
  mediremos con el 1,7B: un esquema estricto, que obliga al modelo a traducir ciudad →
  comunidad, o una herramienta tolerante, que acepta "Sevilla" y la traduce ella con la tabla
  de provincias.
- **Siguiente, en cuanto la GPU quede libre:**
  1. el banco de 40 casos con Qwen3-1.7B base, con y sin thinking;
  2. el banco con el adaptador de GRPO;
  3. `phase1_compare` sobre el test de la fase 1.

---

### 2026-11-17 · Fase 2 · Primer banco: Qwen3-1.7B base frente al adaptador de GRPO de la fase 1

**Qué queríamos saber.** Cómo usa las 10 herramientas el modelo de 1,7B sin entrenar para
ello, y si el adaptador de la fase 1 (SFT + GRPO, `final_rlm_lora`) ayuda o estorba.

**Qué hicimos.** El banco de 40 casos en la GPU, con `scripts/fase2/fase2_bench.sh`:
`uv run python -m tool_use.evaluate --out reports/fase2/phase2_bench_base.json` y lo mismo con
`--adapter …/final_rlm_lora`. Las condiciones:
- formato nativo de Qwen3;
- sin thinking;
- 4 turnos como máximo;
- 2.048 tokens por turno;
- decodificación voraz.

Unos 7 minutos por ejecución.

Las cifras son tras `--rescore` con el evaluador corregido (entrada siguiente): `cap-02` se
daba por fallado cuando el modelo acertaba, y unos argumentos rechazados por la validación ya
no cuentan como correctos.

**Qué pasó.** Casos acertados, de 40:

| | Selección | Argumentos | Secuencia (10 encadenados y paralelos) | Llamadas innecesarias (8) |
|---|---|---|---|---|
| Base | 34 | 24 | 4 | 0 |
| + GRPO fase 1 | 27 | 18 | 2 | 0 |

Informes: [`reports/fase2/phase2_bench_base.json`](reports/fase2/phase2_bench_base.json) y
[`reports/fase2/phase2_bench_grpo.json`](reports/fase2/phase2_bench_grpo.json).

- **El modelo base elige bien y se equivoca en los argumentos.** Selección del 85 %, pero
  en los casos `single` solo acierta los argumentos el 50 %. Cuatro causas:
  - **Inventa la comunidad:** Sevilla → `extremadura`, Málaga → `extremadura`, Bilbao →
    `baleares`, Barcelona → `"barcelona"` (que la validación rechaza). El esquema estricto
    (`Literal` con 17 comunidades) le pide una traducción que no sabe hacer.
  - **Rellena todos los opcionales con 0.** Sin hipoteca pone `loan_years: 0` y la
    validación lo rechaza (≥ 1). En `par-01` hizo bien las dos llamadas en paralelo y falló
    solo por esto.
  - **No encadena:** 1 de 6 casos. Lanza las dos llamadas a la vez, con `price: 0` en la
    segunda (`chain-02`), o se salta la consulta y se inventa el dato (euríbor al 2,5 % en
    `chain-05`).
  - **Confunde mensual y anual** en `rental_income_tax` (`monthly_rent: 15000`).
- **Los 8 casos que no necesitan herramienta se responden sin llamar a ninguna** en los dos
  modelos.
- **El adaptador de GRPO ha perdido el formato de llamada.** 7 casos empeoran en selección y
  ninguno mejora (McNemar exacto, p = 0,016). En 10 de los 32 casos que necesitan
  herramienta no llama a ninguna (el base, en 1). Lo que hace en su lugar:
  - en 3 escribe `<function name=… />` o `<function_call>`;
  - en 1 escribe el JSON sin etiquetas;
  - en 6 describe en prosa la llamada que haría ("necesitamos utilizar la función
    `rental_returns`…") y hace las cuentas él mismo.

**Qué concluimos.**
- **`/tools` lo atiende el modelo base, sin adaptador.** El SFT y el GRPO con trazas de
  razonamiento sin herramientas desplazan el formato `<tool_call>` que Qwen3 trae del
  post-entrenamiento. Si en la fase 4 se quiere el "cerebro" de la fase 1 con herramientas,
  hará falta mezclar trazas con llamadas en el SFT.
- Los fallos del base son de definición más que de capacidad: tres de las cuatro causas se
  pueden atacar en las herramientas y el prompt, sin entrenar. Siguiente entrada.

---

### 2026-11-17 · Fase 2 · Arreglos en herramientas, prompt y evaluador, y segundo banco

**Qué queríamos saber.** Si los fallos del primer banco se arreglan cambiando las
definiciones, sin tocar el modelo.

**Qué hicimos.** Commit `9d147b8`:
- **`region` acepta comunidad, provincia o municipio**
  ([`tool_use/regions.py`](tool_use/regions.py)). Lo traduce con el código INE de los 2.616
  municipios del SERPAVI, también en catalán o euskera; si el nombre es ambiguo, error con las
  opciones.
- **Un 0 en `loan_years` significa sin hipoteca.** El precio y la inversión tienen que ser
  > 0, para que una llamada encadenada que todavía no tiene el valor falle en vez de calcular
  con 0.
- **Prompt de sistema:** dejar fuera los opcionales que no dé el usuario y, si un argumento
  sale de otra herramienta, llamarla primero y esperar.
- **`monthly_rent` y `previous_rent`** dicen que son mensuales.
- **Evaluador:**
  - la región se compara por comunidad;
  - un argumento rechazado por la validación no cuenta como correcto;
  - un 0 donde el valor por defecto es `None` se acepta;
  - `--rescore` vuelve a puntuar un informe guardado sin generar.

Después, el mismo banco con el mismo modelo y la misma configuración:
[`reports/fase2/phase2_bench_base_v2.json`](reports/fase2/phase2_bench_base_v2.json).

**Qué pasó.**

| Qwen3-1.7B base | Selección | Argumentos | Secuencia (10) | `single` arg. (20) | `chain` sec. (6) | `parallel` sec. (4) |
|---|---|---|---|---|---|---|
| Antes | 34/40 | 24/40 | 4 | 10 | 1 | 3 |
| Después | **37/40** | **32/40** | 5 | 13 | 1 | **4** |

- **Argumentos:** 8 casos mejoran y ninguno empeora (McNemar exacto, p = 0,008). Son los de
  la región (acq-01, acq-03, map-02), los ceros (par-01) y el mensual y anual (irpf-02).
  Llamadas innecesarias: sigue en 0 de 8.
- **Encadenar sigue en 1 de 6:**
  - `chain-02` sigue lanzando las dos llamadas a la vez. Ahora la segunda falla con "price
    must be > 0", pero el modelo no la repite con el precio.
  - En `chain-03` se inventa una llamada a `lookup_property` con "Calle Embajadores 100,
    Madrid", **la dirección de ejemplo de la descripción** de la herramienta.
  - En `chain-01` olvida el IBI en la segunda llamada.
- **Efecto secundario del prompt.** "Deja fuera los opcionales" hace que en `yield-02` y
  `chain-05` omita `loan_years: 25`, que el usuario sí daba. En `chain-05` lo pone al
  reintentar tras el error.
- **Sin cambios:**
  - `irpf-01` sigue eligiendo `rental_returns` para una pregunta de IRPF;
  - `port-01` se inventa una referencia catastral;
  - `yield-01` pone `vacant_months: 12` cuando el usuario dice uno.

**Qué concluimos.**
- **El esquema tolerante gana al estricto en este modelo.** Una tabla hace sin error la
  traducción de ciudad a comunidad, y el modelo no.
- 40 casos es poco. Las mejoras por categoría (`parallel` de 3 a 4, `mapping` de 1 a 2) son
  de uno o dos casos y no son concluyentes por sí solas.
- **Siguiente:**
  1. Ejemplos de las descripciones que no sean valores plausibles (el de `lookup_property`
     acaba en la llamada).
  2. Afinar el prompt para que no quite lo que el usuario da.
  3. Probar si con thinking el modelo encadena mejor. Con thinking, el banco tarda unos
     4 minutos por caso (2 casos en 8 minutos; ejecución cortada en
     `reports/fase2/phase2_bench_base_thinking_cortado.json`). Los 40 no caben en una sesión, así
     que va una muestra de 10.

---

### 2026-11-17 · Fase 2 · Thinking en el bucle de herramientas: muestra de 10 casos

**Qué queríamos saber.** Si dejar pensar a Qwen3 antes de cada turno (`enable_thinking`)
mejora la elección de herramienta y, sobre todo, el encadenado, que es lo que más falla sin
thinking.

**Qué hicimos.** Primero, el banco completo con `--thinking`. Lo cortamos tras 2 casos
porque iba a unos 4 minutos por caso (los 40 no caben en una sesión):
[`reports/fase2/phase2_bench_base_thinking_cortado.json`](reports/fase2/phase2_bench_base_thinking_cortado.json).

Después, una muestra de 10 casos elegidos por tipo de fallo, con el código de `9d147b8`, el
mismo del segundo banco:
`uv run python -m tool_use.evaluate --thinking --ids acq-01 map-02 yield-02 irpf-01 cap-01 chain-02 chain-05 par-01 none-01 rates-02 --out reports/fase2/phase2_bench_thinking_muestra.json`.
Tardó 16 minutos, con 2.048 tokens por turno.

**Qué pasó.** Acierta 4 de 10, **los mismos 4 que sin thinking** (acq-01, map-02, none-01 y
par-01): [`reports/fase2/phase2_bench_thinking_muestra.json`](reports/fase2/phase2_bench_thinking_muestra.json).
- **En `yield-02` e `irpf-01` se acaban los tokens pensando.** Calcula la cuota de la
  hipoteca o el IRPF a mano dentro de `<think>` (más de 6.000 caracteres) y no llega a llamar
  a la herramienta. Es el vicio de la fase 1, ahora dentro del razonamiento.
- **Encadenar no mejora:**
  - `chain-02` hace solo la primera llamada;
  - `chain-05` llama a `rental_returns` antes de `get_market_rates`, igual que sin thinking.
- `acq-01` acierta, pero repite la misma llamada tres veces.

**Qué concluimos.**
- **`/tools` va sin thinking.** En esta muestra no gana ningún caso, tarda unas 6 veces más
  y tiene un modo de fallo propio: ponerse a calcular en vez de llamar.
- 10 casos no bastan para descartar un efecto pequeño, pero no hay ninguna señal a favor que
  justifique el coste del banco completo.
- El encadenado no se arregla pensando más. Quedan el prompt (ya cambiado en `d795830`,
  pendiente de medir) y, si no basta, un SFT con trazas de llamadas encadenadas.

---

### 2026-11-18 · Fase 2 · Con y sin herramientas sobre el test de la fase 1 (60 problemas)

**Qué queríamos saber.** Si las herramientas del dominio sustituyen al entrenamiento de la
fase 1: ¿el Qwen3-1.7B base, sin adaptador y sin thinking, resuelve con ellas los problemas
del test que la fase 1 solo resolvía tras SFT y GRPO? Y si basta con una calculadora genérica.

**Qué hicimos.** `tool_use.phase1_compare` sobre los 10 primeros problemas de cada familia de
`rlm/data/test.jsonl` (60), con decodificación greedy, 2.048 tokens por turno y hasta 5 turnos.
La respuesta se verifica con el `EuroVerifier` de la fase 1. Tres variantes:
- `none`: el mismo modelo y un prompt sin herramientas;
- `arithmetic`: solo una calculadora genérica;
- `domain`: el registro completo.

La variante `domain` se midió tres veces, cambiando las herramientas entre una pasada y otra
según los fallos de la anterior:

| Versión | Código | Informe |
|---|---|---|
| v1 | `240de15` | [`phase2_vs_phase1.json`](reports/fase2/phase2_vs_phase1.json) |
| v2 | `542d499`: `annual_net_income` y tope de 4 llamadas por turno | [`…_domain_v2.json`](reports/fase2/phase2_vs_phase1_domain_v2.json) |
| v3 | `12275a8`: `land_value` en euros, una renta mensual ≥ 10.000 € se rechaza, el ingreso neto manda sobre la renta | [`…_domain_v3.json`](reports/fase2/phase2_vs_phase1_domain_v3.json) |

La v1 se cortó en 42/60 a las 11:05 por un OOM: otra sesión lanzó `scripts/fase1/eval_ood.sh` en la GPU, y
su comprobación (`pgrep "python -m rlm"`) no ve `python -m tool_use`. Los 18 problemas que
faltaban se completaron con `--resume` y el mismo código, desde un worktree en `240de15`
(`scripts/fase2/fase2_compare2.sh` y `scripts/fase2/fase2_compare3.sh`). Cada variante tarda unos 35 minutos.

Para comparar con la fase 1 usamos las filas de `eval_*_17b_2048.json` para los mismos 60
problemas. Ojo: esos modelos van con el prompt R1-Zero, thinking y una sola generación.

**Qué pasó.** Aciertos por familia, sobre 10 problemas cada una:

| | acq. | cash-on-cash | IRPF | renta legal | precio máx. | rent. neta | **Total** |
|---|---|---|---|---|---|---|---|
| Base sin herramientas | 1 | 0 | 0 | 0 | 0 | 0 | **1** |
| Base + calculadora | 1 | 0 | 0 | 0 | 0 | 0 | **1** |
| Base + dominio v1 | 9 | 0 | 0 | 1 | 0 | 7 | **17** |
| Base + dominio v2 | 8 | 1 | 0 | 3 | 0 | 5 | **17** |
| Base + dominio v3 | 9 | 3 | 5 | 1 | 0 | 2 | **20** |
| *Fase 1:* base con thinking | 1 | 0 | 0 | 2 | 0 | 2 | 5 |
| *Fase 1:* SFT | 5 | 0 | 0 | 5 | 4 | 6 | 20 |
| *Fase 1:* GRPO | 5 | 0 | 0 | 2 | 3 | 7 | 17 |
| *Fase 1:* SFT 3 | 8 | 0 | 1 | 2 | 2 | 7 | 20 |
| *Fase 1:* GRPO 2 | 8 | 2 | 0 | 5 | 1 | 8 | 24 |

McNemar exacto, v3 frente a cada referencia (problemas que gana · que pierde · p):

| Referencia | Gana | Pierde | p |
|---|---|---|---|
| Sin herramientas | 19 | 0 | < 0,001 |
| Fase 1: base con thinking | 18 | 3 | 0,002 |
| Fase 1: GRPO | 14 | 11 | 0,69 |
| Fase 1: GRPO 2 | 10 | 14 | 0,54 |
| Dominio v1 | 9 | 6 | 0,61 |

Llamadas por problema: 10,0 en la v1, 4,1 en la v2 y 3,75 en la v3.

- **La calculadora genérica no sirve.** El modelo la usa en 16 de 60 problemas, y cuando la
  usa sigue aplicando mal las reglas: el problema era el dominio, no la aritmética.
- **Por qué fallaban v1 y v2.** Casi todo era de interfaz, no de elección de herramienta (el
  modelo llama a una herramienta en 60 de 60):
  - **cash-on-cash:** el enunciado da el ingreso neto anual. En la v1 no había argumento para
    él; en la v2, el modelo lo pasaba junto a una `monthly_rent: 900` inventada, la herramienta
    rechazaba las dos cifras y el modelo repetía la llamada idéntica cinco turnos.
  - **precio máximo:** el modelo metía los "19.770 € netos al año" en `monthly_rent`, y el
    precio salía unas 12 veces mayor.
  - **IRPF:** el modelo calculaba a mano la parte del suelo y la redondeaba (46 % en vez de
    114.300 / 232.000 = 49,27 %). Con la parte exacta salen las cifras esperadas.
  - **renta legal:** el modelo llama a casi todo el registro en un turno y responde con la
    renta mensual cuando se pide la anual.
- **v3: IRPF de 0 a 5 y cash-on-cash de 1 a 3, pero rentabilidad neta de 5 a 2.** Al poner
  `annual_net_income` antes que `monthly_rent` en la firma, el modelo se inventa un ingreso
  neto (1.740 €, la renta mensual; 10.680 €) junto a la renta del usuario, y como el ingreso
  neto mandaba, la herramienta ignoraba la renta buena.
- **Quedan errores del modelo al leer el resultado.** En cash-on-cash, `rental_returns`
  devuelve −3,03 % y el modelo contesta 3,03, o contesta con la rentabilidad neta (5,86) en
  vez del cash-on-cash (5,36). En precio máximo, ignora el "8 %" de ITP del enunciado y se
  inventa Andalucía como región.

**Qué concluimos.**
- **Con las herramientas del dominio, el modelo base sin entrenar llega al nivel de la
  fase 1:** 20/60 frente a 17 (GRPO) y 24 (GRPO 2), sin diferencia significativa con
  ninguno, y muy por encima del mismo modelo sin herramientas (1/60). La diferencia está en
  las herramientas del dominio, no en tener una calculadora.
- **El diseño de la interfaz mueve tanto como el modelo:** cambiar el orden de dos
  argumentos movió la rentabilidad neta de 5 a 2 de 10. Nunca dejar que una cifra mande en
  silencio sobre otra: si llegan las dos, error, diciendo cuál pasar.
- **Hemos ajustado las herramientas mirando estos 60 problemas**, así que la v3 es optimista.
  La v4 (`4e028dd`, ya lanzada) se mide sobre los 10 problemas siguientes de cada familia
  (`--skip-per-family 10`), que no se han mirado, y se compara con la fase 1 en esos mismos.
- Para la sesión que comparta la GPU: comprobar `pgrep -af "python -m (rlm|tool_use)"`, no
  solo `rlm`.

---

### 2026-11-18 · Fase 2 · Herramientas v4 sobre 60 problemas que no habíamos mirado

**Qué queríamos saber.** Si el 20/60 de la v3 se sostiene en problemas que no habíamos usado
para ajustar las herramientas, y si los arreglos de la v4 recuperan la rentabilidad neta que
perdió la v3.

**Qué hicimos.** Código `4e028dd`, con tres cambios respecto a la v3:
- **renta o ingreso neto, nunca las dos:** si el modelo pasa ambas, error diciendo cuál
  corresponde;
- **`monthly_rent` vuelve antes que `annual_net_income`** en la firma;
- **`cash_on_cash_pct` va lo primero del resultado**, e `itp_rate_pct` antes que `region`,
  con "nunca te inventes un lugar".

`scripts/fase2/fase2_compare4.sh` lanzó dos pasadas de la variante `domain`, mismo modelo y ajustes:
1. sobre los problemas 11.º a 20.º de cada familia (`--skip-per-family 10`):
   [`reports/fase2/phase2_vs_phase1_domain_v4_nuevos.json`](reports/fase2/phase2_vs_phase1_domain_v4_nuevos.json);
2. sobre los 60 de la entrada anterior:
   [`reports/fase2/phase2_vs_phase1_domain_v4.json`](reports/fase2/phase2_vs_phase1_domain_v4.json).

Tardó 24 y 30 minutos.

**Qué pasó.** Aciertos por familia (de 10):

| | acq. | cash-on-cash | IRPF | renta legal | precio máx. | rent. neta | **Total** |
|---|---|---|---|---|---|---|---|
| v4, problemas nuevos | 9 | 1 | 6 | 1 | 4 | 6 | **27** |
| *Fase 1:* GRPO 2, los mismos | 10 | 1 | 1 | 5 | 7 | 6 | 30 |
| *Fase 1:* SFT 3, los mismos | 9 | 1 | 0 | 3 | 6 | 7 | 26 |
| *Fase 1:* base con thinking, los mismos | 2 | 0 | 0 | 2 | 0 | 5 | 9 |
| v4, los 60 de antes | 8 | 1 | 6 | 3 | 2 | 4 | **24** |
| v3, los 60 de antes | 9 | 3 | 5 | 1 | 0 | 2 | 20 |

Juntando los 120 problemas, McNemar exacto de la v4 (51 aciertos) frente a la fase 1:

| Referencia | Aciertos | v4 gana | v4 pierde | p |
|---|---|---|---|---|
| Base con thinking | 14 | 42 | 5 | < 0,001 |
| SFT | 44 | 27 | 20 | 0,38 |
| GRPO | 41 | 30 | 20 | 0,20 |
| SFT 3 | 46 | 23 | 18 | 0,53 |
| GRPO 2 | 54 | 23 | 26 | 0,78 |

Frente a la v3, sobre los mismos 60: gana 8 y pierde 4 (p = 0,39). Hace 4,1 llamadas por
problema en los 60 de antes y 2,9 en los nuevos.

- **El resultado se sostiene fuera de lo que miramos.** En los problemas nuevos, 27/60: entre
  SFT 3 y GRPO 2.
- **Los dos enfoques fallan en sitios distintos.** El IRPF sale con herramientas (12 de 20) y
  no con entrenamiento (1 de 20 con GRPO 2), porque la regla vive en el código. La renta legal
  y el precio máximo salen mejor con GRPO 2: el modelo con herramientas llama a casi todo el
  registro en `legal_rent` (el tope de 4 deja fuera la llamada que importa) y responde con la
  renta mensual cuando se pide la anual.
- **Fallos que quedan en la v4:**
  - el error "pass exactly one" se repite en bucle en 8 problemas: el modelo no corrige los
    argumentos aunque el error diga cuáles;
  - en 3 problemas el modelo se come el signo negativo: escribe 2.991,87 cuando es −2.991,87;
  - en 9 problemas alguna llamada sale como JSON inválido (una coma de menos).

**Qué concluimos.**
- **Con las herramientas del dominio, Qwen3-1.7B base, sin entrenar y sin thinking, rinde lo
  mismo que el mejor modelo entrenado de la fase 1:** 51 frente a 54 de 120, p = 0,78. Las
  herramientas sustituyen al entrenamiento en las familias con regla fija (IRPF,
  adquisición), no en las que exigen elegir bien entre varias herramientas.
- **Lo siguiente sería combinar ambos:** un SFT corto con trazas de llamadas, para que el
  adaptador no pierda el formato `<tool_call>` como le pasó al de la fase 1. También quitar
  `legal_rent_cap` del "todo a la vez": que el prompt pida una herramienta por pregunta, salvo
  si son independientes.
- `/tools` se queda con el modelo base y el código de `4e028dd`.

---

### 2026-11-22 · Fase 2 · Banco con el código actual, y una prueba de orden en el IRPF que no funcionó

**Qué queríamos saber.**
- Si los arreglos que salieron de la comparación con la fase 1 (`8b35ffe` a `4e028dd`)
  mejoran o empeoran el banco de 40 casos.
- Si poner `land_share_pct` antes que `land_value` recupera `irpf-02` sin perder el IRPF del
  test de la fase 1.

**Qué hicimos.**
- **Banco:** `scripts/fase2/fase2_bench_v4.sh`, es decir,
  `uv run python -m tool_use.evaluate --out reports/fase2/phase2_bench_base_v4.json`. Qwen3-1.7B
  base, sin thinking, código `a2a59c4` (el de `4e028dd` con `main` unida). Tardó 9 minutos.
- **Prueba del IRPF:** sin commitear y ya deshecha. Pusimos `land_share_pct` antes que
  `land_value`, y un ejemplo con cifras en cada descripción ("un 35 % de suelo", "114.300 €
  corresponde al suelo"). La medimos sobre los 3 casos de IRPF del banco y los 20 problemas de
  IRPF de las dos pasadas de la v4.

**Qué pasó.** El banco frente al anterior
([`phase2_bench_base_v2.json`](reports/fase2/phase2_bench_base_v2.json), código `9d147b8`):

| | Selección | Argumentos | Secuencia | Llamadas innecesarias |
|---|---|---|---|---|
| v2 | 37/40 | 32/40 | 20/40 | 0 |
| v4 | 37/40 | 32/40 | 16/40 | 0 |

En argumentos, la v4 gana `yield-01`, `yield-02` y `rates-02`, y pierde `irpf-02`, `cad-01` y
`chain-02` (McNemar, p = 1). En secuencia, el cambio de `chain-02` a `chain-05` deja el
encadenado en 0 de 6:
- **`irpf-02`:** el usuario da "un 35 % de suelo". El modelo deja vacíos `land_value` y
  `land_share_pct`, y al reintentar se inventa `land_value: 100000`.
- **`cad-01`:** vuelve a meter "escalera A, 2.º B" en la dirección, el fallo que se arregló
  en `d795830`. No es estable.
- **`chain-05`:** calcula la cuota con el Euríbor que se inventa, sin llamar a
  `get_market_rates`.

La prueba del IRPF empeora las dos medidas: 0/3 en argumentos en el banco (antes 1/3) y 10/20
en el test de la fase 1 (antes 12/20). El motivo está en las trazas: **el modelo copia en
`land_value` el "114.300" del ejemplo de la descripción**, también en `irpf-03`, cuyo
enunciado da un 45 %.

**Qué concluimos.**
- **Los arreglos para el test de la fase 1 no han costado nada en el banco:** mismas cifras
  de selección y argumentos, y siguen sin llamadas innecesarias. Se queda `4e028dd`.
- **Las descripciones no llevan cifras de ejemplo.** Es la segunda vez que el modelo las
  copia; la primera fue la dirección de ejemplo de `lookup_property`. Los ejemplos van en
  palabras ("el valor del suelo en euros"), nunca con un número que pueda pasar como argumento.
- **El orden de los argumentos de la misma magnitud decide cuál rellena el modelo.** Con
  `land_value` primero, gana el IRPF del test de la fase 1 (que da euros) y pierde `irpf-02`
  (que da un porcentaje). Como el banco tiene 3 casos de IRPF y la fase 1 tiene 20, nos
  quedamos con `land_value` primero.
- **El encadenado sigue sin resolverse** (0-1 de 6 según la pasada). Es lo siguiente que
  habría que atacar, con trazas de SFT y no con más prompt.

---

### 2026-11-22 · Fase 2 · Encadenado: recordatorio tras cada resultado, ceros como "no dado" y Euríbor

**Qué queríamos saber.** Si se puede mejorar el encadenado (0 de 6 en el banco de esta tarde)
sin entrenar, solo con el bucle y las definiciones.

**Qué hicimos.** Partimos de los fallos de `chain-*` en
[`phase2_bench_base_v4.json`](reports/fase2/phase2_bench_base_v4.json):
- **`chain-01`:** encadena bien, pero mete `annual_net_income: 0` junto a la renta y la
  llamada falla tres veces;
- **`chain-02`, `chain-04` y `chain-06`:** paran tras el primer resultado (en `chain-04` se
  inventa el precio por m²);
- **`chain-05`:** se inventa el Euríbor.

Con tres cambios (`ccc536b`):
- **un 0 en `monthly_rent` o `annual_net_income` cuenta como no dado**, igual que ya hacía
  el evaluador;
- **el bucle añade al último resultado de cada turno** "If the user's question still needs
  another tool that uses these results, call it now; otherwise answer" (`CHAIN_HINT`);
- **`interest_rate_pct` pide llamar a `get_market_rates`** si el usuario habla del Euríbor
  actual.

Banco completo, mismo modelo y ajustes que la entrada anterior: `scripts/fase2/fase2_bench_v5.sh`. Tardó
9 minutos: [`reports/fase2/phase2_bench_base_v5.json`](reports/fase2/phase2_bench_base_v5.json).

**Qué pasó.**

| | Selección | Argumentos | Secuencia (10) | Encadenado (6) | Llamadas innecesarias (8) | Turnos |
|---|---|---|---|---|---|---|
| v4 (`a2a59c4`) | 37 | 32 | 4 | 0 | 0 | 1,98 |
| v5 (`ccc536b`) | 38 | 31 | 6 | 2 | 0 | 2,15 |

- **Gana `chain-05` y `chain-06`.** Ahora el modelo pide primero `get_market_rates` y
  después calcula con ese tipo, y mira la cartera después de la zona tensionada.
- **Pierde `yield-01` y `yield-03`:**
  - en `yield-01` pone `vacant_months: 12` en vez de 1, un error de copia;
  - en `yield-03` omite `loan_years`, y tras el error va a por el Euríbor aunque el usuario
    da el tipo (3,2 %). Es un efecto secundario de la nueva descripción.
- **Siguen sin encadenar:**
  - `chain-02` y `chain-04` responden tras el primer resultado, pese al recordatorio;
  - en `chain-01` y `chain-03` el modelo lanza en paralelo la segunda llamada sin esperar
    al resultado de la primera.
- McNemar exacto, p = 1 en las tres medidas: con 6 casos de encadenado, la mejora no es
  significativa.

**Qué concluimos.**
- **Nos quedamos con `ccc536b`.** Sin llamadas innecesarias y con +2 en encadenado, a
  cambio de −1 en argumentos. Pero el cambio es pequeño y no está demostrado.
- **Falta separar los tres cambios.** La descripción del Euríbor es la que probablemente
  estropea `yield-03`. Lo siguiente es medir el recordatorio solo, en la próxima sesión.
- **El fallo que queda es lanzar en paralelo llamadas que dependen una de otra.** Con prompt y
  bucle no se arregla del todo, así que el paso siguiente sería un SFT con trazas que esperan
  al resultado.

---

### 2026-11-22 · Fase 2 · Encadenado por partes: qué aporta cada cambio (bancos v6 a v8)

**Qué queríamos saber.** El banco v5 subió el encadenado de 0 a 2 de 6, pero perdió
`yield-03`. Queríamos saber cuál de los cambios lo estropeaba, y si se podía quedar lo bueno
sin lo malo.

**Qué hicimos.** Tres bancos completos, mismo modelo y ajustes (Qwen3-1.7B base, sin
thinking, 2.048 tokens), cambiando una cosa cada vez sobre `ccc536b`:

| Banco | Código | Cambio |
|---|---|---|
| v6 | `91965a2` | quitar de `interest_rate_pct` la instrucción de pedir el Euríbor (queda el recordatorio) |
| v7 | `b42e71b` | volver a ponerla, pero solo "si el usuario no da tipo y habla de euríbor más diferencial" |
| v8 | `eca9bc9` | el error del préstamo nombra solo lo que falta; `vacant_months` de 12 se rechaza y su descripción dice "meses VACÍOS" |

Informes: `reports/fase2/phase2_bench_base_v6.json`, `_v7.json` y `_v8.json`. Unos 9 minutos cada uno.

**Qué pasó.**

| | Selección | Argumentos | Secuencia (10) | Encadenado (6) | Llamadas innecesarias (8) |
|---|---|---|---|---|---|
| v4 (`a2a59c4`) | 37 | 32 | 4 | 0 | 0 |
| v5 (`ccc536b`) | 38 | 31 | 6 | 2 | 0 |
| v6 | 37 | 32 | 5 | 1 | 0 |
| v7 | 39 | 31 | 6 | 2 | 0 |
| **v8** | **40** | **33** | **6** | **2** | **0** |

- **El recordatorio solo (v6) ya gana `chain-06`.** El modelo mira la cartera después de la
  zona tensionada.
- **La instrucción del Euríbor gana `chain-05` y, si es incondicional, estropea `yield-03`.**
  Con la versión condicionada (v7), `yield-03` siguió fallando, pero por otra razón: el modelo
  daba el tipo y olvidaba el plazo, y el error "a loan needs interest_rate_pct and loan_years"
  le hacía creer que le faltaba el tipo, así que iba a por el Euríbor. Con el error que nombra
  solo `loan_years` (v8), acierta a la primera.
- **`yield-01`** pasaba "un mes vacío al año" como `vacant_months: 12` en v5 y v7. Con la
  descripción "meses VACÍOS", en v8 pasa 1.
- **v8 frente a v4:** gana `irpf-01`, `irpf-03` y `chain-05` en selección, y `chain-05` y
  `chain-06` en secuencia, sin perder ningún caso en ninguna medida (McNemar: p = 0,25 y
  0,5). Es el mejor banco hasta ahora, pero con 40 casos ninguna diferencia es significativa
  por sí sola.

**Qué concluimos.**
- **Nos quedamos con `eca9bc9`:** 40/40 en selección, 33/40 en argumentos y sin llamadas
  innecesarias.
- **Los mensajes de error son parte de la interfaz, igual que las descripciones:** un error
  que pide algo que el modelo ya dio lo manda en la dirección equivocada. Cada error debe
  nombrar solo lo que falta.
- **Una instrucción en una descripción tiene que llevar su condición.** "Pide el Euríbor"
  sin más se aplica también cuando el usuario ya da el tipo.
- **Siguen sin encadenar:** `chain-01` y `chain-03` lanzan a la vez llamadas que dependen una
  de otra, y `chain-02` y `chain-04` responden tras el primer resultado. Esto ya no parece
  arreglable con texto. El siguiente paso sería un SFT con trazas que esperan al resultado.

---

### 2026-11-23 · API · `docker compose up api` en la DGX, con /tools

**Qué queríamos saber.** El MacBook no puede servir la API ahora que la fase 1 y la fase 2
cargan cada una su Qwen3-1.7B. El enunciado pide que la API levante con `docker compose up
api` y se exponga con ngrok. Queríamos saber si la DGX puede hacer las dos cosas, porque
`docs/dgx.md` dice que allí no hay Docker.

**Qué hicimos.**
- Las sesiones ya tienen Docker 29.6 *rootless* y Compose v5.2, con las GPUs del nodo
  expuestas por CDI.
- `docker compose build api` funcionó a la primera: imagen de 26 GB, en `/tmp`, que se borra
  al acabar la sesión.
- La reserva de GPU del compose monta las 8 GPUs, pero Slurm solo deja abrir la nuestra, así
  que no hay riesgo de usar las de otros.
- Faltaban los ficheros `/dev/nvidia-caps/nvidia-capN` de nuestra partición MIG. Sin ellos,
  torch dice "No CUDA GPUs are available".
- Esos números cambian en cada sesión. En esta, la partición está en la GPU física 5, gi8
  (cap750 y cap751), aunque la sesión la llama GPU 0.
- `smoke/docker_dgx.sh` busca los que la sesión puede abrir, escribe un override con ellos y
  llama a `docker compose`. El `docker-compose.yml` no cambia para otras máquinas.
- `.env` con `ARCA_RLM_ADAPTER=rlm/weights/grpo2_lora`. `/tools` usa el modelo base, como en
  el banco v8.
- Lanzamos `smoke/docker_dgx.sh run --rm check-gpu`, después `smoke/docker_dgx.sh up api`, y
  luego `/health` y cuatro preguntas a `/tools`.

**Qué pasó.**
- `check-gpu`: H200 MIG 1g.18gb, 17,2 GB, 101 TFLOP/s en bf16.
- `/health`: `reasoning` y `tools` en `ready` en 9,5 s; las dos cargan con los modelos ya en
  la caché del clúster.

| Pregunta | Herramientas | Tiempo | Resultado |
|---|---|---|---|
| Piso en Madrid de 250.000 €, coste total | `acquisition_cost` | 69 s | ✅ 265.000 € (ITP 6 %) |
| Diferencia entre rentabilidad bruta y neta | ninguna | 9 s | ✅ responde sin herramientas |
| ¿Barcelona es zona tensionada? Si lo es, ¿soy gran tenedor? | `get_portfolio` | 37 s | ❌ no llama a `get_rent_reference`, afirma que Barcelona no está tensionada (lo está, BOE-A-2024-5214) y responde en inglés |
| Guarda un piso en Valencia de 180.000 € y 900 €/mes | `save_to_portfolio` | 10 s | ⚠️ guarda, pero se inventa `area_m2=180` (copia el precio) porque el usuario no da la superficie |

**Qué concluimos.**
- La DGX sirve para la corrección: `docker compose up api` (vía `smoke/docker_dgx.sh`) más
  ngrok, en una sesión abierta cuando corrijan. Falta instalar ngrok y probar la URL pública;
  la conexión de salida al servidor de ngrok funciona.
- La pregunta encadenada falla igual que `chain-02`/`chain-04` del banco: responde tras el
  primer resultado. Además, inventa la conclusión.
- `save_to_portfolio` pide `area_m2` obligatorio, y si el usuario no lo da, el modelo lo
  rellena con otra cifra. Es la misma lección que con los ejemplos numéricos: no dejar que
  una cifra ocupe en silencio el lugar de otra.

---

### 2026-11-23 · API · Servir la fase 1 fuera de la DGX y una sola copia del modelo para todas las fases

**Qué queríamos saber.** Si la API con el modelo final (GRPO 2) se puede servir desde un
portátil para la corrección: el MacBook Air M2 de 8 GB del equipo o un portátil Windows con una
RTX 3060 de 6 GB. Y, en ese caso, si caben la fase 1 y la fase 2 a la vez.

**Qué hicimos.**
- **Mac.** `uv run --env-file .env arca-api` con el adaptador en la GPU de Apple (MPS,
  bfloat16), y la misma pregunta de coste de adquisición dos veces por `curl`.
- **MLX.** Fusionamos el GRPO 2 con la base y lo convertimos con
  `mlx_lm.convert -q --q-bits 8` (1,8 GB, en Hugging Face privado,
  `umbral-qwen3-1.7b-grpo2-mlx-8bit`). Añadimos `ARCA_RLM_MLX` y `rlm/eval_mlx.py` para
  medirlo.
- **Modelo compartido.** `api/shared_model.py` carga Qwen3-1.7B una vez. La fase 1 genera con
  el adaptador GRPO 2 y la fase 2 con `disable_adapter()`, todo en un solo hilo. Lo comparamos
  en la GPU de la DGX con cada fase cargada por separado (como antes): la misma pregunta, 300 y
  200 tokens greedy, alternando fase 2, fase 1, fase 2, fase 1.

**Qué pasó.**
- **Mac.**
  - La primera petición respondió bien (355.552,50 €): 477 tokens en 132 s con la carga, unos
    2,5 tokens/s.
  - La segunda se quedaba colgada para siempre. FastAPI atiende cada petición en un hilo
    distinto y, en MPS, el modelo cargado en un hilo se bloqueaba al generar desde otro. Desde
    entonces, cargar y generar van siempre en el mismo hilo.
  - Con 8 GB de memoria compartida, a ese ritmo una respuesta de 1.900 tokens tardaría más de
    10 minutos. Descartado.
- **MLX.** No lo pudimos medir en el Mac. En la DGX, `mlx[cuda12]` compila sus kernels contra
  las cabeceras de CUDA 12.6 del sistema y falla. Queda como plan B sin probar.
- **Fusionar el adaptador cambia el texto.** En el Mac, con el adaptador fusionado, la misma
  pregunta dio 506 tokens en vez de 477, con la misma respuesta final. Es el redondeo en
  bfloat16 de W + BA. El modelo compartido vuelve a usarlo sin fusionar, como
  `rlm/evaluate.py`.
- **Modelo compartido**, en la GPU de la DGX (`max_memory_reserved`):

| Configuración | Memoria de GPU |
|---|---|
| Fase 1 sola (base + GRPO 2) | 4,22 GB |
| Fase 2 sola (base) | 4,13 GB |
| Las dos por separado | 8,35 GB |
| **Las dos con el modelo compartido** | **4,31 GB** |

  - Las cuatro generaciones alternadas son idénticas carácter a carácter a las de cada fase
    sola.
  - Velocidad en la DGX: 29 tokens/s. La primera generación tras cargar tardó 128 s y la
    segunda 10 s, así que hay que calentar la API antes de abrirla.

**Qué concluimos.**
- **El Mac no sirve** para la corrección. Lo que sirve es la DGX (entrada anterior) o un
  portátil con NVIDIA y Docker, siguiendo `docs/servir_api.md`; esa guía está sin ensayar.
- **Sin el modelo compartido, la API no cabe en 6 GB.** `/health` carga todas las fases al
  primer aviso. Con él caben las dos con margen.
- **Norma para las fases 3 y 4:** reutilizar `api/shared_model.get_model()` con su adaptador
  en vez de cargar otra copia del modelo.

---

### 2026-11-23 · Fase 2 · Tipos de ITP verificados con fuentes oficiales

**Qué queríamos saber.** La tabla de `tool_use/itp_rates.py` (17 comunidades) venía de una
fuente secundaria (Gibobs, consultada el 17/11) y la herramienta avisaba "tipo de ITP sin
verificar". Queríamos saber si los tipos eran correctos.

**Qué hicimos.** Cotejamos cada fila con la hacienda autonómica o foral, su boletín oficial o
el BOE, y dejamos el enlace junto a la fila. En el País Vasco cotejamos las tres haciendas
forales.

**Qué pasó.** Las 17 filas quedan con `verified=True`. Cuatro tipos generales estaban mal en
la fuente secundaria:

| Comunidad | Gibobs | Oficial |
|---|---|---|
| Cantabria | 10 % | 9 % (desde el 1/1/2024) |
| Comunitat Valenciana | 10 % | 9 % (10 % para devengos anteriores al 1/6/2026) |
| Galicia | 10 % | 8 % |
| Murcia | 8 % | 7,75 % |

Siete notas cambian:
- **Aragón, Baleares, Cataluña y Extremadura:** ahora llevan los tramos con sus importes.
- **Asturias:** no es una escala por tramos. El tipo se elige por el valor total y se aplica
  a toda la base.
- **Castilla y León:** la nota faltaba. Lo que pasa de 250.000 € tributa al 10 %.
- **País Vasco:** la vivienda pierde el 4 % si el comprador tiene más de cinco.

**Qué concluimos.**
- Una de cada cuatro filas tenía mal el tipo general. Con datos que cambian cada año por ley
  de presupuestos, la fuente secundaria no basta.
- El banco de la fase 2 comprueba argumentos, no cifras, así que sus resultados no cambian.
  La fase 1 no usa la tabla: cada problema da su tipo.
- Hay que revisar la tabla con cada ley de presupuestos autonómica.

---

### 2026-11-23 · API · La primera petición de cada longitud iba a 2,8 tokens/s: atención de cuDNN

**Qué queríamos saber.** Servida en la DGX, la primera `/reasoning` tardaba 145 s (2,8
tokens/s). Queríamos saber si era Docker, el modelo compartido (3131fb3) o la partición MIG,
y si una sesión con más GPU lo arreglaría.

**Qué hicimos.** Medimos la misma pregunta de `/reasoning` (piso de 100.000 €, unos 400
tokens) y una de `/tools` con `uv run arca-api`, sin Docker, en la MIG 1g.18gb, lanzando
varias peticiones seguidas tras cada arranque. Después probamos
`torch.backends.cuda.enable_cudnn_sdp(False)` en `api/shared_model.py`, como ya se hizo en el
GRPO.

**Qué pasó.**

| Situación | 1.ª petición | Siguientes |
|---|---|---|
| Antes del modelo compartido (9e0ad62), `/reasoning` | 137 s (2,9 tok/s) | 6,3 s (64 tok/s) |
| Modelo compartido (3131fb3), `/reasoning` | 142 s (2,8 tok/s) | 11-12 s (34-37 tok/s) |
| Ídem, `/tools` | 70 s | 4 s |
| `/reasoning` con 16 tokens y después la pregunta completa | 12,7 s y luego **145 s** | — |
| **Sin atención de cuDNN**, `/reasoning` | **18,9 s** (37 tok/s, incluye la carga) | 12,6 s (38 tok/s) |
| **Sin atención de cuDNN**, `/tools` | **4,0 s** | 3,9 s |

- No era ni Docker ni la GPU. Era el arranque en frío de la atención de cuDNN, que construye
  un plan por cada longitud de secuencia nueva.
- Por eso calentar con una pregunta corta no servía, y calentar `/tools` no calentaba
  `/reasoning`.
- Sin cuDNN, la misma pregunta genera 479 tokens en vez de 401: otro kernel de atención,
  otra aritmética, otro texto greedy. La respuesta sigue siendo correcta (111.000,00).

**Qué concluimos.**
- `api/shared_model.py` desactiva la atención de cuDNN en GPU (fdef57f). No hace falta pedir
  una sesión más grande para la corrección.
- La diferencia 64 frente a 37 tok/s entre antes y después del modelo compartido sale de una
  sola medida: no está confirmada.
- Pendiente: comprobar que el pass@1 de la fase 1 servido sin cuDNN no baja. El 47,3 % se
  midió con el backend por defecto.

---

### 2026-11-23 · Fase 2 · Banco v9: modelo base frente al adaptador GRPO 2 en /tools

**Qué queríamos saber.**
- Si `/tools` mejora con el adaptador de la fase 1 (`grpo2_lora`, 47,3 % en test).
- Con el modelo compartido (3131fb3) no cuesta memoria: basta con cambiar
  `ARCA_TOOLS_ADAPTER` en el `.env`.
- Hasta ahora solo se había probado el adaptador del primer GRPO (`final_rlm_lora`), con un
  banco antiguo (`reports/fase2/phase2_bench_grpo.json`).

**Qué hicimos.** `bash scripts/fase2/fase2_bench_v9.sh` (d7cb17a):
- Las dos pasadas usan el mismo código y los mismos 40 casos de la v8: greedy, sin thinking,
  plantilla nativa, 4 turnos.
- La base se repitió porque, desde la v8, el código usa el modelo compartido y atención sin
  cuDNN.
- Tardó 3 min la base y 11 min el adaptador.
- Informes: `reports/fase2/phase2_bench_base_v9.json` y `phase2_bench_grpo2_v9.json`.

**Qué pasó.**

| Métrica | Base v8 | Base v9 | + grpo2_lora v9 |
|---|---|---|---|
| Selección | 40/40 | 39/40 | **27/40** |
| Argumentos | 33/40 | 32/40 | **21/40** |
| Secuencia | 24/40 | 24/40 | 16/40 |
| Llamadas falsas | 0 | 0 | 0 |

| Categoría (n) | Selección base | Selección grpo2 | Argumentos base | Argumentos grpo2 |
|---|---|---|---|---|
| single (20) | 19 | 11 | 13 | 6 |
| chain (6) | 6 | 4 | 5 | 3 |
| parallel (4) | 4 | 2 | 4 | 2 |
| mapping (2) | 2 | 2 | 2 | 2 |
| no_tool (8) | 8 | 8 | 8 | 8 |

- **Selección por pares:** la base acierta 12 casos que el adaptador falla, y el adaptador no
  gana ninguno. McNemar exacto bilateral, p = 0,0005.
- **Por qué falla el adaptador.** De los 12 casos que pierde:
  - en 9 no llega a hacer una llamada válida. Escribe la llamada entre `<tools>…</tools>`
    en vez de `<tool_call>…</tool_call>`, la deja sin cerrar, o se pone a razonar y calcular
    a mano (`yield-02` acaba en LaTeX con un "5.24 %");
  - en 3 elige otra herramienta. En `irpf-01` y `irpf-03` llama a `rental_returns` con todos
    los argumentos opcionales a 0.
- **El GRPO 2 se entrenó para razonar y cerrar con su formato de respuesta, y ha perdido el
  formato de llamada de Qwen3.**
- **Base v9 frente a v8:** cambia un solo caso, `rates-02` (subida máxima según el IRAV). En
  la v9 llama a `get_rent_reference` con «Barcelona» inventada en vez de a
  `get_market_rates`. Es el cambio de atención (fdef57f): otra aritmética, otro texto greedy
  en un caso al límite. Una diferencia de 1 sobre 40 no distingue nada.

**Qué concluimos.**
- `/tools` sigue con el modelo base: `ARCA_TOOLS_ADAPTER` vacío. Es lo que defendemos en la
  memoria, con estos números.
- Un adaptador de razonamiento entrenado sin llamadas a herramientas estropea el formato de
  llamada. Si en la fase 4 el agente usa el GRPO 2, tendrá que generar con el adaptador
  activado para razonar y desactivado para llamar a herramientas. El modelo compartido ya lo
  permite por petición.
- `rates-02` merece una frase más en la descripción de `get_market_rates` ("también el IRAV
  para actualizar el alquiler") si vuelve a fallar.

---

### 2026-11-23 · Fase 2 · save_to_portfolio sin superficie obligatoria (banco v10)

**Qué queríamos saber.** Probando la API (entrada de `docker compose up api` en la DGX), a
"Guarda en mi cartera un piso en Valencia de 180.000 € alquilado por 900 € al mes" el modelo
respondió con `area_m2=180`. Copió la cifra del precio porque `area_m2` era obligatoria y el
usuario no la había dado. Queríamos que la herramienta no obligue a inventarla.

**Qué hicimos.**
- **`area_m2` pasa a ser opcional.** Va después de `purchase_price` y `monthly_rent` (el
  orden de los argumentos decide qué cifra rellena primero el modelo, 22/11), con la
  descripción "only if the user gives it".
- **Sin superficie, el piso se guarda igual.** La herramienta devuelve el aviso "superficie no
  dada… pide la superficie al usuario".
- **El resumen de la cartera** cuenta `dwellings_without_area`. Si no hay gran tenedor, la
  razón aclara que no se cuenta la superficie de esos pisos.
- **Las bases antiguas,** con `area_m2 NOT NULL`, se copian solas al esquema nuevo.
- Tres tests nuevos.
- Banco completo con `bash scripts/fase2/fase2_bench_v10.sh`: modelo base, 40 casos, 3 min.

**Qué pasó.**

| Métrica | Base v9 | Base v10 |
|---|---|---|
| Selección | 39/40 | 40/40 |
| Argumentos | 32/40 | 34/40 |
| Secuencia | 24/40 | 24/40 |
| Llamadas falsas | 0 | 0 |

- **Cambian dos casos, los dos a mejor.**
  - `port-01` (guardar con 85 m²): en la v9 se inventaba `cadastral_ref="12121212121212"`;
    ahora no.
  - `rates-02` vuelve a llamar a `get_market_rates`. Es ruido de un caso al límite que se mueve
    con cualquier cambio del prompt.
- **La pregunta de Valencia, por la API:** `area_m2=null`, con el aviso, en 4,3 s.
- **Con "95 m²" en la pregunta (Sevilla):** `area_m2=95`.
- **La respuesta final sale en inglés** en las dos preguntas, como ya pasó con la de Barcelona.

**Qué concluimos.**
- `save_to_portfolio` ya no obliga a inventar la superficie.
- Pendiente: el modelo responde en inglés tras algunas herramientas. Probablemente porque los
  resultados y las descripciones están en inglés; habría que pedir en el prompt de sistema
  que responda en el idioma del usuario.
- `stressed_zone` sigue siendo obligatorio y el modelo lo rellena con `false` sin
  comprobarlo. Se podría consultar solo con la tabla de zonas.

---

### 2026-11-23 · Fase 2 · Respuestas en español y zona tensionada consultada por la herramienta (bancos v11 a v13)

**Qué queríamos saber.** Dos fallos que vimos probando la API (entrada de v10):
- **Idioma.** Tras algunas herramientas, el modelo responde en inglés a preguntas en español.
- **Zona tensionada.** `save_to_portfolio` exigía `stressed_zone` y el modelo pasaba `false`
  sin comprobarlo.

**Qué hicimos.**
- **`stressed_zone` pasa a ser opcional.** Si el usuario no lo dice, la herramienta mira la
  tabla de zonas declaradas (`declared_zones`, la misma de `get_rent_reference`) y devuelve
  la fuente.
- **Si solo parte del municipio está declarada** (Gijón, Vitoria…), guarda el valor como
  desconocido y avisa de que hay que preguntar.
- **Las bases antiguas** se migran como con `area_m2`. Dos tests nuevos.
- **Idioma, v11.** El prompt de sistema ya pedía "Answer in the user's language", pero lo
  último que lee el modelo es el resultado en inglés más `CHAIN_HINT`. Añadimos el idioma al
  final de `CHAIN_HINT`: "otherwise answer in the language of the user's question".
- **Idioma, v12:** "…answer the user in the language they wrote in (Spanish if they wrote in
  Spanish)".
- **Referencia catastral, v13.** En `port-01` el modelo se inventaba una
  (`12345678901234`). La descripción de `cadastral_ref` pasa de "if known" a "exactly as the
  user writes it…; never make one up".
- **Medida del idioma.** Nueva: `scripts/fase2/answer_language.py`, que cuenta, entre las
  respuestas que usaron herramientas, las escritas en español. Usa palabras frecuentes de
  cada idioma; todas las preguntas del banco están en español.
- `bash scripts/fase2/fase2_bench_v1{1,2,3}.sh`: modelo base, 40 casos, 3 min cada uno.

**Qué pasó.**

| Banco | Selección | Argumentos | Secuencia (10) | Llamadas falsas | En español |
|---|---|---|---|---|---|
| v10 | 40/40 | 34/40 | 6/10 | 0 | 20/32 |
| v11 (idioma de la pregunta) | 40/40 | 33/40 | 5/10 | 0 | 24/32 |
| v12 (idioma, explícito) | 40/40 | 33/40 | 6/10 | 0 | **29/32** |
| v13 (+ cadastral_ref) | 40/40 | 33/40 | 5/10 | 0 | **29/32** |

- **`port-01`** (el usuario dice "no está en zona tensionada"). Desde la v11 el modelo ya no
  pasa `stressed_zone`; la herramienta consulta Zaragoza y guarda `false`, que es correcto.
  El banco lo cuenta como fallo porque espera el argumento explícito. En la v13 ya no se
  inventa la referencia catastral.
- **`chain-06`** (zona tensionada y luego cartera) pierde la secuencia en v11 y v13 y la
  recupera en v12. En v10 encadenaba, pero añadía una llamada inventada a
  `max_offer_price`. Es el encadenado de siempre, que se mueve con cualquier cambio del
  prompt; `chain-04` hace lo mismo al revés.
- **Siguen en inglés 3 de 32:** `yield-03`, `cad-01` y `chain-03`.

**Qué concluimos.**
- **Nos quedamos con la v13.** El idioma pasa de 20/32 a 29/32 en español, y la zona
  tensionada y la referencia catastral ya no se inventan.
- **El argumento de menos en `port-01` es la herramienta haciendo su trabajo,** no un error.
  No cambiamos el caso del banco, para no mover la portería; lo explicamos.
- **La instrucción de idioma funciona cuando va pegada al punto donde el modelo empieza a
  responder,** no en el prompt de sistema. Es lo mismo que pasó con el encadenado.

---

### 2026-11-22 · Fase 3 · Corpus descargado con un script

**Qué queríamos saber.** Si el corpus de la propuesta (normativa del BOE, manual de la AEAT,
guías oficiales) se puede montar de forma reproducible y con qué tamaño sale.

**Qué hicimos.** `uv run python -m rag.download_corpus` (`rag/download_corpus.py`; fuentes,
licencias y decisiones en `rag/CORPUS.md`). Las leyes consolidadas se fijan a la versión
vigente el 2026-11-22. Después, `rag.ingest` y el troceado recursivo por defecto (800/100).

**Qué pasó.**

| Carpeta | Documentos | Fragmentos recursivos (800/100) |
|---|---|---|
| `boe/` (11 leyes consolidadas) | 11 | 4.004 |
| `aeat/` (Manual de Renta 2025) | 28 | 212 |
| `boe_diario/` (SERPAVI, zonas tensionadas) | 11 | 174 |
| `pdf/` (INE IRAV, BdE) | 2 | 27 |
| **Total** | **52** (2,6 M caracteres) | **4.417** (media 600) |

Las dos preguntas de la propuesta tienen respuesta en el corpus (art. 23.2 LIRPF, 70 %;
art. 17.6 LAU, contrato de diez o más años). Hay 29 fragmentos de menos de 50 caracteres
(«7», «II»…): números de apartado que el troceado recursivo deja sueltos.

**Qué concluimos.**
- El corpus está muy desequilibrado: el 91 % de los fragmentos son de leyes del BOE, y LIRPF y
  su reglamento traen mucho texto que no trata de alquileres. Es deliberado (distractores),
  pero el conjunto dorado debe repartir preguntas entre las cuatro fuentes, no solo leyes.
- Los fragmentos minúsculos son un argumento para el troceado semántico o por artículo.
- Siguiente: anotar el conjunto dorado por documento y artículo (o cita literal) y no por id
  de fragmento, para que sirva a las dos estrategias de troceado.

---

### 2026-11-22 · Fase 3 · Conjunto dorado anotado por artículo y cita

**Qué queríamos saber.** Cómo escribir las 50 preguntas para que sirvan a las dos estrategias de
troceado, y si son demasiado fáciles para BM25.

**Qué hicimos.** Leímos el corpus artículo a artículo y escribimos 51 preguntas con respuesta
(`rag/gold/gold.jsonl`) y 6 sin respuesta (`rag/gold/unanswerable.jsonl`). Cada pregunta
guarda documento, sección y una cita literal. `rag/gold.py` las traduce a ids para cualquier
troceado: es relevante el fragmento que contiene al menos la mitad de una cita. Formato y
criterios en `rag/gold/README.md`. Prueba rápida con BM25 sobre el troceado recursivo (800/100).

Al leer apareció que el RDL 26/2026 estaba **derogado** (no se convalidó). Lo cambiamos por
el RDL 29/2026, que lo sustituye, y el script ahora se niega a descargar normas derogadas.
También quitamos de las 28 páginas de la AEAT el texto del diálogo «Generar PDF».

**Qué pasó.**

| | Valor |
|---|---|
| Preguntas con más de una ubicación válida | 7 (ley + reglamento + manual, ley + preámbulo…) |
| Fragmentos relevantes por pregunta (recursivo 800/100) | 1 en 43 preguntas, 2 en 7, 3 en 1 |
| BM25: acierto@1 / @5 / @10 | 7,8 % / 27,5 % / 31,4 % |
| BM25: MRR@10 | 0,147 |

BM25 no encuentra en los 10 primeros 35 de las 51 preguntas. Las preguntas usan las palabras de
un inversor («honorarios de la agencia», «piso vacío») y no las de la norma («gastos de gestión
inmobiliaria», «desocupados con carácter permanente»).

**Qué concluimos.**
- El conjunto es exigente para recuperación léxica, que es lo que queríamos: deja margen para
  medir el denso y el híbrido. Si el denso tampoco llega, habrá que mirar si las preguntas son
  demasiado indirectas.
- Hay conflictos reales entre fuentes (Manual de Renta 2025 frente a LIRPF vigente, folleto
  del BdE frente a Ley 5/2019): son preguntas para el análisis de fallos de la generación.
- Siguiente: troceado semántico, retriever denso con Qwen3-Embedding y barrido de λ.

---

### 2026-11-23 · Fase 3 · Troceado, tres retrievers, λ e instrucción de consulta

**Qué queríamos saber.** Qué troceado y qué retriever recuperan mejor la respuesta de las 51
preguntas del conjunto dorado, qué λ usar en el híbrido y qué efecto tiene la instrucción de
la consulta en Qwen3-Embedding.

**Qué hicimos.** `uv run python -m rag.evaluate` en la MIG (9 min la primera vez; las 11.761
frases y los índices quedan en `rag/index/`). Resultado en `reports/fase3/phase3_eval.json`,
`reports/fase3/phase3_semantic_distances.png` y `reports/fase3/phase3_lambda.png`.
- Troceado recursivo 800/100 frente a semántico con el umbral en los percentiles 70, 80, 90
  y 95 de la distancia entre frases consecutivas: 0,762, 0,789, 0,821 y 0,845. La media es
  0,63, así que el 0,25 de la docstring cortaría en casi cada frase.
- BM25, denso (Qwen3-Embedding-0.6B, índice NumPy) e híbrido (min-max y λ·BM25 + (1−λ)·denso
  sobre los 20 primeros de cada uno).
- λ de 0 a 1 de 0,1 en 0,1, elegido por MRR con validación cruzada a dos mitades repetida 200
  veces. Así el λ no se puntúa sobre las mismas preguntas con que se eligió.

**Qué pasó.** Acierto@5 = la respuesta está entre los 5 primeros; MRR hasta el puesto 10.

| Troceado | Fragmentos | Media (car.) | BM25 | Denso | Híbrido | λ CV | MRR CV |
|---|---|---|---|---|---|---|---|
| Recursivo 800/100 | 4.422 | 599 | 27,5 % / 0,147 | 41,2 % / 0,272 | 45,1 % / 0,292 | 0,2 | 0,275 ± 0,056 |
| Semántico p70 | 5.384 | 481 | 37,3 % / 0,223 | **62,7 %** / 0,394 | 58,8 % / **0,432** | 0,3 | **0,416** ± 0,060 |
| Semántico p80 | 4.072 | 636 | 39,2 % / 0,200 | 56,9 % / 0,387 | 56,9 % / 0,401 | 0,4 | 0,384 ± 0,055 |
| Semántico p90 | 2.901 | 894 | 39,2 % / 0,212 | 58,8 % / 0,425 | 58,8 % / 0,425 | 0,0 | 0,414 ± 0,057 |
| Semántico p95 | 2.396 | 1.082 | 37,3 % / 0,220 | 54,9 % / 0,358 | 56,9 % / 0,372 | 0,1 | 0,357 ± 0,057 |

Instrucción de la consulta (denso, semántico p90):

| Instrucción | Acierto@5 | MRR | MRR respuesta en BOE (33) | MRR resto (18) | Top-5 del BOE / AEAT |
|---|---|---|---|---|---|
| Ninguna | 60,8 % | 0,431 | 0,473 | 0,353 | 154 / 58 |
| Por defecto (inglés, genérica) | 58,8 % | 0,425 | 0,476 | 0,332 | 142 / 69 |
| Genérica en español | 58,8 % | 0,423 | 0,470 | 0,337 | 151 / 59 |
| De dominio en español | 49,0 % | 0,355 | 0,426 | 0,224 | 176 / 34 |
| De dominio en inglés | 49,0 % | 0,329 | 0,392 | 0,214 | 168 / 33 |
| Equivocada («mismo estilo informal») | 54,9 % | 0,427 | 0,477 | 0,336 | 130 / 78 |

Preguntas sin respuesta: la similitud del primer fragmento es de 0,50 a 0,75 (0,58 de media),
frente a 0,53 a 0,66 de media en las que sí la tienen. «¿Está Madrid declarada zona
tensionada?» saca 0,75.

**Qué concluimos.**
- **El troceado importa más que el retriever.** Pasar del recursivo al semántico sube el MRR
  del denso de 0,27 a 0,39-0,43. El recursivo corta artículos por la mitad y deja fragmentos
  de un solo número de apartado. El semántico tiene un punto óptimo: con fragmentos de más
  de 1.000 caracteres (p95) el vector se diluye y baja.
- **El denso gana a BM25 con claridad** (MRR 0,43 frente a 0,21 en p90). Las preguntas usan las
  palabras de un inversor y no las de la ley, y BM25 no salta de «honorarios de la agencia» a
  «gastos de gestión inmobiliaria».
- **El híbrido aporta poco y depende del troceado.** Con fragmentos pequeños (p70) sí mejora
  en validación cruzada (0,416 frente a 0,394 del denso). En p90 la validación cruzada elige
  λ = 0 en 138 de 400 particiones, pero la curva es plana entre 0 y 0,3. **Elegimos p90 con
  λ = 0,2**, en el centro de la meseta, por dos razones: la meseta es más robusta que el pico
  de p70, y los fragmentos de unos 900 caracteres dan más contexto al generador. Con 51
  preguntas, la desviación de la validación cruzada (±0,06) es mayor que la diferencia entre
  las configuraciones buenas.
- **La instrucción sí es una palanca, y también en contra.** Las genéricas (inglés, español,
  ninguna) quedan empatadas. Pedir «el artículo de ley, la norma o el pasaje oficial» empeora
  el MRR un 20 %, igual en inglés que en español: no es el idioma, es el contenido. Esa
  instrucción empuja hacia el BOE (176 fragmentos del BOE en el top-5 frente a 142), donde
  están los distractores de la LIRPF y su reglamento. Las preguntas que se responden con la
  AEAT o los PDF caen de 0,33 a 0,22, y las del BOE también bajan. Nos quedamos con la
  instrucción por defecto.
- **El «no lo sé» no puede salir de un umbral de similitud**, porque las distribuciones se
  solapan. Tiene que decidirlo el generador.
- **Fallos (22 de 51 fuera del top-5 con p90 y λ = 0,2):**
  - Los preámbulos, sobre todo el del RDL 29/2026, explican las reglas en lenguaje llano y
    ganan al artículo (lau-09, lau-11, aeat-04, ibi-01/02). A veces son respuestas válidas
    no anotadas.
  - El caso práctico de la AEAT hace de «imán»: es una lista de gastos que sale primera en 7
    preguntas de IRPF, IBI e IVA.
  - Las filas de tabla partidas separan el municipio de su definición (zon-02, zon-03).
  - El IVA no tiene puente de vocabulario: «piso usado» frente a «segundas y ulteriores
    entregas».

---

### 2026-11-23 · Fase 3 · Generación con citas: base, base con pensamiento y modelo de la fase 1

**Qué queríamos saber.** Qué generador poner detrás de `/rag`, y si el modelo entrenado en la
fase 1 lee y cita mejor que el base.

**Qué hicimos.**
- Pipeline de `rag/generate.py`: semántico p90, híbrido λ = 0,2, cinco primeros fragmentos.
- La plantilla de clase en español, con citas numeradas [1]…[5] que se traducen a ids después
  de generar.
- Antes, tres pruebas cortas de 8 preguntas (`reports/fase3/phase3_generation_smoke*.json`). Con la
  plantilla inglesa, Qwen3-1.7B contestaba en inglés la mitad de las preguntas, citaba
  «artículo 36» en vez del id, y abría respuestas correctas con «no se especifica».
- Las 57 preguntas (51 + 6 sin respuesta) con `scripts/fase3/rag_gen_compare.sh` y `scripts/fase3/rag_round2.sh`:
  `rag.eval_generation --name {base, base_think, rlm_think}`. El modelo de la fase 1 es
  `rlm/weights/grpo2_lora`. Pensamiento con 1.536 tokens, sin él con 512.
- Las métricas se recalcularon con `--rescore` después de mejorar el detector de abstención:
  no reconocía «No se encuentra información en los pasajes».
- **Corpus.** `base` se repitió (13:04) sobre el corpus definitivo, tras dejar de tomar por
  vigente la versión sin fecha del art. 6 bis RIRPF. La primera ejecución, de las 11:27, está
  en `reports/fase3/phase3_generation_base_corpus_previo.json` y da las mismas cifras salvo en las
  citas: cita algo en el 74,5 % frente al 76,5 %, y el relevante en 14 de 30 frente a 15. Es la
  variación de una o dos respuestas. La evaluación de recuperación también se repitió (12:44) y
  reproduce la entrada anterior con diferencias de milésimas.

**Qué pasó.** El fragmento relevante se recupera en 30 de las 51 preguntas respondibles.

| | Qwen3-1.7B | Qwen3-1.7B con pensamiento | Fase 1 (GRPO 2) con pensamiento |
|---|---|---|---|
| Cita algún fragmento | 76,5 % | **88,2 %** | 74,5 % |
| Cita el relevante, cuando se recuperó | 50,0 % (15/30) | **70,0 %** (21/30) | 46,7 % |
| Cifras de la referencia en la respuesta, cuando se recuperó | 39,1 % | **43,5 %** | 30,4 % |
| Se abstiene con el fragmento delante | 6,7 % | **3,3 %** | 6,7 % |
| Se abstiene sin el fragmento (lo correcto) | 33,3 % | 33,3 % | 14,3 % |
| Se abstiene en las 6 sin respuesta | **6/6** | **6/6** | 5/6 |
| Ids inventados | 0 | 0 | 0 |
| Razonamiento cortado sin cerrar | 0 | 2 | 10 |
| Tiempo para las 57 | **9 min** | 35 min | 31 min |

**Qué concluimos.**
- **Pensar ayuda a leer.** Con pensamiento, el modelo cita el fragmento correcto en 21 de las 30
  preguntas en que lo tiene delante, frente a 15. Pero cuesta cuatro veces más. `/rag` queda sin
  pensamiento por defecto, porque la API se sirve desde el MacBook; `ARCA_RAG_THINKING=1` lo
  activa.
- **El modelo de la fase 1 es peor generador de RAG que el base.** Razona largo y en inglés,
  como le enseñó GRPO, y agota los 1.536 tokens sin cerrar en 10 de 57 preguntas. Cita y
  acierta menos, y contesta una pregunta sin respuesta. El entrenamiento para hacer cuentas no
  se transfiere a leer y citar: dato para la comparación de cerebros de la fase 4.
- **El «no lo sé» funciona** cuando lo decide el generador: 6/6 en las preguntas sin respuesta,
  y solo 1-2 abstenciones de 30 cuando tiene el fragmento delante.
- La «coincidencia de cifras» es una aproximación: no ve paráfrasis ni penaliza cifras de más.
  Las respuestas están guardadas en los JSON.

---

### 2026-11-23 · Fase 3 · Opción 1: el derecho aplicable en una fecha y auditoría del motor

**Qué queríamos saber.** Si un RAG que solo ve los artículos vigentes en la fecha de la pregunta
responde bien donde el RAG normal (la ley de hoy) se equivoca, sin perder lo que la ley de hoy
ya responde bien. Y si esas mismas versiones sirven para detectar reglas desfasadas en el motor
de las fases 1 y 2.

**Qué hicimos.**
- `rag/temporal.py`: 2.049 versiones de artículos de las 11 leyes, con sus intervalos de
  vigencia, partidas en 8.208 fragmentos. En una fecha rige la última versión, en el orden del
  documento, con fecha anterior o igual. Las versiones sin fecha no cuentan.
- `rag/gold/temporal.jsonl`: 17 preguntas con fecha, casi todas en pares que solo se
  distinguen por la fecha. 7 son de control: su respuesta coincide con la de hoy.
- Relevancia por contenido: vale cualquier versión del artículo que contenga la cita entera y
  ninguna de las frases de `absent`. La primera evaluación (13:00,
  `reports/fase3/phase3_temporal_relevancia_por_version.json`) exigía la versión exacta en vigor ese
  día, y por eso los controles nunca se acertaban con la ley de hoy. Lo corregimos (89899d6)
  y la repetimos.
- Recuperación: `uv run python -m rag.eval_temporal` → `reports/fase3/phase3_temporal.json`.
- Generación: `rag.eval_generation --gold rag/gold/temporal.jsonl --unanswerable ""` con el RAG
  normal y con `ARCA_RAG_TEMPORAL=1`, sin pensamiento y con él (1.536 tokens), en
  `reports/fase3/phase3_generation_temporal_{hoy,fecha}{,_think}.json`. Las 68 respuestas se juzgaron
  a mano: correcta, regla equivocada o abstención.
- Auditoría: `uv run python -m rag.audit_rules`.

**Qué pasó.** Recuperación (acierto@5 / MRR; híbrido λ = 0,2):

| Versiones visibles | Respuesta cambiada (10) | Controles (7) | Primero el artículo correcto pero en una versión que no aplicaba (cambiadas) |
|---|---|---|---|
| Solo las de hoy | 0 % / 0,000 | 57 % / 0,397 | 30 % |
| Todas, sin filtro | 30 % / 0,225 | 29 % / 0,213 | 20 % |
| **Las vigentes en la fecha** | **60 %** / **0,389** | **71 %** / **0,440** | 20 % |

El extractor de fechas acierta las 17.

Generación, juzgada a mano:

| | Cambiadas: correctas | Cambiadas: regla equivocada | Controles: correctas |
|---|---|---|---|
| RAG normal, sin pensamiento | 0 | 5 | 2 |
| RAG por fecha, sin pensamiento | 3 | 4 | 2 |
| RAG normal, con pensamiento | 1 | 5 | 3 |
| **RAG por fecha, con pensamiento** | **5** | **2** | 3 |

- **El RAG normal se equivoca con aplomo.** Con la ley de hoy contesta «cinco años» a un
  contrato de febrero de 2019 y «hasta tres años más» a una prórroga de 2016. Al de 2017 le
  aplica el límite de garantía de 2019.
- **El RAG por fecha con pensamiento acierta:** el plazo de 2017 (tres años), el de febrero de
  2019 (tres años, tras la derogación del RDL 21/2018), la prórroga tácita de 2016 (un año) y
  la reducción de 2019 (60 %) y de 2024 (90 %).
- **Fallos que quedan, todos del generador con la versión buena delante:**
  - el ITP de 2020: responde con el ISD de un caso práctico de la AEAT;
  - la imputación de 2027: dice el 2 % estando la escala en el contexto;
  - los honorarios de 2021: el razonamiento se corta sin cerrar;
  - la garantía de 2017: se abstiene en vez de concluir que no había límite.

Auditoría del motor de reglas (versión del 15/09/2026 frente a la del 22/11/2026):
- 4 reglas rotas: la escala 90/70/60/50 % de `rental_reduction_pct`, reescrita por el
  RDL 29/2026.
- 5 por revisar: artículos cambiados que aún contienen el texto en que se apoya la regla.
- 2 sin cambios.

**Qué concluimos.**
- **Filtrar por fecha es lo que convierte la historia del BOE en respuestas correctas.**
  - Con solo la ley de hoy, ninguna de las 10 preguntas cambiadas tiene la versión buena entre
    los 5 primeros.
  - Con todas las versiones sin filtro sube al 30 %, pero se mezclan textos contradictorios.
  - Filtrando por fecha llega al 60 %, y la respuesta pasa de 1 a 5 aciertos de 10.
  - Los controles no empeoran, y en recuperación mejoran, porque en una fecha pasada desaparecen
    distractores que hoy existen (los artículos nuevos del RDL 29/2026).
- **Con 10 + 7 preguntas son indicios, no pruebas estadísticas.** Pero el patrón es el que
  predice el diseño: ganan las preguntas cuya respuesta cambió, y no pierden las que no.
- **Ahora el límite es el generador.** En 3 de los 5 fallos que quedan tiene delante la
  versión correcta. Un generador mayor o con más tokens de pensamiento es la palanca siguiente.
- **La auditoría convierte la lección de la fase 2 en una prueba repetible.** El motor de la
  fase 1 aplica una escala que ya no está en el texto vigente. Para contratos anteriores al
  1/12/2026 sigue valiendo, por la transitoria 38.ª; eso lo decide una persona. Cuando se
  fusione la fase 2, que añade `rental_reduction_pct_2026` al motor, hay que darle reglas en
  `RULES`.

---

### 2026-11-23 · Fase 4 · Corpus ampliado con normativa autonómica, Sociedades y subastas (issue #13)

**Qué queríamos saber.** Si añadir las fuentes que piden las palancas del playbook (issue #10)
empeora la recuperación de la fase 3. La spec pide que no empeore el Recall@5 ni el MRR de las 51
preguntas doradas.

**Qué hicimos.** Añadimos seis documentos oficiales a `rag/download_corpus.py`, documentados en
`rag/CORPUS.md`:

- los textos de tributos cedidos de Madrid (DLeg 1/2010), Cataluña (DLeg 1/2024, libro 6),
  Andalucía (Ley 5/2021) y la Comunitat Valenciana (Ley 13/1997), en su versión consolidada del
  BOE/BOCM;
- el artículo 29 de la Ley 27/2014 del Impuesto sobre Sociedades;
- los artículos 643 a 675 de la LEC (subastas).

Medimos dos veces sobre el mismo corpus de la fase 3, antes y después de añadirlos, con
`rag.evaluate` y la configuración de la fase 3. El "después" está en
`scripts/fase4/ampliar_corpus_eval.sh` y tardó 1.235 s:

- con las 51 preguntas y las 6 sin respuesta del commit 9b1c9ad;
- con las 59 preguntas actuales (8 nuevas sobre los documentos nuevos).

Al final reindexamos el pipeline de `/rag`: 3.956 fragmentos. `none-02` (el ITP de Madrid) deja
de ser una pregunta sin respuesta y pasa a ser `ccaa-01`.

**Qué pasó.** Semántico p90, la configuración de `/rag`:

| Retriever | R@5 antes (51) | R@5 después (51) | MRR antes (51) | MRR después (51) | R@5 (59) | MRR (59) |
|---|---|---|---|---|---|---|
| híbrido λ = 0,2 | 0,529 | 0,510 | 0,421 | 0,395 | 0,492 | 0,375 |
| denso | 0,529 | 0,510 | 0,414 | 0,391 | 0,492 | 0,372 |
| BM25 | 0,382 | 0,353 | 0,218 | 0,208 | 0,322 | 0,197 |

Fragmentos: 2.897 antes y 3.883 después (+34 %). Con troceado recursivo, el R@5 híbrido no cambia
(0,441) y el MRR baja de 0,292 a 0,273.

Con el híbrido, cambia el primer acierto de 6 de las 51 preguntas: 1 mejora y 5 empeoran.

- itp-01 pasa de la posición 1 a la 4. Pregunta por el tipo estatal supletorio del ITP, y los
  cuatro textos autonómicos hablan también del tipo del ITP de la vivienda usada: compiten, y con
  razón.
- lau-06 pasa de 3 a 10, irpf-03 de 2 a 3, y lau-11 e ibi-01, que estaban en la posición 10,
  salen del top 10.

De las 8 preguntas nuevas, 3 tienen un fragmento relevante en el top 5: lec-01 (1), lec-02 (2) y
ccaa-05 (2). Las 4 del tipo autonómico del ITP (ccaa-01 a 04) y lis-01 no aparecen en el top 10.
Las leyes autonómicas son largas y repiten "tipo de gravamen" en cada impuesto cedido, así que el
fragmento del ITP de la vivienda no destaca.

**Qué concluimos.**

- **No se cumple el criterio "no empeora".** En las 51 preguntas, el R@5 baja 0,019, es decir, una
  pregunta menos en el top 5, y el MRR baja 0,026. Con 51 preguntas es una diferencia pequeña.
  Aun así, el sentido es claro: más documentos parecidos diluyen el ranking. La mantenemos
  porque, sin estas fuentes, las palancas autonómicas, la de la sociedad y la de las subastas no
  tienen cita en el corpus (issue #10).
- **Siguiente paso**, para no diluir los textos estatales: trocear las leyes autonómicas solo por
  los artículos del ITP y de las deducciones del IRPF, como ya hacemos con `trlrhl` y `liva`, en
  vez de descargarlas enteras. Sería una pregunta para la issue.
- Las citas del playbook (`evidence.quote`) se comprueban contra el corpus en el test de la
  issue #10. Siguen siendo correctas aunque el retriever no encuentre esos pasajes: el agente las
  cita desde `find_levers`, no desde la búsqueda.
### 2026-11-23 · Fase 4 · Primeras pruebas del bucle ReAct con Qwen3-1.7B (cerebro base)

**Qué queríamos saber.** Si el bucle de la issue #20 (`agent/react_agent.py`) funciona con el
modelo de verdad: que cierre con `final_answer`, que la traza tenga pensamiento, acción y
observación reales, y que los guardarraíles (auditor, bucle, pasos) actúen. No es la
evaluación del banco (issue 06, de Kike): son 5–6 tareas elegidas para cubrir categorías.

**Qué hicimos.** `uv run python -m agent.evaluate --brains base --ids lever-01 lever-04
inconsistent-02 impossible-01 broken_tool-01 [kb_plus_tool-01] --out
reports/fase4/smoke_react_base{,_v2,_v4}.json`, `max_steps=10`, greedy, 1024 tokens por paso,
en la MIG de la DGX. Tres versiones del bucle, cambiando una cosa cada vez:

- v1: el bucle tal como lo pide la spec (commit 2990766).
- v2: una pista al final de la última observación de cada turno (pasos que quedan, "Thought:",
  no repetir, `final_answer` en español), como el `CHAIN_HINT` de la fase 2 (cc4dbcd).
- v3 (parada a mitad, sin informe): un "Thought:" sin tool call deja de tomarse como respuesta
  y cuenta como paso (310a0e1).
- v4: ese pensamiento suelto ya no gasta paso; pasa a ser el `thought` de la siguiente llamada.
  La cuarta llamada idéntica corta el bucle (e3c27ff).

**Qué pasó.**

| Versión | Tareas | Check ok | Cierra con `final_answer` | Texto suelto como respuesta | Reserva | Pasos con pensamiento |
|---|---|---|---|---|---|---|
| v1 | 5 | 0 | 1 | 3 | 1 | 3/30 |
| v2 | 6 | 0 | 0 | 6 | 0 | 12/21 |
| v4 | 6 | 1 | 5 | 0 | 1 | 36/46 |

- **v1.** Qwen3 sin thinking emite el `<tool_call>` sin texto: 27 de 30 pasos sin pensamiento.
  Tras leer resultados en inglés responde en inglés y sin la tool. En inconsistent-02 hizo bien
  la bifurcación (`what_if` con valor de referencia 150.000 y 210.000) pero la repitió dos veces
  más, pese al aviso, y agotó los pasos.
- **v2.** La pista da pensamientos, pero el modelo escribe "Thought: necesito llamar a what_if"
  **sin** la llamada, y la spec trata el texto sin tool call como respuesta: las 6 tareas
  terminaron así, con una intención por respuesta.
- **v3.** Contar ese pensamiento como paso gastaba la mitad de los 10 pasos: el modelo alterna
  un mensaje de pensamiento y otro de llamada (lever-04: 5 pensamientos y 5 búsquedas
  idénticas).
- **v4.** Las 6 tareas llegan a `final_answer`, en español salvo una (lever-04). El auditor
  rechaza cifras inventadas que antes pasaban: "6,8 %" cuando el motor dio 0,68 %
  (impossible-01), "1.140 €" cuando era 11.400 € (broken_tool-01). A la tercera, la respuesta
  sale con `succeeded=false`. inconsistent-02 pasa el check con los dos escenarios.

Lo que falla en v4 es del cerebro, no del bucle:

- lever-04 no guarda los dos pisos con `record_property` y busca en el RAG.
- `search_knowledge_base` recibe un `on_date` inventado (2023-01-01, 2023-10-05) y devuelve la
  ley antigua.
- En impossible-01 se inventa un piso (500.000 €, 300 €/mes) para tener algo que analizar.
- `record_investor` rellena con ceros lo que no se dijo (`loan_years: 0`).

Una incidencia: en v1 el corpus apareció a mitad de la corrida (lo descargaba otro proceso) y la
primera búsqueda construyó el índice dentro del timeout de 30 s. Cada reintento lanzaba otra
construcción en paralelo, así que `_pipeline()` lleva ahora un candado.

**Qué concluimos.**

- El bucle cumple la spec y los guardarraíles actúan sobre el modelo real. Con 6 tareas no se
  puede comparar nada (1/6 frente a 0/5): la tasa la da el banco completo (issue 06).
- Desviación de la spec (punto 9): un texto que empieza por "Thought:" no es una respuesta, sino
  el pensamiento del paso siguiente. Hay que confirmarlo en la issue.
- `brain=thinking` con el bucle v4, en dos tareas (`reports/fase4/smoke_react_thinking.json`):
  funciona. El `thought` de cada paso es el razonamiento de Qwen3, y las dos tareas terminan en
  3 y 6 pasos (51 s y 90 s), pero ninguna pasa el check. En inconsistent-02 dice que el valor de
  referencia "no influye" en el neto y no llama a `what_if`; es falso, porque cambia el ITP. En
  impossible-01 se abstiene bien ("no tools can predict 2027 price drops"), pero en inglés y
  después de repetir búsquedas hasta el "NOT RUN".
- Pendiente para el núcleo, fuera del bucle: que `search_knowledge_base` no acepte un `on_date`
  que la tarea no menciona, y probar `brain=rlm` (aquí no está el adaptador del GRPO 2).
