"""Explicit publication from the existing subagent's private working scope."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.security.workspace_collaboration import WorkspaceCollaboration


class WorkspacePublishTool(Tool):
    _scopes = {"core", "subagent"}
    @property
    def name(self) -> str:
        return "workspace_publish"

    @property
    def description(self) -> str:
        return "Publish a private worker text artifact into shared workspace with revision checking."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
        "type": "object", "additionalProperties": False,
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"},
                       "expected_revision": {"type": "string"}},
        "required": ["source", "destination", "expected_revision"],
    }

    def __init__(self, workspace: Path):
        self.collaboration = WorkspaceCollaboration(workspace)

    @classmethod
    def create(cls, ctx: ToolContext) -> WorkspacePublishTool:
        return cls(Path(ctx.workspace))

    async def execute(self, **kwargs: Any) -> str:
        source, destination, expected_revision = (str(kwargs[k]) for k in ("source", "destination", "expected_revision"))
        request = current_request_context()
        if not request or request.responsibility_scope.closed:
            raise PermissionError("A live delegated execution is required")
        for execution in request.responsibility_scope.executions.values():
            child = execution.store.assert_owner(execution.claim)
            if child.delegation_id and child.parent_responsibility_id:
                parent = execution.store.get(child.parent_responsibility_id)
                if parent.execution_generation != child.parent_execution_generation:
                    raise PermissionError("Parent execution was superseded")
                return self.collaboration.publish(child.delegation_id, source, destination,
                                                  expected_revision=expected_revision)
        raise PermissionError("Publication requires a delegated worker identity")
