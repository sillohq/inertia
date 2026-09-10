"""The branches that only run for unusual callables and misuse.

Small surface, but each of these is a fallback that exists precisely because
the normal path does not apply -- so if one is wrong, it is wrong exactly
when something unusual is already going on.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sillo import SilloApp

from sillo_inertia import Inertia, OutsideRequestError, render
from sillo_inertia.adapter import _wants_context
from sillo_inertia.context import active, current_inertia, current_context


#: The two props the adapter shares on every page without being asked: the
#: validation error bag and the flash bag, both empty here because nothing in
#: these tests installs a session. They are part of Inertia's protocol — the
#: client reads `errors` by that exact name — so every page object carries them
#: and every exact-props assertion below has to say so.
SHARED_PROPS = {"errors": {}, "flash": {}}

ROOT = '<html><body><div id="{{ root_id }}"></div>{{ inertia }}</body></html>'


def write_root(tmp_path: Path) -> Path:
    root = tmp_path / "app.html"
    root.write_text(ROOT, encoding="utf-8")
    return root


async def client_for(app: SilloApp):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


class TestWhetherACallbackWantsTheRequest:
    """Props callbacks come in both shapes, and the adapter has to tell them
    apart without calling them first."""

    def test_a_lambda_taking_nothing(self):
        assert _wants_context(lambda: 1) is False

    def test_a_lambda_taking_the_request(self):
        assert _wants_context(lambda request: request) is True

    def test_a_function_with_varargs_counts_as_wanting_it(self):
        def callback(*args):
            return args

        assert _wants_context(callback) is True

    def test_a_bound_method_ignores_its_self_parameter(self):
        class Props:
            def value(self):
                return 1

            def with_request(self, request):
                return request

        assert _wants_context(Props().value) is False
        assert _wants_context(Props().with_request) is True

    @pytest.mark.parametrize("builtin", [min, int, range])
    def test_a_builtin_with_no_readable_signature_is_given_the_request(self, builtin):
        """``inspect.signature`` raises ValueError for some C callables.

        Assuming the request is wanted is the safe default: handing one to a
        callback that ignores it raises immediately and visibly, whereas
        withholding it from one that needs it fails the same way -- but the
        adapter cannot tell which, so it picks the case that is true of every
        callback written against the documented signature.
        """
        assert _wants_context(builtin) is True

    def test_a_callable_object_is_read_through_its_call(self):
        class Callable:
            def __call__(self, request):
                return request

        assert _wants_context(Callable()) is True


class TestTheContextHelpers:
    def test_active_is_none_outside_a_request(self):
        assert active() is None

    def test_current_inertia_outside_a_request_explains_itself(self):
        with pytest.raises(OutsideRequestError) as caught:
            current_inertia()

        message = str(caught.value)
        assert "No active Inertia request" in message
        # The message is the whole value of this error: it has to name all
        # three ways of getting here, because they need different fixes.
        assert "inertia.middleware(app)" in message
        assert "ctx=ctx" in message

    def test_current_request_outside_a_request_explains_itself(self):
        with pytest.raises(OutsideRequestError) as caught:
            current_context()

        assert "No active Inertia request" in str(caught.value)

    async def test_active_returns_the_pair_inside_a_request(self, tmp_path):
        seen: dict = {}

        app = SilloApp()
        adapter = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(ctx):
            seen["pair"] = active()
            return await render("Home", {})

        async with await client_for(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert seen["pair"] is not None
        assert seen["pair"][0] is adapter


class TestThePageDecoratorInjection:
    async def test_a_handler_that_declares_a_context_receives_it(self, tmp_path):
        """The decorator passes the context only to a handler that asks for it,
        so one declaring nothing is not handed an argument it never named."""
        seen: dict = {}

        app = SilloApp()
        inertia = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        @inertia.page("Home")
        async def home(ctx):
            seen["ctx"] = ctx
            return {"ok": True}

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert seen["ctx"] is not None
        assert seen["ctx"].method == "GET"
        assert page["props"] == {**SHARED_PROPS, "ok": True}

    async def test_a_handler_declaring_nothing_is_called_with_nothing(self, tmp_path):
        """The counterpart. The wrapper still advertises a `ctx` parameter to
        the router — it has to, the router calls every handler with one — but
        does not forward it to a function that did not declare it."""
        seen: dict = {}

        app = SilloApp()
        inertia = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        @inertia.page("Home")
        async def home():
            seen["called"] = True
            return {}

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert seen["called"] is True
        assert page["props"] == SHARED_PROPS
