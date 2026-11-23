"""Shared test setup.

POST /tools loads Qwen3-1.7B the first time it is called. In the tests that would mean
downloading 3.4 GB and generating on CPU, so the tool loop the API uses is replaced, for the
whole test session, by one driven by a scripted model.
"""

from __future__ import annotations

import json

import pytest


class ScriptedChatModel:
    """Calls ``get_rent_reference`` for the first message of a query, then answers."""

    name = "scripted-test-model"

    def generate(self, messages, tools):
        if messages[-1]["role"] == "user" and tools:
            payload = {"name": "get_rent_reference", "arguments": {"municipality": "Barcelona"}}
            return f"<tool_call>\n{json.dumps(payload)}\n</tool_call>"
        return "Barcelona es zona tensionada."


@pytest.fixture(autouse=True, scope="session")
def scripted_tool_loop(tmp_path_factory):
    from tool_use import executor

    previous = executor._loop
    executor._loop = executor.ToolLoop(model=ScriptedChatModel())
    yield executor._loop
    executor._loop = previous
