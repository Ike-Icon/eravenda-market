"""A small in-memory cache with a time limit, for data that is read on every
page but changes rarely (the category menu, for example).

It lives inside one server process. That is right for one Render instance. With
several instances, each keeps its own copy, so a change can take up to the time
limit (60 seconds here) to show on another instance. Writes that matter call
`invalidate` so the instance that handled the change updates at once.
"""
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl_seconds: float, loader: Callable[[], Any]) -> Any:
    """Return the cached value for `key`, or call `loader()` and keep the result."""
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = loader()  # outside the lock: a slow query must not block other requests
    with _lock:
        _store[key] = (now + ttl_seconds, value)
    return value


def invalidate(prefix: str = "") -> None:
    """Forget cached values whose key starts with `prefix` (all of them if empty)."""
    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            del _store[key]


def plain_category(category) -> SimpleNamespace:
    """A detached copy of a Category row. The cache outlives the database session
    that loaded the row, so it must not hold the ORM object itself."""
    return SimpleNamespace(
        id=category.id,
        name=category.name,
        slug=category.slug,
        parent_id=category.parent_id,
        icon_url=category.icon_url,
        children=[],
    )
