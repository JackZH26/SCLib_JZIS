"""Bounded process-local verification cache for immutable RPS files.

This is not publication authorization. Every caller checks current approval,
and every read checks current file identity, including on a cache hit. Cached
objects are owned by this module; validators/consumers must not mutate them.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Callable

MAX_FILE_BYTES = 50_000_000
MAX_ENTRIES = 32
MAX_CACHED_BYTES = 128 * 1024 * 1024
MAX_INFLIGHT = 2
MAX_WAITERS = 32
WAIT_SECONDS = 30.0
NEGATIVE_SECONDS = 1.0


@dataclass(frozen=True)
class _Entry:
    value: object
    size: int
    failure_until: float | None = None


_condition = threading.Condition()
_entries: OrderedDict[tuple, _Entry] = OrderedDict()
_inflight: set[tuple] = set()
_waiters = 0
_cached_bytes = 0
_counts = dict(verifications=0, hits=0, misses=0, failures=0, negative_hits=0)


def file_signature(path: Path) -> tuple[int, ...]:
    """No symlinks, directories, pipes, or unbounded input files."""
    return _signature(path.lstat())


def _signature(value: os.stat_result) -> tuple[int, ...]:
    if not stat.S_ISREG(value.st_mode) or value.st_size > MAX_FILE_BYTES:
        raise ValueError("RPS input is not a bounded regular file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_stable(path: Path, signature: tuple[int, ...]) -> bytes:
    # NONBLOCK also prevents a raced-in FIFO from hanging before fstat.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if _signature(os.fstat(stream.fileno())) != signature:
            raise ValueError("RPS input changed before verification")
        raw = stream.read(signature[2] + 1)
        if len(raw) != signature[2] or _signature(os.fstat(stream.fileno())) != signature:
            raise ValueError("RPS input changed during verification")
    if file_signature(path) != signature:
        raise ValueError("RPS input was replaced during verification")
    return raw


def _retained_size(value: object) -> int:
    """Account reachable Python objects once; not a process RSS guarantee."""
    seen: set[int] = set()
    pending = [value]
    total = 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            pending.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            pending.extend(getattr(item, field.name) for field in fields(item))
        elif hasattr(item, "__dict__"):
            pending.append(vars(item))
            # Pydantic retains field sets outside __dict__.
            if hasattr(item, "__pydantic_fields_set__"):
                pending.append(item.__pydantic_fields_set__)
        if total > MAX_CACHED_BYTES:
            return total
    return total


def _remove(key: tuple) -> None:
    global _cached_bytes
    previous = _entries.pop(key, None)
    if previous:
        _cached_bytes -= previous.size


def _store(key: tuple, entry: _Entry) -> None:
    global _cached_bytes
    if entry.size > MAX_CACHED_BYTES:
        return
    _remove(key)
    while _entries and (len(_entries) >= MAX_ENTRIES or _cached_bytes + entry.size > MAX_CACHED_BYTES):
        _remove(next(iter(_entries)))
    _entries[key] = entry
    _cached_bytes += entry.size


def read_verified_file(path: Path, *, identity: tuple, validator: Callable[[bytes], object]) -> object:
    """Single-flight stable verification; concurrent work and waiting are bounded.

    The key includes a caller-owned verifier namespace and all expected hashes.
    It must not depend only on the filename or bundle self-asserted hash.
    No loader runs under the cache lock. A failed verification is remembered for
    one second without retaining its exception, traceback or input contents.
    """
    global _waiters
    path = path.absolute()
    signature = file_signature(path)
    key = (str(path), signature, identity)
    deadline = time.monotonic() + WAIT_SECONDS
    with _condition:
        _counts["misses"] += 1
        while True:
            entry = _entries.get(key)
            if entry and entry.failure_until is not None and entry.failure_until <= time.monotonic():
                _remove(key)
                entry = None
            if entry:
                _entries.move_to_end(key)
                if entry.failure_until is not None:
                    _counts["negative_hits"] += 1
                    raise ValueError("RPS verification temporarily unavailable")
                _counts["hits"] += 1
                _counts["misses"] -= 1
                value = entry.value
                break
            if key not in _inflight and len(_inflight) < MAX_INFLIGHT:
                _inflight.add(key)
                _counts["verifications"] += 1
                value = None
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0 or _waiters >= MAX_WAITERS:
                raise ValueError("RPS verification capacity unavailable")
            _waiters += 1
            try:
                _condition.wait(remaining)
            finally:
                _waiters -= 1
    if value is not None:
        if file_signature(path) != signature:
            raise ValueError("RPS input changed during cached read")
        return value
    try:
        value = validator(_read_stable(path, signature))
        if value is None:
            raise ValueError("RPS verifier returned no result")
        if file_signature(path) != signature:
            raise ValueError("RPS input changed during validation")
        entry = _Entry(value, _retained_size(value) + _retained_size(key))
    except BaseException:
        with _condition:
            _counts["failures"] += 1
            _store(key, _Entry(None, 512 + _retained_size(key), time.monotonic() + NEGATIVE_SECONDS))
            _inflight.remove(key)
            _condition.notify_all()
        raise
    with _condition:
        _store(key, entry)
        _inflight.remove(key)
        _condition.notify_all()
    return value


def clear_release_cache() -> None:
    """Test/benchmark reset; never cancel a live loader or bypass approval."""
    global _cached_bytes
    with _condition:
        if _inflight or _waiters:
            raise ValueError("cannot reset an active RPS verification cache")
        _entries.clear()
        _cached_bytes = 0
        for key in _counts:
            _counts[key] = 0


def release_cache_stats() -> dict:
    with _condition:
        return {
            **_counts, "entries": len(_entries), "cached_bytes": _cached_bytes,
            "inflight": len(_inflight), "waiters": _waiters,
            "limits": {"entries": MAX_ENTRIES, "cached_bytes": MAX_CACHED_BYTES,
                       "inflight": MAX_INFLIGHT, "waiters": MAX_WAITERS,
                       "file_bytes": MAX_FILE_BYTES, "wait_seconds": WAIT_SECONDS,
                       "negative_seconds": NEGATIVE_SECONDS},
        }
