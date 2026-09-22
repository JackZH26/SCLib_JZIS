"""Synthetic exact-version negative reviews on guarded disposable PostgreSQL."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import research_publication as publication
from services import source_lifecycle as service
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from services.source_lifecycle_status import combined_lifecycle_revision, lifecycle_revision
from tests.test_research_freeze import add, seed, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session


async def prepared_review(db, *, kind="paper", claim=False):
    people = await actors(db)
    fixture = await seed(db, with_children=False)
    name, column = ("papers", "status") if kind == "paper" else ("works", "publication_status")
    await db.execute(sa.text(f"UPDATE {name} SET {column}='corrected' WHERE id=:id"), {"id": fixture[kind]})
    inspection = await service.inspect_source_lifecycle(db, **{f"{kind}_id": fixture[kind]})
    event = inspection["head"]
    arguments = dict(actor_user_id=people["reviewer"], expected_event_id=event["id"],
        expected_event_sha256=event["record_sha256"], decision="retain_hold", reason_code="synthetic_revision_check")
    if claim:
        claim_hash = (await db.execute(sa.text("SELECT public.sclib_source_lifecycle_snapshot_hash_v1('claim',to_jsonb(c)) "
            "FROM material_claims c WHERE id=:id"), {"id": fixture["claim"]})).scalar_one()
        arguments.update(claim_id=fixture["claim"], expected_claim_revision_sha256=claim_hash)
    preview = await service.preview_source_review(db, **arguments)
    payload = canonical(preview["document"])
    artifact = await add(db, "evidence_artifacts", kind="review", schema_version=service.POLICY_VERSION,
        source="synthetic-test", record_sha256=preview["document_sha256"], bytes_sha256=preview["bytes_sha256"],
        hash_status="verified", access="restricted", metadata={"source_lifecycle_review": preview["document"]})
    arguments.update(request_key="synthetic-" + uuid4().hex, review_artifact_id=artifact["id"], review_bytes=payload)
    return {"actors": people, "fixture": fixture, "event": event, "preview": preview,
        "review_args": arguments, "artifact": artifact}


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_review_rehearsal_rollback_and_exact_idempotency(db_session, kind):
    context = await prepared_review(db_session, kind=kind)
    before = await state(db_session)
    rehearsal = await service.record_source_review(db_session, **context["review_args"])
    assert rehearsal["dry_run"] and rehearsal["committed"] is False
    assert await state(db_session) == before
    receipt = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    assert not receipt["replayed"] and receipt["current_review"]
    assert receipt["scientific_acceptance"] is receipt["source_reinstatement"] is receipt["ml_training_approved"] is False
    replay = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    assert replay["id"] == receipt["id"] and replay["replayed"]
    assert (await service.inspect_source_review(db_session, receipt["id"]))["current_review"]
    inspection = await service.inspect_source_lifecycle(db_session, **{f"{kind}_id": context["fixture"][kind]})
    assert inspection["lifecycle_review_required"] is True


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_reset_status_does_not_restore_and_stales_exact_review(db_session, kind):
    context = await prepared_review(db_session, kind=kind)
    receipt = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    original = (await service.inspect_source_review(db_session, receipt["id"]))["review"]
    name, column, status = ("papers", "status", "published") if kind == "paper" else ("works", "publication_status", "active")
    await db_session.execute(sa.text(f"UPDATE {name} SET {column}=:status WHERE id=:id"),
        {"status": status, "id": context["fixture"][kind]})
    resolver = service.resolve_paper_lifecycle if kind == "paper" else service.resolve_work_lifecycle
    overlay = (await resolver(db_session, [str(context["fixture"][kind])]))[str(context["fixture"][kind])]
    assert overlay["status"] == status and overlay["lifecycle_review_required"] is True
    assert overlay["lifecycle_revision"] != context["event"]["record_sha256"]
    current = await service.inspect_source_review(db_session, receipt["id"])
    assert current["current_review"] is False and current["review"] == original
    before = await state(db_session)
    with pytest.raises(service.SourceLifecycleError, match="revision changed"):
        await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_claim_binding_is_exact_and_current(db_session, kind):
    context = await prepared_review(db_session, kind=kind, claim=True)
    receipt = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    await db_session.execute(sa.text("UPDATE material_claims SET value_kelvin=40 WHERE id=:id"),
        {"id": context["fixture"]["claim"]})
    assert (await service.inspect_source_review(db_session, receipt["id"]))["current_review"] is False
    with pytest.raises(service.SourceLifecycleError, match="exact explicitly linked claim"):
        await service.record_source_review(db_session, **context["review_args"], dry_run=False)


async def test_unrelated_claim_cannot_bind_by_generic_material_or_work(db_session):
    context = await prepared_review(db_session)
    other = await seed(db_session, with_children=False)
    claim_hash = (await db_session.execute(sa.text("SELECT public.sclib_source_lifecycle_snapshot_hash_v1('claim',to_jsonb(c)) "
        "FROM material_claims c WHERE id=:id"), {"id": other["claim"]})).scalar_one()
    args = {key: value for key, value in context["review_args"].items()
            if key not in {"request_key", "review_artifact_id", "review_bytes"}}
    with pytest.raises(service.SourceLifecycleError, match="exact explicitly linked claim"):
        await service.preview_source_review(db_session, **args, claim_id=other["claim"], expected_claim_revision_sha256=claim_hash)


@pytest.mark.parametrize("role", ["member", "admin"])
async def test_legacy_flags_cannot_authorize_review(db_session, role):
    context = await prepared_review(db_session)
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.record_source_review(db_session, **{**context["review_args"],
            "actor_user_id": context["actors"][role]}, dry_run=False)
    assert await state(db_session) == before


async def test_revoked_grant_invalidates_currentness_without_erasing_receipt(db_session):
    context = await prepared_review(db_session)
    receipt = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    await publication.revoke_role(db_session, actor_user_id=context["actors"]["admin"],
        grant_id=context["actors"]["grants"]["reviewer"], reason_code="synthetic_revocation", dry_run=False)
    assert (await service.inspect_source_review(db_session, receipt["id"]))["current_review"] is False
    with pytest.raises(ResearchAccessDenied):
        await service.record_source_review(db_session, **context["review_args"], dry_run=False)


@pytest.mark.parametrize("mutation", ["bytes", "extra_field", "artifact_hash", "artifact_access", "artifact_metadata", "event_hash"])
async def test_review_hash_and_actual_bytes_are_not_self_asserted(db_session, mutation):
    context = await prepared_review(db_session)
    args = dict(context["review_args"])
    if mutation == "bytes":
        args["review_bytes"] += b" "
    elif mutation == "extra_field":
        args["review_bytes"] = canonical({**context["preview"]["document"], "approved": True})
    elif mutation == "event_hash":
        args["expected_event_sha256"] = "0" * 64
    else:
        field, value = {"artifact_hash": ("record_sha256", "0" * 64), "artifact_access": ("access", "public"),
            "artifact_metadata": ("metadata", {})}[mutation]
        table = Base.metadata.tables["evidence_artifacts"]
        await db_session.execute(table.update().where(table.c.id == context["artifact"]["id"]).values(**{field: value}))
    before = await state(db_session)
    with pytest.raises(service.SourceLifecycleError):
        await service.record_source_review(db_session, **args, dry_run=False)
    assert await state(db_session) == before


async def test_reviews_supersede_exact_scope_without_clearing_hold(db_session):
    context = await prepared_review(db_session)
    first = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    args = {key: value for key, value in context["review_args"].items()
            if key not in {"request_key", "review_artifact_id", "review_bytes"}}
    args["decision"] = "requires_supersession"
    preview = await service.preview_source_review(db_session, **args)
    artifact = await add(db_session, "evidence_artifacts", kind="review", schema_version=service.POLICY_VERSION,
        source="synthetic-test", record_sha256=preview["document_sha256"], bytes_sha256=preview["bytes_sha256"],
        hash_status="verified", access="restricted", metadata={"source_lifecycle_review": preview["document"]})
    args.update(request_key="synthetic-" + uuid4().hex, review_artifact_id=artifact["id"], review_bytes=canonical(preview["document"]))
    with pytest.raises(service.SourceLifecycleError, match="predecessor"):
        await service.record_source_review(db_session, **args, dry_run=False)
    second = await service.record_source_review(db_session, **args, supersedes_id=first["id"], dry_run=False)
    assert second["current_review"] and second["lifecycle_review_required"]
    assert not (await service.inspect_source_review(db_session, first["id"]))["current_review"]
    replay = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    assert replay["replayed"] and not replay["current_review"]


async def test_idempotency_key_cannot_be_reused_for_a_different_artifact_binding(db_session):
    context = await prepared_review(db_session)
    await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    preview = context["preview"]
    duplicate_document = await add(db_session, "evidence_artifacts", kind="review", schema_version=service.POLICY_VERSION,
        source="synthetic-test", record_sha256=preview["document_sha256"], bytes_sha256=preview["bytes_sha256"],
        hash_status="verified", access="restricted", metadata={"source_lifecycle_review": preview["document"]})
    before = await state(db_session)
    with pytest.raises(service.SourceLifecycleError, match="Idempotency key"):
        await service.record_source_review(db_session, **{**context["review_args"],
            "review_artifact_id": duplicate_document["id"]}, dry_run=False)
    assert await state(db_session) == before


async def test_nonserializable_review_session_is_rejected(db_session):
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.db import get_engine

    context = await prepared_review(db_session)
    engine = get_engine().execution_options(isolation_level="READ COMMITTED")
    try:
        async with AsyncSession(engine) as ordinary:
            with pytest.raises(service.SourceLifecycleError, match="SERIALIZABLE"):
                await service.record_source_review(ordinary, **context["review_args"], dry_run=False)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("target", ["review", "artifact"])
async def test_review_and_registered_document_are_immutable(db_session, target):
    context = await prepared_review(db_session)
    receipt = await service.record_source_review(db_session, **context["review_args"], dry_run=False)
    name = "source_lifecycle_reviews" if target == "review" else "evidence_artifacts"
    identifier = UUID(receipt["id"]) if target == "review" else context["artifact"]["id"]
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f"DELETE FROM {name} WHERE id=:id"), {"id": identifier})


async def test_accepted_work_negative_history_propagates_without_rewriting_paper_status(db_session):
    context = await prepared_review(db_session, kind="work")
    fixture = context["fixture"]
    await add(db_session, "paper_work_map", paper_id=fixture["paper"], work_id=fixture["work"],
        relation_type="published_version", match_method="manual", review_status="pending")
    assert (await service.resolve_paper_lifecycle(db_session, [fixture["paper"]]))[fixture["paper"]] == "published"
    assert not (await service.inspect_source_lifecycle(db_session, paper_id=fixture["paper"]))["lifecycle_review_required"]
    await db_session.execute(sa.text("UPDATE paper_work_map SET review_status='accepted' WHERE paper_id=:id"), {"id": fixture["paper"]})
    await db_session.execute(sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": fixture["work"]})
    overlay = (await service.resolve_paper_lifecycle(db_session, [fixture["paper"]]))[fixture["paper"]]
    work = (await service.resolve_work_lifecycle(db_session, [fixture["work"]]))[str(fixture["work"])]
    assert overlay["status"] == "published" and overlay["lifecycle_review_required"]
    assert lifecycle_revision(overlay) == combined_lifecycle_revision(None, lifecycle_revision(work))
    inspection = await service.inspect_source_lifecycle(db_session, paper_id=fixture["paper"])
    assert inspection["head"] is None and inspection["events"] == []
    assert inspection["direct_lifecycle_review_required"] is False and inspection["lifecycle_review_required"] is True
    assert inspection["effective_lifecycle_revision"] == lifecycle_revision(overlay)
    assert (await db_session.execute(sa.text("SELECT status FROM papers WHERE id=:id"), {"id": fixture["paper"]})).scalar_one() == "published"


async def test_source_inspection_cursor_and_missing_inventory(db_session):
    context = await prepared_review(db_session)
    identifier = context["fixture"]["paper"]
    await db_session.execute(sa.text("UPDATE papers SET status='published' WHERE id=:id"), {"id": identifier})
    current = await service.inspect_source_lifecycle(db_session, paper_id=identifier, limit=1)
    assert current["events"][0]["revision"] == 2 and current["next_before_revision"] == 2
    older = await service.inspect_source_lifecycle(db_session, paper_id=identifier, before_revision=2, limit=1)
    assert older["head"] == current["head"] and older["events"][0]["revision"] == 1
    assert older["next_before_revision"] is None
    assert await service.resolve_paper_lifecycle(db_session, ["missing:" + uuid4().hex]) == {}
    with pytest.raises(service.SourceLifecycleError, match="inventory limit"):
        await service.resolve_paper_lifecycle(db_session, [identifier] * (service.MAX_SOURCES + 1))
    with pytest.raises(service.SourceLifecycleError, match="bounded iterable"):
        await service.resolve_paper_lifecycle(db_session, None)
    with pytest.raises(service.SourceLifecycleError, match="history window"):
        await service.inspect_source_lifecycle(db_session, paper_id=identifier, before_revision=2**32)


@pytest.mark.parametrize("key,value", [("decision", "reinstate"), ("review_bytes", bytearray(b"x")),
    pytest.param("review_bytes", b"x" * (service.MAX_REVIEW_BYTES + 1), id="oversized_review_bytes"),
    ("request_key", "bad key"), ("dry_run", 1), ("claim_id", uuid4())])
async def test_bounded_closed_inputs_fail_before_review_mutation(db_session, key, value):
    context = await prepared_review(db_session)
    before = await state(db_session)
    with pytest.raises(service.SourceLifecycleError):
        await service.record_source_review(db_session, **{**context["review_args"], key: value})
    assert await state(db_session) == before
