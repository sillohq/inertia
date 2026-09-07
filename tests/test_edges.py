"""The paths the happy-path suite does not reach.

Error cases, the escape hatches, and the conditions on the version gate.
Each of these is a branch that only runs when something has gone wrong or a
less common option was used, which is exactly where an adapter accumulates
bugs nobody notices until a user hits them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from sillo import SilloApp

from sillo_inertia import (
    Inertia,
    back,
    lazy,
    location,
    raw,
    redirect,
    render,
)


#: The two props the adapter shares on every page without being asked: the
#: validation error bag and the flash bag, both empty here because nothing in
#: these tests installs a session. They are part of Inertia's protocol — the
#: client reads `errors` by that exact name — so every page object carries them
#: and every exact-props assertion below has to say so.
SHARED_PROPS = {"errors": {}, "flash": {}}

ROOT = '<html><body><div id="{{ root_id }}"></div>{{ inertia }}</body></html>'


def write_root(tmp_path: Path, template: str = ROOT) -> Path:
    root = tmp_path / "app.html"
    root.write_text(template, encoding="utf-8")
    return root


def extract_page(markup: str) -> dict:
    match = re.search(
        r'<script type="application/json" data-page="[^"]*">(.*?)</script>',
        markup,
        re.DOTALL,
    )
    assert match is not None, f"no page script tag in: {markup}"
    return json.loads(match.group(1))


async def client_for(app: SilloApp):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )




class TestTheRootView:
    async def test_a_missing_root_view_names_the_path(self, tmp_path):
        """A first visit is the only thing that reads the root view, so a
        wrong path is invisible until a browser navigates directly to a page
        -- typically after every Inertia visit has worked fine.
        """
        app = SilloApp()
        Inertia(app=app, root_view=tmp_path / "nope" / "app.html", base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {})

        # Sillo's ServerErrorMiddleware catches it, so this surfaces as a 500
        # rather than propagating out of the client. What matters is that the
        # failure is loud and names the path it looked in -- "not found"
        # without a path sends the reader to the wrong file.
        async with await client_for(app) as client:
            response = await client.get("/")

        assert response.status_code == 500
        assert "Inertia root view not found" in response.text
        assert "app.html" in response.text

    async def test_an_inertia_visit_never_touches_the_root_view(self, tmp_path):
        """The XHR branch returns JSON, so a missing root view must not break
        it -- otherwise one misconfiguration takes down every page rather
        than only first visits."""
        app = SilloApp()
        Inertia(app=app, root_view=tmp_path / "missing.html", base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {"ok": True})

        async with await client_for(app) as client:
            response = await client.get("/", headers={"X-Inertia": "true"})

        assert response.status_code == 200
        assert response.json()["props"] == {**SHARED_PROPS, "ok": True}


class TestViewDataEscaping:
    async def test_a_view_value_is_escaped(self, tmp_path):
        root = write_root(
            tmp_path, '<html><head><title>{{ title }}</title></head><body>{{ inertia }}</body></html>'
        )

        app = SilloApp()
        Inertia(app=app, root_view=root, base_dir=tmp_path, view_data={"title": "<script>x</script>"})

        @app.get("/")
        async def home(ctx):
            return await render("Home", {})

        async with await client_for(app) as client:
            body = (await client.get("/")).text

        assert "<script>x</script>" not in body.split("{{")[0]
        assert "&lt;script&gt;" in body

    async def test_raw_marks_a_value_as_markup(self, tmp_path):
        """The escape hatch for a value that really is markup -- a preloaded
        meta block, an SSR fragment."""
        root = write_root(
            tmp_path, "<html><head>{{ meta }}</head><body>{{ inertia }}</body></html>"
        )

        app = SilloApp()
        Inertia(
            app=app,
            root_view=root,
            base_dir=tmp_path,
            view_data={"meta": raw('<meta name="x" content="y">')},
        )

        @app.get("/")
        async def home(ctx):
            return await render("Home", {})

        async with await client_for(app) as client:
            body = (await client.get("/")).text

        assert '<meta name="x" content="y">' in body

    async def test_per_render_view_data_overrides_the_adapter(self, tmp_path):
        root = write_root(
            tmp_path, "<html><head><title>{{ title }}</title></head><body>{{ inertia }}</body></html>"
        )

        app = SilloApp()
        Inertia(app=app, root_view=root, base_dir=tmp_path, view_data={"title": "default"})

        @app.get("/")
        async def home(ctx):
            return await render("Home", {}, view_data={"title": "specific"})

        async with await client_for(app) as client:
            body = (await client.get("/")).text

        assert "<title>specific</title>" in body


class TestTheVersionGate:
    """Only a GET, only from the client, only when both versions are known."""

    def _app(self, tmp_path, version="v2"):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path, version=version)

        @app.get("/page")
        async def page(ctx):
            return await render("Page", {})

        @app.post("/page")
        async def submit(ctx):
            return await render("Page", {})

        return app

    async def test_a_stale_get_is_sent_to_reload(self, tmp_path):
        async with await client_for(self._app(tmp_path)) as client:
            response = await client.get(
                "/page", headers={"X-Inertia": "true", "X-Inertia-Version": "v1"}
            )

        assert response.status_code == 409
        assert response.headers["X-Inertia-Location"] == "/page"

    async def test_a_stale_post_is_not_interrupted(self, tmp_path):
        """Version checking a mutating request would throw away the body and
        turn a submitted form into a silent no-op. Inertia's protocol only
        version-checks GET for exactly that reason.
        """
        async with await client_for(self._app(tmp_path)) as client:
            response = await client.post(
                "/page", headers={"X-Inertia": "true", "X-Inertia-Version": "v1"}
            )

        assert response.status_code == 200

    async def test_a_plain_browser_visit_is_not_interrupted(self, tmp_path):
        """A first visit has no assets loaded yet, so there is nothing stale
        to correct -- and a 409 to a browser renders as an error page."""
        async with await client_for(self._app(tmp_path)) as client:
            response = await client.get("/page", headers={"X-Inertia-Version": "v1"})

        assert response.status_code == 200

    async def test_a_client_that_sends_no_version_is_left_alone(self, tmp_path):
        async with await client_for(self._app(tmp_path)) as client:
            response = await client.get("/page", headers={"X-Inertia": "true"})

        assert response.status_code == 200

    async def test_the_reload_location_keeps_the_query_string(self, tmp_path):
        """The client is being told to re-visit *this* URL. Dropping the query
        sends the user to a different page than the one they asked for."""
        async with await client_for(self._app(tmp_path)) as client:
            response = await client.get(
                "/page?tab=settings&page=2",
                headers={"X-Inertia": "true", "X-Inertia-Version": "v1"},
            )

        assert response.headers["X-Inertia-Location"] == "/page?tab=settings&page=2"


class TestModuleLevelBackAndLocation:
    """``back`` and ``location`` imported directly, as a routes module uses
    them -- without importing the application that owns the adapter."""

    async def test_back_follows_the_referer(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.post("/submit")
        async def submit(ctx):
            return back(fallback="/fallback")

        async with await client_for(app) as client:
            response = await client.post(
                "/submit", headers={"Referer": "/origin"}, follow_redirects=False
            )

        assert response.status_code == 303
        assert response.headers["location"] == "/origin"

    async def test_back_uses_the_fallback_without_a_referer(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.post("/submit")
        async def submit(ctx):
            return back(fallback="/fallback")

        async with await client_for(app) as client:
            response = await client.post("/submit", follow_redirects=False)

        assert response.headers["location"] == "/fallback"

    async def test_location_forces_a_full_visit(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/leave")
        async def leave(ctx):
            return location("https://example.com/elsewhere")

        async with await client_for(app) as client:
            response = await client.get("/leave", headers={"X-Inertia": "true"})

        assert response.status_code == 409
        assert response.headers["X-Inertia-Location"] == "https://example.com/elsewhere"


class TestHistoryFlags:
    async def test_encrypt_history_reaches_the_page_object(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {}, encrypt_history=True)

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert page["encryptHistory"] is True

    async def test_clear_history_reaches_the_page_object(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {}, clear_history=True)

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert page["clearHistory"] is True

    async def test_the_flags_are_absent_when_not_asked_for(self, tmp_path):
        """Sending them as ``false`` on every page would be noise in a payload
        that ships on every navigation."""
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {})

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert "encryptHistory" not in page
        assert "clearHistory" not in page


class TestCaching:
    async def test_vary_is_set_on_both_branches(self, tmp_path):
        """The two responses share a URL and differ only by request header.

        Without ``Vary: X-Inertia`` a shared cache can hand one visitor's page
        JSON to another visitor's first visit, which renders as a blank page
        with JSON in it.
        """
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {})

        async with await client_for(app) as client:
            first = await client.get("/")
            xhr = await client.get("/", headers={"X-Inertia": "true"})

        assert first.headers["Vary"] == "X-Inertia"
        assert xhr.headers["Vary"] == "X-Inertia"


class TestPartialReloadsAndLazyProps:
    async def test_a_lazy_prop_is_skipped_unless_named(self, tmp_path):
        """The whole point of ``lazy``: the callback must not run when the
        client did not ask for it."""
        calls: list[str] = []

        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render(
                "Home",
                {
                    "cheap": 1,
                    "expensive": lazy(lambda: calls.append("ran") or "value"),
                },
            )

        async with await client_for(app) as client:
            await client.get(
                "/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Partial-Component": "Home",
                    "X-Inertia-Partial-Data": "cheap",
                },
            )

        assert calls == [], "the lazy callback ran for a prop nobody asked for"

    async def test_a_lazy_prop_runs_when_named(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {"cheap": 1, "expensive": lazy(lambda: "value")})

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/",
                    headers={
                        "X-Inertia": "true",
                        "X-Inertia-Partial-Component": "Home",
                        "X-Inertia-Partial-Data": "expensive",
                    },
                )
            ).json()

        assert page["props"] == {**SHARED_PROPS, "expensive": "value"}

    async def test_a_shared_prop_can_be_partially_reloaded(self, tmp_path):
        app = SilloApp()
        inertia = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)
        inertia.share(auth={"user": "ada"})

        @app.get("/")
        async def home(ctx):
            return await render("Home", {"page": 1})

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/",
                    headers={
                        "X-Inertia": "true",
                        "X-Inertia-Partial-Component": "Home",
                        "X-Inertia-Partial-Data": "auth",
                    },
                )
            ).json()

        assert page["props"] == {**SHARED_PROPS, "auth": {"user": "ada"}}

    async def test_whitespace_around_partial_names_is_tolerated(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {"a": 1, "b": 2, "c": 3})

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/",
                    headers={
                        "X-Inertia": "true",
                        "X-Inertia-Partial-Component": "Home",
                        "X-Inertia-Partial-Data": " a , b ",
                    },
                )
            ).json()

        assert page["props"] == {**SHARED_PROPS, "a": 1, "b": 2}


class TestPropsThatLookLikeMarkup:
    async def test_a_prop_cannot_close_the_script_tag(self, tmp_path):
        """The page object is embedded in a ``<script>``, whose content is raw
        text. A prop containing ``</script>`` would end the element early and
        drop the rest of the JSON into the document as markup.
        """
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render(
                "Home", {"bio": "</script><img src=x onerror=alert(1)>"}
            )

        async with await client_for(app) as client:
            body = (await client.get("/")).text

        script = re.search(
            r'<script type="application/json" data-page="[^"]*">(.*?)</script>',
            body,
            re.DOTALL,
        )
        assert script is not None
        content = script.group(1)

        # The property that matters: no literal angle bracket survives inside
        # the script content, so nothing in a prop can start or end an element.
        # The payload is still *present* -- as `</script>` -- which
        # is correct, and is why asserting on the substring alone proves
        # nothing.
        assert "<" not in content
        assert ">" not in content
        assert "\\u003c" in content

        # And it must still survive the round trip as data.
        assert extract_page(body)["props"]["bio"] == "</script><img src=x onerror=alert(1)>"

    async def test_a_prop_with_ampersands_parses_back_unchanged(self, tmp_path):
        """``&`` is escaped as ``\\u0026`` rather than ``&amp;``: the content
        of a script element is not HTML, so an entity would reach JSON.parse
        verbatim and fail."""
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            return await render("Home", {"q": "a & b <c> d"})

        async with await client_for(app) as client:
            body = (await client.get("/")).text

        assert "&amp;" not in body
        assert extract_page(body)["props"]["q"] == "a & b <c> d"
