"""Controlled visual chart perception with a structured-only model fallback."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.chart import current_chart_actor
from nanobot.agent.tools.context import ToolContext
from nanobot.charts.render import render_scene
from nanobot.charts.scene import build_scene
from nanobot.charts.state import ChartService
from nanobot.utils.helpers import build_image_content_blocks


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_id: str
    format: Literal["structured", "image"] = "structured"
    width: int = Field(default=1000, ge=320, le=1600)
    height: int = Field(default=640, ge=240, le=1200)


class ChartSnapshotTool(Tool):
    _scopes = {"core", "subagent"}

    def __init__(self, ctx: ToolContext):
        self.service = ChartService()

    @property
    def name(self) -> str:
        return "chart_snapshot"

    @property
    def description(self) -> str:
        return "Inspect the current cloud chart scene and exact metadata. Use format=image only with an image-capable model; structured works with all models. Renders only cached chart data, drawings and indicators, with no browser. Complex curves use labeled anchor previews; exact prices come from inspect_candle."

    @property
    def parameters(self) -> dict[str, Any]:
        return SnapshotRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.charts_enabled

    @classmethod
    def create(cls, ctx: ToolContext) -> ChartSnapshotTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str | list[dict[str, Any]]:
        request = SnapshotRequest.model_validate(kwargs)
        actor = current_chart_actor()
        chart = self.service.get(request.chart_id, actor)
        scene = await asyncio.to_thread(build_scene, chart, actor)
        if request.format == "structured":
            return scene.model_dump_json()
        raw = await asyncio.to_thread(render_scene, scene, request.width, request.height)
        return build_image_content_blocks(raw, "image/png", "", json.dumps(scene.metadata()))
