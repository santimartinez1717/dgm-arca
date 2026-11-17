"""The five-step loop, tested with a scripted model: no GPU, no network, milliseconds."""

from __future__ import annotations

import json

import pytest

from tool_use.executor import ToolLoop
from tool_use.registry import ToolRegistry, tool


@tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: First number.
        b: Second number.
    """
    return a + b


@tool(requires_confirmation=True)
def write_note(text: str) -> str:
    """Write a note.

    Args:
        text: The note.
    """
    return "written"


def call(name: str, **arguments) -> str:
    return f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"


class ScriptedModel:
    """Returns the scripted outputs in order and records what it was shown."""

    name = "scripted"

    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.seen: list[list[dict]] = []
        self.tools_seen: list = []

    def generate(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        self.tools_seen.append(tools)
        return self.outputs.pop(0)


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry().register(add, write_note)


def test_answer_without_tools_ends_in_one_turn(registry):
    model = ScriptedModel("<think>No tool needed.</think>Hola.")
    response = ToolLoop(model, registry).run("Saluda")
    assert response.answer == "Hola." and response.tool_calls == [] and response.turns == 1


def test_multi_step_feeds_each_result_back(registry):
    model = ScriptedModel(call("add", a=2, b=3), call("add", a=5, b=10), "Son 15.")
    response = ToolLoop(model, registry).run("2+3, y luego +10")
    assert [r.result for r in response.tool_calls] == [5, 15]
    assert response.turns == 3 and response.answer == "Son 15."
    last_prompt = model.seen[-1]
    tool_messages = [m for m in last_prompt if m["role"] == "tool"]
    assert [m["content"] for m in tool_messages] == ["5", "15"]
    assistant = [m for m in last_prompt if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"] == {"name": "add", "arguments": {"a": 2, "b": 3}}


def test_parallel_calls_run_in_the_same_turn(registry):
    model = ScriptedModel(call("add", a=1, b=1) + "\n" + call("add", a=2, b=2), "2 y 4.")
    response = ToolLoop(model, registry).run("1+1 y 2+2")
    assert [r.result for r in response.tool_calls] == [2, 4]
    assert response.turns == 2


def test_errors_become_observations_and_the_model_can_retry(registry):
    model = ScriptedModel(
        call("add", a="two", b=1),  # validation error
        "<tool_call>{not json}</tool_call>",  # parse error
        call("multiply", a=2, b=2),  # unknown tool
        call("add", a=2, b=1),
        "3",
    )
    response = ToolLoop(model, registry).run("2+1", max_turns=5)
    oks = [r.ok for r in response.tool_calls]
    assert oks == [False, False, False, True] and response.answer == "3"
    errors = [m["content"] for m in model.seen[-1] if m["role"] == "tool"][:3]
    assert "invalid arguments" in errors[0]
    assert "not valid JSON" in errors[1]
    assert "unknown tool" in errors[2]


def test_max_turns_stops_the_loop(registry):
    model = ScriptedModel(*[call("add", a=1, b=1)] * 3)
    response = ToolLoop(model, registry).run("bucle", max_turns=3)
    assert response.turns == 3 and len(response.tool_calls) == 3
    assert "3 turnos" in response.answer


def test_confirmation_policy(registry):
    auto = ToolLoop(ScriptedModel(call("write_note", text="x"), "ok"), registry).run("nota")
    assert auto.tool_calls[0].ok
    deny = ToolLoop(
        ScriptedModel(call("write_note", text="x"), "ok"), registry, confirm_policy="deny"
    ).run("nota")
    assert not deny.tool_calls[0].ok and "confirm" in deny.tool_calls[0].error


def test_native_prompt_passes_definitions_and_no_tools_mode_hides_them(registry):
    model = ScriptedModel("a")
    ToolLoop(model, registry).run("q")
    assert {d["function"]["name"] for d in model.tools_seen[0]} == {"add", "write_note"}

    course = ScriptedModel("a")
    ToolLoop(course, registry, prompt_style="course").run("q")
    assert course.tools_seen[0] is None and '"name": "add"' in course.seen[0][0]["content"]

    bare = ScriptedModel(call("add", a=1, b=1), "a")
    response = ToolLoop(bare, registry, use_tools=False).run("q")
    assert bare.tools_seen[0] is None and "add" not in bare.seen[0][0]["content"]
    assert not response.tool_calls[0].ok  # no tools registered: the call is refused
