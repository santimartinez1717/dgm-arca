"""The contrast of phase 4: smolagents' ``CodeAgent`` with the same tools, model and bench.

CodeAct (Wang et al., 2024) says that writing Python as the action, instead of one JSON tool
call per step, needs fewer steps and succeeds more on tasks that chain tools. Our bench has
the ideal case for it, fifteen flats where a ``for`` loop replaces fifteen calls. This module
puts a ``CodeAgent`` in the same conditions as our JSON agent, so only the action format
changes:

* **the same tools**: every ``tool_use.registry.Tool`` of the agent registry, wrapped as a
  smolagents ``Tool`` (``RegistryTool``) that calls through the registry, so arguments are
  validated the same way, errors read the same, and ``evaluate.broken`` can break one;
* **the same model**: the shared Qwen3-1.7B (``api.shared_model``) behind a smolagents
  ``Model``, with the brain's adapter or thinking mode;
* **the same case file**: the CSV of the task is ingested before the loop and the run happens
  inside ``agent.case_file.active``, so ``analyze_property`` and friends see the flats;
* **the same ``max_steps``** and the same per-tool timeout (``ARCA_AGENT_TOOL_TIMEOUT``).

The result is an ``AgentResponse``-like dict that ``agent/evaluate.py`` scores with the same
checks: one step per code action, plus ``tool_calls`` (the tools the code called) and
``code_errors`` (actions whose code failed). ``smolagents`` is only imported here (the
``agent`` extra)::

    uv run python -m agent.evaluate --agent code --brains base thinking
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from smolagents import CodeAgent, Model, Tool
from smolagents.models import ChatMessage, MessageRole, get_clean_message_list
from smolagents.monitoring import TokenUsage

from agent import case_file as cf
from agent.ingest import extract_properties
from tool_use.registry import Tool as RegistryToolSpec
from tool_use.registry import ToolRegistry

# Phase 2 calculators that overlap with analyze_property: the JSON agent's registry drops
# them too (docs/fase4/issues/11-bucle-react.md, "Registro").
OVERLAPPING = ("acquisition_cost", "rental_returns", "legal_rent_cap", "rental_income_tax")

JSON_TYPES = {"string", "boolean", "integer", "number", "array", "object", "null"}
THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def agent_registry() -> ToolRegistry:
    """The tools of the JSON agent, without its ``final_answer`` (smolagents has its own).

    It is the loop's own ``build_registry`` (issue 20) when the loop is in this checkout, so
    both agents always see the same tools, including screen_properties and
    write_investment_report when they exist. Before that, the same rule written here.
    """
    try:
        from agent.react_agent import build_registry
    except ImportError:
        build_registry = None
    if build_registry is not None:
        registry = build_registry()
        registry.tools.pop("final_answer", None)
        return registry

    from agent.tools.case_tools import CASE_TOOLS
    from agent.tools.knowledge import search_knowledge_base
    from tool_use.tools import default_registry

    registry = default_registry()
    for name in OVERLAPPING:
        registry.tools.pop(name, None)
    return registry.register(*CASE_TOOLS, search_knowledge_base)


# --------------------------------------------------------------------------- tools


def _input_spec(name: str, prop: dict[str, Any], required: bool) -> dict[str, Any]:
    """One JSON Schema property as a smolagents input: type, description, nullable."""
    options = prop.get("anyOf") or [prop]
    types = [o.get("type") for o in options if o.get("type") in JSON_TYPES]
    nullable = "null" in types or not required
    types = [t for t in types if t != "null"] or ["any"]
    spec: dict[str, Any] = {
        "type": types[0] if len(types) == 1 else "any",
        "description": prop.get("description") or name.replace("_", " "),
    }
    if nullable:
        spec["nullable"] = True
    return spec


def tool_timeout() -> float:
    return float(os.environ.get("ARCA_AGENT_TOOL_TIMEOUT", "30"))


class RegistryTool(Tool):
    """A tool of our registry seen by smolagents. Calls go through the registry at call time."""

    output_type = "object"
    skip_forward_signature_validation = True

    def __init__(self, spec: RegistryToolSpec, registry: ToolRegistry, calls: list[dict]):
        schema = spec.definition["function"]["parameters"]
        required = set(schema.get("required", []))
        self.name = spec.name
        self.description = spec.description
        self.inputs = {
            arg: _input_spec(arg, prop, arg in required)
            for arg, prop in schema.get("properties", {}).items()
        }
        self.registry = registry
        self.calls = calls  # shared log of the run: what the code actually called
        self.case = None  # set by the runner: smolagents runs the code in another thread
        super().__init__()

    def forward(self, **kwargs: Any) -> Any:
        arguments = {k: v for k, v in kwargs.items() if v is not None}
        record = _call_with_timeout(self.registry, self.name, arguments, tool_timeout(), self.case)
        self.calls.append({"name": self.name, "arguments": arguments, "ok": record["ok"]})
        if not record["ok"]:
            # The code sees an exception, like any Python call that fails.
            raise RuntimeError(record["error"])
        return record["result"]


def _call_with_timeout(
    registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
    timeout: float,
    case: Any = None,
) -> dict[str, Any]:
    """registry.call in a thread that sees the case file; a timeout is an error.

    ``case`` is activated explicitly: the context variable of ``agent.case_file.active`` does
    not survive the thread in which smolagents executes the code.
    """
    box: dict[str, Any] = {}
    context = contextvars.copy_context()

    def call() -> Any:
        if case is None:
            return registry.call(name, arguments)
        with cf.active(case):
            return registry.call(name, arguments)

    def target() -> None:
        box["record"] = context.run(call)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return {"ok": False, "result": None, "error": f"{name} timed out after {timeout:g} s"}
    record = box["record"]
    return {"ok": record.ok, "result": record.result, "error": record.error}


# --------------------------------------------------------------------------- model

BRAIN_SETTINGS = {
    "base": {"adapter": None, "thinking": False},
    "rlm": {"adapter": "rlm", "thinking": False},
    "thinking": {"adapter": None, "thinking": True},
}


def model_id() -> str:
    return os.environ.get("ARCA_AGENT_MODEL") or os.environ.get(
        "ARCA_RLM_BASE_MODEL", "Qwen/Qwen3-1.7B"
    )


def rlm_adapter() -> str | None:
    return os.environ.get("ARCA_AGENT_RLM_ADAPTER") or os.environ.get("ARCA_RLM_ADAPTER")


class SharedModel(Model):
    """A smolagents ``Model`` over our chat model: same weights, adapter and thinking mode.

    ``chat`` is anything with ``generate(messages, tools) -> str`` (``HFChatModel`` on the
    GPU, a scripted model in the tests) and optionally a ``tokenizer`` to count tokens.
    """

    def __init__(self, chat: Any, name: str = "shared"):
        super().__init__(model_id=name)
        self.chat = chat

    def _count(self, text: str) -> int:
        tokenizer = getattr(self.chat, "tokenizer", None)
        if tokenizer is None:
            return len(text.split())
        return len(tokenizer(text)["input_ids"])

    def generate(
        self,
        messages: list[ChatMessage | dict],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        clean = get_clean_message_list(
            messages,
            role_conversions={
                MessageRole.TOOL_RESPONSE: MessageRole.USER,
                MessageRole.TOOL_CALL: MessageRole.ASSISTANT,
            },
            flatten_messages_as_text=True,
        )
        text = self.chat.generate(clean, None)
        visible = THINK.sub("", text)
        for stop in stop_sequences or []:
            if stop in visible:
                visible = visible[: visible.index(stop)]
        prompt = "\n".join(str(m["content"]) for m in clean)
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=visible,
            raw=text,
            token_usage=TokenUsage(
                input_tokens=self._count(prompt), output_tokens=self._count(text)
            ),
        )


def load_chat(brain: str) -> Any:
    """The shared HF model for a brain (on the GPU), as the JSON agent uses it."""
    from tool_use.executor import HFChatModel

    settings = BRAIN_SETTINGS[brain]
    adapter = rlm_adapter() if settings["adapter"] else None
    if settings["adapter"] and not adapter:
        raise RuntimeError("brain='rlm' needs ARCA_AGENT_RLM_ADAPTER or ARCA_RLM_ADAPTER")
    return HFChatModel(
        model_id(), adapter_path=adapter, enable_thinking=settings["thinking"]
    ).load()


# --------------------------------------------------------------------------- runner


@dataclass
class CodeAgentRunner:
    """Runs a task with ``CodeAgent`` and returns it in the shape of ``AgentResponse``."""

    registry: ToolRegistry = field(default_factory=agent_registry)
    chat_for: Any = load_chat  # brain -> chat model; replaced by a scripted one in tests
    _models: dict[str, SharedModel] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> CodeAgentRunner:
        return cls()

    def model(self, brain: str) -> SharedModel:
        if brain not in self._models:
            self._models[brain] = SharedModel(self.chat_for(brain), name=f"{model_id()}:{brain}")
        return self._models[brain]

    def run(
        self,
        task: str,
        max_steps: int = 10,
        brain: str = "base",
        session_id: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        case = cf.load(session_id) if session_id else cf.CaseFile(session_id=uuid.uuid4().hex)
        properties, text = extract_properties(task)
        for prop in properties:
            case.properties[prop.id] = prop
        if properties:
            text += "\n(The flats are in the case file: pass their ids to the tools.)"
        calls: list[dict] = []
        tools = [
            RegistryTool(spec, self.registry, calls)
            for spec in self.registry.tools.values()
            if confirm or not spec.requires_confirmation
        ]
        for tool in tools:
            tool.case = case
        agent = CodeAgent(tools=tools, model=self.model(brain), max_steps=max_steps)
        with cf.active(case):
            result = agent.run(text, max_steps=max_steps, return_full_result=True)
        cf.save(case)
        return to_response(result, agent, calls, case, brain)


def to_response(result: Any, agent: Any, calls: list[dict], case: Any, brain: str) -> dict:
    """smolagents' memory as our trace: one step per code action."""
    from smolagents.memory import ActionStep

    steps, code_errors = [], 0
    for step in agent.memory.steps:
        if not isinstance(step, ActionStep):
            continue
        output = step.model_output or ""
        if isinstance(output, list):
            output = " ".join(str(o) for o in output)
        thought = output.split("<code>")[0].strip() if step.code_action else output.strip()
        observation = step.observations
        if step.error is not None:
            code_errors += 1
            observation = f"ERROR: {step.error}"
        steps.append(
            {
                "thought": thought,
                "action": {"name": "python", "arguments": {"code": step.code_action}}
                if step.code_action
                else None,
                "observation": observation,
            }
        )
    usage = result.token_usage
    answer = result.output
    return {
        "final_answer": answer if isinstance(answer, str) else json.dumps(answer, default=str),
        "steps": steps,
        "n_steps": len(steps),
        "succeeded": result.state == "success",
        "model": f"CodeAgent · {model_id()} · {brain}",
        "tokens_used": (usage.input_tokens + usage.output_tokens) if usage else 0,
        "session_id": case.session_id,
        "open_questions": list(case.open_questions),
        "tool_calls": calls,
        "code_errors": code_errors,
    }
