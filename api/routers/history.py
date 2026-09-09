"""GET/DELETE /history — per-user Ask history.

Rows are written by ``routers.ask`` on every successful authenticated
/ask call. A periodic task in ``main.py`` prunes rows older than 90
days (product decision — see project memory file).

Both endpoints use the JWT auth path (``current_user_from_jwt``). Ask
history is dashboard-UI data, not something external API-key clients
need to read, so we don't expose it on the X-API-Key path.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import AskHistory, Base, User, get_engine
from models.history_receipts import HistoryEvidenceDetail, HistoryReceiptSummary
from models.personal import AskHistoryDetailResponse, AskHistoryEntry, AskHistoryListResponse
from models.user import MessageResponse
from routers.auth import current_user_from_jwt
from services import answer_evidence
from services.history_evidence import current_history_evidence

router = APIRouter(prefix="/history", tags=["history"])
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_LIST_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_DETAIL_BYTES = 3 * 1024 * 1024
RECEIPT_VERSION = "ask-answer-evidence/1.0.0"


async def history_read_session(request: Request):
    """Check mutable evidence in a bounded, request-local read-only snapshot."""
    try:
        async with asyncio.timeout(10):
            async with AsyncSession(get_engine().execution_options(isolation_level="REPEATABLE READ")) as session:
                async with session.begin():
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                    await session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                    # Resolve the session and account in the SAME snapshot as
                    # private history, not a detached identity from another DB.
                    user = await current_user_from_jwt(request,
                        authorization=request.headers.get("authorization"), db=session)
                    session.info["history_owner_id"] = user.id
                    yield session
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "Cache-Control": "private, no-store"}
        raise
    except (SQLAlchemyError, TimeoutError):
        raise HTTPException(503, "Current history evidence unavailable", headers={"Cache-Control": "private, no-store"}) from None


@router.get("", response_model=AskHistoryListResponse)
async def list_history(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(history_read_session),
) -> AskHistoryListResponse:
    """List the current user's Ask history, newest first.

    Paginated because power users can accumulate hundreds of entries
    within the 90-day window. Frontend default page size is 50.
    """
    # total first so the dashboard can render the "N questions" counter
    # without pulling all rows
    total_q = await db.execute(
        select(func.count()).select_from(AskHistory)
        .where(AskHistory.user_id == db.info["history_owner_id"])
    )
    total = int(total_q.scalar_one() or 0)

    # Reserve the complete page before hydrating potentially large saved text.
    page = (await db.execute(select(AskHistory.id, _history_size())
        .where(AskHistory.user_id == db.info["history_owner_id"])
        .order_by(AskHistory.created_at.desc(), AskHistory.id.desc())
        .offset(offset)
        .limit(limit))).all()
    if sum(size for _, size in page) > MAX_PAGE_BYTES:
        raise HTTPException(503, "History page exceeds the safe size limit; request fewer entries")
    q = await db.execute(select(AskHistory).where(AskHistory.id.in_([identifier for identifier, _ in page]))
        .order_by(AskHistory.created_at.desc(), AskHistory.id.desc()))
    rows = q.scalars().all()
    current_evidence = await current_history_evidence(db, rows)
    receipts = await _receipt_summaries(db, rows)
    response.headers["Cache-Control"] = "private, no-store"
    result = AskHistoryListResponse(
        total=total,
        results=[AskHistoryEntry.model_validate(r).model_copy(update={
            "current_evidence": current_evidence[r.id],
            "receipt": receipts[r.id],
        }) for r in rows],
        limit=limit,
        offset=offset,
    )
    if len(result.model_dump_json().encode("utf-8")) > MAX_LIST_RESPONSE_BYTES:
        raise HTTPException(503, "History page exceeds the safe size limit; request fewer entries")
    return result


def _history_size():
    return func.octet_length(cast(func.to_jsonb(AskHistory.__table__.table_valued()), Text))


async def _receipt_summaries(db, rows):
    if not rows:
        return {}
    table = Base.metadata.tables["answer_evidence_receipts"]
    recorded = {row.history_id: row for row in (await db.execute(select(
        table.c.history_id, table.c.version, table.c.record_sha256)
        .where(table.c.history_id.in_([row.id for row in rows])))).all()}
    summaries = {}
    for row in rows:
        receipt = recorded.get(row.id)
        if row.evidence_receipt_version is None and receipt is None:
            summaries[row.id] = HistoryReceiptSummary()
        elif row.evidence_receipt_version == RECEIPT_VERSION and receipt is not None and receipt.version == RECEIPT_VERSION:
            summaries[row.id] = HistoryReceiptSummary(status="recorded", receipt_sha256=receipt.record_sha256)
        else:
            summaries[row.id] = HistoryReceiptSummary(status="unavailable")
    return summaries


@router.get("/{entry_id}", response_model=AskHistoryDetailResponse)
async def get_history_entry(entry_id: UUID, response: Response,
                            db: AsyncSession = Depends(history_read_session)) -> AskHistoryDetailResponse:
    """Owner-only saved evidence; no provider, active-index or source refresh."""
    header = (await db.execute(select(AskHistory.id, _history_size()).where(
        AskHistory.id == entry_id, AskHistory.user_id == db.info["history_owner_id"]))).one_or_none()
    if header is None:
        raise HTTPException(404, "History entry not found")
    if header[1] > MAX_DETAIL_BYTES // 2:
        raise HTTPException(503, "Saved history exceeds the safe size limit")
    row = await db.get(AskHistory, entry_id)
    summary = (await _receipt_summaries(db, [row]))[row.id]
    result_current_evidence = {}
    if summary.status == "legacy_unpinned":
        detail = HistoryEvidenceDetail(status="legacy_unpinned", reason_codes=["legacy_receipt_not_recorded"])
    else:
        table = Base.metadata.tables["answer_evidence_receipts"]
        size = await db.scalar(select(func.octet_length(table.c.request_json)
            + func.octet_length(table.c.response_json) + func.octet_length(table.c.bindings_json))
            .where(table.c.history_id == row.id))
        try:
            if summary.status != "recorded" or type(size) is not int or not 1 <= size <= 1024 * 1024:
                raise ValueError("Receipt unavailable")
            stored = (await db.execute(select(table).where(table.c.history_id == row.id))).mappings().one()
            receipt = await answer_evidence.verify_historical(db, stored)
            if receipt["record_sha256"] != summary.receipt_sha256 or receipt["history_id"] != str(row.id):
                raise ValueError("Receipt identity changed")
            detail = HistoryEvidenceDetail(status="verified", receipt=receipt,
                binding_scope=answer_evidence.binding_scope(receipt["bindings"]), historical_integrity_verified=True)
            numeric_sources = [{"paper_id": item["binding"]["paper_id"]}
                               for item in receipt["response"]["scientific_results"]]
            if numeric_sources:
                result_current_evidence = (await current_history_evidence(db,
                    [SimpleNamespace(id=row.id, sources=numeric_sources)]))[row.id]
        except (ValueError, KeyError, TypeError):
            detail = HistoryEvidenceDetail(status="unavailable", reason_codes=["receipt_unavailable"])
    current = (await current_history_evidence(db, [row]))[row.id]
    entry = AskHistoryEntry.model_validate(row).model_copy(update={"current_evidence": current, "receipt": summary})
    result = AskHistoryDetailResponse(entry=entry, evidence=detail, result_current_evidence=result_current_evidence)
    if len(result.model_dump_json().encode("utf-8")) > MAX_DETAIL_BYTES:
        raise HTTPException(503, "Saved history exceeds the safe size limit")
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.delete("/{entry_id}", response_model=MessageResponse)
async def delete_history_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    """Delete one history entry owned by the current user.

    Cross-user deletes 404 (not 403) so an attacker can't confirm whether
    a specific UUID exists.
    """
    row = await db.get(AskHistory, entry_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "History entry not found")
    await db.delete(row)
    await db.commit()
    return MessageResponse(message="Deleted")
