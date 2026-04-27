"""
Shared in-process state: tree cache + revision counter.

Tree cache: caches _build_tree results per (user_id, cred_id) for TREE_TTL seconds.
Revision:   monotonic counter incremented on every mutation (start/stop/delete/clone/…).
            The frontend polls /api/revision every 10 s; when it changes, clients
            invalidate their local cache and refresh.
"""

from __future__ import annotations

import threading
import time

# ---------- Tree cache ----------

_tree_cache: dict[tuple[int, int], tuple[dict, float]] = {}
_tree_lock = threading.Lock()
TREE_TTL = 20.0  # seconds


def get_cached_tree(user_id: int, cred_id: int) -> dict | None:
    key = (user_id, cred_id)
    with _tree_lock:
        entry = _tree_cache.get(key)
        if entry and (time.monotonic() - entry[1]) < TREE_TTL:
            return entry[0]
    return None


def set_cached_tree(user_id: int, cred_id: int, result: dict) -> None:
    key = (user_id, cred_id)
    with _tree_lock:
        _tree_cache[key] = (result, time.monotonic())


def invalidate_tree(cred_id: int) -> None:
    with _tree_lock:
        for k in list(_tree_cache):
            if k[1] == cred_id:
                del _tree_cache[k]


# ---------- Revision counter ----------

_revision: int = 0
_rev_lock = threading.Lock()


def bump_revision(cred_id: int) -> int:
    global _revision
    with _rev_lock:
        _revision += 1
        rev = _revision
    invalidate_tree(cred_id)
    return rev


def get_revision() -> int:
    with _rev_lock:
        return _revision
