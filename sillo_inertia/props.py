"""Prop wrappers — the vocabulary a handler uses to say *when* a value is sent.

A plain value in the props mapping is resolved and sent on every visit. The
wrappers here each opt out of that in a different way, and every one of them
exists because Inertia's client understands a matching instruction in the page
object:

===================  ==================================================
:func:`optional`     never sent unless a partial reload asks for it
:func:`defer`        left out of the first response, fetched right after
:func:`always`       sent even on a partial reload that did not ask
:func:`merge`        appended to what the client already holds
:func:`deep_merge`   merged into what the client already holds, recursively
===================  ==================================================

:func:`merge` and :func:`defer` compose — ``defer(load_more, merge=True)`` is
how an infinite list is paged — so the wrappers are one class with flags rather
than five unrelated ones.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sillo.core.http import HttpContext

# A props callback may take the context or take nothing — most do not need it,
# and requiring a parameter that is then ignored is how `lambda _: ...` gets
# written everywhere.
PropCallback = (
    Callable[[], Any]
    | Callable[["HttpContext"], Any]
    | Callable[[], Awaitable[Any]]
    | Callable[["HttpContext"], Awaitable[Any]]
)

#: The group name a deferred prop lands in when none is given. The client
#: fetches one group per request, so grouping is how a page says "these three
#: can arrive together, that slow one should not hold them up".
DEFAULT_DEFER_GROUP = "default"


@dataclass(frozen=True, slots=True)
class Prop:
    """A value plus the instructions that decide when it is sent.

    Handlers do not construct this directly; the functions below do.
    """

    value: Any

    #: Left out of a normal visit — only a partial reload naming it gets it.
    optional: bool = False

    #: Left out of the first response and announced in ``deferredProps``, so
    #: the client immediately asks for it in a follow-up partial reload. The
    #: string is the group it is fetched with; ``None`` means not deferred.
    defer_group: str | None = None

    #: Included even in a partial reload that did not name it. Errors and
    #: flash messages are the reason this exists: a form post that redirects
    #: back into a partial reload must still carry its own error bag.
    always: bool = False

    #: Announced in ``mergeProps``/``deepMergeProps`` so the client combines
    #: this value with what it already holds instead of replacing it.
    merge: bool = False
    deep: bool = False

    #: For a deep merge of records, the key that identifies "the same item",
    #: reported to the client as ``matchPropsOn``.
    match_on: str | None = None

    @property
    def deferred(self) -> bool:
        return self.defer_group is not None

    def as_merge(self, *, deep: bool = False, match_on: str | None = None) -> Prop:
        return replace(self, merge=True, deep=deep, match_on=match_on)


@dataclass(frozen=True, slots=True)
class HtmlString:
    """A view value that reaches the root view unescaped."""

    value: str


def optional(callback: PropCallback) -> Prop:
    """Defer a prop until a partial reload asks for it by name.

    The callback does not run on a normal visit at all, so the work behind it
    is not done on requests that would throw the result away::

        {"comments": optional(lambda: Comment.for_post(post.id))}

    Nothing fetches it on its own — the page has to ask, usually from a tab or
    a disclosure that only then needs the data. Use :func:`defer` for a value
    that should arrive without being asked for.
    """
    return Prop(value=callback, optional=True)


#: Inertia 1.x called this ``lazy``. The name is kept because it is still what
#: the JavaScript docs called it for years, and renaming it would break every
#: page written against the old adapter for no gain.
lazy = optional


def defer(
    callback: PropCallback,
    group: str = DEFAULT_DEFER_GROUP,
    *,
    merge: bool = False,
    deep: bool = False,
    match_on: str | None = None,
) -> Prop:
    """Send the page now and this prop a moment later.

    The first response omits the value and names it in ``deferredProps``; the
    client renders the page, then immediately requests the group. A dashboard
    whose charts take a second to aggregate paints its shell straight away::

        {
            "orders": recent_orders,
            "revenue": defer(aggregate_revenue, "charts"),
            "funnel": defer(aggregate_funnel, "charts"),
        }

    Args:
        callback: Produces the value. Takes the context or nothing.
        group: Deferred props sharing a group are fetched in one request.
        merge: Combine with the value the client holds rather than replacing
            it — this is how "load more" pages a list.
        deep: Merge recursively rather than by appending.
        match_on: The identity key for a deep merge of records.
    """
    return Prop(
        value=callback,
        defer_group=group,
        merge=merge,
        deep=deep,
        match_on=match_on,
    )


def always(value: Any) -> Prop:
    """Send this prop on every response, partial reloads included.

    A partial reload keeps only the props it named. Anything the page needs
    regardless — the flash message the redirect just set, the error bag, an
    unread count in the chrome — has to say so::

        {"flash": always(read_flash)}
    """
    return Prop(value=value, always=True)


def merge(callback: PropCallback | Any, *, match_on: str | None = None) -> Prop:
    """Append this value to the one the client already holds.

    For arrays the client concatenates; for objects it takes the union. The
    page keeps what it had, which is what makes pagination additive::

        {"orders": merge(next_page_of_orders)}
    """
    return Prop(value=callback, merge=True, match_on=match_on)


def deep_merge(callback: PropCallback | Any, *, match_on: str | None = None) -> Prop:
    """Merge recursively into what the client holds.

    Args:
        callback: Produces the value.
        match_on: The field identifying "the same record", so an item that
            arrives twice updates in place instead of appearing twice.
    """
    return Prop(value=callback, merge=True, deep=True, match_on=match_on)


def raw(value: str) -> HtmlString:
    """Mark a view value as markup, so it reaches the root view unescaped."""
    return HtmlString(value=value)


#: Retained so ``isinstance(value, LazyProp)`` in older code keeps working:
#: every wrapper is now a :class:`Prop`.
LazyProp = Prop
