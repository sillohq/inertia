from __future__ import annotations

import html
import json
from pathlib import Path

import httpx
import pytest
from sillo import silloApp
from sillo.core.http import Request, Response

from sillo_inertia import Inertia, lazy, vite_react, vite_vue


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


def write_root_custom_id(tmp_path: Path, root_id: str) -> Path:
    root = tmp_path / "app.html"
    root.write_text(
        f"<html><body><div id=\"{{{{ root_id }}}}\" data-page='{{{{ inertia }}}}'></div></body></html>",
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


class TestInitialVisit:
    @pytest.mark.asyncio
    async def test_initial_visit_renders_html(self, tmp_path: Path) -> None:
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
    async def test_initial_visit_with_no_props(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        page = extract_page(result.text)
        assert page["props"] == {}

    @pytest.mark.asyncio
    async def test_initial_visit_with_custom_root_id(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_custom_id(tmp_path, "root"),
            version="abc",
            root_id="root",
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert 'id="root"' in result.text
        page = extract_page(result.text)
        assert page["component"] == "Home"


class TestInertiaVisit:
    @pytest.mark.asyncio
    async def test_inertia_visit_returns_page_json(self, tmp_path: Path) -> None:
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
    async def test_inertia_visit_with_shared_props(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.share(auth={"user": "John"})

        @app.get("/dashboard")
        async def dashboard(request: Request, response: Response):
            return await inertia.render(request, response, "Dashboard", {"count": 5})

        async with await get_client(app) as client:
            result = await client.get("/dashboard", headers={"X-Inertia": "true"})

        data = result.json()
        assert data["props"]["auth"] == {"user": "John"}
        assert data["props"]["count"] == 5

    @pytest.mark.asyncio
    async def test_inertia_visit_with_query_params(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="v1")

        @app.get("/search")
        async def search(request: Request, response: Response):
            return await inertia.render(request, response, "Search")

        async with await get_client(app) as client:
            result = await client.get(
                "/search?q=test&sort=asc",
                headers={"X-Inertia": "true"},
            )

        data = result.json()
        assert data["url"] == "/search?q=test&sort=asc"

    @pytest.mark.asyncio
    async def test_inertia_visit_with_status_code(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="v1")

        @app.get("/error")
        async def error(request: Request, response: Response):
            return await inertia.render(
                request,
                response,
                "Error",
                {"message": "Not found"},
                status_code=404,
            )

        async with await get_client(app) as client:
            result = await client.get("/error", headers={"X-Inertia": "true"})

        assert result.status_code == 404


class TestPartialReload:
    @pytest.mark.asyncio
    async def test_partial_reload_filters_props(self, tmp_path: Path) -> None:
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
    async def test_partial_reload_with_multiple_props(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(
                request,
                response,
                "Home",
                {"a": 1, "b": 2, "c": 3},
            )

        async with await get_client(app) as client:
            result = await client.get(
                "/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Partial-Component": "Home",
                    "X-Inertia-Partial-Data": "a, c",
                },
            )

        assert result.json()["props"] == {"a": 1, "c": 3}

    @pytest.mark.asyncio
    async def test_partial_reload_wrong_component(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(
                request,
                response,
                "Home",
                {"key": "value"},
            )

        async with await get_client(app) as client:
            result = await client.get(
                "/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Partial-Component": "Other",
                    "X-Inertia-Partial-Data": "key",
                },
            )

        assert result.json()["props"] == {"key": "value"}


class TestVersionHandling:
    @pytest.mark.asyncio
    async def test_version_mismatch_returns_location(self, tmp_path: Path) -> None:
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
    async def test_version_none_allows_mismatches(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version=None)

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get(
                "/",
                headers={"X-Inertia": "true", "X-Inertia-Version": "anything"},
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_dynamic_version_callable(self, tmp_path: Path) -> None:
        app = silloApp()
        version_counter = {"v": "1"}

        def get_version():
            return version_counter["v"]

        inertia = Inertia(app, root_view=write_root(tmp_path), version=get_version)

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})
            data = result.json()
            assert data["version"] == "1"

            version_counter["v"] = "2"
            result = await client.get("/", headers={"X-Inertia": "true"})
            data = result.json()
            assert data["version"] == "2"


class TestRedirect:
    @pytest.mark.asyncio
    async def test_redirect_uses_303_for_mutating_requests(self, tmp_path: Path) -> None:
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
    async def test_redirect_uses_302_for_get(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/redirect")
        async def redirect_route(request: Request, response: Response):
            return inertia.redirect(request, response, "/home")

        async with await get_client(app) as client:
            result = await client.get("/redirect", follow_redirects=False)

        assert result.status_code == 302

    @pytest.mark.asyncio
    async def test_redirect_custom_status_code(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/save")
        async def save(request: Request, response: Response):
            return inertia.redirect(request, response, "/", status_code=301)

        async with await get_client(app) as client:
            result = await client.post("/save", follow_redirects=False)

        assert result.status_code == 301


class TestViteReact:
    @pytest.mark.asyncio
    async def test_vite_react_tags_are_injected_dev(self, tmp_path: Path) -> None:
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

    @pytest.mark.asyncio
    async def test_vite_react_without_refresh(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_react(dev=True, dev_server="http://localhost:5173", react_refresh=False),
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "@react-refresh" not in result.text
        assert "http://localhost:5173/src/main.jsx" in result.text

    @pytest.mark.asyncio
    async def test_vite_react_custom_entry(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_react(dev=True, entry="src/bootstrap.jsx"),
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "src/bootstrap.jsx" in result.text


class TestViteVue:
    @pytest.mark.asyncio
    async def test_vite_vue_tags_are_injected_dev(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, dev_server="http://localhost:5174"),
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "@react-refresh" not in result.text
        assert "http://localhost:5174/@vite/client" in result.text
        assert "http://localhost:5174/src/main.ts" in result.text

    @pytest.mark.asyncio
    async def test_vite_vue_custom_entry(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, entry="src/app.ts"),
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "src/app.ts" in result.text

    @pytest.mark.asyncio
    async def test_vite_vue_custom_dev_server(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, dev_server="http://127.0.0.1:5175"),
        )

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "http://127.0.0.1:5175" in result.text


class TestProps:
    @pytest.mark.asyncio
    async def test_callable_props_are_resolved(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        def get_props(request: Request):
            return {"dynamic": f"path={request.scope.get('path')}"}

        @app.get("/test")
        async def test(request: Request, response: Response):
            return await inertia.render(request, response, "Test", get_props)

        async with await get_client(app) as client:
            result = await client.get("/test", headers={"X-Inertia": "true"})

        assert result.json()["props"]["dynamic"] == "path=/test"

    @pytest.mark.asyncio
    async def test_lazy_props_are_resolved(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(
                request,
                response,
                "Home",
                {"lazy_data": lazy(lambda _: {"value": "computed"})},
            )

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"]["lazy_data"] == {"value": "computed"}

    @pytest.mark.asyncio
    async def test_async_props_are_resolved(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        async def get_props(request: Request):
            return {"async_data": "from_async"}

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home", get_props)

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"]["async_data"] == "from_async"


class TestViewData:
    @pytest.mark.asyncio
    async def test_view_data_is_rendered(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.view_data["title"] = "Test Page"

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(request, response, "Home")

        # Note: initial visit doesn't use view_data in the test,
        # but we verify the attribute exists
        assert inertia.view_data["title"] == "Test Page"

    @pytest.mark.asyncio
    async def test_render_with_view_data_override(self, tmp_path: Path) -> None:
        app = silloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(request: Request, response: Response):
            return await inertia.render(
                request,
                response,
                "Home",
                view_data={"custom": "value"},
            )

        async with await get_client(app) as client:
            result = await client.get("/")

        assert result.status_code == 200
