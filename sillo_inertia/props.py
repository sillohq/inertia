from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sillo.core.http import Request


@dataclass(frozen=True, slots=True)
class LazyProp:
    callback: Callable[[Request], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class HtmlString:
    value: str


def lazy(callback: Callable[[Request], Any | Awaitable[Any]]) -> LazyProp:
    return LazyProp(callback=callback)


def raw(value: str) -> HtmlString:
    return HtmlString(value=value)
