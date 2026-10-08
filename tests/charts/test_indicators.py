from decimal import Decimal

import pytest

from nanobot.charts.indicators import (
    CustomIndicator,
    IndicatorDefinition,
    IndicatorRegistry,
    evaluate,
)
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore


def swing_definition():
    return IndicatorDefinition.model_validate({"name": "Confirmed swings", "nodes": [
        {"op": "input", "field": "high"}, {"op": "swing_high", "inputs": [0], "window": 3, "offset": 3},
        {"op": "input", "field": "low"}, {"op": "swing_low", "inputs": [2], "window": 3, "offset": 3}],
        "outputs": [{"name": "high", "node": 1, "kind": "marker"}, {"name": "low", "node": 3, "kind": "marker"}]})


def test_confirmed_swing_does_not_look_ahead(workstation):
    *_, data = workstation
    values = [1, 2, 3, 10, 4, 3, 2, 1]
    data = [c.model_copy(update={"high": Decimal(v), "low": -Decimal(v)}) for c, v in zip(data, values)]
    output = evaluate(swing_definition(), data)
    assert output["high"][:6] == [None] * 6
    assert output["high"][6] == 10
    assert evaluate(swing_definition(), data[:6])["high"] == output["high"][:6]
    assert evaluate(swing_definition(), []) == {"high": [], "low": []}


def test_immutable_version_and_private_access(tmp_path):
    records = RecordStore("indicators", CustomIndicator, ActionStore(tmp_path / "state.db"))
    registry = IndicatorRegistry(records)
    definition = swing_definition()
    first = registry.register(definition, "websocket:main")
    assert registry.register(definition, "websocket:main", family_id=first.family_id).id == first.id
    updated = definition.model_copy(deep=True)
    updated.nodes[1].offset = 4
    second = registry.register(updated, "websocket:main", family_id=first.family_id)
    assert second.indicator_version == 2
    assert registry.get(first.id, first.author).definition.nodes[1].offset == 3
    assert IndicatorRegistry(records).get(second.id, first.author).definition_hash != first.definition_hash
    with pytest.raises(PermissionError):
        registry.get(first.id, "websocket:other")
    with pytest.raises(PermissionError):
        registry.register(definition, "websocket:other", family_id=first.family_id)
    published = registry.register(updated, first.author, family_id=first.family_id, scope="SHARED")
    assert published.indicator_version == 3
    assert registry.get(published.id, "websocket:other").scope == "SHARED"
    with pytest.raises(PermissionError):
        registry.get(second.id, "websocket:other")


@pytest.mark.parametrize("change", [
    {"op": "javascript", "value": "fetch('secret')"},
    {"op": "mean", "window": 100000, "inputs": [0]},
    {"op": "constant", "value": "NaN"},
    {"op": "add", "inputs": [99, 0]},
    {"op": "input", "path": "/etc/passwd"},
    {"op": "parameter", "parameter": "missing"},
])
def test_unsafe_or_invalid_definition_is_rejected(change):
    with pytest.raises(ValueError):
        IndicatorDefinition.model_validate({"name": "Unsafe", "nodes": [change], "outputs": [{"name": "x", "node": 0}]})


def test_bounded_work_and_safe_zero_division(workstation):
    *_, data = workstation
    definition = IndicatorDefinition.model_validate({"name": "Test", "nodes": [{"op": "input"}, {"op": "constant"}, {"op": "divide", "inputs": [0, 1]}], "outputs": [{"name": "ratio", "node": 2}]})
    assert evaluate(definition, data)["ratio"] == [None] * len(data)
    with pytest.raises(ValueError, match="5000"):
        evaluate(definition, data * 51)
    costly = IndicatorDefinition.model_validate({"name": "Bounded", "nodes": [{"op": "input"}] + [{"op": "mean", "inputs": [0], "window": 512} for _ in range(63)], "outputs": [{"name": "x", "node": 1}]})
    with pytest.raises(ValueError, match="budget"):
        evaluate(costly, data)


def test_conditional_output_can_mask_markers_with_missing_series(workstation):
    *_, data = workstation
    definition = IndicatorDefinition.model_validate({"name": "Masked", "nodes": [
        {"op": "constant", "value": "1"}, {"op": "input", "field": "high"}, {"op": "missing"},
        {"op": "choose", "inputs": [0, 1, 2]}], "outputs": [{"name": "point", "node": 3, "kind": "marker"}]})
    assert evaluate(definition, data)["point"] == [c.high for c in data]
    definition.nodes[0].value = Decimal(0)
    assert evaluate(definition, data)["point"] == [None] * len(data)
