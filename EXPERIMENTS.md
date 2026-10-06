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
