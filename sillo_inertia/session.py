"""One-shot values that survive a redirect: validation errors and flash.

Inertia's whole form story is a redirect. A POST that fails validation answers
303 to the page the form is on, the client follows it, and the errors have to
still be there when that page renders — which means they live in the session
for exactly one request.

Two bags, both read-and-clear:

``errors``
    ``{field: message}``, exposed as the ``errors`` prop. Inertia's ``useForm``
    reads that name and nothing else, so it is not configurable.

``flash``
    ``{level: message}``, exposed as ``flash``. Levels are conventional
    (``success``, ``error``, ``info``, ``warning``); nothing here enforces a set.

Both are registered as :func:`~sillo_inertia.props.always` props, so a partial
reload that asks for two unrelated keys still delivers the message the redirect
just set. Without that a "Saved" toast would appear only on full visits.

Everything degrades to empty when no session middleware is installed, so an
application that renders Inertia pages without sessions still works — it just
has no flash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sillo.core.http import HttpContext

ERROR_BAG_KEY = "_inertia_errors"
FLASH_KEY = "_inertia_flash"

#: Inertia lets a page namespace its errors — two forms on one screen each get
#: their own bag, selected by this request header. When it is set, the errors
#: prop becomes ``{bag: {field: message}}`` instead of ``{field: message}``.
ERROR_BAG_HEADER = "X-Inertia-Error-Bag"


def _session(ctx: HttpContext) -> Any | None:
    """The session, or ``None`` when no session middleware is installed.

    ``ctx.session`` asserts rather than returning a null object, and an
    assertion is not something a shared prop should raise on every page of an
    application that simply chose not to use sessions.
    """
    if "session" not in ctx.scope:
        return None
    return ctx.scope["session"]


def _take(ctx: HttpContext, key: str) -> dict[str, Any]:
    """Read a bag and clear it, so it is delivered exactly once."""
    session = _session(ctx)
    if session is None:
        return {}
    value = session.get(key)
    if not value:
        return {}
    session.delete(key)
    return dict(value)


def _put(ctx: HttpContext, key: str, values: dict[str, Any]) -> None:
    session = _session(ctx)
    if session is None:
        return
    existing = dict(session.get(key) or {})
    existing.update(values)
    session.set(key, existing)


def set_errors(ctx: HttpContext, errors: dict[str, Any], bag: str | None = None) -> None:
    """Stash validation errors for the page this request redirects to.

    Args:
        ctx: The request that failed validation.
        errors: ``{field: message}``. Values are coerced to strings, because
            that is what the client renders and a stray exception object in a
            prop tree is a 500 at serialisation time.
        bag: An optional error-bag name, for a page with more than one form.
    """
    flat = {str(field): _first_message(message) for field, message in errors.items()}
    _put(ctx, ERROR_BAG_KEY, {bag: flat} if bag else flat)


def set_flash(ctx: HttpContext, level: str, message: str) -> None:
    """Stash a flash message for the next page rendered on this session."""
    _put(ctx, FLASH_KEY, {level: message})


def take_errors(ctx: HttpContext) -> dict[str, Any]:
    """The error bag for this request, cleared as it is read."""
    return _take(ctx, ERROR_BAG_KEY)


def take_flash(ctx: HttpContext) -> dict[str, Any]:
    """The flash bag for this request, cleared as it is read."""
    return _take(ctx, FLASH_KEY)


def _first_message(message: Any) -> str:
    """Reduce a validation error to the one line a field can display.

    Validators disagree about shape: Pydantic hands back a list of dicts,
    hand-written checks hand back a string, and a form library may hand back a
    list of strings. The client renders one message per field, so anything
    richer is flattened to its first entry rather than being stringified into
    ``["{'type': 'missing', ...}"]`` in the UI.
    """
    if isinstance(message, str):
        return message
    if isinstance(message, (list, tuple)):
        return _first_message(message[0]) if message else ""
    if isinstance(message, dict):
        for key in ("msg", "message", "detail"):
            if key in message:
                return _first_message(message[key])
    return str(message)
