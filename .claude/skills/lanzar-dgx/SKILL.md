---
name: lanzar-dgx
description: Lanzar y vigilar un proceso largo en la DGX (evaluación, destilación, SFT, GRPO) sin perder el progreso. Usar antes de cualquier comando que tarde más de unos minutos o use la GPU.
---

# Lanzar un proceso largo en la DGX

## Antes de lanzar

1. ¿Cabe en la sesión? Tiempo que queda:
   `echo $(( (SLURM_JOB_END_TIME - $(date +%s)) / 60 )) min`. Si no cabe, el proceso tiene
   que guardar por partes y poder reanudarse (`--resume` en `rlm.distill`,
   `--save-steps` + `--resume-from-checkpoint` en SFT/GRPO). Si no puede, no lanzarlo.
2. ¿La GPU está libre? `pgrep -af "python -m rlm"`. Si hay otro proceso en la GPU, esperar.
3. ¿Se ha probado la memoria? Si la configuración (modelo, tokens, lote) es nueva, hacer
   antes una prueba corta (`--limit`, `--steps`, `--n-examples` pequeños).
4. ¿El archivo de salida ya existe? No pisar resultados de otra ejecución.

## Lanzar

```bash
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.<script> <args> > <nombre>.log 2>&1 &
```

- `PYTHONUNBUFFERED=1` es obligatorio: sin él, el log no muestra nada hasta el final.
- No meter la salida por una tubería a `awk` para añadir la hora: aquí `awk` es `mawk` y
  retiene la entrada. Los scripts ya imprimen la hora ellos mismos.
- Cada orden en su línea: `source ... && nohup ... &` manda al fondo la cadena entera.
- Apuntar el PID (`echo $!`) y la hora de inicio.

## Vigilar

Con la herramienta Monitor, filtrando el progreso **y todos los finales posibles**:

```bash
tail -n +1 -F <nombre>.log | grep --line-buffered -E "batch [0-9]+/|ELAPSED_S|PEAK_GPU|Traceback|Error:|OutOfMemory|Killed" &
while kill -0 <PID> 2>/dev/null; do sleep 5; done; sleep 3; echo "PROCESO TERMINADO"; kill %1
```

`pgrep -f <patrón>` lanzado desde la shell de Claude se encuentra a sí mismo (la orden
contiene el patrón): comprobar con `kill -0 <PID>`.

## Si falla

- `OutOfMemoryError`: bajar el lote y relanzar con `--resume`. Renombrar antes el log
  (`mv x.log x_oom.log`) para conservar el error.
- Sesión a punto de acabar: no hacer nada. Lo guardado se conserva; en la siguiente sesión,
  mismo comando con `--resume` (o `--resume-from-checkpoint`).

Al terminar, registrar el resultado con la skill `registrar-experimento`.
