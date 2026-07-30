# sillo-inertia

`sillo-inertia` is a modern Inertia.js adapter for Sillo with support for React and Vue. It renders normal HTML on first-page visits and Inertia page JSON for requests with `X-Inertia: true`.

Use the canonical import:

```python
from sillo_inertia import Inertia, vite_react, vite_vue
```

## Install

```bash
pip install sillo-inertia
```

## Quick Start

### React + Vite

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

### Vue + Vite

```python
from sillo import silloApp
from sillo.core.http import Request, Response
from sillo_inertia import Inertia, vite_vue

app = silloApp()
inertia = Inertia(
    app,
    root_view="resources/views/app.html",
    version="1",
    vite=vite_vue(dev=True),
)

@app.get("/")
async def home(request: Request, response: Response):
    return await inertia.render(request, response, "Home", {"name": "Sillo"})
```

### Root View Template

Your `resources/views/app.html` must include the `{{ inertia }}` placeholder:

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    {{ inertia_head }}
  </head>
  <body>
    <div id="app" data-page='{{ inertia }}'></div>
  </body>
</html>
```

## Features

- **Framework Agnostic**: Full support for React and Vue (more to come)
- **Full-page HTML**: Renders HTML on first-page visits
- **Inertia JSON**: Responds with JSON for `X-Inertia` requests
- **Version Handling**: Asset version conflict detection with HTTP `409` and `X-Inertia-Location`
- **Partial Reload**: Supports `X-Inertia-Partial-Component` and `X-Inertia-Partial-Data` for efficient updates
- **Shared Props**: Global props accessible to all pages
- **Sync & Async Props**: Both sync callables and async functions work seamlessly
- **Lazy Props**: Defer expensive computations with `lazy()` helper
- **Custom Root ID**: Use any element ID for the Inertia mount point
- **Dynamic Versioning**: Support for callable version functions

## Configuration

### Inertia Configuration

```python
Inertia(
    app=app,                          # Sillo app instance (optional)
    root_view="app.html",             # Path to root template
    version="1.0.0",                  # Static or callable version
    root_id="app",                    # Root element ID
    base_dir=".",                     # Base directory for asset paths
    vite=vite_react(dev=True),        # Vite configuration
)
```

### React Options

```python
vite_react(
    entry="src/main.jsx",             # Entry point
    dev_server="http://localhost:5173", # Dev server URL
    manifest_path="dist/.vite/manifest.json",  # Production manifest
    asset_prefix="/assets/",          # Asset URL prefix
    dev=True,                         # Development mode
    react_refresh=True,               # Enable React Fast Refresh
)
```

### Vue Options

```python
vite_vue(
    entry="src/main.ts",              # Entry point
    dev_server="http://localhost:5173", # Dev server URL
    manifest_path="dist/.vite/manifest.json",  # Production manifest
    asset_prefix="/assets/",          # Asset URL prefix
    dev=True,                         # Development mode
)
```

## API Reference

### Rendering Pages

```python
# Basic rendering with props
await inertia.render(
    request,
    response,
    "Home",                           # Component name
    {"user": {"name": "John"}},       # Props dict
    status_code=200,                  # HTTP status
    view_data={"title": "Home"},      # Extra template data
)

# Lazy props for expensive computations
from sillo_inertia import lazy

await inertia.render(
    request,
    response,
    "Home",
    {
        "user": {"id": 1, "name": "John"},
        "permissions": lazy(lambda r: compute_permissions(r)),
    }
)
```

### Shared Props

```python
inertia.share(
    app_name="MyApp",
    auth={"user": None},
)
```

### Redirects

```python
# Returns 303 for POST/PUT/PATCH, 302 for GET
inertia.redirect(request, response, "/dashboard")

# Custom status code
inertia.redirect(request, response, "/home", status_code=301)
```

### Dynamic Props

Props can be static values, callables, or async functions:

```python
# Static value
{"count": 5}

# Sync callable
{"count": lambda request: request.app.cache.get("count")}

# Async callable
async def get_count(request):
    return await request.app.db.count()

{"count": get_count}

# Lazy prop (deferred resolution)
{"data": lazy(lambda r: expensive_computation())}
```

## Examples

### User Dashboard

```python
@app.get("/dashboard")
async def dashboard(request: Request, response: Response):
    user = await request.app.db.get_user(request.user_id)
    posts = lazy(lambda _: request.app.db.list_posts(request.user_id))
    
    return await inertia.render(
        request,
        response,
        "Dashboard",
        {
            "user": user.to_dict(),
            "posts": posts,
        }
    )
```

### Form Submission

```python
@app.post("/users")
async def create_user(request: Request, response: Response):
    data = await request.json()
    user = await request.app.db.create_user(data)
    return inertia.redirect(request, response, f"/users/{user.id}")
```

### Partial Page Updates

```python
# Client sends:
# GET /api/comments?post_id=1
# X-Inertia: true
# X-Inertia-Partial-Component: PostDetail
# X-Inertia-Partial-Data: comments

@app.get("/posts/{post_id}")
async def post_detail(request: Request, response: Response):
    post = await request.app.db.get_post(request.path_params["post_id"])
    comments = lazy(lambda _: request.app.db.list_comments(post.id))
    
    return await inertia.render(
        request,
        response,
        "PostDetail",
        {
            "post": post.to_dict(),
            "comments": comments,
        }
    )
```

## Project Links

- **Repository**: https://github.com/sillohq/inertia
- **Documentation**: https://sillolabs.com
- **Sillo Framework**: https://github.com/sillohq/core
