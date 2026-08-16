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
from sillo_inertia.adapter import _wants_request
from sillo_inertia.context import active, current_inertia, current_request

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
        assert _wants_request(lambda: 1) is False

    def test_a_lambda_taking_the_request(self):
        assert _wants_request(lambda request: request) is True

    def test_a_function_with_varargs_counts_as_wanting_it(self):
        def callback(*args):
            return args

        assert _wants_request(callback) is True

    def test_a_bound_method_ignores_its_self_parameter(self):
        class Props:
            def value(self):
                return 1

            def with_request(self, request):
                return request

        assert _wants_request(Props().value) is False
        assert _wants_request(Props().with_request) is True

    @pytest.mark.parametrize("builtin", [min, int, range])
    def test_a_builtin_with_no_readable_signature_is_given_the_request(self, builtin):
        """``inspect.signature`` raises ValueError for some C callables.

        Assuming the request is wanted is the safe default: handing one to a
        callback that ignores it raises immediately and visibly, whereas
        withholding it from one that needs it fails the same way -- but the
        adapter cannot tell which, so it picks the case that is true of every
        callback written against the documented signature.
        """
        assert _wants_request(builtin) is True

    def test_a_callable_object_is_read_through_its_call(self):
        class Callable:
            def __call__(self, request):
                return request

        assert _wants_request(Callable()) is True


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
        assert "request=request" in message

    def test_current_request_outside_a_request_explains_itself(self):
        with pytest.raises(OutsideRequestError) as caught:
            current_request()

        assert "No active Inertia request" in str(caught.value)

    async def test_active_returns_the_pair_inside_a_request(self, tmp_path):
        seen: dict = {}

        app = SilloApp()
        adapter = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        async def home(request, response):
            seen["pair"] = active()
            return await render("Home", {})

        async with await client_for(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert seen["pair"] is not None
        assert seen["pair"][0] is adapter


class TestTheOldCallShapes:
    """The adapter used to take ``(request, response, ...)`` first. Both
    entry points absorb the old positionals so the error can say what to
    write instead, rather than Python raising an arity message first."""

    async def test_redirect_with_the_old_arguments_says_what_to_write(self, tmp_path):
        app = SilloApp()
        adapter = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        captured: dict = {}

        @app.get("/")
        async def home(request, response):
            try:
                adapter.redirect(request, response, "/dashboard")
            except TypeError as error:
                captured["message"] = str(error)
            return await render("Home", {})

        async with await client_for(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert "takes the location first" in captured["message"]
        assert 'inertia.redirect("/dashboard")' in captured["message"]

    async def test_redirect_rejects_a_non_string_location(self, tmp_path):
        app = SilloApp()
        adapter = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        captured: dict = {}

        @app.get("/")
        async def home(request, response):
            try:
                adapter.redirect(object())
            except TypeError as error:
                captured["message"] = str(error)
            return await render("Home", {})

        async with await client_for(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert "takes the location first" in captured["message"]


class TestThePageDecoratorInjection:
    async def test_a_handler_that_declares_response_receives_it(self, tmp_path):
        """The decorator passes ``request`` and ``response`` only to handlers
        that ask for them, so a handler declaring neither is not handed two
        arguments it never named."""
        seen: dict = {}

        app = SilloApp()
        inertia = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        @inertia.page("Home")
        async def home(response):
            seen["response"] = response
            return {"ok": True}

        async with await client_for(app) as client:
            page = (await client.get("/", headers={"X-Inertia": "true"})).json()

        assert seen["response"] is not None
        assert page["props"] == {"ok": True}

    async def test_a_handler_may_declare_both(self, tmp_path):
        seen: dict = {}

        app = SilloApp()
        inertia = Inertia(app=app, root_view=write_root(tmp_path), base_dir=tmp_path)

        @app.get("/")
        @inertia.page("Home")
        async def home(request, response):
            seen["both"] = (request is not None, response is not None)
            return {}

        async with await client_for(app) as client:
            await client.get("/", headers={"X-Inertia": "true"})

        assert seen["both"] == (True, True)
