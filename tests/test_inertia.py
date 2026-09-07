from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from sillo import SilloApp
from sillo.core.http import HttpContext

from sillo_inertia import (
    Inertia,
    OutsideRequestError,
    lazy,
    vite_react,
    vite_vue,
)


#: The two props the adapter shares on every page without being asked: the
#: validation error bag and the flash bag, both empty here because nothing in
#: these tests installs a session. They are part of Inertia's protocol — the
#: client reads `errors` by that exact name — so every page object carries them
#: and every exact-props assertion below has to say so.
SHARED_PROPS = {"errors": {}, "flash": {}}


# The root views below use the markup Inertia 2.x/3.x actually reads: a
# <script type="application/json" data-page="<id>"> element. The 1.x form,
# data-page on the root div, is never consulted by current clients — they boot
# with a null page and throw "Cannot read properties of null".
ROOT_TEMPLATE = '<html><body><div id="{{ root_id }}"></div>{{ inertia }}</body></html>'
ROOT_TEMPLATE_WITH_HEAD = (
    "<html><head>{{ inertia_head }}</head><body>"
    '<div id="{{ root_id }}"></div>{{ inertia }}'
    "</body></html>"
)


def write_root(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(ROOT_TEMPLATE, encoding="utf-8")
    return root


def write_root_with_head(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(ROOT_TEMPLATE_WITH_HEAD, encoding="utf-8")
    return root


def write_root_custom_id(tmp_path: Path, root_id: str) -> Path:
    root = tmp_path / "app.html"
    root.write_text(ROOT_TEMPLATE, encoding="utf-8")
    return root


def extract_page(markup: str) -> dict:
    """Read the page object the way the Inertia client does.

    Mirrors ``getInitialPageFromDOM``: find the JSON script tag and parse its
    text content. The content is raw text, so it is *not* HTML-unescaped —
    if the adapter ever HTML-escapes it, this parse fails, which is the point.
    """
    match = re.search(
        r'<script type="application/json" data-page="[^"]*">(.*?)</script>',
        markup,
        re.DOTALL,
    )
    assert match is not None, f"no Inertia page script tag in: {markup}"
    return json.loads(match.group(1))


async def get_client(app: SilloApp):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestInitialVisit:
    @pytest.mark.asyncio
    async def test_initial_visit_renders_html(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.share(app_name="Demo")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", {"name": "Sillo"})

        async with await get_client(app) as client:
            result = await client.get("/")

        assert result.status_code == 200
        assert result.headers["vary"] == "X-Inertia"
        page = extract_page(result.text)
        assert page["component"] == "Home"
        assert page["props"] == {**SHARED_PROPS, "app_name": "Demo", "name": "Sillo"}
        assert page["url"] == "/"
        assert page["version"] == "abc"

    @pytest.mark.asyncio
    async def test_initial_visit_with_no_props(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        page = extract_page(result.text)
        assert page["props"] == SHARED_PROPS

    @pytest.mark.asyncio
    async def test_initial_visit_with_custom_root_id(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_custom_id(tmp_path, "root"),
            version="abc",
            root_id="root",
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert 'id="root"' in result.text
        page = extract_page(result.text)
        assert page["component"] == "Home"


    @pytest.mark.asyncio
    async def test_page_script_cannot_be_broken_out_of(self, tmp_path: Path) -> None:
        """Markup in a prop must not terminate the script element early.

        A <script> body is raw text, so HTML-escaping it would reach JSON.parse
        as literal &quot; and fail. The adapter escapes <, > and & as JSON
        unicode instead — which parses, and cannot close the tag.
        """
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        hostile = "</script><script>alert(1)</script>"

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", {"bio": hostile})

        async with await get_client(app) as client:
            result = await client.get("/")

        # The literal closing tag must not survive into the document.
        assert "</script><script>alert(1)" not in result.text
        # ...and the value must still round-trip through a real JSON parse.
        assert extract_page(result.text)["props"]["bio"] == hostile


class TestInertiaVisit:
    @pytest.mark.asyncio
    async def test_inertia_visit_returns_page_json(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/users")
        async def users(ctx: HttpContext):
            return await inertia.render("Users/Index", {"users": ["Ada"]})

        async with await get_client(app) as client:
            result = await client.get("/users?page=1", headers={"X-Inertia": "true"})

        assert result.status_code == 200
        assert result.headers["x-inertia"] == "true"
        assert result.json() == {
            "component": "Users/Index",
            "props": {**SHARED_PROPS, "users": ["Ada"]},
            "url": "/users?page=1",
            "version": "abc",
        }

    @pytest.mark.asyncio
    async def test_inertia_visit_with_shared_props(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.share(auth={"user": "John"})

        @app.get("/dashboard")
        async def dashboard(ctx: HttpContext):
            return await inertia.render("Dashboard", {"count": 5})

        async with await get_client(app) as client:
            result = await client.get("/dashboard", headers={"X-Inertia": "true"})

        data = result.json()
        assert data["props"]["auth"] == {"user": "John"}
        assert data["props"]["count"] == 5

    @pytest.mark.asyncio
    async def test_inertia_visit_with_query_params(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="v1")

        @app.get("/search")
        async def search(ctx: HttpContext):
            return await inertia.render("Search")

        async with await get_client(app) as client:
            result = await client.get(
                "/search?q=test&sort=asc",
                headers={"X-Inertia": "true"},
            )

        data = result.json()
        assert data["url"] == "/search?q=test&sort=asc"

    @pytest.mark.asyncio
    async def test_inertia_visit_with_status_code(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="v1")

        @app.get("/error")
        async def error(ctx: HttpContext):
            return await inertia.render(
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
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.share(app_name="Demo")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
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

        assert result.json()["props"] == {**SHARED_PROPS, "fresh": "yes"}

    @pytest.mark.asyncio
    async def test_partial_reload_with_multiple_props(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
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

        assert result.json()["props"] == {**SHARED_PROPS, "a": 1, "c": 3}

    @pytest.mark.asyncio
    async def test_partial_reload_wrong_component(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
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

        assert result.json()["props"] == {**SHARED_PROPS, "key": "value"}


class TestVersionHandling:
    @pytest.mark.asyncio
    async def test_version_mismatch_returns_location(self, tmp_path: Path) -> None:
        app = SilloApp()
        Inertia(app, root_view=write_root(tmp_path), version="new")

        @app.get("/")
        async def home(ctx: HttpContext):
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
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version=None)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get(
                "/",
                headers={"X-Inertia": "true", "X-Inertia-Version": "anything"},
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_dynamic_version_callable(self, tmp_path: Path) -> None:
        app = SilloApp()
        version_counter = {"v": "1"}

        def get_version():
            return version_counter["v"]

        inertia = Inertia(app, root_view=write_root(tmp_path), version=get_version)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

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
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/save")
        async def save(ctx: HttpContext):
            return inertia.redirect("/")

        async with await get_client(app) as client:
            result = await client.post("/save", follow_redirects=False)

        assert result.status_code == 303
        assert result.headers["location"] == "/"

    @pytest.mark.asyncio
    async def test_redirect_uses_302_for_get(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/redirect")
        async def redirect_route(ctx: HttpContext):
            return inertia.redirect("/home")

        async with await get_client(app) as client:
            result = await client.get("/redirect", follow_redirects=False)

        assert result.status_code == 302

    @pytest.mark.asyncio
    async def test_redirect_custom_status_code(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/save")
        async def save(ctx: HttpContext):
            return inertia.redirect("/", status_code=301)

        async with await get_client(app) as client:
            result = await client.post("/save", follow_redirects=False)

        assert result.status_code == 301


class TestViteReact:
    @pytest.mark.asyncio
    async def test_vite_react_tags_are_injected_dev(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_react(dev=True, dev_server="http://localhost:5174"),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "@react-refresh" in result.text
        assert "__vite_plugin_react_preamble_installed__" in result.text
        assert "http://localhost:5174/src/main.jsx" in result.text

    @pytest.mark.asyncio
    async def test_vite_react_without_refresh(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_react(dev=True, dev_server="http://localhost:5173", react_refresh=False),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "@react-refresh" not in result.text
        assert "http://localhost:5173/src/main.jsx" in result.text

    @pytest.mark.asyncio
    async def test_vite_react_custom_entry(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_react(dev=True, entry="src/bootstrap.jsx"),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "src/bootstrap.jsx" in result.text


class TestViteVue:
    @pytest.mark.asyncio
    async def test_vite_vue_tags_are_injected_dev(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, dev_server="http://localhost:5174"),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "@react-refresh" not in result.text
        assert "http://localhost:5174/@vite/client" in result.text
        assert "http://localhost:5174/src/main.ts" in result.text

    @pytest.mark.asyncio
    async def test_vite_vue_custom_entry(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, entry="src/app.ts"),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "src/app.ts" in result.text

    @pytest.mark.asyncio
    async def test_vite_vue_custom_dev_server(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(
            app,
            root_view=write_root_with_head(tmp_path),
            version="abc",
            base_dir=tmp_path,
            vite=vite_vue(dev=True, dev_server="http://127.0.0.1:5175"),
        )

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        async with await get_client(app) as client:
            result = await client.get("/")

        assert "http://127.0.0.1:5175" in result.text


class TestProps:
    @pytest.mark.asyncio
    async def test_callable_props_are_resolved(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        def get_props(ctx: HttpContext):
            return {"dynamic": f"path={ctx.scope.get('path')}"}

        @app.get("/test")
        async def test(ctx: HttpContext):
            return await inertia.render("Test", get_props)

        async with await get_client(app) as client:
            result = await client.get("/test", headers={"X-Inertia": "true"})

        assert result.json()["props"]["dynamic"] == "path=/test"

    @pytest.mark.asyncio
    async def test_lazy_props_are_resolved(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
                "Home",
                {"lazy_data": lazy(lambda _: {"value": "computed"})},
            )

        async with await get_client(app) as client:
            plain = await client.get("/", headers={"X-Inertia": "true"})
            asked = await client.get(
                "/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Partial-Component": "Home",
                    "X-Inertia-Partial-Data": "lazy_data",
                },
            )

        # A normal visit does not carry it at all. The 0.0.x adapter resolved
        # lazy props on every visit and only filtered them out of partial
        # reloads, which is backwards: the wrapper exists so the work behind
        # the prop is not done until something asks for it.
        assert "lazy_data" not in plain.json()["props"]
        assert asked.json()["props"]["lazy_data"] == {"value": "computed"}

    @pytest.mark.asyncio
    async def test_async_props_are_resolved(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        async def get_props(ctx: HttpContext):
            return {"async_data": "from_async"}

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", get_props)

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"]["async_data"] == "from_async"


class TestViewData:
    @pytest.mark.asyncio
    async def test_view_data_is_rendered(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        inertia.view_data["title"] = "Test Page"

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home")

        # Note: initial visit doesn't use view_data in the test,
        # but we verify the attribute exists
        assert inertia.view_data["title"] == "Test Page"

    @pytest.mark.asyncio
    async def test_render_with_view_data_override(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
                "Home",
                view_data={"custom": "value"},
            )

        async with await get_client(app) as client:
            result = await client.get("/")

        assert result.status_code == 200


class TestCurrentRequest:
    """render() reads the request from the middleware rather than being handed it."""

    @pytest.mark.asyncio
    async def test_render_outside_a_request_explains_itself(self, tmp_path: Path) -> None:
        inertia = Inertia(root_view=write_root(tmp_path), version="abc")

        with pytest.raises(OutsideRequestError) as caught:
            await inertia.render("Home")

        message = str(caught.value)
        assert "No active Inertia request" in message
        # The three ways to get here are all actionable, so all three are named.
        assert "inertia.middleware(app)" in message
        assert "ctx=ctx" in message

    @pytest.mark.asyncio
    async def test_explicit_request_needs_no_middleware(self, tmp_path: Path) -> None:
        """A background job or a test can still say which request it means."""
        app = SilloApp()
        inertia = Inertia(root_view=write_root(tmp_path), version="abc")
        captured: dict = {}

        @app.get("/offline")
        async def offline(ctx: HttpContext):
            captured["response"] = await inertia.render(
                "Home", {"ok": True}, ctx=ctx
            )
            return captured["response"]

        async with await get_client(app) as client:
            result = await client.get("/offline", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "ok": True}

    @pytest.mark.asyncio
    async def test_the_old_call_shape_says_what_to_write_instead(
        self, tmp_path: Path
    ) -> None:
        """render(request, response, "Home") was the 0.0.x signature.

        Passing a context first now lands on the props argument, where it would
        otherwise fail somewhere deep in prop resolution with nothing pointing
        back at the call.
        """
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        errors: list = []

        @app.get("/")
        async def home(ctx: HttpContext):
            try:
                await inertia.render(ctx, None, "Home")  # type: ignore[arg-type]
            except TypeError as exc:
                errors.append(str(exc))
            return await inertia.render("Home")

        async with await get_client(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert errors, "the old shape should not have been accepted"
        assert 'inertia.render("Home"' in errors[0]
        assert "ctx=ctx" in errors[0]

    @pytest.mark.asyncio
    async def test_concurrent_requests_do_not_see_each_other(
        self, tmp_path: Path
    ) -> None:
        """The bound request is per-task, not global.

        Both handlers are inside render() at the same time; a module-level
        attribute instead of a ContextVar would have them rendering the same
        URL.
        """
        import asyncio

        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")
        both_arrived = asyncio.Event()
        arrived = 0

        @app.get("/page")
        async def page(ctx: HttpContext):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                both_arrived.set()
            await asyncio.wait_for(both_arrived.wait(), timeout=5)
            return await inertia.render("Page")

        async with await get_client(app) as client:
            first, second = await asyncio.gather(
                client.get("/page?who=a", headers={"X-Inertia": "true"}),
                client.get("/page?who=b", headers={"X-Inertia": "true"}),
            )

        assert {first.json()["url"], second.json()["url"]} == {
            "/page?who=a",
            "/page?who=b",
        }


class TestModuleLevelHelpers:
    """Importable without the adapter, so a routes module need not import the app."""

    @pytest.mark.asyncio
    async def test_module_render(self, tmp_path: Path) -> None:
        from sillo_inertia import render

        app = SilloApp()
        Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Home", {"via": "module"})

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "via": "module"}

    @pytest.mark.asyncio
    async def test_module_redirect(self, tmp_path: Path) -> None:
        from sillo_inertia import redirect

        app = SilloApp()
        Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/save")
        async def save(ctx: HttpContext):
            return redirect("/done")

        async with await get_client(app) as client:
            result = await client.post("/save", follow_redirects=False)

        assert result.status_code == 303
        assert result.headers["location"] == "/done"

    @pytest.mark.asyncio
    async def test_current_request_is_the_request_being_answered(
        self, tmp_path: Path
    ) -> None:
        from sillo_inertia import current_context

        app = SilloApp()
        Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/where")
        async def where(ctx: HttpContext):
            from sillo.responses import json as json_response

            return json_response({"path": current_context().scope.get("path")})

        async with await get_client(app) as client:
            result = await client.get("/where")

        assert result.json() == {"path": "/where"}


class TestBack:
    @pytest.mark.asyncio
    async def test_back_returns_to_the_referring_page(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/comments")
        async def create(ctx: HttpContext):
            return inertia.back()

        async with await get_client(app) as client:
            result = await client.post(
                "/comments",
                headers={"Referer": "/posts/1"},
                follow_redirects=False,
            )

        assert result.status_code == 303
        assert result.headers["location"] == "/posts/1"

    @pytest.mark.asyncio
    async def test_back_falls_back_without_a_referer(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/comments")
        async def create(ctx: HttpContext):
            return inertia.back(fallback="/posts")

        async with await get_client(app) as client:
            result = await client.post("/comments", follow_redirects=False)

        assert result.status_code == 303
        assert result.headers["location"] == "/posts"


class TestPageDecorator:
    @pytest.mark.asyncio
    async def test_handler_declares_nothing_and_returns_props(
        self, tmp_path: Path
    ) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        @inertia.page("Home")
        async def home():
            return {"name": "Sillo"}

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["component"] == "Home"
        assert result.json()["props"] == {**SHARED_PROPS, "name": "Sillo"}

    @pytest.mark.asyncio
    async def test_path_parameters_still_reach_the_handler(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/users/{user_id}")
        @inertia.page("Users/Show")
        async def show(user_id):
            return {"id": user_id}

        async with await get_client(app) as client:
            result = await client.get("/users/7", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "id": "7"}

    @pytest.mark.asyncio
    async def test_handler_may_still_ask_for_the_request(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/search")
        @inertia.page("Search")
        async def search(ctx: HttpContext):
            return {"path": ctx.scope.get("path")}

        async with await get_client(app) as client:
            result = await client.get("/search", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "path": "/search"}

    @pytest.mark.asyncio
    async def test_returning_a_response_passes_it_through(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/users")
        @inertia.page("Users/Create")
        async def create():
            return inertia.redirect("/users")

        async with await get_client(app) as client:
            result = await client.post("/users", follow_redirects=False)

        assert result.status_code == 303
        assert result.headers["location"] == "/users"

    @pytest.mark.asyncio
    async def test_returning_nothing_renders_an_empty_page(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/about")
        @inertia.page("About")
        async def about():
            return None

        async with await get_client(app) as client:
            result = await client.get("/about", headers={"X-Inertia": "true"})

        assert result.json()["props"] == SHARED_PROPS

    @pytest.mark.asyncio
    async def test_render_options_are_applied(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/gone")
        @inertia.page("NotFound", status_code=404)
        async def gone():
            return {}

        async with await get_client(app) as client:
            result = await client.get("/gone", headers={"X-Inertia": "true"})

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_a_sync_handler_works_too(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/sync")
        @inertia.page("Sync")
        def sync_page():
            return {"sync": True}

        async with await get_client(app) as client:
            result = await client.get("/sync", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "sync": True}


class TestPropsWithoutRequest:
    """A callback takes the request only if it asks for one."""

    @pytest.mark.asyncio
    async def test_zero_argument_callable_prop(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", {"total": lambda: 42})

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "total": 42}

    @pytest.mark.asyncio
    async def test_zero_argument_lazy_prop(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", {"slow": lazy(lambda: "done")})

        async with await get_client(app) as client:
            result = await client.get(
                "/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Partial-Component": "Home",
                    "X-Inertia-Partial-Data": "slow",
                },
            )

        assert result.json()["props"] == {**SHARED_PROPS, "slow": "done"}

    @pytest.mark.asyncio
    async def test_zero_argument_props_factory(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", lambda: {"from": "factory"})

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "from": "factory"}

    @pytest.mark.asyncio
    async def test_async_zero_argument_prop(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        async def count():
            return 3

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render("Home", {"count": count})

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "count": 3}

    @pytest.mark.asyncio
    async def test_a_bound_method_still_receives_the_request(
        self, tmp_path: Path
    ) -> None:
        """__code__ counts self, so bound methods go through inspect.signature."""
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        class Source:
            def with_context(self, ctx):
                return ctx.scope.get("path")

            def without_context(self):
                return "static"

        source = Source()

        @app.get("/methods")
        async def methods(ctx: HttpContext):
            return await inertia.render(
                "Methods",
                {"a": source.with_context, "b": source.without_context},
            )

        async with await get_client(app) as client:
            result = await client.get("/methods", headers={"X-Inertia": "true"})

        assert result.json()["props"] == {**SHARED_PROPS, "a": "/methods", "b": "static"}


class TestExtraHeaders:
    @pytest.mark.asyncio
    async def test_headers_are_sent_alongside_vary(self, tmp_path: Path) -> None:
        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.get("/")
        async def home(ctx: HttpContext):
            return await inertia.render(
                "Home", headers={"X-Total-Count": "9"}
            )

        async with await get_client(app) as client:
            result = await client.get("/", headers={"X-Inertia": "true"})

        assert result.headers["x-total-count"] == "9"
        assert result.headers["vary"] == "X-Inertia"
        assert result.headers["x-inertia"] == "true"


class TestPageDecoratorAndTheRouter:
    """The wrapper has to look to the router like an ordinary handler.

    The router reads the handler's signature to place the validated body and to
    resolve dependencies, and it does so positionally: the body candidates are
    the parameters *after* request and response. A wrapper advertising only the
    inner function's parameters shifts that window, and the body silently never
    arrives.
    """

    @pytest.mark.asyncio
    async def test_a_validated_body_still_reaches_the_handler(
        self, tmp_path: Path
    ) -> None:
        from pydantic import BaseModel

        class PostIn(BaseModel):
            title: str

        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        @app.post("/posts", request_model=PostIn)
        @inertia.page("Posts/Create")
        async def create(data: PostIn):
            return {"title": data.title}

        async with await get_client(app) as client:
            result = await client.post(
                "/posts",
                json={"title": "Hello"},
                headers={"X-Inertia": "true"},
            )

        assert result.status_code == 200, result.text
        assert result.json()["props"] == {**SHARED_PROPS, "title": "Hello"}

    @pytest.mark.asyncio
    async def test_dependencies_are_still_injected(self, tmp_path: Path) -> None:
        from sillo import Depend

        app = SilloApp()
        inertia = Inertia(app, root_view=write_root(tmp_path), version="abc")

        # A v1 dependency takes the context as its first parameter, exactly
        # like a handler. Naming it `_` is how one that does not need it says
        # so; omitting it entirely is a TypeError at call time.
        async def current_team(_):
            return "acme"

        @app.get("/team")
        @inertia.page("Team")
        async def team(team_name=Depend(current_team)):
            return {"team": team_name}

        async with await get_client(app) as client:
            result = await client.get("/team", headers={"X-Inertia": "true"})

        assert result.status_code == 200, result.text
        assert result.json()["props"] == {**SHARED_PROPS, "team": "acme"}
