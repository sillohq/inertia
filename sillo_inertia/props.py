from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sillo.core.http import Request

# A props callback may take the request or take nothing — most do not need it,
# and requiring a parameter that is then ignored is how `lambda _: ...` gets
# written everywhere.
PropCallback = (
    Callable[[], Any]
    | Callable[[Request], Any]
    | Callable[[], Awaitable[Any]]
    | Callable[[Request], Awaitable[Any]]
)


@dataclass(frozen=True, slots=True)
class LazyProp:
    callback: PropCallback


@dataclass(frozen=True, slots=True)
class HtmlString:
    value: str


def lazy(callback: PropCallback) -> LazyProp:
    """Defer a prop until something asks for it.

    A lazy prop is left out of a partial reload unless it is named in
    ``X-Inertia-Partial-Data``, so the work behind it is not done on requests
    that will throw the result away::

        {"comments": lazy(lambda: Comment.for_post(post.id))}
    """
    return LazyProp(callback=callback)


def raw(value: str) -> HtmlString:
    """Mark a view value as markup, so it reaches the root view unescaped."""
    return HtmlString(value=value)
