"""Let group members talk. The tool cannot move mandates or approvals."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agents.roster import AgentRoster


class _Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_agent_id: str = Field(pattern=r"^agent_[a-f0-9]{32}$")
    message: str = Field(min_length=1, max_length=4000)


class AgentGroupTool(Tool):
    action_class = "local"

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    @property
    def name(self) -> str:
        return "group_message"

    @property
    def description(self) -> str:
        return ("Send a message to another agent in this group and hand them the next reply. "
                "This does not transfer a mandate, approval, account, or trade authority.")

    @property
    def parameters(self) -> dict[str, Any]:
        return _Handoff.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None and ctx.bus is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> AgentGroupTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str:
        request = _Handoff.model_validate(kwargs)
        context = current_request_context()
        if context is None or not context.session_key or self.ctx.sessions is None or self.ctx.bus is None:
            raise PermissionError("Group messages require an active conversation")
        return await AgentRoster(self.ctx.sessions).handoff(
            context.session_key, dict(context.metadata), request.target_agent_id, request.message, self.ctx.bus,
        )
