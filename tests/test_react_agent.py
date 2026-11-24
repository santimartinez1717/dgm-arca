"""The ReAct loop on CPU with a scripted brain: every guardrail of issue 11, no model loaded."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import pytest

from agent.react_agent import LOOP_STOP, NO_TOOL_CALL, ReActAgent, build_registry
from tool_use.registry import tool


def call(name: str, **arguments) -> str:
    return f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"


def answer(text: str) -> str:
    return call("final_answer", answer=text)


@dataclass
class ScriptedBrain:
    """Returns the outputs of ``script`` in order and remembers what it was shown."""

    script: list[str]
    name: str = "scripted"
    tokens: tuple[int, int] = (100, 20)
    seen: list[list[dict]] = field(default_factory=list)

    def generate(self, messages, tools):
        self.seen.append(messages)
        if not self.script:
            raise AssertionError("the brain was asked for more outputs than scripted")
        return self.script.pop(0), *self.tokens


@tool
def ping(n: int = 0) -> dict:
    """A local tool with no network, for the scripts.

    Args:
        n: Any number.
    """
    return {"pong": n}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_CASE_DB", str(tmp_path / "cases.sqlite"))
    monkeypatch.setenv("ARCA_PORTFOLIO_DB", str(tmp_path / "portfolio.sqlite"))


def make_agent(*script: str, **kwargs) -> tuple[ReActAgent, ScriptedBrain]:
    brain = ScriptedBrain(list(script))
    agent = ReActAgent(brains={"base": brain, "rlm": brain, "thinking": brain}, **kwargs)
    agent.registry.register(ping)
    return agent, brain


RECORD = call(
    "record_property",
    property_id="P1",
    municipality="Valencia",
    price=180000,
    monthly_rent=850,
)


def test_registry_has_the_right_tools():
    names = set(build_registry().tools)
    assert {"analyze_property", "find_levers", "what_if", "search_knowledge_base"} <= names
    assert {"final_answer", "record_property", "max_offer_price"} <= names
    assert not names & {"acquisition_cost", "rental_returns", "legal_rent_cap"}
    assert len(names) <= 16
    assert not {"find_levers", "what_if"} & set(build_registry(use_playbook=False).tools)


def test_full_run_records_analyzes_and_answers():
    agent, brain = make_agent(
        "Thought: save the facts\n" + RECORD,
        call("analyze_property", property_id="P1"),
        "Thought: done\n" + answer("Rentabilidad neta calculada por el motor."),
    )
    response = agent.run("Piso en Valencia de 180.000 € por 850 €/mes", max_steps=5, brain="base")
    assert response.succeeded
    assert response.n_steps == len(response.steps) == 3
    assert [s.action.name for s in response.steps] == [
        "record_property",
        "analyze_property",
        "final_answer",
    ]
    assert response.steps[0].thought == "save the facts"
    assert "net_yield_pct" in response.steps[1].observation
    assert "asesor" in response.final_answer  # disclaimer added by the auditor
    assert response.tokens_used == 3 * 120
    assert response.audit["ok"] and response.audit["rejections"] == 0
    # the case file is anchored in the system prompt, regenerated each step
    assert "P1" in brain.seen[2][0]["content"] and "net_yield_pct" in brain.seen[2][0]["content"]


def test_max_steps_is_respected_counting_parallel_calls():
    many = call("ping") + RECORD + call("analyze_property", property_id="P1")
    agent, _ = make_agent(many, many)
    response = agent.run("tarea", max_steps=2, brain="base")
    assert response.n_steps == len(response.steps) == 2
    assert not response.succeeded
    assert "pasos" in response.final_answer and "asesor" in response.final_answer.lower()
    assert response.steps[1].thought == ""  # only the first call of a generation has it


def test_tool_timeout_comes_back_as_an_observation():
    @tool
    def slow(seconds: float) -> str:
        """Sleep.

        Args:
            seconds: how long.
        """
        time.sleep(seconds)
        return "late"

    agent, _ = make_agent(call("slow", seconds=2), answer("No he podido obtenerlo."))
    agent.registry.register(slow)
    agent.tool_timeout = 0.2
    started = time.perf_counter()
    response = agent.run("tarea", max_steps=4, brain="base")
    assert time.perf_counter() - started < 1.5
    assert "timeout" in response.steps[0].observation
    assert response.succeeded


def test_broken_tool_is_an_observation_and_the_agent_goes_on():
    @tool
    def broken() -> str:
        """Always fails."""
        raise RuntimeError("503 Service Unavailable")

    agent, brain = make_agent(call("broken"), answer("El servicio no responde."))
    agent.registry.register(broken)
    response = agent.run("tarea", max_steps=4, brain="base")
    assert "ERROR" in response.steps[0].observation and "503" in response.steps[0].observation
    assert response.succeeded
    assert brain.seen[1][-1]["role"] == "tool" and "503" in brain.seen[1][-1]["content"]


def test_tool_sees_the_case_file_inside_its_thread():
    agent, _ = make_agent(RECORD, answer("Guardado."))
    response = agent.run("tarea", max_steps=3, brain="base")
    assert "saved" in response.steps[0].observation
    assert "P1" in response.case_file


def test_loop_is_detected_warned_and_stopped():
    rates = call("ping")
    agent, _ = make_agent(rates, rates, rates, answer("Hecho."))
    response = agent.run("tarea", max_steps=6, brain="base")
    obs = [s.observation for s in response.steps]
    assert "WARNING" not in obs[0]
    assert "WARNING" in obs[1]
    assert obs[2] == LOOP_STOP
    assert response.succeeded


def test_a_fourth_identical_call_ends_the_run():
    rates = call("ping")
    agent, _ = make_agent(rates, rates, rates, rates, answer("never reached"))
    response = agent.run("tarea", max_steps=8, brain="base")
    assert not response.succeeded
    assert response.n_steps == 4 and "misma llamada" in response.final_answer


def test_tool_with_an_effect_needs_confirmation():
    save = call("save_to_portfolio", property_id="P1", municipality="Valencia", price=180000)
    agent, _ = make_agent(save, answer("Pendiente de tu confirmación."))
    response = agent.run("Guárdalo en mi cartera", max_steps=3, brain="base")
    assert response.steps[0].observation.startswith("NOT RUN")
    assert any("confirm=true" in q for q in response.open_questions)


def test_auditor_rejects_then_accepts():
    agent, brain = make_agent(
        RECORD,
        call("analyze_property", property_id="P1"),
        answer("La rentabilidad neta es del 7,77 %."),  # invented
        answer("Con los datos del motor, mira el expediente."),
    )
    response = agent.run("Piso en Valencia", max_steps=6, brain="base")
    assert response.succeeded
    assert response.audit["rejections"] == 1
    rejected = response.steps[2]
    assert rejected.action.name == "final_answer" and "AUDIT REJECTED" in rejected.observation
    assert "7,77" in rejected.observation
    assert "AUDIT REJECTED" in brain.seen[3][-1]["content"]


def test_auditor_delivers_the_third_failed_answer():
    bad = answer("Te dará un 9,99 % neto.")
    agent, _ = make_agent(bad, bad, bad)
    response = agent.run("tarea", max_steps=6, brain="base")
    assert not response.succeeded
    assert response.audit["rejections"] == 2 and response.audit["ok"] is False
    assert response.n_steps == 3


def test_auditor_off_for_the_ablation():
    agent, _ = make_agent(answer("Te dará un 9,99 % neto."), audit=False)
    response = agent.run("tarea", max_steps=3, brain="base")
    assert response.succeeded
    assert response.audit == {
        "enabled": False,
        "rejections": 0,
        "ok": False,
        "unsupported_numbers": ["9,99 %"],
        "unknown_citations": [],
        "disclaimer_added": True,
    }


def test_text_without_final_answer_is_taken_and_flagged():
    agent, _ = make_agent("No puedo predecir el precio de la vivienda dentro de cinco años.")
    response = agent.run("¿Cuánto valdrá en 2031?", max_steps=3, brain="base")
    assert response.succeeded
    assert response.n_steps == 1
    assert response.steps[0].thought.startswith(NO_TOOL_CALL)
    assert response.steps[0].action is None


def test_a_labelled_thought_without_a_call_is_not_an_answer():
    agent, brain = make_agent(
        "Thought: I need to call ping.",
        call("ping"),
        "Thought: still thinking.",
        "Thought: the answer is pong.",
    )
    response = agent.run("tarea", max_steps=6, brain="base")
    # the thought is not a step: it is the thought of the next tool call
    assert response.steps[0].action.name == "ping"
    assert response.steps[0].thought == "I need to call ping."
    # two thoughts in a row: the second one is taken as the answer, flagged
    assert response.n_steps == 2
    assert response.steps[1].thought.startswith(NO_TOOL_CALL + "still thinking.")
    assert response.final_answer.startswith("the answer is pong.")
    assert "called no tool" in brain.seen[1][-1]["content"]


def test_invalid_arguments_suggest_leaving_them_out():
    agent, _ = make_agent(call("ping", n="mucho"), answer("Hecho."))
    response = agent.run("tarea", max_steps=3, brain="base")
    assert "leave that argument out" in response.steps[0].observation


def test_token_budget_nudges_then_cuts():
    rates = call("ping")
    analyze = call("ping", n=2)
    agent, brain = make_agent(rates, analyze, rates, token_budget=250)
    response = agent.run("tarea", max_steps=10, brain="base")
    assert not response.succeeded
    assert "presupuesto" in response.final_answer
    assert response.tokens_used >= 250
    # after the first step (120 of 250 tokens) no nudge; after the second (240 ≥ 80 %) a nudge
    assert "running out" not in brain.seen[1][-1]["content"]
    assert "running out" in brain.seen[2][-1]["content"]
    assert response.n_steps == 2  # the third generation (360 tokens) is cut, not run


def test_no_playbook_switch_hides_the_lever_tools():
    agent, _ = make_agent(call("find_levers", property_id="P1"), answer("Sin palancas."))
    agent.use_playbook = False
    assert "find_levers" not in {d["function"]["name"] for d in agent.tool_definitions()}
    response = agent.run("tarea", max_steps=3, brain="base")
    assert "unknown tool" in response.steps[0].observation


def test_flat_memory_switch_drops_the_case_file_from_the_system_prompt():
    agent, brain = make_agent(RECORD, answer("Guardado."), anchor_case_file=False)
    agent.run("tarea", max_steps=3, brain="base")
    assert "CASE FILE" not in brain.seen[1][0]["content"]


def test_case_file_persists_between_runs_of_a_session():
    agent, brain = make_agent(RECORD, answer("Guardado."), answer("Sigue ahí."))
    first = agent.run("Piso en Valencia", max_steps=3, brain="base", session_id="s1")
    second = agent.run("¿Y el piso de antes?", max_steps=3, brain="base", session_id="s1")
    assert first.session_id == second.session_id == "s1"
    assert "P1: municipality=Valencia" in brain.seen[2][0]["content"]
    assert "P1" in second.case_file


def test_csv_in_the_task_goes_to_the_case_file():
    task = "Analiza:\nid;municipio;precio;renta\nA;Valencia;180000;850\nB;Madrid;250000;1100\n"
    agent, brain = make_agent(answer("Dos pisos cargados."))
    response = agent.run(task, max_steps=2, brain="base")
    assert "A:" in response.case_file and "B:" in response.case_file
    user = brain.seen[0][1]["content"]
    assert "2 pisos cargados" in user and "250000" not in user


def test_memory_is_compressed_with_the_base_brain():
    brain = ScriptedBrain([call("ping", n=i) for i in range(6)] + [answer("Hecho.")])
    summarizer = ScriptedBrain(["Se hicieron seis consultas."] * 6, name="summarizer")
    agent = ReActAgent(brains={"base": summarizer, "rlm": brain}, context_budget=10)
    agent.registry.register(ping)
    response = agent.run("tarea", max_steps=10, brain="rlm")
    assert summarizer.seen, "the base brain wrote the summary"
    assert "Summary of the earlier steps" in brain.seen[-1][0]["content"]
    assert brain.seen[-1][1]["content"] == "tarea"  # the task stays pinned
    assert response.tokens_used == 120 * (len(brain.seen) + len(summarizer.seen))


def test_a_missing_rlm_adapter_answers_with_base_and_says_so():
    class Unloadable(ScriptedBrain):
        def load(self):
            raise FileNotFoundError("brain adapter rlm/weights/grpo2_lora not found")

    base = ScriptedBrain([answer("Hecho.")], name="Qwen3-1.7B")
    agent = ReActAgent(brains={"base": base, "rlm": Unloadable([], name="rlm")})
    response = agent.run("tarea", max_steps=2, brain="rlm")
    assert response.succeeded
    assert response.model == "Qwen3-1.7B [rlm no disponible: responde base]"


def test_an_invented_on_date_is_dropped_and_a_given_one_kept(monkeypatch):
    seen = []

    @tool
    def search_knowledge_base(query: str, on_date: str | None = None) -> str:
        """Fake search.

        Args:
            query: q.
            on_date: d.
        """
        seen.append(on_date)
        return "[K1] pasaje"

    search = call("search_knowledge_base", query="ITP Madrid", on_date="2023-01-01")
    agent, _ = make_agent(search, answer("Hecho."))
    agent.registry.register(search_knowledge_base)
    response = agent.run("¿Qué ITP pago en Madrid?", max_steps=3, brain="base")
    assert seen == [None] and "on_date 2023-01-01 ignored" in response.steps[0].observation

    agent, _ = make_agent(search, answer("Hecho."))
    agent.registry.register(search_knowledge_base)
    agent.run("Firmé el contrato en marzo de 2023, ¿qué ley aplica?", max_steps=3, brain="base")
    assert seen == [None, "2023-01-01"]
