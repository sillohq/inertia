"""The adapter: one object that turns ``(component, props)`` into a response.

A handler says what to render. Whether that becomes a JSON page object or a
full HTML document is decided here, from the request — and so is which props
survive a partial reload, which are deferred to a follow-up request, and which
the client should merge into what it already holds.
"""

from __future__ import annotations

import datetime as _datetime
import decimal
import enum
import functools
import html
import inspect
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sillo.core.http import HttpContext
from sillo.responses import (
    BaseResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from .config import InertiaConfig
from .context import bind, current_context, unbind
from .props import DEFAULT_DEFER_GROUP, HtmlString, Prop
from .session import ERROR_BAG_HEADER, take_errors, take_flash
from .vite import ViteOptions, render_vite_tags

JsonDict = dict[str, Any]
Props = (
    Mapping[str, Any]
    | Callable[[HttpContext], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
)

_CO_VARARGS = 0x04


def _wants_context(callback: Callable[..., Any]) -> bool:
    """Report whether a props callback wants the context passed to it.

    Both shapes are supported, because only some props need it::

        {"total": lambda: Order.count()}
        {"mine": lambda ctx: Order.for_user(ctx.user)}

    Plain functions and lambdas are read straight off ``__code__``, which costs
    nothing; anything else falls back to ``inspect.signature``, and anything
    that has no readable signature at all is called the old way.
    """
    code = getattr(callback, "__code__", None)
    if code is not None and getattr(callback, "__self__", None) is None:
        return code.co_argcount > 0 or bool(code.co_flags & _CO_VARARGS)
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind
        in (
            parameter.POSITIONAL_ONLY,
            parameter.POSITIONAL_OR_KEYWORD,
            parameter.VAR_POSITIONAL,
        )
        for parameter in parameters.values()
    )


def _invoke(callback: Callable[..., Any], ctx: HttpContext) -> Any:
    return callback(ctx) if _wants_context(callback) else callback()


def encode_prop(value: Any) -> Any:
    """Serialise the values a page object routinely contains but JSON does not.

    ``json.dumps`` on a prop tree fails on the first ``Decimal`` in it, with a
    message naming the type and not the key — which on a page carrying forty
    values tells you nothing about which one. Money is the common case and it
    is the one that must not be approximated: a ``Decimal`` becomes its plain
    decimal string via ``format(value, "f")``, never a float, and never
    ``str()`` — SQLite hands back ``Decimal("6.7E+2")`` for a stored
    ``670.00``, and ``str()`` on that renders in the UI as the literal
    ``6.7E+2``.
    """
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        return value.isoformat()
    if isinstance(value, _datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    for method in ("model_dump", "dict", "to_dict"):
        dump = getattr(value, method, None)
        if callable(dump):
            return dump()
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable, and "
        f"reached an Inertia prop. Convert it in the handler, or give it a "
        f"to_dict()."
    )


def dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), default=encode_prop)


def _endpoint_signature(func: Callable[..., Any]) -> inspect.Signature:
    """Build the signature the router should see for a decorated page handler.

    Sillo v1 hands every handler one leading argument — the ``HttpContext`` —
    and resolves everything after it by name: path parameters, ``Depend(...)``
    dependencies, and the ``Query``/``Header``/``Body`` markers. It reads that
    shape off the handler's signature at registration.

    The wrapper this decorator returns always takes ``(ctx, **kwargs)``, but a
    page function underneath may declare no context at all
    (``def home(): ...``) or name it ``context``. So the signature advertised
    to the router is normalised: a single leading ``ctx: HttpContext``,
    followed by every other parameter the function declared — defaults,
    annotations and DI markers intact — so dependency resolution and path
    binding see exactly what the author wrote.
    """
    signature = inspect.signature(func)
    rest = [
        parameter.replace(kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        else parameter
        for parameter in signature.parameters.values()
        if parameter.name not in ("ctx", "context")
    ]
    injected = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=HttpContext,
        )
    ]
    return signature.replace(parameters=injected + rest)


#: A `{{ name }}` placeholder in the root view. Used to blank the ones no
#: value was supplied for — see `_render_root_view`.
_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")


@dataclass(slots=True)
class InertiaPage:
    component: str
    props: JsonDict
    url: str
    version: str | None = None
    encrypt_history: bool = False
    clear_history: bool = False
    deferred_props: dict[str, list[str]] = field(default_factory=dict)
    merge_props: list[str] = field(default_factory=list)
    deep_merge_props: list[str] = field(default_factory=list)
    match_props_on: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "component": self.component,
            "props": self.props,
            "url": self.url,
            "version": self.version,
        }
        # Every key below is omitted when empty rather than sent as null: the
        # client tests for presence, and a page object carrying six empty
        # instruction keys is noise in every payload and every test assertion.
        if self.encrypt_history:
            payload["encryptHistory"] = True
        if self.clear_history:
            payload["clearHistory"] = True
        if self.deferred_props:
            payload["deferredProps"] = self.deferred_props
        if self.merge_props:
            payload["mergeProps"] = self.merge_props
        if self.deep_merge_props:
            payload["deepMergeProps"] = self.deep_merge_props
        if self.match_props_on:
            payload["matchPropsOn"] = self.match_props_on
        return payload


@dataclass(slots=True)
class Inertia:
    """The adapter. One per application, built at startup.

    Args:
        app: The application to install the middleware on. Optional — call
            :meth:`middleware` later instead.
        root_view: The HTML document a first visit receives, with
            ``{{ inertia }}`` where the page object goes.
        version: The asset version. A client holding a different one is sent
            to do a full browser visit, so it cannot render a new page object
            against components from the previous build.
        root_id: The id of the element the client mounts on.
        base_dir: Where relative Vite manifest paths resolve from.
        vite: Vite options, rendered into ``{{ inertia_head }}``.
    """

    app: Any | None = None
    root_view: str | Path = "app.html"
    version: str | Callable[[], str | None] | None = None
    root_id: str = "app"
    base_dir: str | Path | None = None
    vite: ViteOptions | None = None
    shared_props: dict[str, Any] = field(default_factory=dict)
    view_data: dict[str, Any] = field(default_factory=dict)
    config: InertiaConfig = field(init=False)

    def __post_init__(self) -> None:
        self.config = InertiaConfig(
            root_view=Path(self.root_view),
            version=self.version,
            root_id=self.root_id,
        )
        if self.base_dir is None:
            self.base_dir = self.config.root_view.parent.parent.parent
        else:
            self.base_dir = Path(self.base_dir)

        # Errors and flash are shared props the application never has to
        # remember to add. Both are `always`, because a form post redirects
        # into whatever reload the page was doing and the message has to
        # survive it, and both read-and-clear so they are delivered once.
        self.shared_props.setdefault("errors", Prop(value=self._errors, always=True))
        self.shared_props.setdefault("flash", Prop(value=take_flash, always=True))

        if self.app is not None:
            self.middleware(self.app)

    def middleware(self, app: Any) -> None:
        app.use(self.handle_request)

    def share(self, **props: Any) -> None:
        """Add props that every page receives.

        Called at startup, not per request: the values live on the adapter and
        are merged under each page's own props, which win on a clash. A value
        that has to vary per request is a callable — it is passed the context
        and resolved on each render.
        """
        self.shared_props.update(props)

    # -- responses --------------------------------------------------------

    async def render(
        self,
        component: str,
        props: Props | None = None,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        view_data: Mapping[str, Any] | None = None,
        encrypt_history: bool = False,
        clear_history: bool = False,
        ctx: HttpContext | None = None,
    ) -> BaseResponse:
        """Render a component, as page JSON or as a full HTML document.

        Which one depends on the request: Inertia's client sends
        ``X-Inertia: true`` once the application has booted, and the first
        visit — a plain browser navigation — gets the root view with the page
        object embedded in it.

        Args:
            component: The client-side component's name, as the client
                resolves it, for instance ``"Users/Index"``.
            props: The page's props. A mapping, or a callable taking the
                context and returning one, sync or async.
            status_code: The HTTP status.
            headers: Extra response headers.
            view_data: Values for placeholders in the root view, merged over
                the adapter's own ``view_data``. Only used on a first visit.
            encrypt_history: Ask the client to encrypt this history entry.
            clear_history: Ask the client to drop its history state.
            ctx: The request to answer. Defaults to the current one.

        Returns:
            A response, ready to be returned from the handler.

        Raises:
            OutsideRequestError: If no context is bound and none was passed.
            FileNotFoundError: If a first visit needs the root view and it is
                not where the adapter was told to look.
        """
        ctx = ctx if ctx is not None else current_context()
        resolved, instructions = await self._resolve_props(ctx, component, props or {})

        page = InertiaPage(
            component=component,
            props=resolved,
            url=self._request_url(ctx),
            version=self.current_version(),
            encrypt_history=encrypt_history,
            clear_history=clear_history,
            **instructions,
        )
        page_payload = page.to_dict()

        # Vary is on both branches because the two are the same URL: without it
        # a shared cache can serve one visitor's page JSON to another visitor's
        # first, blank-page visit.
        response_headers = {"Vary": "X-Inertia", **(headers or {})}

        if self.is_inertia_request(ctx):
            return JSONResponse(
                content=json.loads(dumps(page_payload)),
                status_code=status_code,
                headers={**response_headers, "X-Inertia": "true"},
            )

        markup = self._render_root_view(page_payload, view_data or {})
        return HTMLResponse(
            content=markup, status_code=status_code, headers=response_headers
        )

    def redirect(
        self,
        location: str,
        *,
        status_code: int | None = None,
        ctx: HttpContext | None = None,
    ) -> BaseResponse:
        """Redirect in a way Inertia's client will follow.

        Args:
            location: Where to send the visitor.
            status_code: Overrides the default, which is 303 after a mutating
                request and 302 otherwise. 303 is not decoration: on a 302 the
                browser repeats the POST against the new URL, so a redirect
                after a successful create would create a second record.
            ctx: The request to answer. Defaults to the current one.

        Returns:
            A redirect response.
        """
        ctx = ctx if ctx is not None else current_context()
        code = status_code or (303 if ctx.method.upper() != "GET" else 302)
        return RedirectResponse(url=location, status_code=code)

    def back(
        self,
        *,
        fallback: str = "/",
        status_code: int | None = None,
        ctx: HttpContext | None = None,
    ) -> BaseResponse:
        """Redirect to the page the request came from.

        The idiomatic end of an Inertia form post: the client re-renders the
        page it was already on, picking up whatever the handler changed.

        Args:
            fallback: Where to go when there is no Referer — a request made
                outside the client, or one whose referrer policy stripped it.
            status_code: Overrides the 303/302 default.
            ctx: The request to answer. Defaults to the current one.
        """
        ctx = ctx if ctx is not None else current_context()
        referer = self._header(ctx, "Referer")
        return self.redirect(referer or fallback, status_code=status_code, ctx=ctx)

    def location(self, url: str, *, status_code: int = 409) -> BaseResponse:
        """Send the client somewhere Inertia does not control.

        A 409 with ``X-Inertia-Location`` tells the client to do a full browser
        visit instead of an XHR one, which is the only way out of an Inertia
        page and into an external URL or a stale asset version.
        """
        return BaseResponse(status_code=status_code, headers={"X-Inertia-Location": url})

    # -- handlers ---------------------------------------------------------

    def page(
        self, component: str, **render_options: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Turn a function that returns props into a page handler.

        The handler declares only what it uses, and returns a plain mapping::

            @app.get("/users/{user_id:int}")
            @inertia.page("Users/Show")
            async def show(ctx, user_id: int):
                return {"user": await User.get(id=user_id)}

        Returning a response instead of a mapping passes it through untouched,
        so a handler can still redirect or 404 out of a page.

        Args:
            component: The component to render.
            **render_options: Passed to :meth:`render` on every request the
                handler answers — ``status_code``, ``view_data`` and so on.

        Returns:
            A decorator producing a handler the router can call.
        """

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            parameters = list(inspect.signature(func).parameters)
            wants_ctx = bool(parameters) and parameters[0] in ("ctx", "context")
            ctx_name = parameters[0] if wants_ctx else None

            @functools.wraps(func)
            async def endpoint(ctx: HttpContext, **kwargs: Any) -> Any:
                if ctx_name is not None:
                    kwargs[ctx_name] = ctx

                result = func(**kwargs)
                if inspect.isawaitable(result):
                    result = await result

                # A handler that built its own response has already decided
                # what to send; only a mapping means "render this page".
                if isinstance(result, BaseResponse):
                    return result

                return await self.render(component, result or {}, ctx=ctx, **render_options)

            # After functools.wraps, which sets __wrapped__: inspect.signature
            # follows that by default and would report the wrapped function's
            # signature, but it stops unwrapping at anything carrying an
            # explicit __signature__.
            endpoint.__signature__ = _endpoint_signature(func)  # type: ignore[attr-defined]
            return endpoint

        return decorate

    async def handle_request(
        self,
        ctx: HttpContext,
        call_next: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Bind the context, turn away stale clients, and fix redirect codes.

        Three jobs, all of which have to happen for every request rather than
        in any one handler:

        1. Bind the context, so ``render`` can be called from a routes module
           that never imported the adapter.
        2. A client holding an older asset version would render the new page
           object against components that no longer match it. Sending it to do
           a full browser visit is how Inertia gets it onto the current build.
        3. A 302 answering a PUT, PATCH or DELETE makes the browser repeat the
           *method* against the new URL, so a redirect after a successful
           update issues a second update. 303 is the one status that says
           "GET the new location", and Inertia's client relies on the server
           having corrected it.
        """
        token = bind(self, ctx)
        try:
            method = ctx.method.upper()
            current_version = self.current_version()
            request_version = self._header(ctx, "X-Inertia-Version")
            if (
                method == "GET"
                and self.is_inertia_request(ctx)
                and current_version is not None
                and request_version
                and request_version != current_version
            ):
                return self.location(self._request_url(ctx))

            response = await call_next()

            if (
                method in ("PUT", "PATCH", "DELETE")
                and getattr(response, "status_code", None) == 302
            ):
                response.status_code = 303
            return response
        finally:
            unbind(token)

    # -- internals --------------------------------------------------------

    def current_version(self) -> str | None:
        if callable(self.config.version):
            return self.config.version()
        return self.config.version

    def is_inertia_request(self, ctx: HttpContext | None = None) -> bool:
        ctx = ctx if ctx is not None else current_context()
        return self._header(ctx, "X-Inertia").lower() == "true"

    def _errors(self, ctx: HttpContext) -> dict[str, Any]:
        """The ``errors`` prop, namespaced when the client asked for a bag."""
        errors = take_errors(ctx)
        bag = self._header(ctx, ERROR_BAG_HEADER)
        if bag and bag not in errors:
            return {bag: errors}
        return errors

    async def _resolve_props(
        self,
        ctx: HttpContext,
        component: str,
        props: Props,
    ) -> tuple[JsonDict, dict[str, Any]]:
        """Decide which props this response carries, and resolve those.

        Returns the resolved props and the page-object instructions that go
        with them — which keys were deferred, and which the client should merge
        rather than replace.
        """
        page_props = _invoke(props, ctx) if callable(props) else props
        if inspect.isawaitable(page_props):
            page_props = await page_props

        merged: dict[str, Any] = {**self.shared_props, **dict(page_props)}

        only, excluded = self._partial_keys(ctx, component)
        is_partial = only is not None or excluded is not None
        reset = self._reset_keys(ctx)

        selected: dict[str, Any] = {}
        deferred: dict[str, list[str]] = {}

        for key, value in merged.items():
            prop = value if isinstance(value, Prop) else None

            if is_partial:
                # A partial reload carries exactly what it asked for, plus the
                # props that declared they are always sent. `optional` and
                # `defer` stop being special here — being asked for by name is
                # the whole point of both.
                wanted = (only is None or self._selected(key, only)) and not (
                    excluded is not None and self._selected(key, excluded)
                )
                if not wanted and not (prop is not None and prop.always):
                    continue
            else:
                if prop is not None and prop.optional:
                    continue
                if prop is not None and prop.deferred:
                    deferred.setdefault(prop.defer_group or DEFAULT_DEFER_GROUP, []).append(key)
                    continue

            selected[key] = value

        resolved = {
            key: await self._resolve_value(ctx, value) for key, value in selected.items()
        }

        if only is not None:
            resolved = self._prune(resolved, only, keep=set(self._always_keys(merged)))

        merge_props = [
            key
            for key, value in selected.items()
            if isinstance(value, Prop) and value.merge and not value.deep and key not in reset
        ]
        deep_merge_props = [
            key
            for key, value in selected.items()
            if isinstance(value, Prop) and value.merge and value.deep and key not in reset
        ]
        match_props_on = [
            f"{key}.{value.match_on}"
            for key, value in selected.items()
            if isinstance(value, Prop) and value.match_on and key not in reset
        ]

        return resolved, {
            "deferred_props": deferred,
            "merge_props": merge_props,
            "deep_merge_props": deep_merge_props,
            "match_props_on": match_props_on,
        }

    @staticmethod
    def _always_keys(merged: Mapping[str, Any]) -> list[str]:
        return [k for k, v in merged.items() if isinstance(v, Prop) and v.always]

    @staticmethod
    def _selected(key: str, keys: set[str]) -> bool:
        """Whether ``key`` is named by a partial-reload key set.

        Inertia's keys are dotted paths — ``only: ["user.name"]`` asks for one
        field of one prop — so a top-level prop matches when it is named
        outright or when it is the root of a dotted key.
        """
        return key in keys or any(k.split(".", 1)[0] == key for k in keys)

    def _prune(
        self, resolved: JsonDict, only: set[str], keep: set[str]
    ) -> JsonDict:
        """Narrow nested props to the dotted paths that were asked for.

        ``only: ["order.customer"]`` should send the customer and not the other
        thirty fields of the order. A prop named without a dot is untouched.
        """
        paths: dict[str, list[list[str]]] = {}
        for entry in only:
            head, _, tail = entry.partition(".")
            paths.setdefault(head, [])
            if tail:
                paths[head].append(tail.split("."))
            else:
                paths[head] = []  # named outright: take all of it

        output: JsonDict = {}
        for key, value in resolved.items():
            branches = paths.get(key)
            if not branches or key in keep:
                output[key] = value
                continue
            output[key] = _narrow(value, branches)
        return output

    async def _resolve_value(self, ctx: HttpContext, value: Any) -> Any:
        if isinstance(value, Prop):
            value = value.value
        if callable(value) and not isinstance(value, (str, bytes, bytearray)):
            value = _invoke(value, ctx)
        if inspect.isawaitable(value):
            return await value
        return value

    def _partial_keys(
        self, ctx: HttpContext, component: str
    ) -> tuple[set[str] | None, set[str] | None]:
        """The ``only`` and ``except`` key sets for this request.

        Both are ignored unless the client says it is reloading *this*
        component: a partial reload aimed at another page arriving here means
        the handler redirected, and honouring the key list would then answer
        with a page missing most of its props.
        """
        if self._header(ctx, "X-Inertia-Partial-Component") != component:
            return None, None
        only = _split_header(self._header(ctx, "X-Inertia-Partial-Data"))
        excluded = _split_header(self._header(ctx, "X-Inertia-Partial-Except"))
        return only, excluded

    def _reset_keys(self, ctx: HttpContext) -> set[str]:
        return _split_header(self._header(ctx, "X-Inertia-Reset")) or set()

    def _request_url(self, ctx: HttpContext) -> str:
        path = ctx.scope.get("path", "/")
        query = ctx.scope.get("query_string", b"")
        if query:
            return f"{path}?{query.decode('latin-1')}"
        return path

    def _header(self, ctx: HttpContext, name: str) -> str:
        value = ctx.headers.get(name)
        return value if value is not None else ""

    def _render_root_view(self, page: JsonDict, view_data: Mapping[str, Any]) -> str:
        root_view = self.config.root_view
        if not root_view.is_file():
            raise FileNotFoundError(f"Inertia root view not found: {root_view}")

        serialized = dumps(page)
        replacements = {
            "inertia": self._page_script(serialized),
            # The attribute form Inertia 1.x read from the root element. Kept
            # for templates written against that convention; 2.x and later
            # ignore it entirely.
            "inertia_page": html.escape(serialized, quote=True),
            "root_id": html.escape(self.config.root_id, quote=True),
            "inertia_head": self._head_tags(),
            **{key: self._view_value(value) for key, value in self.view_data.items()},
            **{key: self._view_value(value) for key, value in view_data.items()},
        }
        content = root_view.read_text(encoding="utf-8")
        for key, value in replacements.items():
            content = content.replace("{{ " + key + " }}", value)
            content = content.replace("{{" + key + "}}", value)

        # Anything the template asked for and nobody supplied is emptied rather
        # than left in place. A root view that says `<title>{{ title }}</title>`
        # and is never given a title should render an empty title, not ship the
        # literal braces to the browser — which is what a crawler reads, what a
        # link preview shows, and what sits in the tab until the client boots.
        return _PLACEHOLDER.sub("", content)

    def _page_script(self, serialized: str) -> str:
        """Render the page object as the JSON script tag Inertia looks for.

        Since Inertia 2.0 the client reads

            document.querySelector('script[data-page="<id>"][type="application/json"]')

        and returns null when it is absent — which surfaces in the browser as
        ``Cannot read properties of null (reading 'component')`` from inside
        ``createInertiaApp``. The 1.x convention of ``data-page`` on the root
        ``<div>`` is no longer consulted at all.

        The content of a ``<script>`` is raw text, not HTML, so it must *not*
        be HTML-escaped — ``&quot;`` would reach ``JSON.parse`` verbatim and
        fail. ``<``, ``>`` and ``&`` are escaped as JSON unicode sequences
        instead, which ``JSON.parse`` decodes and which cannot terminate the
        script element early.
        """
        safe = (
            serialized.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        root_id = html.escape(self.config.root_id, quote=True)
        return f'<script type="application/json" data-page="{root_id}">{safe}</script>'

    def _view_value(self, value: Any) -> str:
        if isinstance(value, HtmlString):
            return value.value
        return html.escape(str(value), quote=True)

    def _head_tags(self) -> str:
        if self.vite is None:
            return ""
        # base_dir is declared wide enough for the constructor to take a str or
        # nothing at all; __post_init__ resolves both to a Path.
        assert self.base_dir is not None
        return render_vite_tags(self.vite, Path(self.base_dir))


def _split_header(value: str) -> set[str] | None:
    if not value:
        return None
    keys = {item.strip() for item in value.split(",") if item.strip()}
    return keys or None


def _narrow(value: Any, branches: list[list[str]]) -> Any:
    """Keep only ``branches`` of a nested mapping."""
    if not isinstance(value, Mapping):
        return value
    output: dict[str, Any] = {}
    grouped: dict[str, list[list[str]]] = {}
    for branch in branches:
        head, tail = branch[0], branch[1:]
        grouped.setdefault(head, [])
        if tail:
            grouped[head].append(tail)
    for head, sub_branches in grouped.items():
        if head not in value:
            continue
        output[head] = (
            _narrow(value[head], sub_branches) if sub_branches else value[head]
        )
    return output
