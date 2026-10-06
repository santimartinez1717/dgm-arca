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

- Alumno: **Qwen3-1.7B** (línea base 3,3 % pass@1, se corta el 81 % con 1024 tokens).
  Profesor: Qwen3-4B. Detalle y números en EXPERIMENTS.md.
- `rlm/realestate_rules.py` es la única fuente de verdad del dominio. `TEACHER_RULES` en
  `rlm/distill.py` la resume para el profesor: **si cambia una regla, cambiar las dos**.
- Destilación: con la hoja de reglas, 37,5 % de aceptación (4B, 1536 tokens); lo que se
  pierde es longitud y trazas que citan la hoja, no errores. Ahora 2048 tokens por defecto.
  En la MIG de 17 GB, lotes de 2 (con 4 se queda sin memoria); guardado por lote y `--resume`.
- Plan de la sesión de 24 h con 71 GiB, paso a paso: `docs/sesion_24h_fase1.md`.
- Pendiente: medir memoria de SFT (1,7B, 2048 tokens) y de GRPO (1,7B, 1024 tokens) con una
  prueba corta en GPU antes de lanzarlos.

## EXPERIMENTS.md

Una entrada por cosa lanzada o decidida, con la skill `registrar-experimento`.
