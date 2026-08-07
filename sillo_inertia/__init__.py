"""Inertia.js for Sillo.

A handler returns a component name and its props; the adapter decides whether
that becomes a JSON page object or a full HTML document, based on the request
it is answering::

    inertia = Inertia(app, root_view="resources/views/app.html")

    @app.get("/")
    async def home(request: Request, response: Response):
        return await inertia.render("Home", {"name": "Sillo"})

``render`` is also importable on its own, which is what a routes module wants:
it can build Inertia responses without importing the application that owns the
adapter, and so without the circular import that would otherwise cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .adapter import Inertia
from .config import InertiaConfig
from .context import OutsideRequestError, current_inertia, current_request
from .props import HtmlString, LazyProp, lazy, raw
from .vite import ViteOptions, ViteReactOptions, ViteVueOptions, vite_react, vite_vue

if TYPE_CHECKING:
    from sillo.core.http import Request
    from sillo.core.http.response import BaseResponse


async def render(component: str, props: Any = None, **options: Any) -> BaseResponse:
    """Render a page through the adapter handling this request.

    See :meth:`Inertia.render`.
    """
    return await current_inertia().render(component, props, **options)


def redirect(
    location: str,
    *,
    status_code: int | None = None,
    request: Request | None = None,
) -> BaseResponse:
    """Redirect. See :meth:`Inertia.redirect`."""
    return current_inertia().redirect(
        location, status_code=status_code, request=request
    )


def back(
    *,
    fallback: str = "/",
    status_code: int | None = None,
    request: Request | None = None,
) -> BaseResponse:
    """Redirect to the referring page. See :meth:`Inertia.back`."""
    return current_inertia().back(
        fallback=fallback, status_code=status_code, request=request
    )


def location(url: str, *, status_code: int = 409) -> BaseResponse:
    """Force a full browser visit. See :meth:`Inertia.location`."""
    return current_inertia().location(url, status_code=status_code)


__all__ = [
    "HtmlString",
    "Inertia",
    "InertiaConfig",
    "LazyProp",
    "OutsideRequestError",
    "ViteOptions",
    "ViteReactOptions",
    "ViteVueOptions",
    "back",
    "current_inertia",
    "current_request",
    "lazy",
    "location",
    "raw",
    "redirect",
    "render",
    "vite_react",
    "vite_vue",
]
