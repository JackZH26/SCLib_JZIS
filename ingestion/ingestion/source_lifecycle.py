"""Read-only negative ledger overlay for ingestion's independent runtime.

There is deliberately no missing-table fallback: an old schema cannot restore
scientific support after a recorded source change. No extraction flags grant
authority, and this reader never acknowledges or clears an event.
"""
from sqlalchemy import column, select, table

from ingestion.source_lifecycle_status import combined_lifecycle_revision, overlay_source_lifecycle

_EVENTS = table("source_lifecycle_events", column("paper_id"), column("work_id"),
                column("revision"), column("record_sha256"))
_MAPPING = table("paper_work_map", column("paper_id"), column("work_id"), column("review_status"))


async def overlay_paper_lifecycle(db, statuses):
    result = dict(statuses)
    identifiers = sorted(statuses)
    for start in range(0, len(identifiers), 1000):
        batch = identifiers[start:start + 1000]
        rows = (await db.execute(select(_EVENTS.c.paper_id, _EVENTS.c.record_sha256)
            .where(_EVENTS.c.paper_id.in_(batch))
            .distinct(_EVENTS.c.paper_id)
            .order_by(_EVENTS.c.paper_id, _EVENTS.c.revision.desc()))).all()
        paper_heads = dict(rows)
        work_heads = dict((await db.execute(select(_MAPPING.c.paper_id, _EVENTS.c.record_sha256)
            .select_from(_MAPPING.join(_EVENTS, _EVENTS.c.work_id == _MAPPING.c.work_id))
            .where(_MAPPING.c.paper_id.in_(batch), _MAPPING.c.review_status == "accepted")
            .distinct(_MAPPING.c.paper_id)
            .order_by(_MAPPING.c.paper_id, _EVENTS.c.revision.desc()))).all())
        for paper_id in paper_heads.keys() | work_heads.keys():
            digest = combined_lifecycle_revision(paper_heads.get(paper_id), work_heads.get(paper_id))
            result[paper_id] = overlay_source_lifecycle(statuses[paper_id], digest)
    return result
