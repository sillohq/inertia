# Sillo Inertia Architecture

This document describes the architecture and design decisions of Sillo Inertia.

## Overview

Sillo Inertia is a lightweight Inertia.js adapter that enables building modern SPAs with Python backends. It follows Inertia's philosophy: SSR-style simplicity with SPA reactivity.

## Core Components

### Inertia Adapter (`adapter.py`)

The main `Inertia` class is a dataclass that manages:
- Root view template rendering
- Props resolution and merging
- Request/response handling
- Version management
- Middleware registration

**Key Design Decisions:**

1. **Dataclass-based**: Uses `@dataclass(slots=True)` for performance and memory efficiency
2. **Optional middleware**: Integrates with Sillo's middleware system only when needed
3. **Lazy initialization**: `__post_init__` sets up configuration after construction

### Configuration (`config.py`)

The `InertiaConfig` dataclass stores core settings:
- Root view path
- Asset version (static or callable)
- Root element ID

**Design:** Immutable and minimal to avoid complex state management.

### Props System (`props.py`)

Three utilities for prop management:

1. **`LazyProp`**: Defers computation until prop resolution
   - Useful for expensive database queries
   - Only resolved on demand, not for partial reloads unless explicitly included

2. **`HtmlString`**: Wraps raw HTML to bypass escaping
   - Used for head tag injection
   - Prevents double-escaping of HTML entities

3. **`lazy()` / `raw()` helpers**: Factory functions for props

**Design:** Immutable dataclasses prevent accidental modifications.

### Vite Integration (`vite.py`)

Framework-agnostic Vite support with two implementations:

**ViteReactOptions:**
- Includes React Fast Refresh support
- Dev mode: Injects refresh runtime + dev client
- Production: Reads compiled manifest

**ViteVueOptions:**
- No refresh runtime (Vue handles it differently)
- Dev mode: Simple script injection
- Production: Same manifest approach

**Design:** Abstract base class `ViteOptions` allows extending for other frameworks (Svelte, etc.)

## Request Flow

### Initial Page Visit

```
GET /dashboard (no X-Inertia header)
        ↓
Inertia.render() called
        ↓
Props resolved:
  - Shared props merged
  - Callable props evaluated
  - Lazy props skipped (initial visit)
  - Async props awaited
        ↓
InertiaPage created with all props
        ↓
Root template rendered:
  - {{ inertia }} → JSON-encoded page data
  - {{ inertia_head }} → Vite script tags
  - {{ root_id }} → Custom element ID
        ↓
HTML response returned
        ↓
Browser loads Vite client + entry point
        ↓
Frontend framework hydrates from {{ inertia }}
```

### SPA Navigation

```
Client makes fetch with X-Inertia: true
        ↓
Inertia.handle_request() middleware checks version
        ↓
Version mismatch? → 409 with X-Inertia-Location
        ↓
Route handler calls Inertia.render()
        ↓
Props resolved:
  - Shared props merged
  - Callable props evaluated
  - Lazy props evaluated (client can request specific ones)
  - Async props awaited
        ↓
InertiaPage created
        ↓
JSON response returned
        ↓
Frontend JavaScript processes response
        ↓
Component rendered with new props
```

### Partial Reloads

```
Client sends X-Inertia-Partial-Component and X-Inertia-Partial-Data
        ↓
_partial_keys() extracts requested prop names
        ↓
Props resolved normally
        ↓
Props filtered to requested keys only
        ↓
JSON response with subset of props
        ↓
Frontend merges new props with existing state
```

## Props Resolution Strategy

Props can be:

1. **Static values**: `{"count": 5}`
   - No computation needed

2. **Sync callables**: `{"user": lambda r: get_user(r)}`
   - Called per request
   - Can access request context

3. **Async callables**: `{"posts": async_fetch_posts}`
   - Called per request
   - Awaited naturally

4. **Lazy props**: `{"data": lazy(lambda r: expensive_op())}`
   - Never called on initial visit
   - Only resolved if explicitly requested in partial reload
   - Helps optimize performance

**Precedence (override order):**
1. Page props passed to `render()`
2. Shared props set via `share()`

## Template Rendering

Root view uses simple string replacement (not a templating engine):

```html
<html>
  <head>
    {{ inertia_head }}  <!-- Replaced with Vite tags -->
  </head>
  <body>
    <div id="{{ root_id }}" data-page='{{ inertia }}'></div>
  </body>
</html>
```

**Why simple replacement?**
- No dependency on template engine
- Faster than Jinja2
- Works with any HTML structure
- User controls template fully

**Variables provided:**
- `inertia`: JSON-encoded page object (HTML-escaped)
- `inertia_head`: Vite script/link tags
- `root_id`: Custom element ID (escaped)
- Any vars from `view_data` parameter

## Version Handling

Prevents stale assets when code changes:

```python
Inertia(app, version="abc")  # Static version
Inertia(app, version=lambda: hash_assets())  # Dynamic
```

**Behavior:**
- Client sends `X-Inertia-Version` header with its version
- Server compares with `current_version()`
- Mismatch → HTTP 409 with `X-Inertia-Location` header pointing to current URL
- Frontend detects 409 → full page reload (forces fresh asset load)

**Design:** Version can be asset manifest hash, git commit, or timestamp.

## Middleware Integration

When `app` parameter provided:

```python
inertia = Inertia(app, ...)
# Automatically calls: app.use(inertia.handle_request)
```

Middleware checks version on every Inertia request before route handler runs.

## Async/Await Handling

Props resolution is fully async-aware:

```python
async def get_props(request):
    user = await db.get_user()
    return {"user": user}

await inertia.render(
    request, response, "Home",
    get_props  # Called and awaited automatically
)
```

**Implementation:**
- Uses `inspect.isawaitable()` to detect awaitable results
- Each prop can be async independently
- All awaits happen in parallel within `_resolve_props()`

## Error Handling

Current design trusts framework guarantees:
- No validation of prop types (JSON-serializable assumed)
- No fallbacks for missing files (FileNotFoundError raised)
- No exception catching in prop resolution

**Rationale:** Let exceptions bubble up - they're often configuration errors that should fail fast.

## Performance Considerations

1. **Lazy props**: Defer expensive ops when possible
2. **Partial reloads**: Only compute needed props
3. **Dataclass slots**: Reduced memory overhead
4. **String replacement**: Faster than template engines
5. **No prop validation**: Skip unnecessary type checking

## Extension Points

### Adding New Frameworks

Create new Vite options class:

```python
@dataclass(frozen=True, slots=True)
class ViteSvelteOptions(ViteOptions):
    def render_tags(self, base_dir: Path) -> str:
        # Svelte-specific implementation
        ...

def vite_svelte(...) -> ViteSvelteOptions:
    return ViteSvelteOptions(...)
```

### Custom Props Resolution

Override `_resolve_value()` in a subclass to support custom prop types:

```python
class MyInertia(Inertia):
    async def _resolve_value(self, request, value):
        if isinstance(value, MyCustomType):
            return value.render()
        return await super()._resolve_value(request, value)
```

## Testing Strategy

Tests organized by feature:
- **TestInitialVisit**: HTML rendering
- **TestInertiaVisit**: JSON responses
- **TestPartialReload**: Prop filtering
- **TestVersionHandling**: Asset versioning
- **TestRedirect**: Redirect helpers
- **TestViteReact/Vue**: Framework-specific Vite tags
- **TestProps**: Props resolution
- **TestViewData**: Template variables

Each test uses tmpdir for isolated file I/O.

## Backward Compatibility

The refactoring from React-only to React+Vue maintains full backward compatibility:

- `vite_react()` still works exactly as before
- `ViteReactOptions` is still a public API
- Existing code using React continues without changes
- `ViteOptions` base class is new but not breaking

Migration path for Vue users:
```python
# Before (React)
vite=vite_react(dev=True)

# After (Vue)
vite=vite_vue(dev=True)
```

## Future Considerations

- **Svelte support**: Add `ViteSvelteOptions` class
- **Alpine.js**: Lightweight option for partial interactivity
- **Htmx**: Alternative SPA strategy
- **Caching**: Optional prop caching for repeated requests
- **Compression**: Gzip page JSON responses
