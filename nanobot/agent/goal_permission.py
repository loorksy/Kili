"""Turn-local permission for explicit sustained-goal mutations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from nanobot.bus.events import InboundMessage
from nanobot.session.automation_turns import automation_history_overrides
from nanobot.session.turn_continuation import internal_continuation_inbound

_GOAL_MUTATION_ALLOWED: ContextVar[bool] = ContextVar(
    "nanobot_goal_mutation_allowed",
    default=False,
)


def goal_mutation_allowed() -> bool:
    return _GOAL_MUTATION_ALLOWED.get()


def revoke_goal_mutation_permission() -> None:
    _GOAL_MUTATION_ALLOWED.set(False)


@contextmanager
def goal_mutation_permission(allowed: bool):
    """Bind goal permission for one agent-run or direct tool execution scope."""
    token = _GOAL_MUTATION_ALLOWED.set(allowed)
    try:
        yield
    finally:
        _GOAL_MUTATION_ALLOWED.reset(token)


class GoalInputScope(ExitStack):
    """Own goal authorization for fresh inputs consumed during one agent run."""

    def __init__(self, initial_message: InboundMessage | None = None) -> None:
        super().__init__()
        self._initial_message = initial_message

    def __enter__(self) -> GoalInputScope:
        super().__enter__()
        self.enter_context(goal_mutation_permission(False))
        if self._initial_message is not None:
            self.consume_inputs((self._initial_message,))
        return self

    def consume_inputs(self, messages: Iterable[InboundMessage]) -> None:
        """Authorize consumed user requests, never queued or replayed history."""
        if any(self._authorizes(message) for message in messages):
            self.enter_context(goal_mutation_permission(True))

    @staticmethod
    def _authorizes(message: InboundMessage) -> bool:
        if (
            not message.is_user_input
            or message.channel == "system"
            or message.sender_id == "subagent"
            or internal_continuation_inbound(message.metadata)
        ):
            return False
        _, automation_metadata = automation_history_overrides(message.metadata)
        if automation_metadata:
            return False
        # Fresh user intent only: neither stored history nor provider/tool text can grant this.
        return message.metadata.get("goal_requested") is True or persistent_request(message.content)


def persistent_request(content: str) -> bool:
    """Recognize explicit background intent; the model still resolves the schedule."""
    text = content.strip()
    return bool(re.search(
        r"^(?:please\s+)?(?:monitor\b|watch\b|remind me\b|notify me when\b|tell me when\b|"
        r"send me .+ (?:at |after |every )|every (?:morning|evening|day|week)\b|"
        r"راقب|راقبي|ذكرني|ذكّرني|أخبرني عندما|بلغني عندما|أرسل .+ (?:الساعة|بعد|كل))",
        text, re.IGNORECASE,
    ))
