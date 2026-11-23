"""The ReAct agent: Thought -> Action -> Observation, in a loop, with every tool we built.

This is where phases 1 to 3 meet (design in ``docs/fase4/diseno.md``, spec in
``docs/fase4/issues/11-bucle-react.md``). The brain is Qwen3-1.7B as is (``brain="base"``),
with the phase-1 adapter (``"rlm"``) or thinking (``"thinking"``); the hands are the phase-2
registry plus the case tools and ``search_knowledge_base``; the loop below is ours.

One run:

0. The case file of ``session_id`` is loaded (or created) and the CSV tables pasted in the
   task go into it deterministically (``agent.ingest``). The whole run happens inside
   ``with active(case)``, so the case tools find it with ``current()``.
1. Each step the system prompt is ``AGENT_SYSTEM_PROMPT`` plus the case file rendered *now*
   (anchored at the top, never lost in the middle). The task is the first, pinned message.
2. The brain answers with a thought and ``<tool_call>`` blocks. **Each tool call is a step**:
   ``n_steps == len(steps) <= max_steps``, the ``final_answer`` included.
3. Guardrails: a timeout per tool (a thread that runs the tool in a copy of the context),
   tool errors back as observations, the same call a second time gets a warning and a third
   time is not run, tools with an effect need ``confirm=True``, and a token budget per task
   (a nudge at 80 %, a fallback answer at 100 %).
4. ``final_answer`` (or plain text without a tool call, flagged in the thought) goes through
   the deterministic auditor; a rejected answer goes back as an observation, at most twice.
5. The case file is saved and the response carries the optional fields of issue 12.

The brain is anything with ``generate(messages, tools) -> (text, prompt_tokens,
completion_tokens)``: the tests use a scripted fake and load nothing.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agent import case_file
from agent.auditor import DISCLAIMER, AuditResult, audit
from agent.case_file import CaseFile, active
from agent.ingest import ingest
from agent.memory import ConversationMemory
from agent.prompts import AGENT_SYSTEM_PROMPT, BUDGET_NUDGE, SUMMARY_PROMPT
from agent.tools.case_tools import CASE_TOOLS
from agent.tools.knowledge import search_knowledge_base
from api.schemas import AgentAction, AgentResponse, AgentStep, ToolCallRecord
from tool_use.parser import ToolCall, format_tool_result, parse_tool_calls
from tool_use.registry import ToolRegistry, tool
from tool_use.tools import default_registry

log = logging.getLogger("arca.agent")


@tool
def final_answer(answer: str) -> str:
    """Return the final answer to the user and stop the loop.

    Write it in Spanish, with the figures exactly as the tools returned them, the levers, the
    assumptions and the open questions. It is checked before it reaches the user.

    Args:
        answer: The complete answer to the task.
    """
    return answer


# Phase-2 calculators that analyze_property already chains (and chains right: legal rent,
# ITP base, contract date). Offering both makes a 1.7B model pick the loose one.
OVERLAPPING_CALCULATORS = (
    "acquisition_cost",
    "rental_returns",
    "legal_rent_cap",
    "rental_income_tax",
)
PLAYBOOK_TOOLS = ("find_levers", "what_if")
MAX_REJECTIONS = 2  # rejected answers that go back to the loop; the third is delivered
LOOP_WARNING = (
    "\n\nWARNING: you already made this exact call and got this result. Do not repeat it: "
    "use the result, change the arguments, or call final_answer."
)
LOOP_STOP = (
    "NOT RUN: this is the third identical call. Its result is above. Call final_answer now "
    "with what you have."
)
TOOL_ERROR_HINT = (
    " Decide what to do: retry with other arguments, use another tool, or tell the user in "
    "final_answer that you could not get this."
)
# Appended to the last observation of every turn. Phase 2 measured that a hint here works
# where the system prompt does not: after reading English tool results the model answered
# Spanish questions in English, and it rarely wrote a thought before a native tool call.
TURN_HINT = (
    "\n\n[{left} of {total} steps left. In ONE message: a line 'Thought: ...' with what you "
    "know and what you need, then the tool call. Do not repeat a call you already made. "
    "When you have what the user asked for, call final_answer, in Spanish.]"
)
THOUGHT_ONLY = (
    "You wrote a thought but called no tool. Now make the tool call you described, or call "
    "final_answer with the answer for the user, in Spanish."
)
INVALID_ARGS_HINT = " If the user did not give a value, leave that argument out instead of 0."
NO_TOOL_CALL = "[sin final_answer: el texto se toma como respuesta] "
EMPTY_OUTPUT = "Your last message had no text and no tool call. Call a tool, or call final_answer."

# Extra tools of issues 02 and 03, registered when they exist (each lands in its own branch).
EXTRA_TOOL_MODULES = ("agent.tools.screening", "agent.tools.report")


# --------------------------------------------------------------------------- brains


class Brain(Protocol):
    name: str

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict] | None
    ) -> tuple[str, int, int]: ...


@dataclass
class HFBrain:
    """Qwen3 from the shared model (``api.shared_model``), with or without an adapter."""

    model_id: str
    adapter_path: str | None = None
    enable_thinking: bool = False
    max_new_tokens: int = 1024
    loaded: bool = False

    @property
    def name(self) -> str:
        suffix = f"+{Path(self.adapter_path).name}" if self.adapter_path else ""
        return f"{self.model_id}{suffix}" + (" (thinking)" if self.enable_thinking else "")

    def load(self) -> HFBrain:
        if self.loaded:
            return self
        from api.shared_model import get_model

        if self.adapter_path and not Path(self.adapter_path).exists():
            raise FileNotFoundError(
                f"brain adapter {self.adapter_path} not found: download the phase-1 adapter "
                "or set ARCA_AGENT_RLM_ADAPTER (docs/servir_api.md)"
            )
        self.shared = get_model(self.model_id)
        self.tokenizer = self.shared.tokenizer
        self.adapter = self.shared.add_adapter(self.adapter_path) if self.adapter_path else None
        self.loaded = True
        return self

    def count_tokens(self, text: str) -> int:
        self.load()
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict] | None
    ) -> tuple[str, int, int]:
        from api.shared_model import on_model_thread

        self.load()
        return on_model_thread(self._generate, messages, tools)

    def _generate(self, messages, tools) -> tuple[str, int, int]:
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=self.enable_thinking,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.shared.device)
        out = self.shared.generate(
            self.adapter,
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        prompt_tokens = inputs["input_ids"].shape[1]
        new_tokens = out[0, prompt_tokens:]
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        return text, int(prompt_tokens), int(new_tokens.shape[0])


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def brains_from_env() -> dict[str, HFBrain]:
    """The three brains of the spec: one Qwen3-1.7B, adapter and thinking per brain."""
    model = os.environ.get("ARCA_AGENT_MODEL", "Qwen/Qwen3-1.7B")
    adapter = os.environ.get("ARCA_AGENT_RLM_ADAPTER") or os.environ.get("ARCA_RLM_ADAPTER", "")
    max_new = _env_int("ARCA_AGENT_MAX_NEW_TOKENS", 1024)
    return {
        "base": HFBrain(model, max_new_tokens=max_new),
        "rlm": HFBrain(model, adapter_path=adapter or None, max_new_tokens=max_new),
        "thinking": HFBrain(
            os.environ.get("ARCA_THINKING_MODEL", model),
            enable_thinking=True,
            max_new_tokens=_env_int("ARCA_AGENT_THINKING_MAX_NEW_TOKENS", 2048),
        ),
    }


@dataclass
class FallbackBrain:
    """The base brain standing in for one that could not load; the name tells the user."""

    inner: Brain
    note: str

    @property
    def name(self) -> str:
        return f"{self.inner.name} [{self.note}]"

    def count_tokens(self, text: str) -> int:
        counter = getattr(self.inner, "count_tokens", None)
        return counter(text) if counter is not None else len(text) // 4

    def generate(self, messages, tools) -> tuple[str, int, int]:
        return self.inner.generate(messages, tools)


# Kept for readers of the spec: what each brain is, as configured right now.
BRAINS = {name: (lambda b=b: b.name) for name, b in brains_from_env().items()}


# --------------------------------------------------------------------------- registry


def build_registry(use_playbook: bool = True) -> ToolRegistry:
    """Phase-2 tools minus the overlapping calculators, plus the case tools, RAG and the end."""
    registry = default_registry()
    for name in OVERLAPPING_CALCULATORS:
        registry.tools.pop(name, None)
    case_tools = [t for t in CASE_TOOLS if use_playbook or t.name not in PLAYBOOK_TOOLS]
    registry.register(*case_tools, *extra_tools(), search_knowledge_base, final_answer)
    return registry


def extra_tools() -> list:
    """``TOOLS`` of the modules of issues 02 and 03 that are present in this checkout."""
    import importlib

    found = []
    for module in EXTRA_TOOL_MODULES:
        try:
            found.extend(importlib.import_module(module).TOOLS)
        except ModuleNotFoundError:
            continue
    return found


# --------------------------------------------------------------------------- one run


@dataclass
class _Run:
    """The state of one run: what the response reports and what the guardrails count."""

    task: str
    case: CaseFile
    brain: Brain
    max_steps: int
    confirm: bool
    steps: list[AgentStep] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    calls: Counter = field(default_factory=Counter)
    tokens: int = 0
    rejections: int = 0
    pending_thought: str = ""  # a "Thought:" without a call, for the next step's thought
    stuck: bool = False  # the same call a fourth time: the loop ends
    last_audit: AuditResult | None = None
    levers: list[dict[str, Any]] = field(default_factory=list)
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    # Every generation as the model saw and wrote it: the SFT data of issue 18.
    generations: list[dict[str, Any]] = field(default_factory=list)

    def step(self, thought: str, action: AgentAction | None, observation: str | None) -> None:
        self.steps.append(AgentStep(thought=thought, action=action, observation=observation))
        if os.environ.get("ARCA_AGENT_TRACE", "1") != "0":
            # A running process cannot be inspected on the DGX: the log is the only window.
            name = action.name if action else "(text)"
            args = json.dumps(action.arguments, ensure_ascii=False)[:120] if action else ""
            obs = " ".join((observation or "").split())[:160]
            print(
                f"  step {len(self.steps)}/{self.max_steps} · {self.tokens} tok · {name} {args}"
                f" -> {obs}",
                file=sys.stderr,
                flush=True,
            )

    @property
    def steps_left(self) -> int:
        return self.max_steps - len(self.steps)


@dataclass
class ReActAgent:
    registry: ToolRegistry = field(default_factory=build_registry)
    brains: dict[str, Brain] = field(default_factory=dict)
    token_budget: int = field(default_factory=lambda: _env_int("ARCA_AGENT_TOKEN_BUDGET", 100_000))
    context_budget: int = field(default_factory=lambda: _env_int("ARCA_AGENT_CONTEXT_TOKENS", 6000))
    tool_timeout: float = field(
        default_factory=lambda: float(os.environ.get("ARCA_AGENT_TOOL_TIMEOUT", "30"))
    )
    # Switches for the ablations of issue 06 (agent/evaluate.py sets them).
    audit: bool = True
    use_playbook: bool = True
    anchor_case_file: bool = True
    # The generations of the last run (messages shown and raw output), for agent.collect_traces.
    last_generations: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @classmethod
    def from_env(cls) -> ReActAgent:
        agent = cls(brains=brains_from_env())
        agent.load()
        return agent

    def load(self) -> None:
        """Load the base model (shared by the three brains) and warm up the retriever.

        The rlm adapter loads now if it is on disk and otherwise when ``brain="rlm"`` is
        asked for, with a clear error. Without warming the RAG up, the first search would
        build the index inside the tool timeout.
        """
        for name, brain in self.brains.items():
            if not hasattr(brain, "load"):
                continue
            try:
                brain.load()
            except FileNotFoundError as exc:
                log.warning("brain %s not loaded: %s", name, exc)
        try:
            from agent.tools.knowledge import _pipeline

            _pipeline()
        except Exception as exc:  # noqa: BLE001 - the agent works without RAG; the tool says so
            log.warning("knowledge base not loaded: %s", exc)

    def system_prompt(self, max_steps: int, case: CaseFile | None = None) -> str:
        prompt = AGENT_SYSTEM_PROMPT.format(max_steps=max_steps)
        if case is not None and self.anchor_case_file:
            prompt = f"{prompt}\n\n{case.render()}"
        return prompt

    def brain(self, name: str) -> Brain:
        """The brain asked for; ``base`` instead, flagged in its name, if it cannot load.

        ``brain="rlm"`` is the API's default and its adapter is a download of its own: a
        missing adapter answers with the base model and says so in ``model``, rather than
        failing the request with a 500.
        """
        if name not in self.brains:
            raise ValueError(f"unknown brain {name!r}; known: {sorted(self.brains)}")
        chosen = self.brains[name]
        try:
            if hasattr(chosen, "load"):
                chosen.load()
        except FileNotFoundError as exc:
            if name == "base" or "base" not in self.brains:
                raise
            log.warning("brain %s unavailable, using base: %s", name, exc)
            return FallbackBrain(self.brains["base"], f"{name} no disponible: responde base")
        return chosen

    def tool_definitions(self) -> list[dict]:
        return [t.definition for t in self._tools().values()]

    def _tools(self) -> dict:
        tools = self.registry.tools
        if self.use_playbook:
            return tools
        return {n: t for n, t in tools.items() if n not in PLAYBOOK_TOOLS}

    def _count_tokens(self, brain: Brain):
        counter = getattr(brain, "count_tokens", None)
        return counter if counter is not None else (lambda text: len(text) // 4)

    # ----------------------------------------------------------------------- the loop

    def run(
        self,
        task: str,
        max_steps: int = 10,
        brain: str = "rlm",
        session_id: str | None = None,
        confirm: bool = False,
    ) -> AgentResponse:
        model = self.brain(brain)
        case = case_file.load(session_id or uuid.uuid4().hex)
        ingested = ingest(task)
        for prop in ingested.properties:
            case.properties[prop.id] = prop
        for cell in ingested.bad_cells:
            case.ask(f"No he podido leer {cell} del CSV")
        state = _Run(task=task, case=case, brain=model, max_steps=max_steps, confirm=confirm)
        memory = ConversationMemory(
            self.system_prompt(max_steps), self._count_tokens(model), self.context_budget
        )
        memory.add("user", ingested.text)
        with active(case):
            try:
                return self._loop(state, memory)
            finally:
                self.last_generations = state.generations
                case_file.save(case)

    def _loop(self, state: _Run, memory: ConversationMemory) -> AgentResponse:
        tools = self.tool_definitions()
        while state.steps_left > 0:
            if state.tokens >= self.token_budget:
                return self._fallback(
                    state, f"se agotó el presupuesto de {self.token_budget} tokens"
                )
            messages = memory.render(self.system_prompt(state.max_steps, state.case))
            raw, prompt_tokens, completion_tokens = state.brain.generate(messages, tools)
            state.generations.append({"messages": messages, "raw": raw})
            state.tokens += prompt_tokens + completion_tokens
            parsed = parse_tool_calls(raw)
            thought = _thought(parsed.thinking, parsed.text)

            if not parsed.tool_calls:
                text = _strip_label(parsed.text)
                thought = _join(state.pending_thought, thought)
                if not text:
                    state.pending_thought = ""
                    state.step(thought, None, EMPTY_OUTPUT)
                    memory.add("assistant", "")
                    memory.add("user", EMPTY_OUTPUT)
                    continue
                labelled = parsed.text.strip().lower().startswith("thought:")
                if labelled and not state.pending_thought:
                    # "Thought: I need to call what_if" is an intention, not an answer: it is
                    # not a step (steps are tool calls) and becomes the next step's thought.
                    state.pending_thought = thought
                    memory.add("assistant", parsed.text)
                    memory.add("user", THOUGHT_ONLY)
                    continue
                state.pending_thought = ""
                response = self._finish(state, text, NO_TOOL_CALL + thought, None)
                if response is not None:
                    return response
                memory.add("assistant", parsed.text)
                memory.add("user", state.steps[-1].observation or "")
                continue

            ends = any(c.name == "final_answer" for c in parsed.tool_calls)
            if state.tokens >= self.token_budget and not ends:
                return self._fallback(
                    state, f"se agotó el presupuesto de {self.token_budget} tokens"
                )

            thought = _join(state.pending_thought, thought)
            state.pending_thought = ""
            done: list[tuple[ToolCall, str]] = []
            for i, call in enumerate(parsed.tool_calls):
                if state.steps_left <= 0:
                    break
                step_thought = thought if i == 0 else ""
                action = AgentAction(name=call.name or "<unparsed>", arguments=call.arguments)
                if call.error is not None:
                    observation = f"ERROR: {call.error}. Write the call as valid JSON."
                    state.step(step_thought, action, observation)
                    continue
                if call.name == "final_answer":
                    answer = call.arguments.get("answer", "")
                    answer = answer if isinstance(answer, str) else json.dumps(answer)
                    response = self._finish(state, answer, step_thought, action)
                    if response is not None:
                        return response
                    done.append((call, state.steps[-1].observation or ""))
                    break  # the model rewrites its answer before doing anything else
                observation = self._execute(state, call)
                state.step(step_thought, action, observation)
                done.append((call, observation))

            memory.add(
                "assistant",
                parsed.text,
                tool_calls=[
                    {"type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c, _ in done
                ],
            )
            for call, observation in done:
                memory.add("tool", observation, name=call.name)
            if not done:  # only unparseable calls: tell the model why nothing ran
                memory.add("user", state.steps[-1].observation or EMPTY_OUTPUT)
            if state.steps_left <= 1 or state.tokens >= 0.8 * self.token_budget:
                memory.messages[-1]["content"] += f"\n\n{BUDGET_NUDGE}"
            else:
                memory.messages[-1]["content"] += TURN_HINT.format(
                    left=state.steps_left, total=state.max_steps
                )
            if state.stuck:
                return self._fallback(state, "repetía la misma llamada sin avanzar")
            memory.compress(lambda old: self._summarize(state, old))
        return self._fallback(state, f"se agotaron los {state.max_steps} pasos")

    # ----------------------------------------------------------------------- tools

    def _execute(self, state: _Run, call: ToolCall) -> str:
        """Run one tool call through every guardrail; always an observation, never raises."""
        key = json.dumps([call.name, call.arguments], sort_keys=True, default=str)
        state.calls[key] += 1
        repeats = state.calls[key]
        if repeats >= 3:
            state.stuck = repeats >= 4
            return LOOP_STOP
        arguments, note = self._check_date(state, call)
        tool_ = self._tools().get(call.name)
        if tool_ is not None and tool_.requires_confirmation and not state.confirm:
            state.case.ask(
                f"¿Confirmas {call.name}? Repite la petición con confirm=true para ejecutarla."
            )
            return (
                f"NOT RUN: {call.name} has an effect and the user has not confirmed it. Tell the "
                "user what it would do and that they must confirm it (confirm=true)."
            )
        if tool_ is None:
            record = ToolCallRecord(
                name=call.name,
                arguments=call.arguments,
                ok=False,
                error=f"unknown tool '{call.name}'. Available: {sorted(self._tools())}",
            )
        else:
            record = self._call_with_timeout(call.name, arguments)
        if record.ok:
            observation = format_tool_result(call.name, record.result)
            self._collect(state, call.name, record.result)
        else:
            hint = INVALID_ARGS_HINT if record.error.startswith("invalid arguments") else ""
            observation = f"ERROR: {record.error}.{hint}{TOOL_ERROR_HINT}"
        observation += note
        if repeats == 2:
            observation += LOOP_WARNING
        state.observations.append(observation)
        return observation

    @staticmethod
    def _check_date(state: _Run, call: ToolCall) -> tuple[dict[str, Any], str]:
        """Drop an ``on_date`` the task never gave: the model invented 2023-01-01 and got the
        law of 2023 (EXPERIMENTS.md, 23/11/2026). A year in the task or a contract date in the
        case file keeps it."""
        arguments = call.arguments
        on = arguments.get("on_date") if call.name == "search_knowledge_base" else None
        if not on:
            return arguments, ""
        year = str(on)[:4]
        contracts = {
            str(p.contract_date.year) for p in state.case.properties.values() if p.contract_date
        }
        if year in state.task or year in contracts:
            return arguments, ""
        kept = {k: v for k, v in arguments.items() if k != "on_date"}
        return kept, (
            f"\n\n(on_date {on} ignored: the task gives no date in {year}, so this is today's "
            "law. Pass on_date only for a date the user wrote.)"
        )

    def _call_with_timeout(self, name: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """``registry.call`` in a thread that sees the active case file, with a deadline.

        A thread cannot be killed: a tool that times out keeps running in the background and
        its late result is dropped. The tools are short and idempotent, so that is harmless.
        """
        context = contextvars.copy_context()
        box: dict[str, ToolCallRecord] = {}

        def target() -> None:
            box["record"] = context.run(self.registry.call, name, arguments)

        thread = threading.Thread(target=target, name=f"arca-tool-{name}", daemon=True)
        thread.start()
        thread.join(self.tool_timeout)
        if thread.is_alive() or "record" not in box:
            return ToolCallRecord(
                name=name,
                arguments=arguments,
                ok=False,
                error=f"timeout: {name} did not answer in {self.tool_timeout:g} s",
                latency_ms=1000 * self.tool_timeout,
            )
        return box["record"]

    @staticmethod
    def _collect(state: _Run, name: str, result: Any) -> None:
        """Keep the levers and scenarios for the optional fields of the response."""
        if not isinstance(result, dict):
            return
        pid = result.get("property_id")
        if name == "find_levers":
            for group in ("applicable", "maybe", "traps_to_warn_about"):
                for lever in result.get(group, []):
                    state.levers.append({"property_id": pid, "group": group, **lever})
        elif name == "what_if":
            for scenario in result.get("scenarios", []):
                state.scenarios.append({"property_id": pid, **scenario})

    # ----------------------------------------------------------------------- the end

    def _finish(
        self, state: _Run, answer: str, thought: str, action: AgentAction | None
    ) -> AgentResponse | None:
        """Audit an answer: the response if it is delivered, None if it goes back to the loop."""
        case = state.case
        result = audit(
            answer,
            sources=[state.task, case.render(), *state.observations],
            figures=[f.value for f in case.figures],
            retrieved_ids=case.sources,
        )
        empty = not answer.strip()
        if empty:
            result.ok = False
        state.last_audit = result
        if not self.audit:
            state.step(thought, action, "Answer delivered (auditor disabled).")
            return self._response(state, answer, succeeded=bool(answer.strip()))
        if result.ok or state.rejections >= MAX_REJECTIONS:
            verdict = "Audit passed." if result.ok else "Audit failed again: delivered as is."
            state.step(thought, action, verdict)
            return self._response(state, result.answer, succeeded=result.ok)
        state.rejections += 1
        feedback = (
            "AUDIT REJECTED the final answer: it is empty. Call final_answer with the answer."
            if empty
            else result.feedback()
        )
        state.step(thought, action, feedback)
        return None

    def _fallback(self, state: _Run, reason: str) -> AgentResponse:
        answer = (
            f"No he podido terminar el análisis: {reason}. Esto es lo que el motor ha "
            f"calculado hasta ahora:\n\n{state.case.render()}\n\n{DISCLAIMER}"
        )
        return self._response(state, answer, succeeded=False)

    def _response(self, state: _Run, answer: str, succeeded: bool) -> AgentResponse:
        result = state.last_audit
        audit_info: dict[str, Any] = {"enabled": self.audit, "rejections": state.rejections}
        if result is not None:
            audit_info.update(
                ok=result.ok,
                unsupported_numbers=result.unsupported_numbers,
                unknown_citations=result.unknown_citations,
                disclaimer_added=result.disclaimer_added,
            )
        return AgentResponse(
            final_answer=answer,
            steps=state.steps,
            n_steps=len(state.steps),
            succeeded=succeeded,
            model=state.brain.name,
            tokens_used=state.tokens,
            session_id=state.case.session_id,
            case_file=state.case.render(),
            levers=state.levers,
            scenarios=state.scenarios,
            open_questions=list(state.case.open_questions),
            audit=audit_info,
        )

    # ----------------------------------------------------------------------- memory

    def _summarize(self, state: _Run, old: list[dict]) -> str:
        """Summary of the old messages, always with the base brain (same for every brain)."""
        summarizer = self.brains.get("base", state.brain)
        history = "\n".join(f"{m['role']}: {m['content']}" for m in old)
        prompt = [{"role": "user", "content": SUMMARY_PROMPT.format(history=history)}]
        text, prompt_tokens, completion_tokens = summarizer.generate(prompt, None)
        state.tokens += prompt_tokens + completion_tokens
        parsed = parse_tool_calls(text)
        return parsed.text.strip() or text.strip()


def _join(first: str, second: str) -> str:
    return "\n".join(t for t in (first.strip(), second.strip()) if t)


def _strip_label(text: str) -> str:
    """The answer without the "Thought:" label the hint asks the model to start with."""
    text = text.strip()
    if text.lower().startswith("thought:"):
        text = text[len("thought:") :].strip()
    return text


def _thought(thinking: str, text: str) -> str:
    text = text.strip()
    if text.lower().startswith("thought:"):
        text = text[len("thought:") :].strip()
    return f"{thinking.strip()}\n{text}".strip() if thinking.strip() else text
