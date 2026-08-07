# sillo-inertia

An [Inertia.js](https://inertiajs.com) adapter for Sillo, with React and Vue.

A handler names a component and returns its props. Whether that becomes a full
HTML document or a JSON page object is the adapter's problem, not yours — it
depends on whether the client has booted yet, which is a property of the
request rather than of your code.

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
    return await inertia.render("Home", {"name": "Sillo"})
```

## Install

```bash
pip install sillo-inertia
```

Or with uv:

```bash
uv add sillo-inertia
```

## The root view

Your `resources/views/app.html` needs the `{{ inertia }}` placeholder:

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    {{ inertia_head }}
  </head>
  <body>
    <div id="{{ root_id }}"></div>
    {{ inertia }}
  </body>
</html>
```

`{{ inertia }}` expands to a `<script type="application/json" data-page="app">`
element holding the page object — that is where Inertia 2.x and later read it
from. Do **not** put it on the root `<div>` as `data-page`: that was the 1.x
convention, current clients never look there, and the page boots with a null
page object and throws `Cannot read properties of null (reading 'component')`.
If you are targeting a 1.x client, `{{ inertia_page }}` still gives you the
HTML-escaped attribute value.

## Rendering

### `render`

```python
await inertia.render(
    "Users/Index",                     # the component the client resolves
    {"users": [...]},                  # props
    status_code=200,
    headers={"X-Total-Count": "42"},
    view_data={"title": "Users"},      # placeholders in the root view
)
```

`render` returns a response. Return it from the handler; there is no response
object to fill in and nothing to pass along.

The request it answers is the one the middleware is currently handling. If you
need a different one — a background job, a test that calls a function directly
— pass it by keyword:

```python
await inertia.render("Home", props, request=request)
```

Without a request from either source, `render` raises `OutsideRequestError`
and tells you which of those two cases you are in.

### Without the adapter in scope

`render`, `redirect`, `back` and `location` are importable on their own. They
find the adapter through the same middleware, which means a routes module can
build Inertia responses without importing the module that owns the app — and
so without the circular import that would otherwise cause.

```python
from sillo_inertia import render


@app.get("/")
async def home(request: Request, response: Response):
    return await render("Home", {"name": "Sillo"})
```

### As a decorator

When a handler does nothing but produce props, `@inertia.page` takes the rest:

```python
@app.get("/users/{user_id}")
@inertia.page("Users/Show")
async def show(user_id):
    return {"user": await User.get(id=user_id)}
```

The function declares only what it uses. Ask for `request` or `response` by
name and you get them; leave them out and they are not passed. Path parameters
and injected dependencies arrive as usual.

Returning a response instead of a mapping sends that response untouched, so a
handler can still redirect out of a page:

```python
@app.post("/users")
@inertia.page("Users/Create")
async def create(request: Request):
    form = await request.json()
    await User.create(**form)
    return inertia.redirect("/users")
```

Anything you would pass to `render` can be pinned on the decorator:

```python
@inertia.page("Errors/NotFound", status_code=404)
```

## Props

A prop can be a value, a callable, or a coroutine function. Callables that want
the request take one parameter; those that do not, take none.

```python
{
    "count": 5,                                   # a value
    "total": lambda: Order.count(),               # called per request
    "mine": lambda request: request.user.orders,  # given the request
    "stats": fetch_stats,                         # async, awaited
}
```

`props` itself can be a callable returning the whole mapping:

```python
await inertia.render("Home", lambda request: {"path": request.url.path})
```

### Lazy props

A lazy prop is left out of a partial reload unless the client asks for it by
name, so the work behind it is skipped on requests that would discard it:

```python
from sillo_inertia import lazy

await inertia.render(
    "Posts/Show",
    {
        "post": post.to_dict(),
        "comments": lazy(lambda: Comment.for_post(post.id)),
    },
)
```

On a partial reload — `X-Inertia-Partial-Component: Posts/Show` and
`X-Inertia-Partial-Data: comments` — only `comments` is resolved and returned.

Note that this is narrower than `lazy` in Inertia's own server adapters, where
a lazy prop is excluded from *every* regular visit and included only when asked
for by name. Here it is resolved on a full visit like any other prop, and only
partial reloads filter it out. Do not rely on it to keep an expensive query off
the first page load.

### Shared props

Props every page gets. Set them once, at startup:

```python
inertia.share(app_name="MyApp", auth={"user": None})
```

A page's own props win on a name clash.

## Redirects

```python
inertia.redirect("/dashboard")        # 303 after POST/PUT/PATCH, 302 after GET
inertia.redirect("/home", status_code=301)
inertia.back()                        # to the Referer
inertia.back(fallback="/posts")       # ...when there is no Referer
```

The 303 is not decoration. On a 302 the browser repeats the POST against the
new URL, so a redirect after a successful create creates a second record.

`location` sends the client out of Inertia entirely — a full browser visit
rather than an XHR one, which is the only way to reach an external URL:

```python
inertia.location("https://billing.example.com/checkout")
```

## Configuration

```python
Inertia(
    app=app,                            # attaches the middleware
    root_view="resources/views/app.html",
    version="1.0.0",                    # a string, or a callable returning one
    root_id="app",                      # the mount point's element id
    base_dir=".",                       # where asset paths resolve from
    vite=vite_react(dev=True),
)
```

The adapter can also be attached later:

```python
inertia = Inertia(root_view="resources/views/app.html")
inertia.middleware(app)
```

### Asset versions

When the client's `X-Inertia-Version` does not match the current one, the
middleware answers with a 409 and `X-Inertia-Location` before the handler
runs. The client does a full visit and comes back on the current build.
A `version` of `None` disables the check.

Passing a callable re-reads it per request, which is what you want when the
version comes from a build manifest that changes without a restart.

### Vite

```python
vite_react(
    entry="src/main.jsx",
    dev_server="http://localhost:5173",
    manifest_path="dist/.vite/manifest.json",
    asset_prefix="/assets/",
    dev=True,
    react_refresh=True,
)

vite_vue(
    entry="src/main.ts",
    dev_server="http://localhost:5173",
    manifest_path="dist/.vite/manifest.json",
    asset_prefix="/assets/",
    dev=True,
)
```

`{{ inertia_head }}` renders the tags: the dev server's client and entry in
development, the hashed manifest entries and their CSS in production.

## Upgrading from 0.0.x

`render` and `redirect` no longer take `request` and `response`:

```python
# before
return await inertia.render(request, response, "Home", {"name": "Sillo"})
# after
return await inertia.render("Home", {"name": "Sillo"})
```

The old call raises a `TypeError` naming the new form, so nothing fails
silently. `Inertia.location()` is now synchronous — drop the `await`.

Props callbacks taking a request still work unchanged; the parameter is now
optional rather than required, so `lambda _: value` can become
`lambda: value`.

## Project Links

- **Repository**: https://github.com/sillohq/inertia
- **Sillo Framework**: https://github.com/sillohq/core
