"""The parts of the Inertia protocol the 0.0.x adapter did not implement.

Deferred props, merge props, `always`, `except`, `reset`, the error bag and the
303 correction on a mutating redirect. Each one is something the client already
knows how to do and the server was simply never telling it about.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sillo import HttpContext, SilloApp

from sillo_inertia import (
    Inertia,
    always,
    deep_merge,
    defer,
    merge,
    optional,
    render,
    set_errors,
    set_flash,
)

pytestmark = pytest.mark.asyncio

ROOT = '<html><body><div id="{{ root_id }}"></div>{{ inertia }}</body></html>'

INERTIA = {"X-Inertia": "true"}


def write_root(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(ROOT, encoding="utf-8")
    return root


def extract_page(markup: str) -> dict:
    match = re.search(
        r'<script type="application/json" data-page="[^"]*">(.*?)</script>',
        markup,
        re.DOTALL,
    )
    assert match is not None, f"no page script tag in: {markup}"
    return json.loads(match.group(1))


async def client_for(app: SilloApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def partial(component: str, **headers: str) -> dict[str, str]:
    return {**INERTIA, "X-Inertia-Partial-Component": component, **headers}


class TestDeferredProps:
    async def test_a_deferred_prop_is_announced_not_sent(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)
        ran: list[str] = []

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Dashboard",
                {
                    "orders": [1, 2],
                    "revenue": defer(lambda: ran.append("revenue") or 100, "charts"),
                },
            )

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()

        assert "revenue" not in page["props"]
        assert page["deferredProps"] == {"charts": ["revenue"]}
        assert ran == [], "the deferred callback ran on the first response"

    async def test_the_client_fetches_a_deferred_group_by_name(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Dashboard",
                {
                    "orders": [1, 2],
                    "revenue": defer(lambda: 100, "charts"),
                    "funnel": defer(lambda: [1], "charts"),
                    "slow": defer(lambda: "later", "slow"),
                },
            )

        async with await client_for(app) as client:
            first = (await client.get("/", headers=INERTIA)).json()
            follow = (
                await client.get(
                    "/",
                    headers=partial("Dashboard", **{"X-Inertia-Partial-Data": "revenue,funnel"}),
                )
            ).json()

        assert first["deferredProps"] == {
            "charts": ["revenue", "funnel"],
            "slow": ["slow"],
        }
        assert follow["props"]["revenue"] == 100
        assert follow["props"]["funnel"] == [1]
        assert "slow" not in follow["props"], "the other group came along uninvited"

    async def test_a_deferred_prop_can_also_merge(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Feed", {"items": defer(lambda: [1, 2, 3], "page", merge=True)}
            )

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/", headers=partial("Feed", **{"X-Inertia-Partial-Data": "items"})
                )
            ).json()

        assert page["props"]["items"] == [1, 2, 3]
        assert page["mergeProps"] == ["items"]


class TestMergeProps:
    async def test_merge_is_announced(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Feed", {"items": merge([1, 2])})

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()

        assert page["props"]["items"] == [1, 2]
        assert page["mergeProps"] == ["items"]
        assert "deepMergeProps" not in page

    async def test_deep_merge_reports_its_match_key(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Feed", {"orders": deep_merge([{"id": 1}], match_on="id")}
            )

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()

        assert page["deepMergeProps"] == ["orders"]
        assert page["matchPropsOn"] == ["orders.id"]
        assert "mergeProps" not in page

    async def test_reset_suppresses_the_merge_instruction(self, tmp_path):
        """``X-Inertia-Reset`` is the client saying "replace this one".

        The prop is still sent; what changes is that it is no longer named in
        ``mergeProps``, so the client drops what it holds instead of appending
        to it. That is how a filter change empties a paged list rather than
        stacking the new results under the old ones.
        """
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Feed", {"items": merge([9])})

        async with await client_for(app) as client:
            page = (
                await client.get("/", headers={**INERTIA, "X-Inertia-Reset": "items"})
            ).json()

        assert page["props"]["items"] == [9]
        assert "mergeProps" not in page


class TestAlwaysProps:
    async def test_an_always_prop_survives_a_partial_reload(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Home", {"a": 1, "b": 2, "unread": always(7)}
            )

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/", headers=partial("Home", **{"X-Inertia-Partial-Data": "a"})
                )
            ).json()

        assert page["props"]["a"] == 1
        assert page["props"]["unread"] == 7
        assert "b" not in page["props"]


class TestPartialExcept:
    async def test_except_drops_only_what_it_names(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Home", {"a": 1, "b": 2, "c": 3})

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/", headers=partial("Home", **{"X-Inertia-Partial-Except": "b"})
                )
            ).json()

        assert page["props"]["a"] == 1
        assert page["props"]["c"] == 3
        assert "b" not in page["props"]


class TestDottedPartialKeys:
    async def test_a_dotted_key_narrows_a_nested_prop(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Order",
                {
                    "order": {"id": 1, "customer": {"name": "Ada"}, "items": [1, 2]},
                    "other": True,
                },
            )

        async with await client_for(app) as client:
            page = (
                await client.get(
                    "/",
                    headers=partial(
                        "Order", **{"X-Inertia-Partial-Data": "order.customer"}
                    ),
                )
            ).json()

        assert page["props"]["order"] == {"customer": {"name": "Ada"}}
        assert "other" not in page["props"]


class TestErrorsAndFlash:
    async def test_errors_and_flash_are_always_shared(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Home", {})

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()

        assert page["props"]["errors"] == {}
        assert page["props"]["flash"] == {}

    async def test_errors_survive_the_redirect_and_clear_after_one_read(self, tmp_path):
        """The whole reason the bag exists.

        A failed POST redirects, and the errors have to be on the page the
        client lands on — but only that once, or they reappear on every
        subsequent visit to it.
        """
        from sillo.session.middleware import SessionMiddleware

        app = SilloApp()
        app.use(SessionMiddleware(secret_key="test-secret", session_cookie_secure=False))
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.post("/products")
        async def store(ctx: HttpContext):
            set_errors(ctx, {"title": "Title is required."})
            set_flash(ctx, "error", "Could not save the product.")
            from sillo_inertia import back

            return back(fallback="/products/new")

        @app.get("/products/new")
        async def create(ctx: HttpContext):
            return await render("Products/Create", {})

        async with await client_for(app) as client:
            posted = await client.post("/products", headers=INERTIA, follow_redirects=False)
            assert posted.status_code == 303

            first = (await client.get("/products/new", headers=INERTIA)).json()
            second = (await client.get("/products/new", headers=INERTIA)).json()

        assert first["props"]["errors"] == {"title": "Title is required."}
        assert first["props"]["flash"] == {"error": "Could not save the product."}
        assert second["props"]["errors"] == {}, "the bag was not cleared"
        assert second["props"]["flash"] == {}

    async def test_no_session_middleware_is_not_an_error(self, tmp_path):
        """An application that does not use sessions still renders pages — it
        just has no flash. ``ctx.session`` asserts rather than returning a null
        object, and a shared prop must not raise on every page because of it."""
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Home", {})

        async with await client_for(app) as client:
            result = await client.get("/", headers=INERTIA)

        assert result.status_code == 200
        assert result.json()["props"]["errors"] == {}


class TestPropEncoding:
    async def test_a_decimal_reaches_the_page_as_an_exact_string(self, tmp_path):
        """Money is the reason this exists.

        ``json.dumps`` refuses a Decimal outright, and ``str()`` on one read
        back from SQLite gives ``6.7E+2`` — valid JSON, and rendered in the UI
        as that literal text. ``format(value, "f")`` is the only form that is
        both exact and displayable.
        """
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Order",
                {
                    "total": Decimal("670.00"),
                    "scientific": Decimal("6.7E+2"),
                    "tiny": Decimal("0.01"),
                },
            )

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()
            initial = extract_page((await client.get("/")).text)

        assert page["props"]["total"] == "670.00"
        assert page["props"]["scientific"] == "670"
        assert page["props"]["tiny"] == "0.01"
        # The HTML branch serialises separately; it must agree.
        assert initial["props"]["total"] == "670.00"

    async def test_dates_uuids_and_enums_survive(self, tmp_path):
        import enum
        import uuid
        from datetime import date, datetime

        class Status(enum.Enum):
            PAID = "paid"

        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)
        identifier = uuid.uuid4()

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Order",
                {
                    "created_at": datetime(2026, 9, 3, 12, 30),
                    "day": date(2026, 9, 3),
                    "id": identifier,
                    "status": Status.PAID,
                    "tags": {"a"},
                },
            )

        async with await client_for(app) as client:
            props = (await client.get("/", headers=INERTIA)).json()["props"]

        assert props["created_at"] == "2026-09-03T12:30:00"
        assert props["day"] == "2026-09-03"
        assert props["id"] == str(identifier)
        assert props["status"] == "paid"
        assert props["tags"] == ["a"]

    async def test_an_unserialisable_prop_names_the_type(self, tmp_path):
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        class Opaque:
            __slots__ = ()

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render("Home", {"thing": Opaque()})

        async with await client_for(app) as client:
            result = await client.get("/", headers=INERTIA)

        assert result.status_code == 500


class TestRedirectStatusCorrection:
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    async def test_a_302_on_a_mutating_method_becomes_303(self, tmp_path, method):
        """Without this the browser repeats the *method* against the new URL,
        so a redirect after a successful update issues a second update."""
        from sillo.responses import redirect

        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.route("/items/1", methods=["PUT", "PATCH", "DELETE"])
        async def update(ctx: HttpContext):
            return redirect("/items")

        async with await client_for(app) as client:
            result = await getattr(client, method)(
                "/items/1", headers=INERTIA, follow_redirects=False
            )

        assert result.status_code == 303
        assert result.headers["location"] == "/items"

    async def test_a_302_on_a_get_is_left_alone(self, tmp_path):
        from sillo.responses import redirect

        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/old")
        async def old(ctx: HttpContext):
            return redirect("/new")

        async with await client_for(app) as client:
            result = await client.get("/old", headers=INERTIA, follow_redirects=False)

        assert result.status_code == 302


class TestOptionalVersusDeferred:
    async def test_optional_is_never_fetched_on_its_own(self, tmp_path):
        """The difference between the two wrappers, in one page.

        ``optional`` waits to be asked and is not announced; ``defer`` is
        announced, so the client asks without being told to.
        """
        app = SilloApp()
        Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx: HttpContext):
            return await render(
                "Home",
                {"tab": optional(lambda: "tab data"), "chart": defer(lambda: "chart")},
            )

        async with await client_for(app) as client:
            page = (await client.get("/", headers=INERTIA)).json()

        assert "tab" not in page["props"]
        assert "chart" not in page["props"]
        assert page["deferredProps"] == {"default": ["chart"]}


async def test_a_placeholder_with_no_value_is_blanked_not_shipped(tmp_path):
    """A root view asking for `{{ title }}` that nobody supplies must render an
    empty title, not the literal braces.

    What is at stake is not tidiness: the root view is what a crawler reads and
    what a link preview shows, both of which happen before any JavaScript runs.
    A page whose `<title>` says `{{ title }}` says that in Google.
    """
    root = tmp_path / "app.html"
    root.write_text(
        "<html><head><title>{{ title }}</title>{{ inertia_head }}</head>"
        "<body><div id='{{ root_id }}'></div>{{ inertia }}</body></html>"
    )

    adapter = Inertia(root_view=root, base_dir=tmp_path)
    markup = adapter._render_root_view(  # noqa: SLF001
        {"component": "Home", "props": {}, "url": "/", "version": None}, {}
    )

    assert "{{" not in markup
    assert "<title></title>" in markup


async def test_a_supplied_placeholder_still_wins(tmp_path):
    root = tmp_path / "app.html"
    root.write_text("<title>{{ title }}</title>")

    adapter = Inertia(root_view=root, base_dir=tmp_path)
    markup = adapter._render_root_view(  # noqa: SLF001
        {"component": "Home", "props": {}, "url": "/", "version": None},
        {"title": "Northwind"},
    )
    assert markup == "<title>Northwind</title>"
