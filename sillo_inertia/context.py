"""The request the adapter is currently answering.

Every Inertia response is a function of the request that asked for it: the URL
goes into the page object, ``X-Inertia`` decides between JSON and HTML, and the
partial-reload headers decide which props survive. Threading that request
through every call by hand is noise — the handler already has it, and the
adapter already runs middleware on every request.

So the middleware records it here, and :func:`current_request` reads it back.
The value is a :class:`~contextvars.ContextVar`, which is per-task rather than
global: two requests in flight at once each see their own.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sillo.core.http import Request

    from .adapter import Inertia

_active: ContextVar[tuple[Inertia, Request] | None] = ContextVar(
    "sillo_inertia_active", default=None
)


class OutsideRequestError(RuntimeError):
    """Raised when the adapter is asked for a request that is not there."""


_NOT_BOUND = """No active Inertia request.

{what} reads the current request from the middleware that Inertia installs on
the application. There are three ways to end up here:

  1. The adapter was never attached. Pass the app when you build it, or attach
     it afterwards:

         inertia = Inertia(app, root_view="resources/views/app.html")
         # or
         inertia.middleware(app)

  2. The call is outside a request — a background job, a script, a test that
     calls the handler directly. Pass the request explicitly there:

         await inertia.render("Home", props, request=request)

  3. The call escaped the request's task, for instance by handing work to a
     thread or a task group that does not copy the context. Read the request
     in the handler and pass it down.
"""


def bind(adapter: Inertia, request: Request) -> Token:
    """Record the adapter and request for the duration of this request."""
    return _active.set((adapter, request))


def unbind(token: Token) -> None:
    """Restore whatever was bound before :func:`bind`."""
    _active.reset(token)


def active() -> tuple[Inertia, Request] | None:
    """Return the bound ``(adapter, request)`` pair, or ``None``."""
    return _active.get()


def current_request() -> Request:
    """Return the request being answered.

    Raises:
        OutsideRequestError: If no Inertia middleware is active on this task.
    """
    bound = _active.get()
    if bound is None:
        raise OutsideRequestError(_NOT_BOUND.format(what="This"))
    return bound[1]


def current_inertia() -> Inertia:
    """Return the adapter handling this request.

    This is what lets ``from sillo_inertia import render`` work in a routes
    module that never imports the application — which would otherwise be a
    circular import, since the application is what registers the routes.

    Raises:
        OutsideRequestError: If no Inertia middleware is active on this task.
    """
    bound = _active.get()
    if bound is None:
        raise OutsideRequestError(_NOT_BOUND.format(what="This"))
    return bound[0]
