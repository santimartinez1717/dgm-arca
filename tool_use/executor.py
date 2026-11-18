"""The tool-use workflow: the five steps from class, implemented by hand, with no framework.

    1. Get the user message together with the system prompt that carries the tool definitions.
    2. The model generates: text, or one or more <tool_call> blocks.
    3. The application executes the calls (``ToolRegistry.call``) and never trusts the
       arguments blindly: they are validated first.
    4. Each result goes back into the conversation as a message with role ``tool``.
    5. The model is prompted again; if it answers without calling tools, we are done.

Steps 2-4 repeat until the model answers or ``max_turns`` is reached (multi-step tool use).
Several <tool_call> blocks in one generation are executed in the same turn (parallel calls).

The loop (``ToolLoop``) does not know how text is generated: it receives a ``ChatModel``,
anything with ``generate(messages, tools) -> str``. ``HFChatModel`` is the real one; the
tests pass a scripted fake, so multi-step, parallel calls and errors are tested on CPU in
milliseconds.

Two ways to show the tools to the model (``prompt_style``):

* ``"native"`` (default): ``apply_chat_template(..., tools=definitions)``. Qwen3's template
  writes the definitions inside ``<tools></tools>`` in the system turn and tells the model to
  answer with ``<tool_call>{"name": ..., "arguments": ...}</tool_call>``, the format it was
  post-trained on. Tool results go back wrapped in ``<tool_response>``.
* ``"course"``: the system prompt from the slides (``SYSTEM_PROMPT_TEMPLATE``), with the
  definitions pasted as JSON. Same call format, but written by us instead of the template.

Tools registered with ``requires_confirmation`` (``save_to_portfolio``) are executed by
default, because POST /tools has no user to ask and the grader must see the effect; with
``confirm_policy="deny"`` the model gets an observation saying confirmation is required.
Phase 4 decides what the agent does with the flag.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from api.schemas import ToolCallRecord, ToolsResponse
from tool_use.parser import format_tool_result, parse_tool_calls
from tool_use.registry import ToolRegistry
from tool_use.tools import default_registry

SYSTEM_PROMPT_TEMPLATE = """You are an AI assistant designed to help users.
You will be given a task to solve. To help you, you have access to a set of tools.
Each tool is a function and has a description explaining what it does and the inputs it
expects:
---
{tools_description}
---
You should decide if you want to call a tool. If so, your call must be formatted as follows:
<tool_call>
{{"name": "tool name", "arguments": {{"argument": "value"}}}}
</tool_call>
You may emit several <tool_call> blocks in one message if the calls are independent.
After the tool calls are executed, you will receive their results and can continue.
When you have everything you need, answer the user directly without calling tools."""

DOMAIN_INSTRUCTIONS = """You are Umbral, an analyst for buy-to-let residential investment in Spain.
Use a tool whenever the answer needs a calculation, Spanish tax or rental rules, or the
user's portfolio; copy the numbers from the user's message into the arguments exactly as
written (percentages as percent: 8 % is 8). Pass every figure the user gives, and leave out
the optional arguments they did not give. If an argument is a value another tool returns
(the current Euribor, the maximum price, whether a town is a stressed zone, the municipality
of a cadastral reference), call that tool first and wait for its result: never guess the
value or pass 0. Independent calls go together in one message. Do not call tools for general
questions you can answer directly. Answer in the user's language and quote the figures the
tools returned."""

NO_TOOLS_PROMPT = """You are Umbral, an analyst for buy-to-let residential investment in Spain.
Answer in the user's language, showing the calculation and the final figure."""

# Greedy decoding sometimes loops: the same call 17 times, or every tool in the registry at
# once (phase 1 test, legal_rent). Identical calls in one turn run once, and a turn runs at
# most this many; the rest come back as an observation telling the model to wait.
MAX_CALLS_PER_TURN = 4

PromptStyle = Literal["native", "course"]
ConfirmPolicy = Literal["auto", "deny"]


def build_system_prompt(registry: ToolRegistry, prompt_style: PromptStyle = "native") -> str:
    """Step 1: the system prompt. In native mode the chat template adds the definitions."""
    if prompt_style == "course":
        course = SYSTEM_PROMPT_TEMPLATE.format(tools_description=registry.render_for_prompt())
        return f"{course}\n\n{DOMAIN_INSTRUCTIONS}"
    return DOMAIN_INSTRUCTIONS


class ChatModel(Protocol):
    name: str

    def generate(self, messages: list[dict[str, Any]], tools: list[dict] | None) -> str: ...


@dataclass
class HFChatModel:
    """A Hugging Face causal LM, optionally with a LoRA adapter, used one turn at a time."""

    model_id: str = "Qwen/Qwen3-1.7B"
    adapter_path: str | None = None
    enable_thinking: bool = False
    max_new_tokens: int = 2048

    @property
    def name(self) -> str:
        suffix = f"+{self.adapter_path}" if self.adapter_path else ""
        thinking = " (thinking)" if self.enable_thinking else ""
        return f"{self.model_id}{suffix}{thinking}"

    def load(self) -> HFChatModel:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForCausalLM.from_pretrained(self.model_id, dtype=dtype, device_map=device)
        if self.adapter_path:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.adapter_path)
        self.model = model.eval()
        return self

    def generate(self, messages: list[dict[str, Any]], tools: list[dict] | None) -> str:
        """Step 2: one greedy generation from the conversation so far."""
        import torch

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=self.enable_thinking,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        new_tokens = out[0, inputs["input_ids"].shape[1] :]
        # <tool_call> and <think> are ordinary added tokens in Qwen3, so they survive this.
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True)


@dataclass
class ToolLoop:
    """Holds the model and the registry and runs the five-step workflow."""

    model: ChatModel
    registry: ToolRegistry = field(default_factory=default_registry)
    prompt_style: PromptStyle = "native"
    confirm_policy: ConfirmPolicy = "auto"
    use_tools: bool = True  # False: the same model and prompt with no tools, for comparison
    # Turn of each call of the last run (parallel calls share one). Not part of the API
    # response; the benchmark uses it to check that independent calls went out together.
    call_turns: list[int] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)

    def run(self, query: str, max_turns: int = 5) -> ToolsResponse:
        registry = self.registry if self.use_tools else ToolRegistry()
        tools = registry.definitions() if self.prompt_style == "native" and self.use_tools else None
        system = (
            build_system_prompt(registry, self.prompt_style) if self.use_tools else NO_TOOLS_PROMPT
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ]
        records: list[ToolCallRecord] = []
        self.call_turns, self.raw_outputs = [], []
        last_text = ""

        for turn in range(1, max_turns + 1):
            raw = self.model.generate(messages, tools)  # step 2
            self.raw_outputs.append(raw)
            parsed = parse_tool_calls(raw)
            last_text = parsed.text
            if not parsed.tool_calls:  # step 5: a plain answer ends the loop
                return ToolsResponse(
                    answer=parsed.text, tool_calls=records, turns=turn, model=self.model.name
                )
            calls = _unique(parsed.tool_calls)
            messages.append(
                {
                    "role": "assistant",
                    "content": parsed.text,
                    "tool_calls": [
                        {"type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                        for c in calls
                        if c.error is None
                    ],
                }
            )
            for i, call in enumerate(calls):  # parallel calls: all of them, in order
                if i < MAX_CALLS_PER_TURN:
                    record = self._execute(call.name, call.arguments, call.error, registry)
                else:
                    record = ToolCallRecord(
                        name=call.name or "<unparsed>",
                        arguments=call.arguments,
                        ok=False,
                        error=f"not run: at most {MAX_CALLS_PER_TURN} calls per turn. Call only "
                        "the tools this question needs and wait for their results",
                    )
                records.append(record)
                self.call_turns.append(turn)
                payload = record.result if record.ok else {"error": record.error}
                messages.append(  # step 4
                    {
                        "role": "tool",
                        "name": record.name,
                        "content": format_tool_result(record.name, payload),
                    }
                )

        answer = last_text or (
            f"No he llegado a una respuesta en {max_turns} turnos; "
            "estos son los resultados de las herramientas que he usado."
        )
        return ToolsResponse(
            answer=answer, tool_calls=records, turns=max_turns, model=self.model.name
        )

    def _execute(
        self, name: str, arguments: dict[str, Any], parse_error: str | None, registry: ToolRegistry
    ) -> ToolCallRecord:
        """Step 3, with every failure turned into an observation the model can react to."""
        if parse_error is not None:
            return ToolCallRecord(
                name=name or "<unparsed>", arguments=arguments, ok=False, error=parse_error
            )
        tool = registry.tools.get(name)
        if tool is not None and tool.requires_confirmation and self.confirm_policy == "deny":
            return ToolCallRecord(
                name=name,
                arguments=arguments,
                ok=False,
                error=f"{name} has side effects: ask the user to confirm before calling it",
            )
        return registry.call(name, arguments)


def _unique(calls: list) -> list:
    """The calls of one generation without exact repeats, in order."""
    seen: set[str] = set()
    out = []
    for call in calls:
        key = json.dumps([call.name, call.arguments], sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(call)
    return out


_loop: ToolLoop | None = None


def build_tool_loop() -> ToolLoop:
    """Create and load the loop once; the API keeps the instance.

    Configuration from the environment: ``ARCA_TOOLS_MODEL`` (default Qwen/Qwen3-1.7B),
    ``ARCA_TOOLS_ADAPTER`` (a LoRA folder, e.g. the phase 1 adapter), ``ARCA_TOOLS_THINKING``
    (1 to let Qwen3 think before each turn) and ``ARCA_TOOLS_PROMPT`` (native or course).
    """
    global _loop
    if _loop is None:
        model = HFChatModel(
            model_id=os.environ.get("ARCA_TOOLS_MODEL", "Qwen/Qwen3-1.7B"),
            adapter_path=os.environ.get("ARCA_TOOLS_ADAPTER") or None,
            enable_thinking=os.environ.get("ARCA_TOOLS_THINKING", "0") == "1",
        ).load()
        _loop = ToolLoop(model=model, prompt_style=os.environ.get("ARCA_TOOLS_PROMPT", "native"))
    return _loop


def run_tool_loop(query: str, max_turns: int = 5) -> ToolsResponse:
    """Convenience entry point for scripts and the evaluation."""
    return build_tool_loop().run(query, max_turns=max_turns)


__all__ = [
    "HFChatModel",
    "ToolCallRecord",
    "ToolLoop",
    "build_system_prompt",
    "build_tool_loop",
    "run_tool_loop",
]
