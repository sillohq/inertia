from __future__ import annotations

import html
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sillo.core.http import Request, Response

from .config import InertiaConfig
from .props import HtmlString, LazyProp
from .vite import ViteReactOptions, render_vite_react_tags

JsonDict = dict[str, Any]
Props = Mapping[str, Any] | Callable[
    [Request], Mapping[str, Any] | Awaitable[Mapping[str, Any]]
]


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
    vite: ViteReactOptions | None = None
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
        self.shared_props.update(props)

    async def render(
        self,
        request: Request,
        response: Response,
        component: str,
        props: Props | None = None,
        *,
        status_code: int = 200,
        view_data: Mapping[str, Any] | None = None,
        encrypt_history: bool = False,
        clear_history: bool = False,
    ) -> Response:
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
        headers = {"Vary": "X-Inertia", "X-Inertia": "true"}

        if self.is_inertia_request(request):
            return response.json(page_payload, status_code=status_code, headers=headers)

        markup = self._render_root_view(page_payload, view_data or {})
        return response.html(markup, status_code=status_code, headers={"Vary": "X-Inertia"})

    def redirect(
        self,
        request: Request,
        response: Response,
        location: str,
        *,
        status_code: int | None = None,
    ) -> Response:
        code = status_code or (303 if request.method.upper() != "GET" else 302)
        return response.redirect(location, status_code=code)

    async def location(
        self,
        response: Response,
        url: str,
        *,
        status_code: int = 409,
    ) -> Response:
        return response.empty(status_code=status_code).set_header("X-Inertia-Location", url)

    async def handle_request(
        self,
        request: Request,
        response: Response,
        call_next: Callable[[], Awaitable[Any]],
    ) -> Any:
        current_version = self.current_version()
        request_version = self._header(request, "X-Inertia-Version")
        if (
            request.method.upper() == "GET"
            and self.is_inertia_request(request)
            and current_version is not None
            and request_version
            and request_version != current_version
        ):
            return await self.location(response, self._request_url(request))
        return await call_next()

    def current_version(self) -> str | None:
        if callable(self.config.version):
            return self.config.version()
        return self.config.version

    def is_inertia_request(self, request: Request) -> bool:
        return self._header(request, "X-Inertia").lower() == "true"

    async def _resolve_props(
        self,
        request: Request,
        component: str,
        props: Props,
    ) -> JsonDict:
        page_props = props(request) if callable(props) else props
        if inspect.isawaitable(page_props):
            page_props = await page_props

        merged = {**self.shared_props, **dict(page_props)}
        partial_keys = self._partial_keys(request, component)
        if partial_keys is not None:
            merged = {key: value for key, value in merged.items() if key in partial_keys}

        return {
            key: await self._resolve_value(request, value)
            for key, value in merged.items()
        }

    async def _resolve_value(self, request: Request, value: Any) -> Any:
        if isinstance(value, LazyProp):
            value = value.callback(request)
        elif callable(value) and not isinstance(value, (str, bytes, bytearray)):
            value = value(request)
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

        encoded_page = html.escape(json.dumps(page, separators=(",", ":")), quote=True)
        replacements = {
            "inertia": encoded_page,
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

    def _view_value(self, value: Any) -> str:
        if isinstance(value, HtmlString):
            return value.value
        return html.escape(str(value), quote=True)

    def _head_tags(self) -> str:
        if self.vite is None:
            return ""
        return render_vite_react_tags(self.vite, Path(self.base_dir))
