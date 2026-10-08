"""Provider-neutral, sanitized structured evidence validation."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

TIMEFRAMES = {"M1": "1m", "M2": "2m", "M3": "3m", "M4": "4m", "M5": "5m", "M6": "6m",
              "M10": "10m", "M12": "12m", "M15": "15m", "M20": "20m", "M30": "30m",
              "H1": "1h", "H2": "2h", "H3": "3h", "H4": "4h", "H6": "6h", "H8": "8h",
              "H12": "12h", "D": "1d", "W": "1w", "M": "1mn"}


class ProviderUnavailableError(RuntimeError):
    """Never carries provider request/response objects or authentication data."""


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def parse_provider(model: type[_ModelT], data: object) -> _ModelT:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise ProviderUnavailableError("Provider returned invalid structured data") from None
