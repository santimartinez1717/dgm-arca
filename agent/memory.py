"""Conversation memory with a token budget, and our policy for what to forget.

The context window is the agent's working memory, and stuffing it does not work: things in
the middle get lost. Our policy follows from the case file (``agent/case_file.py``):

* **The facts are never summarised.** Every figure the engine produced lives in the case file,
  which ``ReActAgent`` renders into the system prompt on every step: always at the top,
  always exact, never in the middle.
* **The task stays verbatim.** The first user message (``pin_first``) is never summarised:
  a paraphrase of "más de un 4,5 % neto después de impuestos" loses the criterion.
* **Old observations shrink before they are summarised.** A screening table or a passage of
  the BOE is long, and what mattered in it is already in the case file (figures) or cited by
  key ([K3]); the summary only has to keep what was done and decided.
* **The last ``keep_last`` messages stay whole**, so the model sees its latest results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ConversationMemory:
    system_prompt: str
    count_tokens: Callable[[str], int]
    token_budget: int = 6000
    keep_last: int = 6  # most recent messages that are never summarised
    pin_first: bool = True  # keep the first message (the task) verbatim
    old_observation_chars: int = 300  # tool results older than keep_last are cut to this
    messages: list[dict] = field(default_factory=list)
    summary: str = ""
    compressions: int = 0

    def add(self, role: str, content: str, **extra) -> None:
        self.messages.append({"role": role, "content": content, **extra})

    def tokens(self) -> int:
        text = self.system_prompt + self.summary + "".join(m["content"] for m in self.messages)
        return self.count_tokens(text)

    def over_budget(self) -> bool:
        return self.tokens() > self.token_budget

    def render(self, system_prompt: str | None = None) -> list[dict]:
        """Messages to send to the model: system (+ summary) followed by the live messages.

        ``system_prompt`` replaces the stored one for this call: the agent passes the prompt
        with the case file as it is now.
        """
        system = system_prompt if system_prompt is not None else self.system_prompt
        if self.summary:
            system += f"\n\nSummary of the earlier steps:\n{self.summary}"
        return [{"role": "system", "content": system}, *self.messages]

    def compress(self, summarize: Callable[[list[dict]], str]) -> bool:
        """If over budget, summarise everything between the task and the last messages.

        Returns True if a compression happened.
        """
        if not self.over_budget():
            return False
        head = self.messages[:1] if self.pin_first else []
        body = self.messages[len(head) :]
        if len(body) <= self.keep_last:
            return False
        old, recent = body[: -self.keep_last], body[-self.keep_last :]
        # A tool call and its result must not be split: start the recent part at a non-tool.
        while recent and recent[0]["role"] == "tool" and old:
            recent.insert(0, old.pop())
        if not old:
            return False
        shrunk = [self._shrink(m) for m in old]
        new_summary = summarize(shrunk)
        self.summary = f"{self.summary}\n{new_summary}".strip()
        self.messages = [*head, *recent]
        self.compressions += 1
        return True

    def _shrink(self, message: dict) -> dict:
        if message["role"] != "tool" or len(message["content"]) <= self.old_observation_chars:
            return message
        cut = message["content"][: self.old_observation_chars]
        return {**message, "content": f"{cut} […]"}
