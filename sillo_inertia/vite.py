from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ViteReactOptions:
    entry: str = "src/main.jsx"
    dev_server: str = "http://localhost:5173"
    manifest_path: str | Path = "dist/.vite/manifest.json"
    asset_prefix: str = "/assets/"
    dev: bool = True
    react_refresh: bool = True


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
        tags.append(f'<script type="module" src="{options.dev_server}/@vite/client"></script>')
        tags.append(f'<script type="module" src="{options.dev_server}/{options.entry}"></script>')
        return "\n".join(tags)

    manifest_path = Path(options.manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = manifest[options.entry]
    tags = []
    for css_file in asset.get("css", []):
        tags.append(f'<link rel="stylesheet" href="{_asset_url(options, css_file)}">')
    tags.append(f'<script type="module" src="{_asset_url(options, asset["file"])}"></script>')
    return "\n".join(tags)


def _asset_url(options: ViteReactOptions, manifest_file: str) -> str:
    prefix = options.asset_prefix.rstrip("/") + "/"
    return prefix + manifest_file.removeprefix("assets/")
