"""Independent ML04 integration on owned disposable PostgreSQL.

Seeds are actual typed SQL rows with database defaults. Artifact and processing
review bytes are really hashed and verified. All source results remain pending;
an integrity capsule must never imply scientific, publication or ML approval.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services import research_freeze as freeze
from services import research_release_manifest as contract


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def add(db, table_name, **values):
    table = Base.metadata.tables[table_name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


async def state(db):
    """Full SQL row equality, including guard epoch and unrelated tables."""
    # Compare timestamptz instants under a fixed SQL rendering timezone, not
    # the caller's pre/post-commit session default (+08 on this local host).
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    result = {}
    for name, table in sorted(Base.metadata.tables.items()):
        rows = (await db.execute(sa.select(sa.func.to_jsonb(table.table_valued())))).scalars().all()
        result[name] = sorted(rows, key=contract.canonical)
    return result


async def seed(db, *, with_children=True):
    token = uuid4().hex
    material = "freeze-material:" + token
    paper = "freeze-paper:" + token
    await add(db, "materials", id=material, formula="MgB2", formula_normalized="MgB2",
              records=[{"tc_kelvin": 39, "synthetic": True}])
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic freeze integration",
              authors=[], abstract="Synthetic fixture only", status="published")
    work = (await add(db, "works", canonical_title="Synthetic freeze integration"))["id"]
    artifacts = {}
    async def artifact(kind, document):
        payload = contract.canonical(document)
        sha = hashlib.sha256(payload).hexdigest()
        artifacts[sha] = payload
        return (await add(db, "evidence_artifacts", kind=kind, schema_version="synthetic/1",
            source="synthetic-test", record_sha256=contract.digest(document), bytes_sha256=sha,
            hash_status="verified", access="restricted", metadata={"synthetic": True}))["id"]
    source = await artifact("literature_locator", {"source": "synthetic", "page": 1})
    policies = [await artifact("policy", {"role": role, "version": "synthetic/1"})
                for role in ("task", "property_registry")]
    snapshot = (await add(db, "source_snapshots", dataset_version=token,
                         schema_version="synthetic/1", material_count=1, paper_count=1))["id"]
    material_state = (await add(db, "material_states", material_id=material,
        resolution="source_scoped", condition_schema_version="synthetic/1",
        pressure_status="not_reported", temperature_role="unknown", context_sha256="b" * 64,
        source_artifact_id=source))["id"]
    event = (await add(db, "research_events", material_id=material, state_id=material_state,
        event_type="measurement", knowledge_origin="Observed", record_sha256="c" * 64))["id"]
    claim = (await add(db, "material_claims", material_id=material, paper_id=paper, work_id=work,
        source_snapshot_id=snapshot, event_id=event, result_key="tc-main", interpretation_revision=1,
        source_record_hash=hashlib.sha256(token.encode()).hexdigest(), value_relation="exact",
        value_kelvin=39, result_status="observed", source_kind="table", extractor_version="synthetic/1",
        raw_record={"tc": "39 K", "synthetic": True}))["id"]
    member = (await add(db, "snapshot_event_memberships", snapshot_id=snapshot, event_id=event,
        event_revision=1, source_occurrence_key="table:1:row:1", locator={"table": "1"},
        source_record_sha256="d" * 64, result_manifest_sha256="e" * 64))["id"]
    dataset = (await add(db, "ml_dataset_snapshots", source_snapshot_id=snapshot,
        name="synthetic-freeze-" + token, version="1", label_policy_version="synthetic/1",
        feature_schema_version="synthetic/1", split_ruleset_version="synthetic/1", row_count=1))["id"]
    example = (await add(db, "ml_examples", dataset_snapshot_id=dataset, example_key="one",
        claim_id=claim, material_id=material, work_id=work, split="train", task_type="tc_regression",
        label_data={"synthetic_pending": True}, work_group=str(work), material_group=material,
        duplicate_group=token, assignment_hash="f" * 64))["id"]
    children = {}
    if with_children:
        children["property"] = (await add(db, "event_properties", event_id=event,
            property_key="band_gap", relation="exact", value=0, unit="eV",
            record_sha256="1" * 64))["id"]
        children["evidence"] = (await add(db, "event_evidence", event_id=event, link_type="source",
            artifact_id=source, locator={"table": "1", "row": "1"}))["id"]
        children["qc"] = (await add(db, "claim_qc", claim_id=claim, qc_version="synthetic/1"))["id"]
        children["input"] = (await add(db, "ml_example_inputs", example_id=example,
            input_kind="property", input_event_id=event, input_property_id=children["property"],
            feature_key="synthetic_band_gap", matching_policy_version="synthetic/1",
            record_sha256="2" * 64))["id"]
        children["sibling_claim"] = (await add(db, "material_claims", material_id=material,
            source_snapshot_id=snapshot, event_id=event, result_key="tc-secondary", interpretation_revision=1,
            source_record_hash=hashlib.sha256((token + "sibling").encode()).hexdigest(),
            value_relation="lt", value_upper_kelvin=40, source_kind="table", extractor_version="synthetic/1"))["id"]
    return {"args": {"dataset_id": dataset, "policy_artifact_ids": policies,
        "source_roots": [{"table": "snapshot_event_memberships", "row_id": str(member)}],
        "artifact_bytes": artifacts}, "material": material, "paper": paper, "work": work,
        "source": source, "snapshot": snapshot, "state": material_state, "event": event,
        "claim": claim, "example": example, "member": member, "children": children}


async def approved(db, fixture, *, mutate_review=None):
    preview = await freeze.preview_research_release(db, **fixture["args"])
    document = contract.processing_review_payload(preview["manifest"])
    if mutate_review:
        mutate_review(document)
    payload = contract.canonical(document)
    sha = hashlib.sha256(payload).hexdigest()
    review = await add(db, "evidence_artifacts", kind="review", schema_version=contract.REVIEW_VERSION,
        source="synthetic-reviewer", record_sha256=contract.digest(document), bytes_sha256=sha,
        hash_status="verified", access="restricted", metadata={"shadow_freeze_review": document})
    arguments = {**fixture["args"], "artifact_bytes": {**fixture["args"]["artifact_bytes"], sha: payload},
                 "review_artifact_id": review["id"]}
    return preview, arguments


async def test_preview_captures_actual_full_rows_and_all_owned_children(db_session):
    fixture = await seed(db_session)
    before = await state(db_session)
    preview = await freeze.preview_research_release(db_session, **fixture["args"])
    assert await state(db_session) == before
    found = {(row["table"], row["row_id"]): row for row in preview["manifest"]["rows"]}
    for name, identifier in (("ml_example_inputs", fixture["children"]["input"]),
                             ("claim_qc", fixture["children"]["qc"]),
                             ("material_claims", fixture["children"]["sibling_claim"]),
                             ("event_properties", fixture["children"]["property"]),
                             ("event_evidence", fixture["children"]["evidence"])):
        assert (name, str(identifier)) in found
    for key, row in found.items():
        assert set(row["data"]) == contract.TABLE_FIELDS[key[0]]
        assert row["row_sha256"] == contract.digest(row["data"])
    assert found[("material_claims", str(fixture["claim"]))]["data"]["validity_status"] == "pending"
    assert found[("material_states", str(fixture["state"]))]["data"]["pressure_gpa"] is None
    assert found[("ml_dataset_snapshots", str(fixture["args"]["dataset_id"]))]["data"]["status"] == "building"
    assert preview["database_mutated"] is False
    assert preview["scientific_acceptance"] is preview["ml_training_approved"] is preview["public_release"] is False


async def test_dry_run_restores_all_rows_epoch_and_release_tables(db_session):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    before = await state(db_session)
    report = await freeze.freeze_research_release(db_session, **args)
    assert report["dry_run"] is True and report["rows_inserted"] > 0 and report["committed"] is False
    assert await state(db_session) == before


async def test_commit_and_retry_pin_once_without_automatic_scientific_approval(db_session):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    first = await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert first["committed"] is False
    await db_session.commit()
    before = await state(db_session)
    replay = await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert replay["release_id"] == first["release_id"] and replay["replayed"] is True
    assert replay["rows_inserted"] == 0
    # Successful live guard acquisitions may advance the serialization epoch;
    # an idempotent replay adds no release, pin, notice or source row.
    after = await state(db_session)
    assert {key: value for key, value in before.items() if key != "research_integrity_epoch"} == {
        key: value for key, value in after.items() if key != "research_integrity_epoch"}
    assert replay["ml_training_approved"] is replay["scientific_acceptance"] is replay["public_release"] is False
    await db_session.commit()


@pytest.mark.parametrize("target", ["claim", "material", "input", "owned_child"])
async def test_change_after_review_rejects_instead_of_freezing_mixed_version(db_session, target):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    if target == "owned_child":
        await add(db_session, "event_properties", event_id=fixture["event"], property_key="omega_log",
                  relation="exact", value=300, unit="K", record_sha256="3" * 64)
    else:
        table, identifier, values = {
            "claim": ("material_claims", fixture["claim"], {"value_kelvin": 38}),
            "material": ("materials", fixture["material"], {"needs_review": True}),
            "input": ("ml_example_inputs", fixture["children"]["input"], {"feature_key": "different"}),
        }[target]
        relation = Base.metadata.tables[table]
        await db_session.execute(relation.update().where(relation.c.id == identifier).values(**values))
    before = await state(db_session)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="review preview mismatch"):
        await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("mode", ["missing", "tampered", "undeclared", "wrong_type"])
async def test_unavailable_or_changed_artifact_bytes_block_freeze(db_session, mode):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    payloads = dict(args["artifact_bytes"])
    key = next(iter(payloads))
    if mode == "missing":
        del payloads[key]
    elif mode == "tampered":
        payloads[key] = b"changed"
    elif mode == "wrong_type":
        payloads[key] = payloads[key].decode()
    else:
        payloads[hashlib.sha256(b"extra").hexdigest()] = b"extra"
    before = await state(db_session)
    with pytest.raises((contract.ResearchReleaseVerificationError, freeze.ResearchFreezeError)):
        await freeze.freeze_research_release(db_session, **{**args, "artifact_bytes": payloads}, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("field,value", [("restricted_internal_processing_approved", 1),
                                         ("scientific_acceptance", True), ("ml_training_approved", True)])
async def test_resealed_review_cannot_change_authorization_semantics(db_session, field, value):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture, mutate_review=lambda document: document.update({field: value}))
    before = await state(db_session)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="review preview mismatch"):
        await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert await state(db_session) == before


async def test_base_exception_mid_pin_rolls_back_and_allows_clean_retry(db_session, monkeypatch):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    before = await state(db_session)
    original = db_session.execute
    pins = 0
    class Interrupted(BaseException):
        pass
    async def interrupt(statement, *positional, **keywords):
        nonlocal pins
        if getattr(statement, "is_insert", False) and statement.table.name == "research_release_pins":
            pins += 1
            if pins == 3:
                raise Interrupted("Synthetic interrupted pin sequence")
        return await original(statement, *positional, **keywords)
    with monkeypatch.context() as context:
        context.setattr(db_session, "execute", interrupt)
        with pytest.raises(Interrupted):
            await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert pins == 3
    assert await state(db_session) == before
    report = await freeze.freeze_research_release(db_session, **args, dry_run=False)
    assert report["rows_inserted"] > 3 and report["replayed"] is False
    await db_session.commit()


async def test_historical_inspection_survives_live_catalogue_governance_change(db_session):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    report = await freeze.freeze_research_release(db_session, **args, dry_run=False)
    await db_session.commit()
    materials, papers = Base.metadata.tables["materials"], Base.metadata.tables["papers"]
    await db_session.execute(materials.update().where(materials.c.id == fixture["material"]).values(needs_review=True))
    await db_session.execute(papers.update().where(papers.c.id == fixture["paper"]).values(status="retracted"))
    await db_session.commit()
    historical = await freeze.inspect_research_release(db_session, release_id=report["release_id"],
        expected_manifest_sha256=report["manifest_sha256"], artifact_bytes=args["artifact_bytes"])
    assert historical["manifest"] == report["manifest"]
    assert historical["current_eligibility_reassessed"] is False
    assert historical["scientific_acceptance"] is historical["ml_training_approved"] is False
    paper = next(row for row in historical["manifest"]["rows"] if row["table"] == "papers")
    assert paper["data"]["status"] == "published"


@pytest.mark.parametrize("target", ["claim_update", "claim_delete", "new_property", "new_input", "new_example"])
async def test_frozen_scientific_rows_and_owned_membership_cannot_change(db_session, target):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    await freeze.freeze_research_release(db_session, **args, dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    with pytest.raises(sa.exc.DBAPIError, match="frozen_research"):
        async with db_session.begin_nested():
            if target == "new_property":
                await add(db_session, "event_properties", event_id=fixture["event"], property_key="omega_log",
                    relation="exact", value=300, unit="K", record_sha256="4" * 64)
            elif target == "new_input":
                await add(db_session, "ml_example_inputs", example_id=fixture["example"],
                    input_kind="artifact", input_artifact_id=fixture["source"], feature_key="new-input",
                    matching_policy_version="synthetic/1", record_sha256="5" * 64)
            elif target == "new_example":
                original = (await db_session.execute(sa.select(Base.metadata.tables["ml_examples"]).where(
                    Base.metadata.tables["ml_examples"].c.id == fixture["example"]))).mappings().one()
                await add(db_session, "ml_examples", **{**dict(original), "id": uuid4(), "example_key": "new",
                    "task_type": "superconductivity_classification"})
            else:
                table = Base.metadata.tables["material_claims"]
                statement = table.update().values(value_kelvin=38) if target == "claim_update" else table.delete()
                await db_session.execute(statement.where(table.c.id == fixture["claim"]))
    assert await state(db_session) == before


@pytest.mark.parametrize("dry_run", [None, 0, 1, "false"])
async def test_dry_run_parameter_requires_boolean(db_session, dry_run):
    fixture = await seed(db_session)
    _, args = await approved(db_session, fixture)
    with pytest.raises(freeze.ResearchFreezeError, match="Boolean"):
        await freeze.freeze_research_release(db_session, **args, dry_run=dry_run)


async def test_read_committed_session_is_rejected_before_writing(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    engine = get_engine()
    try:
        async with AsyncSession(engine) as ordinary:
            with pytest.raises(freeze.ResearchFreezeError, match="SERIALIZABLE"):
                await freeze.preview_research_release(ordinary, **fixture["args"])
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mutation", ["bool_for_integer", "unknown_field", "missing_field", "rows_cap"])
async def test_contract_checks_typed_full_rows_and_resource_cap(db_session, mutation):
    fixture = await seed(db_session)
    preview = await freeze.preview_research_release(db_session, **fixture["args"])
    manifest = deepcopy(preview["manifest"])
    row = next(row for row in manifest["rows"] if row["table"] == "ml_dataset_snapshots")
    if mutation == "bool_for_integer":
        row["data"]["row_count"] = True
    elif mutation == "unknown_field":
        row["data"]["invented_scientific_confidence"] = 1
    elif mutation == "missing_field":
        del row["data"]["filters"]
    else:
        manifest["rows"] = manifest["rows"] * (1001 // len(manifest["rows"]) + 1)
    row["row_sha256"] = contract.digest(row["data"])
    with pytest.raises(contract.ResearchReleaseVerificationError):
        contract.verify_manifest(manifest, artifact_bytes=fixture["args"]["artifact_bytes"], allow_preview=True)


@pytest.mark.parametrize("which", ["policies", "sources", "bytes"])
async def test_service_caps_fail_before_database_access(db_session, which, monkeypatch):
    fixture = await seed(db_session)
    args = dict(fixture["args"])
    if which == "policies":
        args["policy_artifact_ids"] = [uuid4() for _ in range(21)]
    elif which == "sources":
        args["source_roots"] = fixture["args"]["source_roots"] * 1001
    else:
        args["artifact_bytes"] = {hashlib.sha256(str(index).encode()).hexdigest(): b"fixture" for index in range(201)}
    async def forbidden(*args, **kwargs):
        pytest.fail("Malformed bounded parameters must be rejected before opening a transaction")
    with monkeypatch.context() as context:
        context.setattr(db_session, "execute", forbidden)
        with pytest.raises(freeze.ResearchFreezeError):
            await freeze.preview_research_release(db_session, **args)


async def test_actual_database_example_count_cap_is_enforced(db_session):
    fixture = await seed(db_session, with_children=False)
    claims = []
    for index in range(100):
        claims.append({"id": uuid4(), "material_id": fixture["material"],
            "source_snapshot_id": fixture["snapshot"], "event_id": fixture["event"],
            "result_key": f"extra-{index}", "interpretation_revision": 1, "extractor_version": "synthetic/1",
            "source_record_hash": hashlib.sha256(str(index).encode()).hexdigest()})
    await db_session.execute(Base.metadata.tables["material_claims"].insert().values(claims))
    examples = [{"id": uuid4(), "dataset_snapshot_id": fixture["args"]["dataset_id"],
        "example_key": f"extra-{index}", "claim_id": claim["id"], "material_id": fixture["material"],
        "split": "train", "task_type": "tc_regression", "work_group": "synthetic", "material_group": fixture["material"],
        "duplicate_group": str(index), "assignment_hash": "8" * 64} for index, claim in enumerate(claims)]
    await db_session.execute(Base.metadata.tables["ml_examples"].insert().values(examples))
    datasets = Base.metadata.tables["ml_dataset_snapshots"]
    await db_session.execute(datasets.update().where(datasets.c.id == fixture["args"]["dataset_id"]).values(row_count=101))
    before = await state(db_session)
    with pytest.raises(freeze.ResearchFreezeError, match="bounded dataset closure"):
        await freeze.preview_research_release(db_session, **fixture["args"])
    assert await state(db_session) == before


async def test_caller_container_mutation_after_first_await_cannot_change_capture(db_session, monkeypatch):
    fixture = await seed(db_session)
    expected = await freeze.preview_research_release(db_session, **fixture["args"])
    original = freeze._session
    async def change_caller_containers(db):
        fixture["args"]["policy_artifact_ids"].clear()
        fixture["args"]["source_roots"][0]["row_id"] = str(uuid4())
        fixture["args"]["artifact_bytes"].clear()
        await original(db)
    monkeypatch.setattr(freeze, "_session", change_caller_containers)
    observed = await freeze.preview_research_release(db_session, **fixture["args"])
    assert observed["manifest"] == expected["manifest"]


async def notice_approved(db, old, new, *, mutate_review=None):
    document = freeze.notice_review_payload(release_id=old["release_id"],
        manifest_sha256=old["manifest_sha256"], kind="superseded", reason_code="synthetic_capsule_replacement",
        successor_release_id=new["release_id"], successor_manifest_sha256=new["manifest_sha256"])
    if mutate_review:
        mutate_review(document)
    payload = contract.canonical(document)
    review = await add(db, "evidence_artifacts", kind="review", schema_version=freeze.NOTICE_REVIEW_VERSION,
        source="synthetic-reviewer", record_sha256=contract.digest(document),
        bytes_sha256=hashlib.sha256(payload).hexdigest(), hash_status="verified", access="restricted",
        metadata={"release_notice_review": document})
    return {"release_id": old["release_id"], "kind": "superseded", "reason_code": "synthetic_capsule_replacement",
        "successor_release_id": new["release_id"], "review_artifact_id": review["id"], "review_bytes": payload}


async def release_pair(db):
    old_fixture, new_fixture = await seed(db), await seed(db)
    _, old_args = await approved(db, old_fixture)
    _, new_args = await approved(db, new_fixture)
    old = await freeze.freeze_research_release(db, **old_args, dry_run=False)
    new = await freeze.freeze_research_release(db, **new_args, dry_run=False)
    await db.commit()
    return old, new, old_args


async def test_new_release_notice_preserves_both_versions_and_supports_dry_run_retry(db_session):
    old, new, old_args = await release_pair(db_session)
    args = await notice_approved(db_session, old, new)
    before = await state(db_session)
    dry_run = await freeze.append_release_notice(db_session, **args)
    assert dry_run["dry_run"] is True and dry_run["committed"] is False
    assert await state(db_session) == before
    notice = await freeze.append_release_notice(db_session, **args, dry_run=False)
    await db_session.commit()
    repeated = await freeze.append_release_notice(db_session, **args, dry_run=False)
    assert repeated["notice_id"] == notice["notice_id"] and repeated["replayed"] is True
    assert repeated["downstream_propagation_performed"] is repeated["public_release"] is False
    await db_session.commit()
    historical = await freeze.inspect_research_release(db_session, release_id=old["release_id"],
        expected_manifest_sha256=old["manifest_sha256"], artifact_bytes=old_args["artifact_bytes"])
    assert historical["manifest"] == old["manifest"]
    assert len(historical["notices"]) == 1 and str(historical["notices"][0]["id"]) == notice["notice_id"]
    assert historical["scientific_acceptance"] is False
    artifact = Base.metadata.tables["evidence_artifacts"]
    with pytest.raises(sa.exc.DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(artifact.update().where(artifact.c.id == args["review_artifact_id"]).values(
                metadata={"release_notice_review": {"changed": True}}))


@pytest.mark.parametrize("change", ["body", "flag", "bytes"])
async def test_release_notice_rejects_changed_review_body_flag_or_actual_bytes(db_session, change):
    old, new, _ = await release_pair(db_session)
    mutate = None
    if change == "body":
        mutate = lambda document: document.update({"reason_code": "different_reason"})
    elif change == "flag":
        mutate = lambda document: document.update({"restricted_internal_notice_approved": 1})
    args = await notice_approved(db_session, old, new, mutate_review=mutate)
    if change == "bytes":
        args["review_bytes"] += b" "
    before = await state(db_session)
    with pytest.raises(freeze.ResearchFreezeError, match="registered notice review"):
        await freeze.append_release_notice(db_session, **args, dry_run=False)
    assert await state(db_session) == before
