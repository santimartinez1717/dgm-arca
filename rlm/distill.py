"""Phase 1, step 1b: generate reasoning traces with a teacher model and keep the verified ones.

This is what Sky-T1, OpenThoughts and DeepSeek's cold start have in common: a strong
model writes solutions with visible reasoning, a verifier throws away the wrong ones,
and what survives becomes SFT data. Our teacher is Qwen3 in thinking mode.

Run (on the DGX; a subset is enough, SFT needs 1-2k verified traces)::

    PYTHONUNBUFFERED=1 uv run python -m rlm.distill --data rlm/data/train.jsonl \
        --teacher Qwen/Qwen3-4B --samples 4 --limit 400 --output rlm/data/sft_traces.jsonl

The teacher gets ``TEACHER_RULES`` in its system prompt (``--no-rules`` turns it off). A
first probe without it accepted 18.8 % of the traces: Qwen3-4B does not know the implicit
Spanish rules (VAT on new builds, the mortgage payment in cash-on-cash) and fails the same
way in every sample. The student never sees the sheet: SFT uses the plain R1 prompt, so
the rules have to be learnt from the reasoning in the traces.

Each batch is appended to the output as soon as it finishes, so a run that dies loses at
most one batch; ``--resume`` skips the problems already in the file.

Output: one JSON line per generated trace with ``question``, ``answer``, ``family``,
``trace`` (canonical ``<think>…</think><answer>…</answer>``), ``verified``, ``truncated``,
``mentions_rules`` and ``teacher``. The acceptance rate, overall and per family, is printed
and saved next to the output: it is the first measurement of how hard each family is, and
goes to EXPERIMENTS.md.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import time
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from rlm.data import R1_ZERO_SYSTEM_PROMPT
from rlm.generation import Generator, batched
from rlm.realestate_rewards import verify_row
from rlm.rewards import has_valid_format

THINK = re.compile(r"<think>(?P<think>.*?)</think>", re.DOTALL)
ANSWER = re.compile(r"<answer>(?P<answer>.*?)</answer>", re.DOTALL)

# The same rules as realestate_rules.py, written for the teacher. Keep both in sync.
TEACHER_RULES = """\
Reglas del dominio (inversión en vivienda para alquilar en España). Razona como si las \
conocieras de memoria: no digas que te las han dado ni las cites como una lista.

- Coste de adquisición. Vivienda usada: ITP al tipo de la comunidad sobre el mayor entre \
el precio y el valor de referencia del Catastro. Obra nueva: no paga ITP; paga IVA del 10 % \
sobre el precio más AJD al tipo de la comunidad sobre el mayor entre el precio y el valor \
de referencia. Total = precio + impuestos + notaría, registro y gestoría + comisión de \
agencia + reforma.
- Rentabilidad neta (antes de impuestos y sin hipoteca). Renta cobrada = renta mensual × \
(12 − meses vacíos). Gastos = IBI + comunidad del año + seguro + mantenimiento y gestora \
como porcentaje de la renta cobrada. Rentabilidad = (renta cobrada − gastos) / inversión \
total × 100.
- Rentabilidad sobre fondos propios (cash-on-cash). Cuota mensual de un préstamo francés: \
C = P·i / (1 − (1 + i)^(−n)), con i = tipo anual / 12 y n = años × 12; redondea la cuota a \
céntimos. Flujo de caja = ingreso neto anual − 12·C. Fondos propios = inversión total − \
préstamo. Rentabilidad = flujo de caja / fondos propios × 100; puede ser negativa.
- Precio máximo para una rentabilidad objetivo. Inversión total = P·(1 + ITP) + gastos \
fijos (notaría, registro, reforma…); el ITP se paga sobre el precio. Se despeja P de \
ingreso neto / inversión total = objetivo: P = (ingreso neto / objetivo − gastos fijos) / \
(1 + ITP).
- Renta máxima legal de un contrato nuevo (LAU art. 17.6 y 17.7, Ley 12/2023). Gran \
tenedor: más de 10 viviendas o más de 1.500 m² de uso residencial; o, si la declaración de \
la zona rebaja el umbral, 5 o más viviendas en esa zona. Fuera de zona tensionada no hay \
tope: se cobra la renta de mercado. En zona tensionada: si hubo contrato de vivienda \
habitual en los últimos cinco años, el tope es la última renta actualizada (un 10 % más si \
hubo obras de rehabilitación, eficiencia energética o accesibilidad en los dos años \
anteriores, o si el contrato fue de diez años o más). Si el propietario es gran tenedor, \
se añade el tope del índice: valor superior del índice de referencia (€/m² al mes) × m². \
Sin contrato en los últimos cinco años, el tope del índice solo se aplica si la declaración \
de la zona lo extiende a esas viviendas. Se aplican todos los topes que correspondan, y la \
renta es la menor entre la de mercado y esos topes. Si preguntan por el año: renta mensual × 12.
- Rendimiento del alquiler en el IRPF. Neto = ingresos − IBI − comunidad − seguro − \
mín(intereses + reparaciones, ingresos) − amortización. Amortización = 3 % × el mayor entre \
el coste de adquisición y el valor catastral × (1 − valor del suelo / valor catastral). \
Reducción, solo si el neto es positivo (gana la primera que encaje): 90 % en zona tensionada \
si ya estaba alquilada y la renta baja más de un 5 %; 70 % en zona tensionada si es el \
primer alquiler y el inquilino tiene de 18 a 35 años, o si se alquila a una administración \
pública o entidad sin ánimo de lucro para vivienda social; 60 % si se terminó una \
rehabilitación en los dos años anteriores; 50 % en el resto. Rendimiento reducido = neto × \
(1 − reducción). Un neto negativo no se reduce.
- Redondea a dos decimales solo el resultado final (y la cuota de la hipoteca). En \
<answer> pon solo el número, con punto decimal y sin unidades."""

# A trace that cites the sheet teaches the student to refer to rules it will never be shown.
RULES_LEAK = re.compile(
    r"(rules? (provided|given|listed|above)|(provided|given|listed) rules?|system prompt|"
    r"reglas (dadas|proporcionadas|indicadas|del dominio)|hoja de reglas)",
    re.IGNORECASE,
)


def canonicalize(raw: str) -> str | None:
    """Rewrite a teacher completion into ``<think>…</think><answer>…</answer>``.

    Qwen3 in thinking mode opens ``<think>`` inside the chat template, so the decoded text
    often starts mid-thought and only shows the closing tag. After ``</think>`` it may or may
    not use ``<answer>``; when it does not, the last non-empty line is taken as the answer.
    Returns None when there is no reasoning at all.
    """
    if "</think>" not in raw:
        return None
    thinking, after = raw.split("</think>", 1)
    thinking = thinking.replace("<think>", "").strip()
    if not thinking:
        return None
    match = ANSWER.search(after)
    if match:
        answer = match.group("answer").strip()
    else:
        lines = [line.strip() for line in after.strip().splitlines() if line.strip()]
        if not lines:
            return None
        answer = lines[-1]
    return f"<think>\n{thinking}\n</think>\n<answer>{answer}</answer>"


def generate_traces(
    rows: list[dict],
    teacher: str,
    samples: int,
    max_new_tokens: int,
    batch_size: int,
    temperature: float,
    min_think_words: int,
    system_prompt: str = R1_ZERO_SYSTEM_PROMPT,
) -> Iterator[list[dict]]:
    """For each problem, sample ``samples`` teacher completions, canonicalise and verify them.

    Yields the traces of one batch at a time, so that the caller can save them right away.

    A trace is kept as ``verified`` only if it has valid format, the answer passes the domain
    verifier, it was not truncated, the reasoning has at least ``min_think_words`` words
    (a cheap filter against answers that are right by luck with no reasoning) and it does
    not cite the teacher's rule sheet.
    """
    generator = Generator(teacher, enable_thinking=True, system_prompt=system_prompt).load()
    for chunk in batched(rows, batch_size):
        outputs = generator.generate(
            [row["question"] for row in chunk],
            num_return_sequences=samples,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        batch: list[dict] = []
        for row, completions in zip(chunk, outputs, strict=True):
            for raw, n_tokens, truncated in completions:
                trace = canonicalize(raw)
                mentions_rules = bool(RULES_LEAK.search(trace or raw))
                ok = False
                if trace is not None and not truncated and has_valid_format(trace):
                    correct, _ = verify_row(trace, row)
                    think_words = len(THINK.search(trace).group("think").split())
                    ok = correct and think_words >= min_think_words and not mentions_rules
                batch.append(
                    {
                        "question": row["question"],
                        "answer": row["answer"],
                        "family": row.get("family", "control"),
                        "trace": trace or raw,
                        "verified": ok,
                        "truncated": truncated,
                        "mentions_rules": mentions_rules,
                        "n_tokens": n_tokens,
                        "teacher": teacher,
                    }
                )
        yield batch


def read_traces(path: Path) -> list[dict]:
    """Traces already saved by an earlier run, dropping a last line cut off mid-write."""
    traces = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            traces.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return traces


def acceptance_report(traces: list[dict]) -> dict:
    """Acceptance rate overall and per family, plus truncation, for EXPERIMENTS.md."""
    total = Counter(t["family"] for t in traces)
    kept = Counter(t["family"] for t in traces if t["verified"])
    truncated = Counter(t["family"] for t in traces if t["truncated"])
    solved = {}
    for t in traces:
        solved.setdefault((t["family"], t["question"]), False)
        solved[(t["family"], t["question"])] |= t["verified"]
    problems = Counter(f for f, _ in solved)
    problems_solved = Counter(f for (f, _), ok in solved.items() if ok)
    return {
        "overall": sum(kept.values()) / max(len(traces), 1),
        "mentions_rules": sum(t.get("mentions_rules", False) for t in traces) / max(len(traces), 1),
        "per_family": {
            f: {
                "traces": total[f],
                "acceptance": kept[f] / total[f],
                "truncated": truncated[f] / total[f],
                "problems_with_a_verified_trace": problems_solved[f] / problems[f],
            }
            for f in sorted(total)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", required=True, help="domain JSONL with question / answer")
    parser.add_argument("--teacher", default="Qwen/Qwen3-4B")
    parser.add_argument("--samples", type=int, default=4, help="traces per problem")
    parser.add_argument("--limit", type=int, default=None, help="random subset of problems")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="problems per batch; x samples sequences share the KV cache (MIG 1g.18gb: 4 "
        "with 1536 new tokens, 2 with 3072)",
    )
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=1536,
        help="longer traces are dropped as truncated: the student answers within 1024 tokens",
    )
    parser.add_argument("--min-think-words", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--rules",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="give the teacher TEACHER_RULES in its system prompt",
    )
    parser.add_argument(
        "--resume", action="store_true", help="skip the problems already in --output"
    )
    parser.add_argument("--output", default="rlm/data/sft_traces.jsonl")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines()]
    if args.limit:
        rows = random.Random(args.seed).sample(rows, min(args.limit, len(rows)))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    traces: list[dict] = []
    if out.exists():
        if not args.resume:
            raise SystemExit(f"{out} already exists: pass --resume to continue it")
        traces = read_traces(out)
        # Rewrite it without a half-written last line before appending to it.
        out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces))
    done = {t["question"] for t in traces}
    pending = [row for row in rows if row["question"] not in done]
    n_batches = math.ceil(len(pending) / args.batch_size)
    print(f"{len(done)} problems already in {out}, {len(pending)} to go in {n_batches} batches")

    system_prompt = R1_ZERO_SYSTEM_PROMPT
    if args.rules:
        system_prompt += "\n\n" + TEACHER_RULES
    start = last = time.time()
    with out.open("a", encoding="utf-8") as handle:
        batches = generate_traces(
            pending,
            args.teacher,
            args.samples,
            args.max_new_tokens,
            args.batch_size,
            args.temperature,
            args.min_think_words,
            system_prompt,
        )
        for i, batch in enumerate(batches, 1):
            handle.write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in batch))
            handle.flush()
            os.fsync(handle.fileno())
            traces.extend(batch)
            now = time.time()
            per_batch = (now - start) / i
            kept = sum(t["verified"] for t in traces)
            print(
                f"[{datetime.now():%H:%M:%S}] batch {i}/{n_batches} in {(now - last) / 60:.1f} min"
                f" · {len(traces)} traces, {kept} verified ({100 * kept / len(traces):.1f}%)"
                f" · ~{per_batch * (n_batches - i) / 60:.0f} min to go",
                flush=True,
            )
            last = now
    print(f"ELAPSED_S={time.time() - start:.0f}")
    import torch

    if torch.cuda.is_available():
        print(f"PEAK_GPU_GB={torch.cuda.max_memory_reserved() / 2**30:.1f}")

    report = acceptance_report(traces)
    report_path = out.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"acceptance {100 * report['overall']:.1f}% -> {out}\nper family -> {report_path}")


if __name__ == "__main__":
    main()
