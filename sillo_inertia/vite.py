from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ViteOptions(ABC):
    entry: str
    dev_server: str
    manifest_path: str | Path
    asset_prefix: str
    dev: bool

    @abstractmethod
    def render_tags(self, base_dir: Path) -> str:
        pass


@dataclass(frozen=True, slots=True)
class ViteReactOptions(ViteOptions):
    react_refresh: bool = True

    def render_tags(self, base_dir: Path) -> str:
        return render_vite_react_tags(self, base_dir)


@dataclass(frozen=True, slots=True)
class ViteVueOptions(ViteOptions):
    def render_tags(self, base_dir: Path) -> str:
        return render_vite_vue_tags(self, base_dir)


def vite_react(
    *,
    entry: str = "src/main.jsx",
    dev_server: str = "http://localhost:5173",
    manifest_path: str | Path = "dist/.vite/manifest.json",
    asset_prefix: str = "/assets/",
    dev: bool = True,
    react_refresh: bool = True,
) -> ViteReactOptions:
    return ViteReactOptions(
        entry=entry,
        dev_server=dev_server.rstrip("/"),
        manifest_path=manifest_path,
        asset_prefix=asset_prefix,
        dev=dev,
        react_refresh=react_refresh,
    )


def vite_vue(
    *,
    entry: str = "src/main.ts",
    dev_server: str = "http://localhost:5173",
    manifest_path: str | Path = "dist/.vite/manifest.json",
    asset_prefix: str = "/assets/",
    dev: bool = True,
) -> ViteVueOptions:
    return ViteVueOptions(
        entry=entry,
        dev_server=dev_server.rstrip("/"),
        manifest_path=manifest_path,
        asset_prefix=asset_prefix,
        dev=dev,
    )


def render_vite_tags(options: ViteOptions, base_dir: Path) -> str:
    return options.render_tags(base_dir)


def render_vite_react_tags(options: ViteReactOptions, base_dir: Path) -> str:
    if options.dev:
        tags: list[str] = []
        if options.react_refresh:
            tags.append(
                "\n".join(
                    [
                        '<script type="module">',
                        f'  import RefreshRuntime from "{options.dev_server}/@react-refresh"',
                        "  RefreshRuntime.injectIntoGlobalHook(window)",
                        "  window.$RefreshReg$ = () => {}",
                        "  window.$RefreshSig$ = () => (type) => type",
                        "  window.__vite_plugin_react_preamble_installed__ = true",
                        "</script>",
                    ]
                )
            )
        tags.append(
            f'<script type="module" src="{options.dev_server}/@vite/client"></script>'
        )
        tags.append(
            f'<script type="module" src="{options.dev_server}/{options.entry}"></script>'
        )
        return "\n".join(tags)

    return _render_vite_production_tags(options, base_dir)


def render_vite_vue_tags(options: ViteVueOptions, base_dir: Path) -> str:
    if options.dev:
        tags: list[str] = [
            f'<script type="module" src="{options.dev_server}/@vite/client"></script>',
            f'<script type="module" src="{options.dev_server}/{options.entry}"></script>',
        ]
        return "\n".join(tags)

    return _render_vite_production_tags(options, base_dir)


def _render_vite_production_tags(options: ViteOptions, base_dir: Path) -> str:
    manifest_path = Path(options.manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = manifest[options.entry]
    tags = []
    for css_file in asset.get("css", []):
        tags.append(f'<link rel="stylesheet" href="{_asset_url(options, css_file)}">')
    tags.append(
        f'<script type="module" src="{_asset_url(options, asset["file"])}"></script>'
    )
    return "\n".join(tags)


def _asset_url(options: ViteOptions, manifest_file: str) -> str:
    prefix = options.asset_prefix.rstrip("/") + "/"
    return prefix + manifest_file.removeprefix("assets/")
