"""Deterministic chart-only rasterizer; no browser, desktop or network access."""
from __future__ import annotations

import io
from bisect import bisect_left
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from nanobot.charts.controller import candle_time
from nanobot.charts.scene import ChartScene


def render_scene(scene: ChartScene, width: int = 1000, height: int = 640) -> bytes:
    if not 320 <= width <= 1600 or not 240 <= height <= 1200:
        raise ValueError("Chart image dimensions outside bounded limits")
    image = Image.new("RGB", (width, height), "#0f172a")
    draw = ImageDraw.Draw(image)
    # Ship the font so deployment does not depend on host fonts. Pillow's RAQM
    # layout shapes Arabic and resolves mixed RTL/LTR labels when available.
    draw.font = ImageFont.truetype(str(Path(__file__).parent / "assets" / "DejaVuSans.ttf"), 13)
    draw.text((20, 12), f"{scene.chart.canonical_instrument} / {scene.chart.timeframe} / OANDA", fill="white")
    data = scene.candles
    if not data:
        draw.text((20, 40), "No candles in requested viewport", fill="white")
    else:
        left, right, top = 55, width - 90 - scene.chart.right_spacing, 45
        separate = list(dict.fromkeys(s.instance_id for s in scene.series if s.pane == "separate"))
        pane_size = max(8, min(85, int((height - 100) * 0.35 / max(len(separate), 1))))
        bottom = height - 45 - len(separate) * pane_size
        low = min(float(c.low) for c in data)
        high = max(float(c.high) for c in data)
        for series in scene.series:
            if series.pane == "main":
                valid = [float(v) for v in series.values if v is not None]
                if valid:
                    low, high = min(low, min(valid)), max(high, max(valid))
        spread = max(high - low, abs(high) * 0.001, 0.01)
        low -= spread * 0.05
        high += spread * 0.05
        spread = high - low
        times = [candle_time(c) for c in data]

        def x(timestamp: int) -> float:
            index = bisect_left(times, timestamp)
            index = max(0, min(len(times) - 1, index))
            if index and abs(times[index - 1] - timestamp) <= abs(times[index] - timestamp):
                index -= 1
            return left + index / max(len(times) - 1, 1) * (right - left)

        def y(price: float) -> float:
            return max(-height * 4, min(height * 4, bottom - (price - low) / spread * (bottom - top)))

        for step in range(6):
            price = low + spread * step / 5
            pixel = y(price)
            draw.line((left, pixel, right, pixel), fill="#263449")
            draw.text((right + 8, pixel - 5), f"{price:.5f}", fill="#cbd5e1")
        bar = max(1.0, min(8.0, (right - left) / len(data) * 0.32))
        for candle in data:
            px = x(candle_time(candle))
            color = "#34d399" if candle.close >= candle.open else "#fb7185"
            draw.line((px, y(float(candle.high)), px, y(float(candle.low))), fill=color)
            y1, y2 = sorted((y(float(candle.open)), y(float(candle.close))))
            draw.rectangle((px - bar, y1, px + bar, max(y1 + 1, y2)), fill=color)
        for annotation in scene.chart.annotations:
            if not annotation.visible:
                continue
            points = [(x(p.timestamp if p.timestamp is not None else times[-1]), y(float(p.value))) for p in annotation.points]
            name = annotation.library_name or annotation.type
            color = "#fbbf24" if annotation.origin == "USER" else "#38bdf8"
            if name in {"horizontal_line", "horizontalStraightLine", "priceLine", "entry", "stop", "target"}:
                draw.line((left, points[0][1], right, points[0][1]), fill=color, width=2)
            elif name in {"verticalStraightLine"}:
                draw.line((points[0][0], top, points[0][0], bottom), fill=color, width=2)
            elif name in {"price_zone", "rect", "gannBox"} and len(points) == 2:
                xa, xb = sorted((points[0][0], points[1][0]))
                ya, yb = sorted((points[0][1], points[1][1]))
                draw.rectangle((xa, ya, xb, yb), outline=color, width=2)
            elif name in {"circle", "fibonacciCircle"} and len(points) == 2:
                xa, xb = sorted((points[0][0], points[1][0]))
                ya, yb = sorted((points[0][1], points[1][1]))
                draw.ellipse((xa, ya, xb, yb), outline=color, width=2)
            elif name in {"fibonacciLine", "fibonacciSegment", "fibonacciExtension"} and len(points) >= 2:
                for ratio in (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1):
                    level = points[0][1] + (points[1][1] - points[0][1]) * ratio
                    draw.line((points[0][0], level, points[1][0], level), fill=color)
                    draw.text((points[1][0], level), str(ratio), fill=color)
            elif len(points) > 1:
                draw.line(points, fill=color, width=2)
                # Complex library curves are explicitly identified as anchor previews.
                if name not in {"segment", "trend_line", "arrow", "threeWaves", "fiveWaves", "eightWaves", "abcd", "xabcd"}:
                    draw.text(points[0], name + " (anchors)", fill=color)
            else:
                px, py = points[0]
                draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=color)
            if annotation.text:
                draw.text(points[0], annotation.text[:100], fill=color)
        for series in scene.series:
            sy: Callable[[float], float]
            if series.pane == "main":
                sy = y
            else:
                pane = separate.index(series.instance_id)
                pane_top, pane_bottom = bottom + 5 + pane * pane_size, bottom + pane_size + pane * pane_size
                valid = [float(v) for v in series.values if v is not None]
                if not valid:
                    continue
                minimum, maximum = min(valid), max(valid)
                delta = max(maximum - minimum, 0.01)

                def pane_y(value: float, lower: float = minimum, size: float = delta,
                       start: int = pane_top, end: int = pane_bottom) -> float:
                    return end - (value - lower) / size * (end - start)

                sy = pane_y
                draw.text((left, pane_top), series.name, fill=series.color)
            run: list[tuple[float, float]] = []
            for candle, value in zip(data, series.values):
                if value is None:
                    if len(run) > 1:
                        draw.line(run, fill=series.color)
                    run = []
                    continue
                point = (x(candle_time(candle)), sy(float(value)))
                if series.kind in {"marker", "point", "circle"}:
                    draw.ellipse((point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3), fill=series.color)
                elif series.kind in {"bar", "histogram"}:
                    draw.line((point[0], sy(0), point[0], point[1]), fill=series.color, width=2)
                else:
                    run.append(point)
            if len(run) > 1:
                draw.line(run, fill=series.color)
        draw.text((left, height - 24), datetime.fromtimestamp(times[0] / 1000, timezone.utc).isoformat(), fill="#cbd5e1")
        draw.text((right - 150, height - 24), datetime.fromtimestamp(times[-1] / 1000, timezone.utc).isoformat(), fill="#cbd5e1")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()
