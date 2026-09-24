"""Bounded response caching fenced by transactional catalogue/source epochs.

Cache only source-derived public bytes. Projection tables are not covered by
these epochs, so their contents must never be used to populate this cache.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import UTC, datetime

from sqlalchemy import text


class BoundedResponseCache:
    """Bound serialized public pages; never retain ORM objects or identities."""

    def __init__(self, *, max_bytes=32 * 1024 * 1024, max_entries=128):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.entries.get(key)
            if value is not None:
                self.entries.move_to_end(key)
            return value

    def put(self, key, value):
        weight = len(value) + len(key[-1])
        if weight > self.max_bytes:
            return
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous is not None:
                self.size -= len(previous) + len(key[-1])
            self.entries[key] = value
            self.size += weight
            while self.size > self.max_bytes or len(self.entries) > self.max_entries:
                expired_key, expired = self.entries.popitem(last=False)
                self.size -= len(expired) + len(expired_key[-1])


async def catalogue_revision(db, *, year=None):
    """Read committed 0067 catalogue and 0056 source fences, without a write.

    The catalogue trigger covers INSERT/UPDATE/DELETE/TRUNCATE of materials,
    papers, works and paper_work_map, including raw SQL and parent changes.
    Source lifecycle events are trigger-only, and share these transactions.
    A writing or repeatable-read caller cannot publish its private snapshot.
    """
    if db.new or db.dirty or db.deleted:
        return None
    row = (await db.execute(text("""
        SELECT r.epoch, r.xmin::text, s.epoch, s.xmin::text,
               pg_current_xact_id_if_assigned()::text,
               current_setting('transaction_isolation')
        FROM public.research_integrity_epoch r
        CROSS JOIN public.source_lifecycle_epoch s WHERE r.id=1 AND s.id=1
    """))).one_or_none()
    if row is None or row[4] is not None or row[5] != "read committed":
        return None
    # The bound Engine/Connection separates databases and credentials. xmin
    # also separates rolled-back/reused epoch values; the year is policy input.
    return (db.sync_session.get_bind(), *row[:4], datetime.now(UTC).year if year is None else year)

