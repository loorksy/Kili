"""Controlled visual chart perception with a structured-only model fallback."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.chart import current_chart_actor
from nanobot.agent.tools.context import ToolContext
from nanobot.charts.render import render_scene
from nanobot.charts.scene import build_scene
from nanobot.charts.state import ChartService
from nanobot.utils.artifacts import generated_image_tool_result, store_generated_image_artifact
from nanobot.utils.helpers import build_image_content_blocks


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_id: str
    format: Literal["structured", "image", "attachment"] = "structured"
    width: int = Field(default=1000, ge=320, le=1600)
    height: int = Field(default=640, ge=240, le=1200)


class ChartSnapshotTool(Tool):
    action_class = "read"
    _scopes = {"core", "subagent"}

    def __init__(self, ctx: ToolContext):
        self.service = ChartService()

    @property
    def name(self) -> str:
        return "chart_snapshot"

    @property
    def description(self) -> str:
        return "Inspect or export the current KLineChart Pro cloud chart. When the user asks for a chart picture, use format=attachment: it saves a PNG and returns artifact paths; call message with those paths in media to send it. No vision model or image-generation provider is needed. Use format=image for internal vision inspection or structured for exact metadata. The isolated chart-only exporter has no browsing or network access."

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
        if request.format == "attachment":
            artifact = await asyncio.to_thread(
                store_generated_image_artifact,
                "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
                prompt=f"Chart snapshot: {chart.canonical_instrument} / {chart.timeframe}; chart {chart.id}; revision {chart.revision}",
                model="klinechart-pro-export", provider="nanobot", save_dir="charts",
            )
            return generated_image_tool_result([artifact])
        return build_image_content_blocks(raw, "image/png", "", json.dumps(scene.metadata()))
