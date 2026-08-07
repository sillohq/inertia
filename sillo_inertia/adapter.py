from __future__ import annotations

import functools
import html
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sillo.core.http import Request, Response

# sillo.core.http re-exports only Request and the Response manager, so the
# concrete response classes come from the module itself. render() returns one
# of these rather than mutating a Response manager: a response is the whole of
# what an Inertia handler produces, and building it here means the handler
# never has to be handed a manager to fill in.
from sillo.core.http.response import (
    BaseResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Responder,
)

from .config import InertiaConfig
from .context import bind, current_request, unbind
from .props import HtmlString, LazyProp
from .vite import ViteOptions, render_vite_tags

JsonDict = dict[str, Any]
Props = (
    Mapping[str, Any]
    | Callable[[Request], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
)

_CO_VARARGS = 0x04

_WRONG_ARGUMENTS = """Inertia.{method}() takes {expected} first, not a request.

    {example}

The request comes from the middleware Inertia installs on the application, and
the return value is a complete response — so neither one is passed in. If you
need a request other than the current one (a test, a background job), pass it
by keyword:

    await inertia.render("Home", props, request=request)
"""


def _wants_request(callback: Callable[..., Any]) -> bool:
    """Report whether a props callback wants the request passed to it.

    Both shapes are supported, because only some props need the request::

        {"total": lambda: Order.count()}
        {"mine": lambda request: Order.for_user(request.user)}

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


def _invoke(callback: Callable[..., Any], request: Request) -> Any:
    return callback(request) if _wants_request(callback) else callback()


def _endpoint_signature(func: Callable[..., Any]) -> inspect.Signature:
    """Build the signature the router should see for a decorated page handler.

    The router reads the handler's signature to resolve dependencies, locate
    the validated body and bind path parameters, then calls it as
    ``handler(request, response, **rest)``. A decorated function that declares
    neither would break both halves of that, so the wrapper advertises them
    even when the function underneath does not want them.
    """
    signature = inspect.signature(func)
    rest = [
        parameter.replace(kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        else parameter
        for parameter in signature.parameters.values()
        if parameter.name not in ("request", "response")
    ]
    injected = [
        inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("response", inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ]
    return signature.replace(parameters=injected + rest)


@dataclass(slots=True)
class InertiaPage:
    component: str
    props: JsonDict
    url: str
    version: str | None = None
    encrypt_history: bool = False
    clear_history: bool = False

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "component": self.component,
            "props": self.props,
            "url": self.url,
            "version": self.version,
        }
        if self.encrypt_history:
            payload["encryptHistory"] = True
        if self.clear_history:
            payload["clearHistory"] = True
        return payload


@dataclass(slots=True)
class Inertia:
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
        if self.app is not None:
            self.middleware(self.app)

    def middleware(self, app: Any) -> None:
        app.use(self.handle_request)

    def share(self, **props: Any) -> None:
        """Add props that every page receives.

        Called at startup, not per request: the values live on the adapter and
        are merged under each page's own props, which win on a clash.
        """
        self.shared_props.update(props)

    # -- responses --------------------------------------------------------

    async def render(
        self,
        component: str,
        props: Props | None = None,
        # Absorbs the two extra positionals of the old render(request, response,
        # component, props) so the guard below can name the new shape. Without
        # it Python raises first, with an arity message that says nothing about
        # what to write instead.
        *_legacy: Any,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        view_data: Mapping[str, Any] | None = None,
        encrypt_history: bool = False,
        clear_history: bool = False,
        request: Request | None = None,
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
                request and returning one, sync or async.
            status_code: The HTTP status. Inertia expects 200 for pages and
                422 for a form that failed validation.
            headers: Extra response headers.
            view_data: Values for placeholders in the root view, merged over
                the adapter's own ``view_data``. Only used on a first visit.
            encrypt_history: Ask the client to encrypt this history entry.
            clear_history: Ask the client to drop its history state.
            request: The request to answer. Defaults to the current one.

        Returns:
            A response, ready to be returned from the handler.

        Raises:
            OutsideRequestError: If no request is bound and none was passed.
            FileNotFoundError: If a first visit needs the root view and it is
                not where the adapter was told to look.
        """
        if _legacy or not isinstance(component, str):
            raise TypeError(
                _WRONG_ARGUMENTS.format(
                    method="render",
                    expected="the component name",
                    example='return await inertia.render("Home", {"name": "Sillo"})',
                )
            )

        request = request if request is not None else current_request()
        resolved_props = await self._resolve_props(request, component, props or {})
        page = InertiaPage(
            component=component,
            props=resolved_props,
            url=self._request_url(request),
            version=self.current_version(),
            encrypt_history=encrypt_history,
            clear_history=clear_history,
        )
        page_payload = page.to_dict()

        # Vary is on both branches because the two are the same URL: without it
        # a shared cache can serve one visitor's page JSON to another visitor's
        # first, blank-page visit.
        response_headers = {"Vary": "X-Inertia", **(headers or {})}

        if self.is_inertia_request(request):
            return JSONResponse(
                content=page_payload,
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
        # As on render(): absorbs redirect(request, response, location).
        *_legacy: Any,
        status_code: int | None = None,
        request: Request | None = None,
    ) -> BaseResponse:
        """Redirect in a way Inertia's client will follow.

        Args:
            location: Where to send the visitor.
            status_code: Overrides the default, which is 303 after a mutating
                request and 302 otherwise. 303 is not decoration: on a 302 the
                browser repeats the POST against the new URL, so a redirect
                after a successful create would create a second record.
            request: The request to answer. Defaults to the current one.

        Returns:
            A redirect response.
        """
        if _legacy or not isinstance(location, str):
            raise TypeError(
                _WRONG_ARGUMENTS.format(
                    method="redirect",
                    expected="the location",
                    example='return inertia.redirect("/dashboard")',
                )
            )

        request = request if request is not None else current_request()
        code = status_code or (303 if request.method.upper() != "GET" else 302)
        return RedirectResponse(url=location, status_code=code)

    def back(
        self,
        *,
        fallback: str = "/",
        status_code: int | None = None,
        request: Request | None = None,
    ) -> BaseResponse:
        """Redirect to the page the request came from.

        The idiomatic end of an Inertia form post: the client re-renders the
        page it was already on, picking up whatever the handler changed.

        Args:
            fallback: Where to go when there is no Referer — a request made
                outside the client, or one whose referrer policy stripped it.
            status_code: Overrides the 303/302 default.
            request: The request to answer. Defaults to the current one.
        """
        request = request if request is not None else current_request()
        referer = self._header(request, "Referer")
        return self.redirect(
            referer or fallback, status_code=status_code, request=request
        )

    def location(self, url: str, *, status_code: int = 409) -> BaseResponse:
        """Send the client somewhere Inertia does not control.

        A 409 with ``X-Inertia-Location`` tells the client to do a full browser
        visit instead of an XHR one, which is the only way out of an Inertia
        page and into an external URL or a stale asset version.
        """
        return BaseResponse(
            status_code=status_code, headers={"X-Inertia-Location": url}
        )

    # -- handlers ---------------------------------------------------------

    def page(
        self, component: str, **render_options: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Turn a function that returns props into a page handler.

        The handler declares only what it uses, and returns a plain mapping::

            @app.get("/users/{user_id}")
            @inertia.page("Users/Show")
            async def show(user_id: int):
                return {"user": await User.get(id=user_id)}

        Returning a response instead of a mapping passes it through untouched,
        so a handler can still redirect or 404 out of a page::

            @app.post("/users")
            @inertia.page("Users/Create")
            async def create(request: Request):
                ...
                return inertia.redirect("/users")

        Args:
            component: The component to render.
            **render_options: Passed to :meth:`render` on every request the
                handler answers — ``status_code``, ``view_data`` and so on.

        Returns:
            A decorator producing a handler the router can call.
        """

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            accepted = set(inspect.signature(func).parameters)

            @functools.wraps(func)
            async def endpoint(
                request: Request, response: Response, **kwargs: Any
            ) -> Any:
                if "request" in accepted:
                    kwargs["request"] = request
                if "response" in accepted:
                    kwargs["response"] = response

                result = func(**kwargs)
                if inspect.isawaitable(result):
                    result = await result

                # A handler that built its own response has already decided
                # what to send; only a mapping means "render this page".
                if isinstance(result, (BaseResponse, Responder)):
                    return result

                return await self.render(
                    component,
                    result or {},
                    request=request,
                    **render_options,
                )

            # After functools.wraps, which sets __wrapped__: inspect.signature
            # follows that by default and would report the wrapped function's
            # signature, but it stops unwrapping at anything carrying an
            # explicit __signature__.
            endpoint.__signature__ = _endpoint_signature(func)  # type: ignore[attr-defined]
            return endpoint

        return decorate

    async def handle_request(
        self,
        request: Request,
        response: Response,
        call_next: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Bind the request, and turn away clients running stale assets.

        A client holding an older asset version would render the new page
        object against components that no longer match it. Sending it to do a
        full browser visit is how Inertia gets it onto the current build.
        """
        token = bind(self, request)
        try:
            current_version = self.current_version()
            request_version = self._header(request, "X-Inertia-Version")
            if (
                request.method.upper() == "GET"
                and self.is_inertia_request(request)
                and current_version is not None
                and request_version
                and request_version != current_version
            ):
                return self.location(self._request_url(request))
            return await call_next()
        finally:
            unbind(token)

    # -- internals --------------------------------------------------------

    def current_version(self) -> str | None:
        if callable(self.config.version):
            return self.config.version()
        return self.config.version

    def is_inertia_request(self, request: Request | None = None) -> bool:
        request = request if request is not None else current_request()
        return self._header(request, "X-Inertia").lower() == "true"

    async def _resolve_props(
        self,
        request: Request,
        component: str,
        props: Props,
    ) -> JsonDict:
        page_props = _invoke(props, request) if callable(props) else props
        if inspect.isawaitable(page_props):
            page_props = await page_props

        merged = {**self.shared_props, **dict(page_props)}
        partial_keys = self._partial_keys(request, component)
        if partial_keys is not None:
            merged = {
                key: value for key, value in merged.items() if key in partial_keys
            }

        return {
            key: await self._resolve_value(request, value)
            for key, value in merged.items()
        }

    async def _resolve_value(self, request: Request, value: Any) -> Any:
        if isinstance(value, LazyProp):
            value = _invoke(value.callback, request)
        elif callable(value) and not isinstance(value, (str, bytes, bytearray)):
            value = _invoke(value, request)
        if inspect.isawaitable(value):
            return await value
        return value

    def _partial_keys(self, request: Request, component: str) -> set[str] | None:
        partial_component = self._header(request, "X-Inertia-Partial-Component")
        partial_data = self._header(request, "X-Inertia-Partial-Data")
        if partial_component != component or not partial_data:
            return None
        return {item.strip() for item in partial_data.split(",") if item.strip()}

    def _request_url(self, request: Request) -> str:
        path = request.scope.get("path", "/")
        query = request.scope.get("query_string", b"")
        if query:
            return f"{path}?{query.decode('latin-1')}"
        return path

    def _header(self, request: Request, name: str) -> str:
        value = request.headers.get(name)
        return value if value is not None else ""

    def _render_root_view(self, page: JsonDict, view_data: Mapping[str, Any]) -> str:
        root_view = self.config.root_view
        if not root_view.is_file():
            raise FileNotFoundError(f"Inertia root view not found: {root_view}")

        serialized = json.dumps(page, separators=(",", ":"))
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
        return content

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
