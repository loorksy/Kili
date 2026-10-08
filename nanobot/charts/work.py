"""Bounded ephemeral analysis objects. Never authoritative runtime/chart storage."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from nanobot.charts.state import Annotation, ChartPoint


@dataclass
class _Work:
    expires: float
    drawings: dict[str, Annotation] = field(default_factory=dict)
    cursor: ChartPoint | None = None
    drawing_tool: str | None = None
    presence_at: float = 0


_lock = threading.Lock()
_work: dict[tuple[str, str], _Work] = {}


def temporary_drawings(chart_id: str, principal: str) -> list[Annotation]:
    with _lock:
        _expire()
        entry = _work.get((chart_id, principal))
        return [a.model_copy(deep=True) for a in entry.drawings.values()] if entry else []


def _expire() -> None:
    now = time.monotonic()
    for key in list(_work):
        if _work[key].expires <= now:
            del _work[key]


def put_temporary(chart_id: str, principal: str, annotation: Annotation) -> None:
    with _lock:
        _expire()
        key = (chart_id, principal)
        if key not in _work and len(_work) >= 256:
            raise ValueError("Temporary chart analysis capacity exceeded")
        entry = _work.setdefault(key, _Work(time.monotonic() + 600))
        if len(entry.drawings) >= 100 and annotation.id not in entry.drawings:
            raise ValueError("Temporary drawing limit exceeded")
        entry.drawings[annotation.id] = annotation.model_copy(deep=True)
        entry.expires = time.monotonic() + 600


def remove_temporary(chart_id: str, principal: str, annotation_id: str | None = None) -> None:
    with _lock:
        entry = _work.get((chart_id, principal))
        if entry:
            if annotation_id is None:
                del _work[(chart_id, principal)]
            else:
                entry.drawings.pop(annotation_id, None)


def set_presence(chart_id: str, principal: str, cursor: ChartPoint | None, tool: str | None) -> None:
    with _lock:
        _expire()
        key = (chart_id, principal)
        if key not in _work and len(_work) >= 256:
            raise ValueError("Chart presence capacity exceeded")
        entry = _work.setdefault(key, _Work(time.monotonic() + 600))
        if cursor is not None:
            entry.cursor = cursor.model_copy(deep=True)
        if tool is not None:
            entry.drawing_tool = tool
        entry.presence_at = time.monotonic()


def get_presence(chart_id: str, principal: str) -> tuple[ChartPoint | None, str | None]:
    with _lock:
        entry = _work.get((chart_id, principal))
        if entry is None or time.monotonic() - entry.presence_at > 5:
            return None, None
        return entry.cursor.model_copy(deep=True) if entry.cursor else None, entry.drawing_tool
