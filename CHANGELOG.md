# Changelog

All notable changes to Sillo Inertia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

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
