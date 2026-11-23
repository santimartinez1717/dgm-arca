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
2. Terminal 1: `bash serve_dgx.sh`. Espera a que la API responda, la calienta con una pregunta
   (la primera carga el modelo) y escribe `API lista`.
3. Terminal 2:
   ```bash
   ~/clusters/dgx/bin/ngrok http 8000 --url=https://sculptor-fled-magical.ngrok-free.dev \
       --config ~/clusters/dgx/.ngrok.yml
   ```
   (Con una versión antigua de ngrok, `--domain=sculptor-fled-magical.ngrok-free.dev`.)
4. Comprobar desde fuera, por ejemplo desde el móvil o el portátil:
   `https://sculptor-fled-magical.ngrok-free.dev/health`.

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
    --batch-size 4 --compare reports/eval_grpo2_17b_2048.json \
    --out reports/eval_grpo2_mlx8_2048.json
```

## 3. Desde otro portátil (Linux o Windows con NVIDIA)

Lo que necesita: una GPU NVIDIA con 6 GB o más y drivers recientes, 16 GB de RAM, unos 10 GB de
disco, `git`, [`uv`](https://docs.astral.sh/uv/) y ngrok con la cuenta del equipo (o su propia
cuenta y su propia URL, que habría que comunicar a los profesores).

```bash
git clone https://github.com/santimartinez1717/dgm-arca.git && cd dgm-arca
uv sync --extra train
cp .env.example .env    # y descomentar ARCA_RLM_ADAPTER=rlm/weights/grpo2_lora
```

El adaptador (67 MB) está en un repositorio privado de Hugging Face: o se le pasa la carpeta
`rlm/weights/grpo2_lora` directamente, o se descarga con un token que tenga acceso.

```bash
uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
uv run --env-file .env arca-api
```

La primera línea tiene que decir `True` y el nombre de la tarjeta. La terminal de la API escribe
`phase 1 model on cuda` al cargar. Después, ngrok como en el Mac. Sin GPU NVIDIA (solo CPU)
va igual de lento que el Mac sin MLX.
