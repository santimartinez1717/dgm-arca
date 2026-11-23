"""agent/evaluate.py on CPU: a scripted agent that calls the real tools, no model loaded."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent import evaluate as ev
from api.schemas import AgentAction, AgentResponse, AgentStep
from tool_use.tools import default_registry

BENCH = {t["id"]: t for t in ev.load_tasks(Path("agent/bench/tasks.jsonl"))}


@dataclass
class ScriptedAgent:
    """Plays a fixed script per task: tool calls through the real registry, then an answer.

    ``script`` maps a task id to ``(calls, answer)``; the brain name is appended to the
    answer lookup so two brains can answer differently.
    """

    script: dict[str, tuple[list[tuple[str, dict]], str | dict[str, str]]]
    registry: object = field(default_factory=default_registry)
    audit: bool = True
    anchor_case_file: bool = True
    seen: list[dict] = field(default_factory=list)

    def run(self, task: str, max_steps: int = 10, brain: str = "rlm") -> dict:
        task_id = next(i for i, t in BENCH.items() if t["task"] == task)
        calls, answer = self.script[task_id]
        if isinstance(answer, dict):
            answer = answer[brain]
        if answer == "CRASH":
            raise RuntimeError("the model ran out of memory")
        steps = []
        for name, arguments in calls:
            record = self.registry.call(name, arguments)
            observation = json.dumps(record.result) if record.ok else f"ERROR: {record.error}"
            steps.append(
                AgentStep(
                    thought=f"call {name}",
                    action=AgentAction(name=name, arguments=arguments),
                    observation=observation,
                )
            )
        self.seen.append({"task": task_id, "brain": brain, "steps": steps})
        steps.append(AgentStep(thought="done", action=AgentAction(name="final_answer")))
        response = AgentResponse(
            final_answer=answer, steps=steps, n_steps=len(steps), tokens_used=100 * len(steps)
        ).model_dump()
        # audit is an optional field of the response (issue 21): added here as a dict
        return {**response, "audit": {"ok": True, "rejections": int("rechazo" in answer)}}


# --------------------------------------------------------------------------- configurations


def test_configure_sets_switches_and_drops_playbook_tools():
    agent = ScriptedAgent(script={})
    agent.registry.tools["find_levers"] = agent.registry.tools["get_portfolio"]
    agent.registry.tools["what_if"] = agent.registry.tools["get_portfolio"]
    ev.configure(agent, "no_playbook")
    assert "find_levers" not in agent.registry.tools and "what_if" not in agent.registry.tools
    assert ev.configure(ScriptedAgent(script={}), "no_auditor").audit is False
    assert ev.configure(ScriptedAgent(script={}), "flat_memory").anchor_case_file is False


def test_configure_refuses_a_switch_the_agent_does_not_have():
    class Bare:
        registry = default_registry()

    with pytest.raises(AttributeError, match="audit"):
        ev.configure(Bare(), "no_auditor")


# --------------------------------------------------------------------------- isolation


def test_isolated_seeds_the_portfolio_and_restores_the_environment():
    from tool_use.portfolio import get_portfolio

    before = os.environ.get("ARCA_PORTFOLIO_DB")
    with ev.isolated(BENCH["large_holder-01"]):
        summary = get_portfolio.fn(municipality="Santiago de Compostela")
        assert summary["dwellings"] == 4 and summary["dwellings_in_zone"] == 4
    assert os.environ.get("ARCA_PORTFOLIO_DB") == before
    with ev.isolated(BENCH["large_holder-02"]):  # a fresh portfolio, not the previous one
        assert get_portfolio.fn()["dwellings"] == 4


def test_broken_tool_errors_and_is_restored():
    agent = ScriptedAgent(script={})
    task = BENCH["broken_tool-01"]
    with ev.broken(agent, task):
        record = agent.registry.call("get_rent_reference", {"municipality": "Pamplona"})
        assert not record.ok and "unavailable" in record.error
    assert agent.registry.call("get_rent_reference", {"municipality": "Pamplona"}).ok


def test_broken_tool_hangs_past_the_timeout():
    agent = ScriptedAgent(script={})
    task = {**BENCH["broken_tool-01"], "break_mode": "timeout"}
    with ev.broken(agent, task, hang_s=0.01):
        record = agent.registry.call("get_rent_reference", {"municipality": "Pamplona"})
    assert not record.ok and "did not answer" in record.error


def test_hang_is_longer_than_the_agent_timeout(monkeypatch):
    monkeypatch.setenv("ARCA_AGENT_TOOL_TIMEOUT", "2")
    assert ev.hang_seconds() > 2


# --------------------------------------------------------------------------- statistics


def test_wilson_and_mcnemar():
    low, high = ev.wilson(5, 10)
    assert round(low, 3) == 0.237 and round(high, 3) == 0.763
    assert ev.wilson(0, 10)[0] == 0 and ev.wilson(0, 0) == (0.0, 0.0)
    assert ev.mcnemar(0, 0) == 1.0
    assert ev.mcnemar(5, 0) == pytest.approx(0.0625)
    assert ev.mcnemar(3, 3) == 1.0


# --------------------------------------------------------------------------- end to end

RENT_CALL = ("get_rent_reference", {"municipality": "Pamplona"})
SCRIPT = {
    # correct for both brains
    "kb_plus_tool-02": (
        [RENT_CALL],
        "Pamplona es zona tensionada: no puedes superar la renta del contrato anterior, "
        "850 €. Consulta a un asesor.",
    ),
    # right for base only
    "inconsistent-02": (
        [],
        {
            "base": "Si el valor es 150.000 €, el neto es 4,97 %; si es 210.000 €, 4,87 %.",
            "rlm": "El neto es 4,97 %.",
        },
    ),
    # abstains (base) or invents a figure (rlm)
    "impossible-01": (
        [],
        {
            "base": "No puedo predecir los precios de 2027: nadie lo sabe.",
            "rlm": "Los precios bajarán un 5 % en 2027 (rechazo previo del auditor).",
        },
    ),
    # the broken tool: the agent says it could not check
    "broken_tool-01": (
        [("get_rent_reference", {"municipality": "Santiago de Compostela"})],
        {"base": "No he podido comprobar la zona; si es tensionada, 800 €.", "rlm": "CRASH"},
    ),
}


def test_evaluate_end_to_end(tmp_path):
    tasks = [BENCH[i] for i in SCRIPT]
    agents: list[ScriptedAgent] = []

    def make_agent():
        agents.append(ScriptedAgent(script=SCRIPT))
        return agents[-1]

    lines: list[str] = []
    results = ev.evaluate(
        tasks, make_agent, ["base", "rlm"], ["full", "no_auditor"], log=lines.append
    )

    assert len(agents) == 2  # one fresh agent per configuration
    assert len(lines) == 2 * 2 * len(tasks) and lines[0].startswith("[1/16] full/base")
    base, rlm = results["runs"]["full/base"], results["runs"]["full/rlm"]
    assert (base["correct"], rlm["correct"]) == (4, 1)
    assert base["abstention_rate"] == 1.0 and rlm["abstention_rate"] == 0.0
    assert rlm["crashes"] == 1 and rlm["audit_rejection_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert base["by_category"]["broken_tool"]["correct"] == 1
    assert base["wilson_95"][1] == 1.0

    # the broken tool really failed inside the run, and came back afterwards
    broken_obs = next(s for s in agents[0].seen if s["task"] == "broken_tool-01")
    assert "unavailable" in broken_obs["steps"][0].observation
    ok_obs = next(s for s in agents[0].seen if s["task"] == "kb_plus_tool-02")
    assert ok_obs["steps"][0].observation.startswith("{")

    [m, _] = [m for m in results["mcnemar"]]
    assert (m["config"], m["only_a"], m["only_b"]) == ("full", 3, 0)

    written = ev.write_reports(results, tmp_path / "phase4_eval.json", tmp_path / "trazas")
    md = (tmp_path / "phase4_eval.md").read_text()
    assert "| full | base | 4/4 (100 %)" in md and "McNemar" in md
    traces = sorted(p.name for p in (tmp_path / "trazas").iterdir())
    assert len(written) == 2 + len(traces)
    assert any(n.startswith("tool_rota-broken_tool-01") for n in traces)
    assert any(n.startswith("buena-") for n in traces)
    assert "**Acción:** `get_rent_reference`" in (
        tmp_path / "trazas" / traces[-1]
    ).read_text() or any("**Acción:**" in (tmp_path / "trazas" / n).read_text() for n in traces)
    saved = json.loads((tmp_path / "phase4_eval.json").read_text())
    assert saved["runs"]["full/rlm"]["rows"][3]["crash"].startswith("RuntimeError")


def test_required_tools_are_measured():
    agent = ScriptedAgent(script=SCRIPT)
    row = ev.run_task(agent, BENCH["kb_plus_tool-02"], "base", 10, None)
    assert row["tools_used"] == ["final_answer", "get_rent_reference"]
    assert row["required_tools_used"] is False  # search_knowledge_base and analyze_property


def test_checkpoint_resumes_a_cut_run(tmp_path):
    tasks = [BENCH[i] for i in SCRIPT]
    checkpoint = tmp_path / "eval.partial.jsonl"
    made: list[ScriptedAgent] = []

    def make_agent():
        made.append(ScriptedAgent(script=SCRIPT))
        return made[-1]

    # A run cut after two tasks: their rows are in the checkpoint, the last line half written.
    first = ev.evaluate(
        tasks[:2], make_agent, ["base"], ["full"], log=lambda _: None, checkpoint=checkpoint
    )
    with checkpoint.open("a") as handle:
        handle.write('{"config": "full", "brain": "base", "id": "impossible-01", "corr')
    lines: list[str] = []
    resumed = ev.evaluate(
        tasks, make_agent, ["base"], ["full"], log=lines.append, checkpoint=checkpoint
    )
    assert sum("(reanudada)" in line for line in lines) == 2
    assert len(made) == 2  # the second run built an agent only for the missing tasks
    run = resumed["runs"]["full/base"]
    assert run["n"] == 4 and run["correct"] == 4
    assert run["rows"][:2] == first["runs"]["full/base"]["rows"]


def test_fully_resumed_configuration_loads_no_agent(tmp_path):
    checkpoint = tmp_path / "eval.partial.jsonl"
    tasks = [BENCH["kb_plus_tool-02"]]
    ev.evaluate(
        tasks,
        lambda: ScriptedAgent(script=SCRIPT),
        ["base"],
        ["full"],
        log=lambda _: None,
        checkpoint=checkpoint,
    )

    def no_agent():
        raise AssertionError("nothing left to run: the model must not load")

    assert (
        ev.evaluate(tasks, no_agent, ["base"], ["full"], log=lambda _: None, checkpoint=checkpoint)[
            "runs"
        ]["full/base"]["correct"]
        == 1
    )


def test_no_playbook_uses_the_loop_switch():
    from agent.react_agent import ReActAgent

    agent = ev.configure(ReActAgent(), "no_playbook")
    assert agent.use_playbook is False
    assert not {"find_levers", "what_if"} & {
        t["function"]["name"] for t in agent.tool_definitions()
    }
