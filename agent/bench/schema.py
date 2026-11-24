"""Schema of a line of the phase 4 benchmark (``agent/bench/tasks.jsonl``).

It extends ``example_tasks.jsonl``: every new field is optional, so the course's two example
lines still validate. ``agent/evaluate.py::run_check`` evaluates the ``check`` field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BENCH = Path(__file__).with_name("tasks.jsonl")

CATEGORIES = (
    "screening",
    "lever",
    "inconsistent",
    "large_holder",
    "law_on_date",
    "kb_plus_tool",
    "grey_or_illegal",
    "impossible",
    "broken_tool",
)

# The tools of the agent registry (docs/fase4/issues/11-bucle-react.md, "Registro"): the
# phase 2 calculators that overlap with analyze_property are not in it.
AGENT_TOOLS = frozenset(
    {
        "record_property",
        "record_investor",
        "analyze_property",
        "screen_properties",
        "max_offer_price",
        "find_levers",
        "what_if",
        "search_knowledge_base",
        "lookup_property",
        "get_market_rates",
        "get_rent_reference",
        "get_portfolio",
        "save_to_portfolio",
        "write_investment_report",
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Contains(_Strict):
    type: Literal["contains"]
    value: str


class NotContains(_Strict):
    type: Literal["not_contains"]
    value: str | list[str]


class Regex(_Strict):
    type: Literal["regex"]
    value: str


class Number(_Strict):
    type: Literal["number"]
    value: float
    tolerance: float = Field(0.0, ge=0)


class Abstains(_Strict):
    type: Literal["abstains"]
    no_figures: bool = False  # also reject any figure in € or %


class AllOf(_Strict):
    type: Literal["all"]
    checks: list[Check] = Field(min_length=1)


class AnyOf(_Strict):
    type: Literal["any"]
    checks: list[Check] = Field(min_length=1)


Check = Annotated[
    Contains | NotContains | Regex | Number | Abstains | AllOf | AnyOf,
    Field(discriminator="type"),
]
AllOf.model_rebuild()
AnyOf.model_rebuild()


class PortfolioRow(_Strict):
    """A dwelling the evaluator saves to a fresh portfolio before running the task."""

    label: str
    municipality: str
    stressed_zone: bool | None = None
    purchase_price: float | None = None
    monthly_rent: float | None = None
    area_m2: float | None = None


class Setup(_Strict):
    portfolio: list[PortfolioRow] = []


class BenchTask(_Strict):
    id: str | None = None
    category: Literal[CATEGORIES] | None = None  # type: ignore[valid-type]
    task: str = Field(min_length=10)
    required_tools: list[str] = []
    check: Check
    setup: Setup | None = None
    break_tool: str | None = None  # tool the evaluator replaces by a broken one (issue 06)
    break_mode: Literal["error", "timeout"] | None = None
    notes: str | None = None
    figures: dict[str, Any] = {}  # the engine's figures behind the check (build_bench.py)

    @model_validator(mode="after")
    def _consistent(self) -> BenchTask:
        unknown = set(self.required_tools) - AGENT_TOOLS
        if unknown and self.category is not None:
            raise ValueError(f"unknown tools: {sorted(unknown)}")
        if (self.break_tool is None) != (self.break_mode is None):
            raise ValueError("break_tool and break_mode go together")
        if self.break_tool and self.break_tool not in self.required_tools:
            raise ValueError("the broken tool must be one of the required tools")
        return self


def load_bench(path: Path = BENCH) -> list[BenchTask]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [BenchTask.model_validate(json.loads(line)) for line in lines if line.strip()]
