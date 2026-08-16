"""Vite in production: the manifest, and the tags built from it.

Every existing Vite test runs with ``dev=True``, which emits three fixed
script tags pointing at the dev server and reads nothing from disk. That is
the half of the feature nobody deploys.

The production half is the one that can actually break a release: it opens a
manifest written by ``vite build``, looks up the entry, and turns the hashed
filenames inside into URLs. Each of those steps has a way to go wrong that
does not show up until the assets are built and the dev server is gone --
which, for anyone using this adapter, is the moment they first deploy.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sillo import SilloApp

from sillo_inertia import Inertia, render, vite_react, vite_vue

ROOT_WITH_HEAD = (
    "<html><head>{{ inertia_head }}</head><body>"
    '<div id="{{ root_id }}"></div>{{ inertia }}</body></html>'
)


def write_manifest(base: Path, entries: dict, *, at: str = "dist/.vite/manifest.json") -> Path:
    path = base / at
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def write_root(base: Path) -> Path:
    root = base / "app.html"
    root.write_text(ROOT_WITH_HEAD, encoding="utf-8")
    return root


#: What `vite build` writes for a React entry with a stylesheet.
TYPICAL = {
    "src/main.jsx": {
        "file": "assets/main-DkH3xQ1p.js",
        "css": ["assets/main-B7kLm2Zx.css"],
        "isEntry": True,
    }
}


class TestTheTagsBuiltFromAManifest:
    def test_the_hashed_script_is_emitted(self, tmp_path):
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.jsx",
            manifest_path="dist/.vite/manifest.json",
            dev=False,
        )

        tags = options.render_tags(tmp_path)

        assert '<script type="module" src="/assets/main-DkH3xQ1p.js"></script>' in tags

    def test_the_stylesheet_is_emitted(self, tmp_path):
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert '<link rel="stylesheet" href="/assets/main-B7kLm2Zx.css">' in tags

    def test_css_comes_before_the_script(self, tmp_path):
        """Order is not cosmetic.

        A stylesheet discovered after the module has executed produces a
        flash of unstyled content on every first visit.
        """
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert tags.index("stylesheet") < tags.index("<script")

    def test_nothing_points_at_the_dev_server(self, tmp_path):
        """The failure this catches is a page that works only on the author's
        machine, because the built document still asks for :5173."""
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert "5173" not in tags
        assert "@vite/client" not in tags
        assert "@react-refresh" not in tags

    def test_an_entry_with_no_css_emits_only_the_script(self, tmp_path):
        write_manifest(tmp_path, {"src/main.jsx": {"file": "assets/main-abc.js"}})
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert "stylesheet" not in tags
        assert tags.count("<script") == 1

    def test_every_stylesheet_is_emitted(self, tmp_path):
        write_manifest(
            tmp_path,
            {
                "src/main.jsx": {
                    "file": "assets/main-abc.js",
                    "css": ["assets/a-1.css", "assets/b-2.css", "assets/c-3.css"],
                }
            },
        )
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert tags.count("stylesheet") == 3
        for name in ("a-1.css", "b-2.css", "c-3.css"):
            assert name in tags

    def test_vue_builds_the_same_production_tags(self, tmp_path):
        """React and Vue differ only in development, where React adds the
        refresh preamble. The built output must not diverge."""
        write_manifest(tmp_path, {"src/main.ts": TYPICAL["src/main.jsx"]})
        options = vite_vue(
            entry="src/main.ts", manifest_path="dist/.vite/manifest.json", dev=False
        )

        tags = options.render_tags(tmp_path)

        assert '<script type="module" src="/assets/main-DkH3xQ1p.js"></script>' in tags
        assert "stylesheet" in tags
        assert "5173" not in tags


class TestWhereTheManifestIsLookedFor:
    def test_a_relative_path_resolves_against_base_dir(self, tmp_path):
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        assert "main-DkH3xQ1p.js" in options.render_tags(tmp_path)

    def test_an_absolute_path_is_used_as_given(self, tmp_path):
        """The adapter derives ``base_dir`` by walking up from the root view,
        which is right for a conventional layout and wrong for anything else.
        An absolute manifest path is the escape hatch, so it must not be
        joined onto base_dir."""
        manifest = write_manifest(tmp_path / "elsewhere", TYPICAL, at="manifest.json")
        options = vite_react(entry="src/main.jsx", manifest_path=manifest, dev=False)

        # A deliberately wrong base_dir: an absolute path must ignore it.
        tags = options.render_tags(Path("/nonexistent"))

        assert "main-DkH3xQ1p.js" in tags

    def test_a_missing_manifest_says_which_file(self, tmp_path):
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        with pytest.raises(FileNotFoundError) as caught:
            options.render_tags(tmp_path)

        assert "manifest.json" in str(caught.value)


class TestTheEntryKey:
    def test_an_entry_absent_from_the_manifest_is_refused(self, tmp_path):
        """The entry is a string that has to match a manifest key exactly.

        Nothing checks the two against each other: Vite writes the key from
        its own config, and the adapter is told the entry separately. They
        drift whenever one side is renamed, and development keeps working
        because the dev-server branch never opens the manifest.
        """
        write_manifest(tmp_path, TYPICAL)
        options = vite_react(
            entry="src/main.tsx",  # the manifest says .jsx
            manifest_path="dist/.vite/manifest.json",
            dev=False,
        )

        with pytest.raises(KeyError):
            options.render_tags(tmp_path)


class TestAssetUrls:
    """How a manifest filename becomes a URL.

    Vite writes ``assets/main-hash.js`` into the manifest. The adapter strips
    that leading ``assets/`` and prefixes ``asset_prefix``, so the served
    directory is the ``assets`` folder *inside* the build output. Getting this
    wrong produces a manifest that is perfectly correct and a page whose every
    script 404s.
    """

    @pytest.mark.parametrize(
        ("prefix", "expected"),
        [
            ("/assets/", "/assets/main-abc.js"),
            ("/assets", "/assets/main-abc.js"),
            ("/static/build/", "/static/build/main-abc.js"),
            ("/static/build", "/static/build/main-abc.js"),
            ("https://cdn.example.com/", "https://cdn.example.com/main-abc.js"),
        ],
    )
    def test_the_prefix_is_applied_with_exactly_one_slash(self, tmp_path, prefix, expected):
        write_manifest(tmp_path, {"src/main.jsx": {"file": "assets/main-abc.js"}})
        options = vite_react(
            entry="src/main.jsx",
            manifest_path="dist/.vite/manifest.json",
            asset_prefix=prefix,
            dev=False,
        )

        assert f'src="{expected}"' in options.render_tags(tmp_path)

    def test_a_file_outside_assets_keeps_its_path(self, tmp_path):
        """``removeprefix`` only strips ``assets/``. A manifest that names a
        file anywhere else keeps its directory, rather than being flattened
        into one that does not exist."""
        write_manifest(tmp_path, {"src/main.jsx": {"file": "js/nested/main-abc.js"}})
        options = vite_react(
            entry="src/main.jsx", manifest_path="dist/.vite/manifest.json", dev=False
        )

        assert 'src="/assets/js/nested/main-abc.js"' in options.render_tags(tmp_path)


class TestThroughARealRender:
    """The tags have to reach the document, not merely be constructible."""

    async def test_a_first_visit_carries_the_built_assets(self, tmp_path):
        write_manifest(tmp_path, TYPICAL)
        root = write_root(tmp_path)

        app = SilloApp()
        Inertia(
            app=app,
            root_view=root,
            base_dir=tmp_path,
            vite=vite_react(
                entry="src/main.jsx",
                manifest_path="dist/.vite/manifest.json",
                dev=False,
            ),
        )

        @app.get("/")
        async def home(request, response):
            return await render("Home", {})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            body = (await client.get("/")).text

        assert '<script type="module" src="/assets/main-DkH3xQ1p.js"></script>' in body
        assert '<link rel="stylesheet" href="/assets/main-B7kLm2Zx.css">' in body
        assert "5173" not in body

    async def test_no_vite_configured_leaves_the_head_empty(self, tmp_path):
        """The adapter is usable without Vite at all, and must not emit a
        stray placeholder when it is absent."""
        root = write_root(tmp_path)

        app = SilloApp()
        Inertia(app=app, root_view=root, base_dir=tmp_path)

        @app.get("/")
        async def home(request, response):
            return await render("Home", {})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            body = (await client.get("/")).text

        assert "<head></head>" in body
        assert "{{" not in body
