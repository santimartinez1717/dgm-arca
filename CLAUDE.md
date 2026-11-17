# CLAUDE.md — Umbral (práctica ARCA, MGD · ICAI 2026-2027)

Equipo: Bernardo Ordás, Enrique Rodríguez, Santiago Martínez Díe. Tema: analista de inversión
inmobiliaria para alquilar en España (propuesta en `docs/propuesta.md`). Enunciado en
`docs/enunciado.tex`, rúbrica en `docs/rubrica.md`, plan de la fase 1 en `docs/fase1_plan.md`.

## Idioma y estilo

- Commits, EXPERIMENTS.md y documentación en español. Código, comentarios y `print` en inglés,
  como el resto del repo.
- Antes de commitear: `uv run ruff check` y `uv run ruff format`, y `uv run pytest -q`.
- No hacer push sin que lo pidan. La terminal de Claude no tiene credenciales de GitHub
  (`could not read Username`): el push lo hace el usuario desde su terminal de code-server.
- `docs/fase1_plan.md`, `docs/dgx.md` y el enunciado son del profesor: no editarlos.

## La DGX (lo que no está en `docs/dgx.md`)

- Cada sesión es un trabajo de Slurm que corre `code-server`; Claude vive dentro. Recursos:
  **MIG 1g.18gb (~17,2 GB usables) y 4 CPUs**. `nvidia-smi` enseña la H200 entera (143 GB) y
  la memoria de todas las particiones: no sirve para medir lo nuestro, usar
  `torch.cuda.max_memory_reserved()`.
- La sesión termina en `$SLURM_JOB_END_TIME` (epoch) y Slurm mata todo lo que hay dentro,
  `nohup` incluido. Cerrar el navegador no la termina. Dentro no hay `squeue`/`scontrol`/`sbatch`.
- Antes de cualquier proceso largo: `source smoke/dgx_env.sh` (pone `HF_HOME` en la caché
  del clúster; si no, los modelos van a `~/.cache`).
- No hay `py-spy` ni `gdb` y `ptrace_scope=1`: un proceso en marcha no se puede inspeccionar.
  Si no escribe su progreso en el log, no hay forma de saberlo.
- Mientras un proceso usa la GPU, no lanzar otro en ella: con 17 GB, el segundo tumba al primero.
  Las pruebas de código se hacen en CPU con `CUDA_VISIBLE_DEVICES=""` y
  `HuggingFaceTB/SmolLM2-135M-Instruct`.

Para lanzar y vigilar procesos largos, usar la skill `lanzar-dgx`.

## Fase 1: estado y decisiones

- Alumno: **Qwen3-1.7B** + LoRA r16. Profesor: Qwen3-4B con la hoja `TEACHER_RULES`.
  pass@1 en test (1024 tokens): base 3,3 % → SFT 32,0 % → GRPO 36,3 %; con 2048: 10,3 / 37,7 /
  38,3 %. Desde el 18/11 la cifra principal es la de **2048 tokens** (evaluación, muestreo y
  GRPO 2): las trazas del profesor miden ~1.900 tokens y cortar a 1024 las penalizaba. Detalle en EXPERIMENTS.md;
  cinco fallos analizados en `docs/analisis_fallos_fase1.md`.
- `rlm/realestate_rules.py` es la única fuente de verdad del dominio. `TEACHER_RULES` en
  `rlm/distill.py` la resume para el profesor: **si cambia una regla, cambiar las dos**.
- Lo que GRPO no arregló: `irpf_rental` (se salta la amortización), `cash_on_cash` (cuota a mano)
  y obra nueva (IVA). GRPO solo aprende de grupos con algún acierto; en irpf hubo 0 de 552.
- Ronda 2 en curso (nov 2026): destilación con información privilegiada (`--privileged
  --only-unsolved`: el profesor ve la clave del motor) + `rlm/rewrite_traces.py` (reescribe sin
  citar la clave). SFT 2 hecho el 17/11 (`rlm/weights/sft2_lora`): 30,0 % en test, obra nueva
  de 1/11 a 9/11, `irpf_rental` sigue en 1/50. Siguiente: `bash sesion3.sh` (muestreo del SFT 2
  y `cash_on_cash` con clave) → GRPO con `--third-reward process` y un learning rate mayor.
- Filtro de fugas (`RULES_LEAK`): la hoja ("background knowledge") y la clave ("the key says…")
  no pueden llegar al alumno; `train_sft` las limpia (`scrub_leaks`) o descarta la traza.
- Memoria en la MIG de 17 GB: destilación lotes de 2; SFT 1,7B con `--batch-size 2 --grad-accum
  8 --max-length 3328` (5,3 GB); GRPO con micro-lotes de 2 y sin atención de cuDNN (10,6 GB).
- La GPU está libre solo si `pgrep -af "python -m rlm"` no devuelve nada.

## EXPERIMENTS.md

Una entrada por cosa lanzada o decidida, con la skill `registrar-experimento`.
