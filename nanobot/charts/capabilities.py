"""Safe capability manifest extracted from KLineChart 9.8.12 / Pro 0.1.1.

Bounded anchor overlays only; unbounded freehand anyWaves is excluded.
This is metadata, not copied executable library code.
"""
from __future__ import annotations

DRAWING_ANCHORS: dict[str, int] = {'fibonacciLine': 2, 'horizontalRayLine': 2, 'horizontalSegment': 2, 'horizontalStraightLine': 1, 'parallelStraightLine': 3, 'priceChannelLine': 3, 'priceLine': 1, 'rayLine': 2, 'segment': 2, 'straightLine': 2, 'verticalRayLine': 2, 'verticalSegment': 2, 'verticalStraightLine': 1, 'simpleAnnotation': 1, 'simpleTag': 1, 'arrow': 2, 'circle': 2, 'rect': 2, 'parallelogram': 3, 'triangle': 3, 'fibonacciCircle': 2, 'fibonacciSegment': 2, 'fibonacciSpiral': 2, 'fibonacciSpeedResistanceFan': 2, 'fibonacciExtension': 3, 'gannBox': 2, 'threeWaves': 4, 'fiveWaves': 6, 'eightWaves': 9, 'abcd': 4, 'xabcd': 5}

BUILTIN_DEFAULTS: dict[str, list[float]] = {'AVP': [], 'AO': [5.0, 34.0], 'BIAS': [6.0, 12.0, 24.0], 'BOLL': [20.0, 2.0], 'BRAR': [26.0], 'BBI': [3.0, 6.0, 12.0, 24.0], 'CCI': [20.0], 'CR': [26.0, 10.0, 20.0, 40.0, 60.0], 'DMA': [10.0, 50.0, 10.0], 'DMI': [14.0, 6.0], 'EMV': [14.0, 9.0], 'EMA': [6.0, 12.0, 20.0], 'MTM': [12.0, 6.0], 'MA': [5.0, 10.0, 30.0, 60.0], 'MACD': [12.0, 26.0, 9.0], 'OBV': [30.0], 'PVT': [], 'PSY': [12.0, 6.0], 'ROC': [12.0, 6.0], 'RSI': [6.0, 12.0, 24.0], 'SMA': [12.0, 2.0], 'KDJ': [9.0, 3.0, 3.0], 'SAR': [2.0, 2.0, 20.0], 'TRIX': [12.0, 9.0], 'VOL': [5.0, 10.0, 20.0], 'VR': [26.0, 6.0], 'WR': [6.0, 10.0, 14.0]}


def drawing_descriptors() -> list[dict[str, object]]:
    return [{"id": name, "display_name": name, "category": "semantic_overlay", "anchors": anchors,
             "anchor_coordinates": ["timestamp", "price"], "editable": True, "agent_compatible": True,
             "configuration": ["text", "visible", "locked"], "library": "klinecharts@9.8.12+pro@0.1.1"}
            for name, anchors in DRAWING_ANCHORS.items()]


def indicator_descriptors(query: str = "") -> list[dict[str, object]]:
    return [{"id": name, "name": name, "source": "BUILTIN", "version": "9.8.12",
             "pane": "main" if name in {"MA", "EMA", "BOLL", "SAR"} else "separate",
             "defaults": defaults, "parameters": [{"index": i, "type": "number", "default": value,
             "minimum": 0, "maximum": 512} for i, value in enumerate(defaults)]}
            for name, defaults in BUILTIN_DEFAULTS.items() if query.casefold() in name.casefold()]
