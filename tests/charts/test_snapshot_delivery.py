import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageFont, features

from nanobot.agent.tools.chart_snapshot import ChartSnapshotTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.charts.render import render_scene
from nanobot.charts.scene import build_scene
from nanobot.charts.state import Annotation, ChartPoint
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import ToolsConfig


async def test_requested_picture_becomes_real_attachment_without_vision_or_image_provider(workstation, tmp_path, monkeypatch):
    charts, controller, actor, chart, _ = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda **_scope: controller.cache)
    bus = MessageBus()
    config = ToolsConfig(restrict_to_workspace=True)
    assert not config.image_generation.enabled
    ctx = ToolContext(config=config, workspace=str(tmp_path / "workspace"), bus=bus)
    snapshot = ChartSnapshotTool(ctx)
    snapshot.service = charts
    registry = ToolRegistry()
    registry.register(snapshot)
    registry.register(MessageTool.create(ctx))
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        result = await registry.execute("chart_snapshot", {"chart_id": chart.id, "format": "attachment"})
        assert isinstance(result, str), result
        artifact = json.loads(result)["artifacts"][0]
        path = Path(artifact["path"])
        assert path.is_relative_to(get_media_dir()) and path.suffix == ".png"
        assert Image.open(io.BytesIO(path.read_bytes())).size == (1000, 640)
        sent = await registry.execute("message", {"content": "صورة الشارت", "media": [str(path)]})
        assert not getattr(sent, "is_error", False), sent
    outbound = await bus.consume_outbound()
    assert outbound.channel == "websocket" and outbound.chat_id == "main"
    assert outbound.media == [str(path)]
    assert charts.get(chart.id, actor).revision == chart.revision


async def test_snapshot_scope_denial_cannot_export_another_private_chart(workstation, tmp_path):
    charts, _, _, chart, _ = workstation
    tool = ChartSnapshotTool(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)))
    tool.service = charts
    with request_context(RequestContext(channel="websocket", chat_id="other", session_key="websocket:other")):
        with pytest.raises(PermissionError):
            await tool.execute(chart_id=chart.id, format="attachment")


def test_bundled_font_arabic_shaping_and_deterministic_picture(workstation, monkeypatch):
    _, controller, actor, chart, _ = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda **_scope: controller.cache)
    chart.annotations.append(Annotation(id="annotation_" + "a" * 32, type="horizontal_line",
        points=[ChartPoint(value="110")], created_by=actor.principal, text="منطقة شراء — الهدف ١٢٠"))
    scene = build_scene(chart, actor)
    raw = render_scene(scene)
    assert raw == render_scene(scene)
    font_path = Path(__file__).parents[2] / "nanobot/charts/assets/DejaVuSans.ttf"
    font = ImageFont.truetype(str(font_path), 13)
    assert bytes(font.getmask("ش")) != bytes(font.getmask("\ufffd"))
    if features.check("raqm"):
        assert font.layout_engine == ImageFont.Layout.RAQM
    chart.annotations[0].text = "Buy zone"
    assert render_scene(build_scene(chart, actor)) != raw
