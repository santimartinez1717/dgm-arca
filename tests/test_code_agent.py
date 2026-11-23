"""The CodeAgent contrast on CPU: a scripted model writes the Python, the real tools run it."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("smolagents")

from agent import code_agent as ca  # noqa: E402
from agent import evaluate as ev  # noqa: E402
from agent.bench.build_bench import FLATS  # noqa: E402

BENCH = {t["id"]: t for t in ev.load_tasks(Path("agent/bench/tasks.jsonl"))}


class ScriptedChat:
    """Returns the next scripted output on each call and keeps the prompts it saw."""

    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.prompts: list[list[dict]] = []

    def generate(self, messages, tools):
        self.prompts.append(messages)
        return self.outputs.pop(0) if self.outputs else "<code>\nfinal_answer('nada')\n</code>"


def runner(*outputs: str) -> tuple[ca.CodeAgentRunner, ScriptedChat]:
    chat = ScriptedChat(*outputs)
    return ca.CodeAgentRunner(chat_for=lambda brain: chat), chat


SCREEN_LOOP = """Thought: analyse every flat in a loop and keep those above 4.5 %.
<code>
ids = ["P%02d" % i for i in range(1, 16)]
good, capped = [], []
for pid in ids:
    r = analyze_property(property_id=pid)
    if r["net_yield_pct"] > 4.5:
        good.append((r["net_yield_pct"], pid))
    elif r["effective_rent"] < r["asking_rent"]:
        capped.append(pid)
good.sort(reverse=True)
lines = [f"{pid}: {y} %" for y, pid in good]
lines += [f"{pid} se descarta por el tope legal de la renta" for pid in capped]
final_answer("; ".join(lines))
</code>"""


def test_tools_are_the_agent_registry_without_overlapping_calculators():
    names = set(ca.agent_registry().tools)
    assert {"analyze_property", "find_levers", "what_if", "search_knowledge_base"} <= names
    assert not names & set(ca.OVERLAPPING)
    assert "final_answer" not in names


def test_registry_tool_schema():
    registry = ca.agent_registry()
    tool = ca.RegistryTool(registry.tools["max_offer_price"], registry, [])
    assert tool.inputs["target_net_yield_pct"] == {
        "type": "number",
        "description": tool.inputs["target_net_yield_pct"]["description"],
    }
    assert tool.inputs["monthly_rent"]["nullable"] is True
    assert tool.inputs["monthly_rent"]["type"] == "number"


def test_screening_in_one_code_step(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_CASE_DB", str(tmp_path / "cases.sqlite"))
    agent, chat = runner(SCREEN_LOOP)
    out = agent.run(BENCH["screening-01"]["task"], max_steps=4, brain="base")

    assert out["succeeded"] and out["n_steps"] == 1 and out["code_errors"] == 0
    assert len(out["tool_calls"]) == 15 and {c["name"] for c in out["tool_calls"]} == {
        "analyze_property"
    }
    passing = [f for f in FLATS if f.net_yield > 4.5]
    for flat in passing:
        assert f"{flat.id}: {flat.net_yield} %" in out["final_answer"]
    # the CSV went to the case file, not to the prompt
    prompt = " ".join(str(m["content"]) for m in chat.prompts[0])
    assert "15 pisos cargados en el expediente" in prompt and "265000" not in prompt
    assert out["steps"][0]["action"]["name"] == "python"
    assert "for pid in ids" in out["steps"][0]["action"]["arguments"]["code"]


def test_broken_tool_is_a_code_error_and_the_agent_goes_on(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_CASE_DB", str(tmp_path / "cases.sqlite"))
    monkeypatch.setenv("ARCA_PORTFOLIO_DB", str(tmp_path / "portfolio.sqlite"))
    agent, _ = runner(
        "<code>\nr = get_rent_reference(municipality='Santiago de Compostela')\nprint(r)\n</code>",
        "Thought: the lookup failed, say so.\n<code>\n"
        "final_answer('No he podido comprobar la zona; si es tensionada, 800 €.')\n</code>",
    )
    task = BENCH["broken_tool-01"]
    with ev.broken(agent, task):
        out = agent.run(task["task"], max_steps=4, brain="base")
    assert out["code_errors"] == 1 and out["n_steps"] == 2
    assert "unavailable" in out["steps"][0]["observation"]
    assert ev.check_answer(task, out["final_answer"])


def test_tool_timeout(monkeypatch):
    import time

    registry = ca.agent_registry()
    spec = registry.tools["get_market_rates"]
    registry.tools["get_market_rates"] = type(spec)(
        spec.name, spec.description, lambda: time.sleep(1), spec.args_model
    )
    record = ca._call_with_timeout(registry, "get_market_rates", {}, timeout=0.05)
    assert not record["ok"] and "timed out" in record["error"]


def test_confirmation_tools_need_confirm(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_CASE_DB", str(tmp_path / "cases.sqlite"))
    agent, chat = runner(
        "<code>\nfinal_answer('ok')\n</code>", "<code>\nfinal_answer('ok')\n</code>"
    )
    agent.run("Guarda el piso en mi cartera, por favor.", max_steps=2, brain="base")
    assert "save_to_portfolio" not in str(chat.prompts[0])
    agent.run("Guarda el piso en mi cartera, por favor.", max_steps=2, brain="base", confirm=True)
    assert "save_to_portfolio" in str(chat.prompts[1])


def test_thinking_is_hidden_from_the_code_parser():
    model = ca.SharedModel(
        ScriptedChat("<think>maybe <code>x</code></think>\n<code>\nfinal_answer(1)\n</code>")
    )
    message = model.generate([{"role": "user", "content": [{"type": "text", "text": "hola"}]}])
    assert message.content.startswith("<code>") and "<think>" in message.raw
    assert message.token_usage.output_tokens > 0


def test_evaluate_with_the_code_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_AGENT_TOOL_TIMEOUT", "1")
    chat = ScriptedChat(SCREEN_LOOP)
    tasks = [BENCH["screening-01"]]
    results = ev.evaluate(
        tasks, lambda: ca.CodeAgentRunner(chat_for=lambda b: chat), ["base"], ["full"], log=print
    )
    run = results["runs"]["full/base"]
    assert run["correct"] == 1 and run["mean_steps"] == 1 and run["mean_code_errors"] == 0
    # analyze_property was called from the code; screen_properties does not exist yet
    assert run["rows"][0]["tools_used"] == ["analyze_property", "python"]
    results["agent"] = "code"
    assert "Errores de código" in ev.markdown(results) and "(code)" in ev.markdown(results)


def test_code_agent_refuses_json_only_ablations():
    with pytest.raises(AttributeError, match="audit"):
        ev.configure(ca.CodeAgentRunner(chat_for=lambda b: None), "no_auditor")
