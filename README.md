# sillo-inertia

`sillo-inertia` is a small Inertia.js adapter for Sillo. It renders normal HTML on first-page visits and Inertia page JSON for requests with `X-Inertia: true`.

Use the canonical import:

```python
from sillo_inertia import Inertia
```

## Install

```bash
pip install sillo-inertia
```

## Minimal usage

```python
from sillo import silloApp
from sillo.core.http import Request, Response
from sillo_inertia import Inertia, vite_react

app = silloApp()
inertia = Inertia(
    app,
    root_view="resources/views/app.html",
    version="1",
    vite=vite_react(dev=True),
)

@app.get("/")
async def home(request: Request, response: Response):
    return await inertia.render(request, response, "Home", {"name": "Sillo"})
```

`resources/views/app.html` must include the `{{ inertia }}` placeholder:

```html
{{ inertia_head }}
<div id="app" data-page='{{ inertia }}'></div>
```

## Features

- Full-page HTML rendering for browser visits.
- Inertia JSON responses for `X-Inertia` requests.
- Asset version conflict handling with HTTP `409` and `X-Inertia-Location`.
- Partial reload support via `X-Inertia-Partial-Component` and `X-Inertia-Partial-Data`.
- Sync and async shared props.
- Redirect helper that returns `303` after non-GET mutating requests.
