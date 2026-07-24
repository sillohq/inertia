from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class InertiaConfig:
    root_view: Path
    version: str | Callable[[], str | None] | None = None
    root_id: str = "app"
