# Changelog

All notable changes to Sillo Inertia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0a1] - 2026-09-13

First alpha, released alongside `sillo-framework` 1.0.0a1. Install with
`pip install --pre sillo-inertia==1.0.0a1`.

An alpha: this is what 1.0 is expected to look like, but the API is not frozen
yet and may still change before `1.0.0`.

### Fixed

- **A test assumed `debug` defaulted to on.** Sillo 1.0 flipped
  `SilloApp(debug=...)` to default `False`, so a 500 now renders the bare
  "Internal Server Error" string rather than a page naming the exception. The
  missing-root-view test asserts on that message, so it builds its app with
  `debug=True` explicitly. The behaviour under test never changed.

## [0.1.0.dev1] - 2026-09-07

Development pre-release for testing against `sillo-framework==0.3.2.dev1`.
Install both with:

```
pip install --pre "sillo-framework==0.3.2.dev1" "sillo-inertia==0.1.0.dev1"
```

The adapter now runs on Sillo v1, and speaks the parts of the Inertia protocol
it had never implemented.

### Changed

- **Breaking: ported to the Sillo v1 context API.** `Request` and the
  `Responder` builder no longer exist in Sillo, so every signature that named
  them has changed. A handler takes one argument, the context:

  ```python
  # before
  async def home(request: Request, response: Response):
      return await render("Home", {"name": "Sillo"})

  # after
  async def home(ctx: HttpContext):
      return await render("Home", {"name": "Sillo"})
  ```

  `render`, `redirect` and `back` take `ctx=` where they took `request=`;
  `current_request()` is now `current_context()`; a props callback that wants
  the request is handed the context instead. **Requires
  `sillo-framework>=0.3.2`** — on an earlier core, `import sillo_inertia`
  raises `ImportError: cannot import name 'Request'`.

- **`lazy()` no longer runs on a normal visit.** It resolved the callback on
  every render and only filtered it out of *partial* reloads, which is
  backwards — the wrapper exists so the work is not done until something asks
  for it. It is now excluded from a standard visit and sent only when a partial
  reload names it, which is what Inertia's own adapters do and what the
  docstring always claimed. `optional()` is the current name; `lazy` is an
  alias and stays one.

### Added

- **Deferred props** — `defer(callback, group="charts")`. The first response
  omits the value and announces it in `deferredProps`; the client renders the
  page and immediately fetches the group. Props sharing a group arrive in one
  request, so one slow aggregate does not hold up three fast ones.

- **Merge props** — `merge(value)` and `deep_merge(value, match_on="id")`,
  reported as `mergeProps` / `deepMergeProps` / `matchPropsOn`, so a paged list
  appends to what the client holds instead of replacing it. `X-Inertia-Reset`
  is honoured: a prop the client asked to reset is still sent, but is no longer
  named in the merge lists.

- **`always(value)`** — a prop that survives a partial reload it was not named
  in. `errors` and `flash` are registered this way, so a form post that
  redirects into a partial reload still delivers its messages.

- **Validation errors and flash**, via `set_errors(ctx, {...})` and
  `set_flash(ctx, level, message)`. Both live in the session for exactly one
  request, which is what makes them survive the redirect that ends a form post.
  `errors` is the name Inertia's `useForm` reads, so it is not configurable.
  Named error bags are supported through `X-Inertia-Error-Bag`. With no session
  middleware installed both are empty rather than an error.

- **`X-Inertia-Partial-Except`**, and dotted partial keys — `only: ["order.customer"]`
  now narrows a nested prop instead of sending the whole of it.

### Fixed

- **A `Decimal` anywhere in a prop tree 500'd the page.** Props were serialised
  with a plain `json.dumps`, which refuses `Decimal` outright and names only
  the type in the error — on a page carrying forty values that says nothing
  about which one. Props now go through an encoder that handles `Decimal`,
  `datetime`/`date`/`time`, `timedelta`, `UUID`, `Enum`, `set` and anything
  with `model_dump`/`dict`/`to_dict`. Money is formatted with
  `format(value, "f")`, never `str()`: SQLite returns `Decimal("6.7E+2")` for a
  stored `670.00`, and `str()` on that renders in the UI as the literal
  `6.7E+2`.

- **A 302 answering a PUT, PATCH or DELETE is corrected to 303.** On a 302 the
  browser repeats the *method* against the new URL, so a redirect after a
  successful update issued a second update. `inertia.redirect()` already chose
  303; a handler returning Sillo's own `redirect()` did not, and now the
  middleware fixes it either way.


## [0.0.1a4] - 2026-08-09

### Changed

- **Requires `sillo-framework>=0.0.2a1`**, where the application class was
  renamed from `silloApp` to `SilloApp`. No code here names the class — the
  adapter takes `app` as `Any` — so this changes nothing at runtime. The floor
  is raised because the README and every example now spell it the new way, and
  a resolver left free to pick an older core would hand you a framework those
  examples do not run against.

  If you are still on `silloApp`: it warns under sillo-core 0.0.2a1 and is
  removed outright in 0.0.2a2, where importing it raises.

### Removed

- **The explicit `aerich>=0.7.0` dependency.** It existed to work around
  `sillo/record/helpers.py` doing `from aerich import Command` while the
  framework's `[record]` extra declared only `tortoise-orm` — so `import
  sillo_inertia` failed on a clean install without it. Sillo moved migrations
  to Tortoise-native on 2026-08-01 and no longer imports aerich anywhere;
  verified against a fresh environment with aerich absent. Raising the floor
  to 0.0.2a1 makes the workaround unreachable, so it is gone. Existing
  environments keep aerich; new ones no longer pull it in.

### Changed (API)

- **Breaking: `render` and `redirect` no longer take `request` and
  `response`.**

  ```python
  # before
  return await inertia.render(request, response, "Home", {"name": "Sillo"})
  # after
  return await inertia.render("Home", {"name": "Sillo"})
  ```

  The request is read from the middleware the adapter already installs on
  every request, and `render` returns a response of its own rather than
  filling in one it was handed. Neither argument carried information the
  adapter could not get for itself.

  The old call raises a `TypeError` naming the new form rather than failing
  somewhere further in. Where there is no request to read — a background job,
  a test calling a handler directly — pass one explicitly with
  `request=request`; without either, `render` raises `OutsideRequestError` and
  says which case you are in.

- **Breaking: `Inertia.location()` is synchronous.** It never awaited
  anything. Drop the `await`.

- Props callbacks may now take no arguments. `lambda _: value` still works;
  `lambda: value` is now equivalent. This applies to `lazy()` callbacks, to
  callable prop values, and to a callable passed as `props` itself.

### Added

- **`@inertia.page(component)`**, for handlers that only produce props:

  ```python
  @app.get("/users/{user_id}")
  @inertia.page("Users/Show")
  async def show(user_id):
      return {"user": await User.get(id=user_id)}
  ```

  The function declares only the parameters it uses — `request` and `response`
  are passed only if named. Returning a response instead of a mapping sends
  that response unchanged, so a handler can still redirect out of a page.

- **Module-level `render`, `redirect`, `back` and `location`.** They resolve
  the adapter through the same middleware, so a routes module can build
  Inertia responses without importing the module that owns the application —
  and so without the circular import that would otherwise cause.

- **`inertia.back()`**, redirecting to the `Referer`, with a `fallback` for
  requests that do not carry one. The usual end of an Inertia form post.

- **`headers=` on `render`**, merged with the `Vary` and `X-Inertia` headers
  the adapter sets.

- `current_request()` and `current_inertia()`, for reaching the bound request
  or adapter directly.

### Fixed

- **The page object is now emitted as a JSON script tag**, which is where
  Inertia 2.x and later actually look for it:

  ```html
  <script type="application/json" data-page="app">{...}</script>
  ```

  Previously `{{ inertia }}` produced the HTML-escaped JSON intended for
  `data-page` on the root `<div>` — the Inertia 1.x convention. Current clients
  never read that attribute (`getInitialPageFromDOM` queries only for the
  script element and returns `null` otherwise), so every page failed in the
  browser with `TypeError: Cannot read properties of null (reading
  'component')` from inside `createInertiaApp`.

### Changed

- **Breaking:** `{{ inertia }}` now renders a complete `<script>` element
  rather than a bare attribute value. Update root views from

  ```html
  <div id="{{ root_id }}" data-page="{{ inertia }}"></div>
  ```

  to

  ```html
  <div id="{{ root_id }}"></div>
  {{ inertia }}
  ```

  The old escaped-JSON value is still available as `{{ inertia_page }}` for
  anyone deliberately targeting an Inertia 1.x client.

- Page JSON inside the script tag is escaped with JSON unicode sequences
  (`<`, `>`, `&`) rather than HTML entities. A `<script>` body
  is raw text, so HTML escaping would reach `JSON.parse` verbatim and fail;
  the unicode form parses correctly and cannot terminate the element early.

## [0.1.0] - 2026-07-30

### Added

#### Core Features
- Inertia.js adapter for Sillo framework
- Support for React and Vue.js with Vite
- Full-page HTML rendering for initial page visits
- Inertia JSON responses for SPA navigation
- Asset version conflict detection (HTTP 409)
- Partial page reload support

#### React Support
- `vite_react()` configuration helper
- React Fast Refresh support in development
- Production manifest-based asset loading
- Custom dev server and entry point configuration

#### Vue Support
- `vite_vue()` configuration helper
- Vue-specific Vite tag generation
- Production manifest-based asset loading
- Custom dev server and entry point configuration

#### Props System
- Shared props across all pages
- Sync and async callable props
- Lazy props for deferred computation
- Props filtering via partial reloads
- Mixed prop resolution strategies

#### Template System
- Customizable root view template
- Template variable replacement
- Custom root element ID support
- Raw HTML injection for head tags
- View data passing to templates

#### Response Handling
- Redirect helper with HTTP status detection
- Custom status codes for redirects
- Preserve request method in redirects
- Dynamic version checking
- Callable version functions

#### Configuration
- `Inertia` adapter class with flexible options
- `InertiaConfig` for core settings
- `InertiaPage` data model
- Support for callable versions

#### Utilities
- `lazy()` helper for deferred props
- `raw()` helper for raw HTML strings
- `HtmlString` for HTML escaping control
- `LazyProp` data structure

#### Testing
- Comprehensive test suite (30+ tests)
- React Vite configuration tests
- Vue Vite configuration tests
- Partial reload tests
- Version handling tests
- Props resolution tests
- Redirect behavior tests

#### Documentation
- Comprehensive README with examples
- API reference documentation
- Configuration guide for React and Vue
- Example applications for both frameworks
- Integration guide with Sillo

### Infrastructure
- BSD-3-Clause license
- GitHub Actions CI/CD pipeline
- PyPI auto-publishing on tag push
- Test matrix on Python 3.10, 3.11, 3.12, 3.13
- Mypy type checking
- Ruff code formatting

### Known Limitations

- **Alpha Release**: API may change before 1.0.0
- **Browser Support**: Requires modern browsers with ES Module support
- **Framework Coverage**: Only React and Vue supported (extensible for others)

### Dependency Changes

#### Core Dependencies (Always Installed)
- sillo-framework>=0.0.1a1 (Sillo core framework)

#### Optional Dependencies (Dev Only)
- httpx: HTTP testing client
- pytest: Test runner
- pytest-asyncio: Async test support

### Versioning

Sillo Inertia uses semantic versioning:
- **0.1.0**: Initial stable release with React/Vue support
- **0.x.y**: API may change between minor versions
- **1.0.0**: First stable release with API stability guarantee

### Tag Format

Tags follow package-scoped format:
- Sillo Inertia: `inertia-v0.1.0`

---

## Coming Soon

- v0.2.0: Performance optimizations and additional frameworks
- v0.3.0: Enhanced templating and middleware support
- v1.0.0: First stable release with API guarantee

---

For more information, see GitHub [releases](https://github.com/sillohq/inertia/releases).
