"""Schema of the lever playbook (``levers.yaml``): what a "truco" of the wise guy looks like.

A lever is a change to the case that the law allows (or that people try although it does
not) and that changes what the investment returns. Each one says *when* it applies
(``applies_when``, predicates on the case file), *what* it changes in the engine's inputs
(``engine.set``, or nothing for a qualitative lever), and *where the law says so*
(``evidence``, a literal quote of the phase-3 corpus, checked by ``tests/test_playbook.py``).

Values in ``applies_when`` and ``engine.set`` may refer to the case instead of being
constants: ``"$property.price"``, ``"$property.previous_rent*0.94"``, or one of the named
values computed by ``agent.levers`` (``"$max_offer_price"``, ``"$cheapest_itp_region"``).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from agent.case_file import InvestorProfile, Property

PLAYBOOK_PATH = Path(__file__).parent / "levers.yaml"

Op = Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "is_null", "not_null"]
Level = Literal["legal", "grey", "illegal_warning"]

NAMED_VALUES = {"$max_offer_price", "$cheapest_itp_region"}
REFERENCE = re.compile(r"^\$(property|profile)\.(\w+)(?:\*([0-9.]+))?$")
# A figure in the explanation would be a number the engine did not produce.
FIGURE = re.compile(r"\d[\d.,]*\s*(%|€|euros|por ciento)", re.IGNORECASE)


def check_path(path: str) -> str:
    """``property.<field>`` or ``profile.<field>``, with a field that exists."""
    scope, _, name = path.partition(".")
    model = {"property": Property, "profile": InvestorProfile}.get(scope)
    if model is None or name not in model.model_fields:
        raise ValueError(f"{path!r} is not property.<field> or profile.<field> of the case file")
    return path


def check_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$") and value not in NAMED_VALUES:
        match = REFERENCE.match(value)
        if match is None:
            raise ValueError(f"{value!r}: use $property.<field>[*factor] or {NAMED_VALUES}")
        check_path(f"{match.group(1)}.{match.group(2)}")
    return value


class Condition(BaseModel):
    field: str
    op: Op
    value: Any = None

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        return check_path(value)

    @field_validator("value")
    @classmethod
    def _value(cls, value: Any) -> Any:
        return check_value(value)


class Engine(BaseModel):
    set: dict[str, Any] = Field(min_length=1)

    @field_validator("set")
    @classmethod
    def _paths(cls, value: dict[str, Any]) -> dict[str, Any]:
        for path, v in value.items():
            check_path(path)
            check_value(v)
        return value


class Evidence(BaseModel):
    source: str
    section: str | None = None
    quote: str = Field(min_length=20)


class Lever(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    level: Level
    title: str
    applies_when: list[Condition] = Field(default_factory=list)
    engine: Engine | None = None
    evidence: Evidence
    risk: str | None = None
    explanation: str

    @model_validator(mode="after")
    def _consistent(self) -> Lever:
        if self.level != "legal" and not self.risk:
            raise ValueError(f"{self.id}: a {self.level} lever must say its risk")
        if self.level == "illegal_warning" and self.engine is not None:
            raise ValueError(f"{self.id}: an illegal lever is never simulated (engine: null)")
        if FIGURE.search(self.explanation):
            raise ValueError(f"{self.id}: no figures in the explanation, what_if computes them")
        return self

    @property
    def quantified(self) -> bool:
        return self.engine is not None


def parse_levers(data: Any) -> list[Lever]:
    levers = [Lever.model_validate(item) for item in data or []]
    ids = [lever.id for lever in levers]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise ValueError(f"duplicated lever ids: {sorted(duplicated)}")
    return levers


@functools.cache
def load_levers(path: Path = PLAYBOOK_PATH) -> tuple[Lever, ...]:
    """Every lever of the playbook, validated. Cached: the file does not change at runtime."""
    return tuple(parse_levers(yaml.safe_load(Path(path).read_text(encoding="utf-8"))))
