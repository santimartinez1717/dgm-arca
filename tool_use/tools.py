"""The tools Umbral's model can call, and the registries that group them.

* ``calculators.py``: the phase 1 rule engine as tools (acquisition cost, yields, maximum
  offer, legal rent cap, IRPF of the rental).
* ``portfolio.py``: the investor's portfolio in SQLite, a tool with state and an effect.
* ``public_data.py``: cadastre lookup, Euribor and IRAV, stressed zones and SERPAVI rents.

``calculator`` is the generic arithmetic tool from the course template. It is not in the
default registry: it exists for the ablation that gives the model arithmetic but no rules,
to measure how much of phase 1's failures were rules and how much arithmetic.
"""

from __future__ import annotations

import ast
import operator

from tool_use.calculators import CALCULATORS
from tool_use.portfolio import PORTFOLIO_TOOLS
from tool_use.public_data import PUBLIC_DATA_TOOLS
from tool_use.registry import ToolRegistry, tool

_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


@tool
def calculator(expression: str) -> float:
    """Evaluate an arithmetic expression such as '(12.5 * 3) / 2 - 1'.

    Only numbers, parentheses and the operators + - * / ** % are allowed.

    Args:
        expression: The arithmetic expression to evaluate.
    """

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](evaluate(node.operand))
        raise ValueError("unsupported expression")

    return float(evaluate(ast.parse(expression, mode="eval").body))


def default_registry() -> ToolRegistry:
    """The registry behind POST /tools and the phase 4 agent."""
    return ToolRegistry().register(*PUBLIC_DATA_TOOLS, *CALCULATORS, *PORTFOLIO_TOOLS)


def arithmetic_registry() -> ToolRegistry:
    """Ablation: only a generic calculator, so the model must still apply the rules itself."""
    return ToolRegistry().register(calculator)
