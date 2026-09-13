"""Inertia.js for Sillo.

A handler returns a component name and its props; the adapter decides whether
that becomes a JSON page object or a full HTML document, based on the request
it is answering::

    inertia = Inertia(app, root_view="resources/views/app.html")

    @app.get("/")
    async def home(ctx: HttpContext):
        return await render("Home", {"name": "Sillo"})

``render`` is importable on its own, which is what a routes module wants: it
can build Inertia responses without importing the application that owns the
adapter, and so without the circular import that would otherwise cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .adapter import Inertia, encode_prop
from .config import InertiaConfig
from .context import (
    OutsideRequestError,
    current_context,
    current_inertia,
)
from .props import (
    HtmlString,
    LazyProp,
    Prop,
    always,
    deep_merge,
    defer,
    lazy,
    merge,
    optional,
    raw,
)
from .session import set_errors, set_flash
from .vite import ViteOptions, ViteReactOptions, ViteVueOptions, vite_react, vite_vue

if TYPE_CHECKING:
    from sillo.core.http import HttpContext
    from sillo.responses import BaseResponse

__version__ = "1.0.0a2"


async def render(component: str, props: Any = None, **options: Any) -> BaseResponse:
    """Render a page through the adapter handling this request.

    See :meth:`Inertia.render`.
    """
    return await current_inertia().render(component, props, **options)


def redirect(
    location: str,
    *,
    status_code: int | None = None,
    ctx: HttpContext | None = None,
) -> BaseResponse:
    """Redirect. See :meth:`Inertia.redirect`."""
    return current_inertia().redirect(location, status_code=status_code, ctx=ctx)


def back(
    *,
    fallback: str = "/",
    status_code: int | None = None,
    ctx: HttpContext | None = None,
) -> BaseResponse:
    """Redirect to the referring page. See :meth:`Inertia.back`."""
    return current_inertia().back(fallback=fallback, status_code=status_code, ctx=ctx)


def location(url: str, *, status_code: int = 409) -> BaseResponse:
    """Force a full browser visit. See :meth:`Inertia.location`."""
    return current_inertia().location(url, status_code=status_code)


def share(**props: Any) -> None:
    """Add props every page receives. See :meth:`Inertia.share`."""
    current_inertia().share(**props)


__all__ = [
    "HtmlString",
    "Inertia",
    "InertiaConfig",
    "LazyProp",
    "OutsideRequestError",
    "Prop",
    "ViteOptions",
    "ViteReactOptions",
    "ViteVueOptions",
    "__version__",
    "always",
    "back",
    "current_context",
    "current_inertia",
    "deep_merge",
    "defer",
    "encode_prop",
    "lazy",
    "location",
    "merge",
    "optional",
    "raw",
    "redirect",
    "render",
    "set_errors",
    "set_flash",
    "share",
    "vite_react",
    "vite_vue",
]
