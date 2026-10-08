import re
from decimal import Decimal
from pathlib import Path

import pytest

from nanobot.charts.capabilities import DRAWING_ANCHORS
from nanobot.charts.state import Annotation, ChartActor, ChartPoint


@pytest.mark.parametrize("name,anchors", DRAWING_ANCHORS.items())
def test_supported_semantic_drawing_geometry(name, anchors):
    points = [ChartPoint(timestamp=1000 * (i + 1), value=i + 1) for i in range(anchors)]
    drawing = Annotation(id="annotation_" + "a" * 32, type="drawing", library_name=name,
                         points=points, created_by="nanobot")
    assert drawing.library_name == name
    with pytest.raises(ValueError):
        Annotation.model_validate({**drawing.model_dump(), "points": []})


def test_catalog_matches_actual_pinned_library():
    root = Path(__file__).parents[2] / "webui/node_modules"
    if not root.exists():
        pytest.skip("Pinned frontend dependencies not installed")
    source = (root / "klinecharts/dist/index.esm.js").read_text() + (root / "@klinecharts/pro/dist/klinecharts-pro.js").read_text()
    for name, count in DRAWING_ANCHORS.items():
        match = re.search(r'name: [\'\"]' + name + r'[\'\"][\s\S]{0,300}?totalStep: (\d+)', source)
        assert match and int(match[1]) == count + 1
    assert "anyWaves" not in DRAWING_ANCHORS


def test_user_drawing_cannot_be_overwritten_by_agent(workstation):
    service, _, actor, chart, _ = workstation
    chart.annotations.append(Annotation(id="annotation_" + "a" * 32, type="horizontal_line",
        points=[ChartPoint(value=100)], created_by=actor.principal, origin="USER"))
    user = ChartActor(principal=actor.principal, user_interaction=True)
    saved = service.update(chart, user, chart.revision)
    saved.annotations[0].points[0].value = Decimal(200)
    with pytest.raises(PermissionError, match="User drawings"):
        service.update(saved, actor, saved.revision)
    updated = service.update(saved, user, saved.revision)
    assert updated.annotations[0].points[0].value == 200


def test_old_annotation_provenance_is_conservative(workstation):
    service, _, actor, chart, _ = workstation
    raw = chart.model_dump(mode="json")
    raw["annotations"] = [{"id": "annotation_" + "c" * 32, "type": "note", "points": [{"value": "100"}], "created_by": actor.principal}]
    from nanobot.charts.state import CloudChart
    migrated = CloudChart.model_validate(raw)
    assert migrated.annotations[0].origin == "IMPORT"
    saved = service.update(migrated, ChartActor(principal=actor.principal, user_interaction=True), 0)
    saved.annotations = []
    with pytest.raises(PermissionError):
        service.update(saved, actor, saved.revision)


def test_explicit_user_permission_can_allow_agent_edit(workstation):
    service, _, actor, chart, _ = workstation
    user = ChartActor(principal=actor.principal, user_interaction=True)
    chart.annotations.append(Annotation(id="annotation_" + "d" * 32, type="note", points=[ChartPoint(value=100)], created_by=actor.principal, origin="USER"))
    saved = service.update(chart, user, chart.revision)
    saved.annotations[0].agent_editable = True
    with pytest.raises(PermissionError):
        service.update(saved, actor, saved.revision)
    allowed = service.update(saved, user, saved.revision)
    allowed.annotations[0].text = "User-authorized revision"
    result = service.update(allowed, actor, allowed.revision)
    assert result.annotations[0].text == "User-authorized revision"


def test_legacy_type_cannot_smuggle_an_unbounded_library_overlay():
    from nanobot.agent.tools.chart import ChartRequest
    with pytest.raises(ValueError):
        ChartRequest(operation="add_annotation", annotation_type="horizontal_line", drawing_name="anyWaves", points=[ChartPoint(value=100)])
    with pytest.raises(ValueError):
        Annotation(id="annotation_" + "e" * 32, type="horizontal_line", library_name="anyWaves", points=[ChartPoint(value=100)], created_by="model")
