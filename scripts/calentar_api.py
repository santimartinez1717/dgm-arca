"""Warm the API up and check every endpoint before a demo or the live evaluation.

The first call to each phase loads its model, its index or its adapter. This script makes that
call so nobody in class waits for a cold start, and checks that every endpoint answers what the
grader expects. It needs no dependency beyond the standard library::

    uv run python scripts/calentar_api.py                      # API on localhost:8000
    uv run python scripts/calentar_api.py --url https://….ngrok-free.dev --thinking

Each line says the endpoint, the HTTP status, the seconds and a short sign that it worked. The
exit code is 1 if any endpoint failed, so ``scripts/serve_dgx.sh`` can say so.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TASK = "Piso en Valencia de 180.000 € alquilado por 850 €/mes, ¿qué rentabilidad neta saco?"


def call(url: str, path: str, body: dict | None = None, timeout: float = 600) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url + path,
        data=data,
        headers={"Content-Type": "application/json", "ngrok-skip-browser-warning": "1"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except json.JSONDecodeError:
            return exc.code, {"detail": exc.reason}
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, {"detail": str(exc)}


def reasoning_sign(d: dict) -> str:
    verdict = (d.get("verifier") or {}).get("is_correct")
    return f"answer={d['answer'][:40]!r} correcta={verdict}"


def checks(thinking: bool) -> list[tuple[str, str, dict | None, callable]]:
    agent = {"task": TASK, "max_steps": 6}
    out = [
        (
            "/health",
            "/health",
            None,
            lambda d: ", ".join(f"{k}={v['status']}" for k, v in d["phases"].items()),
        ),
        (
            "/reasoning",
            "/reasoning",
            {
                "question": "Un piso de segunda mano cuesta 100.000 €. El ITP es del 10 % y la "
                "notaría 1.000 €. ¿Cuál es el desembolso total? Da el resultado en euros, con dos "
                "decimales.",
                "expected_answer": "111000.00",
            },
            reasoning_sign,
        ),
        (
            "/tools",
            "/tools",
            {"query": "¿Cuánto ITP pago por un piso de segunda mano de 180.000 € en Valencia?"},
            lambda d: f"tools={[c['name'] for c in d['tool_calls']]}",
        ),
        (
            "/rag",
            "/rag",
            {"question": "¿Cuánto puede subir la renta en una zona tensionada?", "top_k": 3},
            lambda d: f"{len(d['chunks'])} pasajes, citas={d['citations'][:2]}",
        ),
        ("/agent base", "/agent", {**agent, "brain": "base"}, None),
        ("/agent rlm", "/agent", {**agent, "brain": "rlm"}, None),
    ]
    if thinking:
        out.append(("/agent thinking", "/agent", {**agent, "brain": "thinking"}, None))
    return out


def agent_sign(d: dict) -> str:
    actions = [s["action"]["name"] for s in d["steps"] if s.get("action")]
    return f"model={d['model']} pasos={d['n_steps']} ok={d['succeeded']} tools={actions}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--thinking", action="store_true", help="also the thinking brain (~1 min)")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    failed = []
    for label, path, body, sign in checks(args.thinking):
        started = time.perf_counter()
        status, data = call(url, path, body)
        seconds = time.perf_counter() - started
        try:
            ok = status == 200
            detail = (sign or agent_sign)(data) if ok else str(data.get("detail", data))[:200]
        except (KeyError, TypeError) as exc:
            ok, detail = False, f"respuesta inesperada: {exc}"
        mark = "OK " if ok else "MAL"
        print(f"{mark} {label:<16} HTTP {status:<3} {seconds:6.1f} s  {detail}", flush=True)
        if not ok:
            failed.append(label)
    if failed:
        print(f"\nFallan: {', '.join(failed)}. Mira logs/serve_dgx.log.", flush=True)
        return 1
    print("\nTodos los endpoints responden: API caliente.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
