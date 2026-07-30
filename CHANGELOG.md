# Changelog

All notable changes to Sillo Inertia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
