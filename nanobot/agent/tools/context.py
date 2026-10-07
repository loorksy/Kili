"""Runtime context for tool construction."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.agent.tools.file_state import FileStates
    from nanobot.agent.tools.runtime_control import RuntimeControl
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ProviderConfig, ToolsConfig
    from nanobot.cron.service import CronService
    from nanobot.providers.factory import ProviderSnapshot
    from nanobot.security.workspace_access import WorkspaceSandboxStatus
    from nanobot.session.manager import SessionManager
    from nanobot.session.responsibilities import ExecutionClaim, ResponsibilityStore
    from nanobot.utils.llm_runtime import LLMRuntime

_CURRENT_REQUEST_CONTEXT: ContextVar["RequestContext | None"] = ContextVar(
    "nanobot_tool_request_context",
    default=None,
)


@dataclass(frozen=True)
class ResponsibilityExecution:
    store: ResponsibilityStore
    claim: ExecutionClaim
    foreground: bool = True


@dataclass
class ResponsibilityExecutionScope:
    executions: dict[str, ResponsibilityExecution] = field(default_factory=dict)
    closed: bool = False


def finish_responsibility_executions(ctx: RequestContext, *, uncertain: bool = False) -> None:
    scope = ctx.responsibility_scope
    if scope.closed:
        return
    try:
        for execution in scope.executions.values():
            if execution.foreground:
                execution.store.finish(execution.claim, uncertain=uncertain)
    finally:
        # Retain immutable claims: late callbacks cannot acquire fresh ownership.
        scope.closed = True


@dataclass(frozen=True)
class RequestContext:
    """Per-request context injected into tools at message-processing time."""
    channel: str
    chat_id: str
    message_id: str | None = None
    session_key: str | None = None
    original_user_text: str | None = None
    runtime: LLMRuntime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sender_id: str | None = None
    turn_id: str | None = None
    workspace: Path | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    log_content: bool = True
    # The host can consume completion messages after this request returns.
    can_receive_background_results: bool = True
    persist_session: bool = True
    # Backend-only capabilities, never part of model-visible metadata.
    responsibility_scope: ResponsibilityExecutionScope = field(default_factory=ResponsibilityExecutionScope)


@runtime_checkable
class ContextAware(Protocol):
    def set_context(self, ctx: RequestContext) -> None:
        ...


def bind_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _CURRENT_REQUEST_CONTEXT.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _CURRENT_REQUEST_CONTEXT.reset(token)


@contextmanager
def request_context(ctx: RequestContext):
    """Bind one immutable request snapshot and restore the previous value."""
    # Reusing an adapter snapshot starts a new host-owned turn, not a refresh
    # inside an old running callback. Existing active claims remain unchanged.
    if ctx.responsibility_scope.closed:
        ctx = replace(ctx, responsibility_scope=ResponsibilityExecutionScope())
    token = bind_request_context(ctx)
    try:
        yield ctx
    finally:
        try:
            finish_responsibility_executions(ctx, uncertain=sys.exc_info()[0] is not None)
        finally:
            reset_request_context(token)


def current_request_context() -> RequestContext | None:
    return _CURRENT_REQUEST_CONTEXT.get()


def tool_log_content_allowed() -> bool:
    """Whether diagnostics may include content from the current tool request."""
    ctx = current_request_context()
    return ctx is None or ctx.log_content


def current_request_session_key() -> str | None:
    ctx = current_request_context()
    return ctx.session_key if ctx else None


@dataclass
class ToolContext:
    config: ToolsConfig
    workspace: str
    bus: MessageBus | None = None
    subagent_manager: SubagentManager | None = None
    cron_service: CronService | None = None
    exec_session_manager: ExecSessionManager | None = None
    sessions: SessionManager | None = None
    file_state_store: FileStates | None = None
    provider_snapshot_loader: Callable[..., ProviderSnapshot] | None = None
    image_generation_provider_configs: dict[str, ProviderConfig] | None = None
    timezone: str = "UTC"
    workspace_sandbox: WorkspaceSandboxStatus | None = None
    runtime_control: RuntimeControl | None = None
