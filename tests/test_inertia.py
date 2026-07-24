from __future__ import annotations

import html
import json
from pathlib import Path

import httpx
import pytest
from sillo import silloApp
from sillo.core.http import Request, Response

from sillo_inertia import Inertia, lazy, vite_react


def write_root(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(
        "<html><body><div id=\"{{ root_id }}\" data-page='{{ inertia }}'></div></body></html>",
        encoding="utf-8",
    )
    return root


def write_root_with_head(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(
        "<html><head>{{ inertia_head }}</head><body>"
        "<div id=\"{{ root_id }}\" data-page='{{ inertia }}'></div>"
        "</body></html>",
        encoding="utf-8",
    )
    return root


def extract_page(markup: str) -> dict:
    prefix = "data-page='"
    start = markup.index(prefix) + len(prefix)
    end = markup.index("'", start)
    return json.loads(html.unescape(markup[start:end]))


async def get_client(app: silloApp):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_initial_visit_renders_html(tmp_path: Path) -> None:
    app = silloApp()
    inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
    inertia.share(app_name="Demo")

    @app.get("/")
    async def home(request: Request, response: Response):
        return await inertia.render(request, response, "Home", {"name": "Sillo"})

    async with await get_client(app) as client:
        result = await client.get("/")

    assert result.status_code == 200
    assert result.headers["vary"] == "X-Inertia"
    page = extract_page(result.text)
    assert page["component"] == "Home"
    assert page["props"] == {"app_name": "Demo", "name": "Sillo"}
    assert page["url"] == "/"
    assert page["version"] == "abc"


@pytest.mark.asyncio
async def test_inertia_visit_returns_page_json(tmp_path: Path) -> None:
    app = silloApp()
    inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

    @app.get("/users")
    async def users(request: Request, response: Response):
        return await inertia.render(request, response, "Users/Index", {"users": ["Ada"]})

    async with await get_client(app) as client:
        result = await client.get("/users?page=1", headers={"X-Inertia": "true"})

    assert result.status_code == 200
    assert result.headers["x-inertia"] == "true"
    assert result.json() == {
        "component": "Users/Index",
        "props": {"users": ["Ada"]},
        "url": "/users?page=1",
        "version": "abc",
    }


@pytest.mark.asyncio
async def test_partial_reload_filters_props(tmp_path: Path) -> None:
    app = silloApp()
    inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
    inertia.share(app_name="Demo")

    @app.get("/")
    async def home(request: Request, response: Response):
        return await inertia.render(
            request,
            response,
            "Home",
            {"fresh": lazy(lambda _request: "yes"), "expensive": "skip"},
        )

    async with await get_client(app) as client:
        result = await client.get(
            "/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Partial-Component": "Home",
                "X-Inertia-Partial-Data": "fresh",
            },
        )

    assert result.json()["props"] == {"fresh": "yes"}


@pytest.mark.asyncio
async def test_version_mismatch_returns_location(tmp_path: Path) -> None:
    app = silloApp()
    Inertia(app, root_view=write_root(tmp_path), version="new")

    @app.get("/")
    async def home(request: Request, response: Response):
        return response.json({"unreachable": True})

    async with await get_client(app) as client:
        result = await client.get(
            "/?tab=1",
            headers={"X-Inertia": "true", "X-Inertia-Version": "old"},
        )

    assert result.status_code == 409
    assert result.headers["x-inertia-location"] == "/?tab=1"


@pytest.mark.asyncio
async def test_redirect_uses_303_for_mutating_requests(tmp_path: Path) -> None:
    app = silloApp()
    inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

    @app.post("/save")
    async def save(request: Request, response: Response):
        return inertia.redirect(request, response, "/")

    async with await get_client(app) as client:
        result = await client.post("/save", follow_redirects=False)

    assert result.status_code == 303
    assert result.headers["location"] == "/"


@pytest.mark.asyncio
async def test_vite_react_tags_are_injected(tmp_path: Path) -> None:
    app = silloApp()
    inertia = Inertia(
        app,
        root_view=write_root_with_head(tmp_path),
        version="abc",
        base_dir=tmp_path,
        vite=vite_react(dev=True, dev_server="http://localhost:5174"),
    )

    @app.get("/")
    async def home(request: Request, response: Response):
        return await inertia.render(request, response, "Home")

    async with await get_client(app) as client:
        result = await client.get("/")

    assert "@react-refresh" in result.text
    assert "__vite_plugin_react_preamble_installed__" in result.text
    assert "http://localhost:5174/src/main.jsx" in result.text
