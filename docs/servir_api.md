# Servir la API de corrección

La corrección llama a nuestra API por una URL pública de ngrok:
`https://sculptor-fled-magical.ngrok-free.dev`. La cuenta gratuita de ngrok solo permite **un
túnel a la vez** con ese dominio: antes de abrirlo en una máquina, cerrarlo en las demás.

Hay tres formas de servirla, de mejor a peor:

| Dónde | Modelo | Velocidad aproximada | Pregunta larga (~1.900 tokens) |
|---|---|---|---|
| DGX (GPU) | GRPO 2, base + LoRA (el del 47,3 %) | 30-60 tokens/s | 30-60 s |
| Portátil con NVIDIA (≥ 6 GB) | el mismo | 30-60 tokens/s | 30-60 s |
| Mac con chip M | GRPO 2 en 8 bits con MLX | por medir | por medir |

Un Mac sin MLX (PyTorch en la GPU de Apple) va a unos 2,5 tokens/s con 8 GB de RAM: más de 10
minutos por pregunta larga. No sirve para la corrección.

## 1. Desde la DGX

**Una vez, instalar ngrok** en la carpeta que se conserva entre sesiones. En la terminal de
code-server:

```bash
mkdir -p ~/clusters/dgx/bin && cd ~/clusters/dgx/bin
curl -sSLO https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xzf ngrok-v3-stable-linux-amd64.tgz && rm ngrok-v3-stable-linux-amd64.tgz
./ngrok version
```

Y guardar el token de ngrok (dashboard.ngrok.com → *Your Authtoken*) en esa misma carpeta, no
en `~/.config`, que no se conserva:

```bash
~/clusters/dgx/bin/ngrok config add-authtoken <TOKEN> --config ~/clusters/dgx/.ngrok.yml
```

**Cada vez que haya que exponerla:**

1. Abrir una sesión en Open OnDemand con duración suficiente (máximo 24 h) para cubrir toda la
   ventana de corrección o la demo.
2. Terminal 1: `bash scripts/serve_dgx.sh`. Espera a que la API responda, la calienta con una pregunta
   (la primera carga el modelo) y escribe `API lista`.
3. Terminal 2:
   ```bash
   ~/clusters/dgx/bin/ngrok http 8000 --url=https://sculptor-fled-magical.ngrok-free.dev \
       --config ~/clusters/dgx/.ngrok.yml
   ```
   (Con una versión antigua de ngrok, `--domain=sculptor-fled-magical.ngrok-free.dev`.)
4. Comprobar desde fuera, por ejemplo desde el móvil o el portátil:
   `https://sculptor-fled-magical.ngrok-free.dev/health`.

**Con Docker, en la misma sesión.** Las sesiones tienen Docker *rootless*, así que también
se puede servir con `docker compose`, como pide el enunciado. Hace falta
`smoke/docker_dgx.sh` en lugar de `docker compose`: pasa al contenedor los ficheros de
nuestra partición MIG, que cambian en cada sesión y sin los cuales torch no ve la GPU. Se usa
desde `~/clusters/dgx/dgm-arca`, con el `.env` de siempre:

```bash
smoke/docker_dgx.sh build              # la imagen vive en /tmp: rehacerla en cada sesión (~10 min)
smoke/docker_dgx.sh run --rm check-gpu # tiene que salir "H200 MIG 1g.18gb"
smoke/docker_dgx.sh up api             # en lugar del paso 2; ngrok igual que en el paso 3
```

Probado el 23/11 en la sesión de la rama `fase2`: `/health` con `reasoning` y `tools` en
`ready`, y `/tools` respondiendo (ver EXPERIMENTS.md).

Mientras la API está en marcha ocupa 4-5 GB de la GPU. No lanzar a la vez evaluaciones ni
entrenamientos: con 17 GB, el segundo proceso puede tumbar al primero. Cuando la sesión llega a
su hora, Slurm mata la API y el túnel.

## 2. Desde un Mac (con MLX)

```bash
git pull team main
uv sync --extra train --extra mac
uv run hf download santimartinez1717/umbral-qwen3-1.7b-grpo2-mlx-8bit \
    --local-dir rlm/weights/grpo2_mlx_8bit
```

En el `.env`, añadir `ARCA_RLM_MLX=rlm/weights/grpo2_mlx_8bit` (si está, se usa en lugar de
`ARCA_RLM_ADAPTER`). Después, `uv run --env-file .env arca-api` y `ngrok http 8000
--url=https://sculptor-fled-magical.ngrok-free.dev`. La terminal de la API escribe
`generated N tokens in X s (Y tokens/s)` en cada petición.

Para comprobar que el modelo en 8 bits acierta lo mismo que el original, en 30 problemas del
test (con la API parada, para no tener dos modelos en memoria):

```bash
uv run python -m rlm.eval_mlx --model rlm/weights/grpo2_mlx_8bit --n-examples 30 \
    --batch-size 4 --compare reports/fase1/eval_grpo2_17b_2048.json \
    --out reports/fase1/eval_grpo2_mlx8_2048.json
```

## 3. Desde un portátil con Windows y NVIDIA (Docker)

Pensado para (sin probar aún): Windows 11, RTX 3060 Laptop de 6 GB, 16 GB de RAM. En Windows hay que usar
Docker: `uv` directamente instalaría torch sin CUDA (el proyecto solo lo pide con CUDA en
Linux) y la API iría en CPU, inservible. Docker corre un Linux con acceso a la GPU.

Hace falta: unos 30 GB libres en disco, conexión buena (la imagen y el modelo son ~15 GB) y
1-2 horas la primera vez. **Hacerlo entero el día antes**, no el de la demo.

### Paso 1. Driver de NVIDIA

Instalar el último driver Game Ready o Studio para la RTX 3060 Laptop desde
<https://www.nvidia.com/Download/index.aspx> (o la app NVIDIA). Reiniciar. Con él, la GPU ya
funciona dentro de WSL2 y Docker: **no** hay que instalar CUDA aparte.

### Paso 2. WSL2

PowerShell **como administrador**:

```powershell
wsl --install
```

Reiniciar cuando lo pida. Si ya estaba instalado, `wsl --update`.

### Paso 3. Docker Desktop

Descargar e instalar <https://www.docker.com/products/docker-desktop/> dejando marcada la
opción *Use WSL 2 instead of Hyper-V*. Abrir Docker Desktop y esperar a que diga *Engine
running*. Comprobar que Docker ve la GPU (PowerShell normal):

```powershell
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

Tiene que salir una tabla con la *GeForce RTX 3060 Laptop GPU*. Si sale un error, revisar el
paso 1 y reiniciar.

### Paso 4. El código y el modelo

```powershell
cd $HOME
git clone https://github.com/santimartinez1717/dgm-arca.git
cd dgm-arca
```

(Si el repositorio es privado, Santiago tiene que añadirlo como colaborador en GitHub primero.)

Crear la carpeta `rlm\weights\grpo2_lora` y copiar dentro los ficheros del adaptador que le
pasa Santiago: `adapter_config.json`, `adapter_model.safetensors`, `chat_template.jinja`,
`tokenizer.json` y `tokenizer_config.json`. Comprobar:

```powershell
dir rlm\weights\grpo2_lora
```

### Paso 4 bis. El corpus y el índice de la fase 3

`/rag` necesita el corpus (`rag/corpus/`) y los vectores ya calculados (`rag/index/`), que no
están en git. Calcularlos en el portátil llevaría mucho tiempo, así que se copian de la DGX: el
paquete es `~/clusters/dgx/rag_demo_fase3.tar.gz` (43 MB, preparado el 23/11). Santiago se lo
pasa junto con el adaptador, y se descomprime en la carpeta del repositorio:

```powershell
tar -xzf rag_demo_fase3.tar.gz
dir rag\index
```

Tienen que salir tres ficheros `.npy` (las frases, los 2.894 fragmentos y las 8.208 versiones
de artículos). Si se rehace el corpus con `download_corpus`, el índice deja de coincidir y se
recalcula al arrancar.

### Paso 5. El `.env`

```powershell
copy .env.example .env
```

No hay que tocar nada: ya trae `ARCA_RLM_ADAPTER=rlm/weights/grpo2_lora` y
`ARCA_RLM_VERIFIER=euro`. **No** hace falta `HF_TOKEN`: el modelo base es público.

### Paso 6. Construir y arrancar

```powershell
docker compose build
docker compose run --rm check-gpu
docker compose up api
```

`build` tarda la primera vez (descarga ~10 GB). `check-gpu` tiene que decir que ve CUDA y
`bf16 supported: True`. `up api` deja la API en marcha en esa ventana; se para con `Ctrl+C`.

### Paso 7. Probarla y calentarla

Abrir en el navegador <http://localhost:8000/docs>, desplegar **POST /reasoning**, *Try it
out*, y pegar:

```json
{"question": "Estoy analizando un piso de segunda mano que se vende por 338.500 €. El barrio tiene metro a cinco minutos. No necesita reforma. El tipo de ITP de la comunidad es del 3,5 %. No hay comisión de agencia. El valor de referencia del Catastro es 369.500 €. Notaría, registro y gestoría suman 4.120 €. ¿Cuál es el desembolso total de la operación? Da el resultado en euros, con dos decimales.", "expected_answer": "355552.50"}
```

*Execute*. La primera vez descarga el modelo base (3,4 GB) y tarda unos minutos; en la ventana
de Docker sale `phase 1 model on cuda` y después `generated N tokens in X s`. Tiene que
devolver `"answer": "355552.50"` y `"is_correct": true`. Repetir: la segunda vez debe tardar
menos de un minuto. Probar también <http://localhost:8000/health>.

### Paso 8. ngrok

En otra ventana de PowerShell:

```powershell
winget install ngrok.ngrok
ngrok config add-authtoken <TOKEN>
ngrok http 8000 --url=https://sculptor-fled-magical.ngrok-free.dev
```

Con el token de la cuenta del equipo se usa la URL de siempre (y no puede haber otro ngrok
abierto con ella). Con su propia cuenta, quitar `--url=...`: ngrok le dará otra URL, que hay
que mandar a los profesores. Comprobar desde el móvil `<URL>/health`.

### Durante la corrección o la demo

- Portátil enchufado y sin suspensión: *Configuración → Sistema → Energía → Suspender: Nunca*.
- Las dos ventanas abiertas (Docker y ngrok). Si el portátil se reinicia: abrir Docker
  Desktop, `docker compose up api`, calentar (paso 7) y `ngrok http ...`.
- Las fases 1 y 2 comparten una sola copia de Qwen3-1.7B (`api/shared_model.py`): la fase 1
  con el adaptador GRPO 2 activado y la fase 2 con él desactivado. Las dos juntas ocupan unos
  4,3 GB de GPU (por separado serían 8,4 GB y no cabrían en 6 GB), con respuestas idénticas
  a las de cada fase cargada sola (comprobado en la DGX el 23/11).
- Las peticiones se atienden de una en una, también entre fases.
- `/rag` usa la misma copia de Qwen3-1.7B (sin adaptador). El modelo de embeddings va en CPU
  (`ARCA_RAG_EMBEDDING_DEVICE=cpu` en el `.env`): con el índice ya calculado solo embebe la
  pregunta, en menos de un segundo, y no ocupa memoria de la GPU de 6 GB. Probarla con
  `{"question": "Firmé un contrato de alquiler el 1 de febrero de 2019. ¿Cuál era la duración
  mínima con las prórrogas?"}`: tiene que devolver `"law_date": "2019-02-01"` y tres años.
