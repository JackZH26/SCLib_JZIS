"""Owned native SQL proofs. All accepting records and reviewer acts are synthetic.

The scalar vocabulary mirrors the captured Pt rank90 shape; it is not a claim
that its original source/window or native retained provenance was recovered.
"""
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from services import material_field_cases as cases
from services import material_field_review as review
from services.research_release_manifest import canonical, digest
from services.source_property_pending import SourcePropertyConflict
from tests.research_access_helpers import research_operator, revoke_research_grant
from tests.test_material_field_cases import target
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _owned_db_session
from tests.test_source_expression_contract_v2 import span, synthetic_package

PREFIX = "/v1/research/material-field-review"
FORMULA = "BaFe1.906Pt0.094As2"
db_session = _owned_db_session


def migration85(connection, action):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0085_material_field_review.py"
    spec = importlib.util.spec_from_file_location("field_review_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, action)()


@pytest.mark.asyncio
async def test_0085_empty_roundtrip_retains_all_other_rows_and_functions(db_session):
    before = await state(db_session)
    assert all(not before[n] for n in review.TABLE_ORDER)
    functions = "SELECT proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND proname LIKE 'sclib_material_field_review_%' ORDER BY proname"
    original_functions = (await db_session.execute(sa.text(functions))).all()
    connection = await db_session.connection()
    await connection.run_sync(lambda c: migration85(c, "downgrade"))
    assert not (await db_session.execute(sa.text(functions))).all()
    await connection.run_sync(lambda c: migration85(c, "upgrade"))
    assert (await db_session.execute(sa.text(functions))).all() == original_functions
    assert await state(db_session) == before


def pt_shape():
    return {"year": 2009, "family": "iron_based", "formula": FORMULA, "tc_kelvin": 23.0,
        "tc_type": "unknown", "measurement": "resistivity", "hc2_tesla": 65.0, "hc2_conditions": "0 K",
        "lattice_a": 3.9772, "lattice_c": 12.988, "doping_level": 0.094, "confidence": 0.9,
        "tc_regime": "bulk_equilibrium", "ambient_sc": True, "paper_type": "experimental",
        "doping_type": "electron", "sample_form": "single_crystal", "space_group": "I4/mmm",
        "evidence_type": "primary_experimental", "credibility_tier": "T1", "crystal_structure": "Tetragonal",
        "is_unconventional": True, "synthetic": True}


async def fixture(db, field="tc_criterion", *, record_changes=None, source_method="resistivity", role="reported_result_condition", extra_kind=None, extra_method="resistivity", target_curator=None, capture_curator=None):
    curator = await research_operator()
    capture_actor = capture_curator or curator
    reviewer = await research_operator(role="reviewer")
    token = uuid4().hex
    paper, material = "review-paper:"+token, "review-material:"+token
    raw = pt_shape()
    if field == "measurement_method":
        raw["measurement"] = None
    raw.update(record_changes or {})
    raw["paper_id"] = paper
    await add(db, "papers", id=paper, source="arxiv", title="Synthetic representative-shape review", authors=[], abstract="Synthetic only", status="published")
    await add(db, "materials", id=material, formula=FORMULA, formula_normalized=FORMULA, family="iron_based", records=[raw])
    _, retained_target, ctx = await target(db, target_curator or curator, material)
    source = FORMULA+" observed superconductivity at 23 K using "+source_method+" with onset criterion under 2 GPa pressure."
    if extra_kind == "method":
        source += " A separate "+extra_method+" statement occurs in this synthetic paragraph."
    elif extra_kind == "other_tc":
        source += " A distinct transition is 21.5 K with zero resistance."
    elif extra_kind == "hc2":
        source += " A separate upper critical field is 65 T with midpoint criterion at 5 GPa pressure."
    package = synthetic_package()
    import base64
    from hashlib import sha256
    package["source_text_base64"] = base64.b64encode(source.encode()).decode()
    package["source_content_sha256"] = sha256(source.encode()).hexdigest()
    package["source"].update(source_id="synthetic:review:"+token, currentness="declared_current", rights_status="declared_private_inspection")
    expr = package["expressions"][0]
    expr.update(subject={"formula_spans": [span(source, FORMULA)], "sample_label_spans": []},
        knowledge_origin="Observed", origin_basis={"statement": "Synthetic reported observation", "spans": [span(source, "observed")]},
        model_spans=[], value_spans=[span(source, "23")], unit_spans=[span(source, "K")],
        conditions=[{"field_id": "method_statement", "role": "reported_result_condition", "value_spans": [span(source, source_method)], "unit_spans": []},
            {"field_id": "criterion_statement", "role": "reported_result_condition", "value_spans": [span(source, "onset criterion")], "unit_spans": []},
            {"field_id": "pressure_gpa", "role": role, "value_spans": [span(source, "2", source.index("under"))], "unit_spans": [span(source, "GPa")]}])
    if extra_kind:
        other = deepcopy(expr)
        if extra_kind == "method":
            other.update(field_id="method_statement", value_spans=[span(source, extra_method, source.index(" A separate"))], unit_spans=[], conditions=[])
        elif extra_kind == "other_tc":
            other.update(value_spans=[span(source, "21.5")], unit_spans=[span(source, "K", source.index("21.5"))])
            other["conditions"][1]["value_spans"] = [span(source, "zero resistance")]
        else:
            other.update(field_id="hc2_tesla", value_spans=[span(source, "65")], unit_spans=[span(source, "T", source.index("65"))])
            other["conditions"][1]["value_spans"] = [span(source, "midpoint criterion")]
            other["conditions"][2]["value_spans"] = [span(source, "5", source.index("at 5"))]
            other["conditions"][2]["unit_spans"] = [span(source, "GPa", source.index("at 5"))]
        if extra_kind != "other_tc":
            package["expressions"].append(other)
    key = "synthetic:review-import:"+token
    preview = await review.expressions.import_package(db, actor_user_id=capture_actor["id"], request_key_value=key, package=package)
    saved = await review.expressions.import_package(db, actor_user_id=capture_actor["id"], request_key_value=key, package=package,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    eid = str(review.expressions._stable("revision", saved["receipt_id"], 0))
    if capture_curator:
        assert extra_kind is None
        first = await review.expressions.expression(db, actor_user_id=curator["id"], revision_id=eid)
        expr["predecessor"] = {"revision_id": eid, "record_sha256": first["record_sha256"], "revision_number": first["revision_number"]}
        p2 = await review.expressions.import_package(db, actor_user_id=curator["id"], request_key_value=key+":new-importer", package=package)
        saved2 = await review.expressions.import_package(db, actor_user_id=curator["id"], request_key_value=key+":new-importer", package=package,
            dry_run=False, expected_preview_sha256=p2["preview_sha256"])
        assert saved2["capture_id"] == saved["capture_id"]
        eid = str(review.expressions._stable("revision", saved2["receipt_id"], 0))
    if extra_kind == "other_tc":
        original = await review.expressions.expression(db, actor_user_id=curator["id"], revision_id=eid)
        other["predecessor"] = {"revision_id": eid, "record_sha256": original["record_sha256"], "revision_number": original["revision_number"]}
        package["expressions"] = [other]
        p2 = await review.expressions.import_package(db, actor_user_id=curator["id"], request_key_value=key+":successor", package=package)
        await review.expressions.import_package(db, actor_user_id=curator["id"], request_key_value=key+":successor", package=package,
            dry_run=False, expected_preview_sha256=p2["preview_sha256"])
    index = {"measurement_method": 0, "tc_criterion": 1, "pressure_gpa": 2}[field]
    return curator, reviewer, material, paper, raw, retained_target, ctx, eid, index


async def sibling(db, eid):
    t = review.Base.metadata.tables["source_expression_revisions_v2"]
    capture = await db.scalar(sa.select(t.c.capture_id).where(t.c.id == review.identifier(eid)))
    return str(await db.scalar(sa.select(t.c.id).where(t.c.capture_id == capture, t.c.id != review.identifier(eid))))


async def sql_request_insert(db, reviewer, req):
    """Rehash all submitted envelope bytes while bypassing Python validation."""
    grant, session = await review._grant(db, reviewer["id"], "reviewer")
    rid = uuid4()
    preview = {"version": review.contract.VERSION, "receipt_id": str(rid), "actor_user_id": str(reviewer["id"]),
        "actor_grant_id": str(grant["id"]), "actor_session_version": session, "request_sha256": digest(req)}
    row = {"id": rid, "actor_user_id": reviewer["id"], "actor_grant_id": grant["id"], "actor_session_version": session,
        "request_key": req["request_key"], "request_json": canonical(req).decode(), "request_sha256": digest(req),
        "preview_json": canonical(preview).decode(), "preview_sha256": digest(preview)}
    row["record_sha256"] = digest(review._body(row))
    await review._insert(db, review.TABLE_ORDER[0], row)


async def request_for(db, reviewer, target, eid, field, index):
    ctx = await review.context(db, actor_user_id=reviewer["id"], target_id=target["target_id"], field_id=field,
                               expression_revision_id=eid, component_index=index)
    item = deepcopy(ctx["item_template"])
    item.update(decision="accept", checks={k: "satisfied" for k in review.contract.CHECKS},
        source_inspection_attested=True, rationale="Synthetic native fixture: exact retained Tc, method and source component inspected.")
    return {"version": review.contract.VERSION, "profile_version": review.contract.PROFILE,
            "request_key": "review-test:"+uuid4().hex, "items": [item]}, ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("field", review.contract.FIELDS)
async def test_actual_append_preview_commit_effective_and_no_retained_mutation(db_session, field):
    curator, reviewer, material, _, raw, t, _, eid, index = await fixture(db_session, field)
    req, ctx = await request_for(db_session, reviewer, t, eid, field, index)
    assert ctx["subject"]["eligible"], ctx["subject"]["reason_codes"]
    assert ctx["subject"]["target_user_id"] == str(curator["id"])
    assert ctx["subject"]["association_user_id"] is None
    assert digest(__import__("json").loads(ctx["subject_canonical_json"])) == ctx["subject_sha256"]
    assert ctx["subject"]["admission"]["legacy_result_id"] == cases.legacy_result_id(raw, scope_id=material)
    assert ctx["subject"]["admission"]["retained_record_sha256"] == digest(raw)
    assert ctx["subject"]["candidate_sha256"] == digest(ctx["subject"]["candidate"])
    expression = await review.expressions.expression(db_session, actor_user_id=reviewer["id"], revision_id=eid)
    assert ctx["subject"]["candidate"]["value_spans"] == expression["source_entry"]["conditions"][index]["value_spans"]
    assert ctx["subject"]["candidate"]["unit_spans"] == expression["source_entry"]["conditions"][index]["unit_spans"]
    before = await state(db_session)
    preview = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    assert await state(db_session) == before
    saved = await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False,
                                  expected_preview_sha256=preview["preview_sha256"])
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    effective = await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id=field)
    assert effective["field_fidelity_accepted"] and effective["effective_value"]["value"]["raw_value"]
    assert cases.text_sha(effective["effective_value_canonical_json"]) == req["items"][0]["expected_candidate_sha256"]
    assert all(effective[k] == v for k,v in review.contract.AUTHORITY.items())
    after = await state(db_session)
    changed = {k for k in before if before[k] != after[k]}
    assert set(review.TABLE_ORDER) <= changed
    assert changed <= set(review.TABLE_ORDER) | {"research_integrity_epoch", "source_lifecycle_epoch", "research_publication_epoch"}
    replay = await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False)
    assert replay["replayed"] and await state(db_session) == after
    recovered = await review.outcome(db_session, actor_user_id=reviewer["id"], request_key_value=req["request_key"],
                                      expected_request_sha256=saved["request_sha256"])
    assert recovered["receipt_sha256"] == saved["receipt_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [({"measurement": "specific_heat"}, "different_measurement_window"),
    ({"tc_criterion": "existing criterion"}, "field_already_reported_or_ambiguous"),
    ({"method": "specific_heat"}, "different_measurement_window"),
    ({"tc_type": "zero_resistance"}, "coarse_criterion_requires_review"),
    ({"tc_kelvin": 140.0}, "finite_retained_eligibility_hold"),
    ({"scientific_values": {"tc_kelvin": {"raw_value": 23}}}, "finite_retained_eligibility_hold"),
    ({"year": 2009.0}, "finite_retained_eligibility_hold"),
    ({"pressure_gpa": 0.0}, "finite_retained_eligibility_hold")])
async def test_contextual_and_unsupported_holds_cannot_accept(db_session, changes, expected):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session, record_changes=changes)
    req, ctx = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    assert expected in ctx["subject"]["reason_codes"]
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    assert await state(db_session) == before
    req["items"][0].update(decision="request_clarification", source_inspection_attested=False,
                           checks={k: "unresolved" for k in review.contract.CHECKS})
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    assert not (await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion"))["field_fidelity_accepted"]


@pytest.mark.asyncio
async def test_study_extent_component_is_not_tc_pressure(db_session):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session, "pressure_gpa", role="study_extent")
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await request_for(db_session, reviewer, t, eid, "pressure_gpa", index)


@pytest.mark.asyncio
async def test_private_head_successor_and_source_hold_hide_value(db_session):
    _, reviewer, material, paper, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    req2, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    req2["items"][0]["decision"] = "reject"
    p2 = await review.operate(db_session, actor_user_id=reviewer["id"], request=req2)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req2, dry_run=False, expected_preview_sha256=p2["preview_sha256"])
    hist = await review.history(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], limit=1)
    assert hist["total"] == 2 and hist["next_offset"] == 1 and hist["entries"][0]["is_head"]
    assert not (await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion"))["field_fidelity_accepted"]
    await db_session.execute(sa.update(review.Base.metadata.tables["papers"]).where(review.Base.metadata.tables["papers"].c.id==paper).values(status="withdrawn"))
    held = await review.history(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"])
    assert all(not r["field_fidelity_accepted"] for r in held["entries"])
    assert all(r["effective_value"] is None for r in held["entries"])


@pytest.mark.asyncio
async def test_changed_pins_and_actor_key_are_conflicts(db_session):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    with pytest.raises(SourcePropertyConflict):
        await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256="0"*64)
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    other = deepcopy(req)
    other["items"][0]["rationale"] += " Changed."
    with pytest.raises(SourcePropertyConflict):
        await review.operate(db_session, actor_user_id=reviewer["id"], request=other)


@pytest.mark.asyncio
async def test_sql_admission_matches_current_v2_exact_source_partition(db_session):
    curator, reviewer, material, paper, raw, t, _, eid, index = await fixture(db_session)
    other_paper = "held-paper:"+uuid4().hex
    await add(db_session, "papers", id=other_paper, source="arxiv", title="Synthetic held same-value control", authors=[], abstract="Synthetic only", status="withdrawn")
    other = {**raw, "paper_id": other_paper}
    mt = review.Base.metadata.tables["materials"]
    await db_session.execute(sa.update(mt).where(mt.c.id==material).values(records=[raw,other]))
    # The old target fingerprint changed. Establish a fresh exact target.
    _, fresh, _ = await target(db_session, curator, material)
    req, ctx = await request_for(db_session, reviewer, fresh, eid, "tc_criterion", index)
    assert ctx["subject"]["eligible"]
    assert ctx["subject"]["admission"]["visibility_version"] == "material-visibility/2.0.0"
    python = await cases.eligibility(db_session, (await cases.row_by_id(db_session,"target",fresh["target_id"]))["context_json"],
        (await cases.row_by_id(db_session,"target",fresh["target_id"]))["payload"]["target"])
    assert python["eligible"]
    denied = await db_session.scalar(sa.text("SELECT public.sclib_material_field_review_admission_v1(:m,1)"), {"m": material})
    assert not denied["eligible"] and denied["paper_id"] == other_paper
    assert denied["legacy_result_id"] != ctx["subject"]["admission"]["legacy_result_id"]
    preview = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    assert preview["dry_run"]


@pytest.mark.asyncio
async def test_rehashed_sql_cannot_transfer_other_tc_condition_via_companion(db_session):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session, extra_kind="other_tc")
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    other = await review.expressions.expression(db_session, actor_user_id=reviewer["id"], revision_id=await sibling(db_session, eid))
    parent = await review.expressions.expression(db_session, actor_user_id=reviewer["id"], revision_id=eid)
    assert other["projection"]["window"] == parent["projection"]["window"]
    assert other["projection"]["value"]["value"] == 21.5 and parent["projection"]["value"]["value"] == 23
    item = req["items"][0]
    item["expression"] = {k: other[k] for k in ("id", "record_sha256", "projection_sha256")}
    item["tc_expression"] = {k: parent[k] for k in ("id", "record_sha256", "projection_sha256")}
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="tc_companion_scope"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field,index", [("tc_criterion", 1), ("pressure_gpa", 2)])
async def test_two_live_heads_hc2_conditions_cannot_transfer_to_tc_companion(db_session, field, index):
    _, reviewer, _, _, _, t, _, eid, _ = await fixture(db_session, field, extra_kind="hc2")
    req, _ = await request_for(db_session, reviewer, t, eid, field, index)
    other_id = await sibling(db_session, eid)
    other = await review.expressions.expression(db_session, actor_user_id=reviewer["id"], revision_id=other_id)
    parent = await review.expressions.expression(db_session, actor_user_id=reviewer["id"], revision_id=eid)
    for expression_id in (eid, other_id):
        sql = await db_session.scalar(sa.text("SELECT public.sclib_material_field_review_expression_v1(:e)"), {"e": review.identifier(expression_id)})
        assert sql["current"]
    assert other["projection"]["window"] == parent["projection"]["window"]
    assert other["projection"]["subject"] == parent["projection"]["subject"]
    assert other["projection"]["field_id"] == "hc2_tesla" and parent["projection"]["field_id"] == "tc_kelvin"
    item = req["items"][0]
    item["expression"] = {k: other[k] for k in ("id", "record_sha256", "projection_sha256")}
    item["tc_expression"] = {k: parent[k] for k in ("id", "record_sha256", "projection_sha256")}
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="tc_companion_scope"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("method,accepted", [("resistivity", True), ("specific_heat", False)])
async def test_standalone_method_must_match_explicit_tc_companion_technique(db_session, method, accepted):
    _, reviewer, _, _, _, t, _, eid, _ = await fixture(db_session, "measurement_method", extra_kind="method", extra_method=method)
    context = await review.context(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="measurement_method",
        expression_revision_id=await sibling(db_session, eid), component_kind="value", tc_expression_revision_id=eid)
    assert context["subject"]["eligible"] is accepted
    req = {"version": review.contract.VERSION, "profile_version": review.contract.PROFILE,
        "request_key": "standalone-method:"+uuid4().hex, "items": [deepcopy(context["item_template"])]}
    req["items"][0].update(decision="accept", source_inspection_attested=True, checks={k: "satisfied" for k in review.contract.CHECKS},
        rationale="Synthetic standalone method and explicit companion technique inspected.")
    if accepted:
        p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
        await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
        assert (await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="measurement_method"))["field_fidelity_accepted"]
    else:
        assert "different_measurement_window" in context["subject"]["reason_codes"]
        with pytest.raises(DBAPIError, match="acceptance_unavailable"):
            await review.operate(db_session, actor_user_id=reviewer["id"], request=req)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,reason", [({"knowledge_origin": "Computed"}, "retained_origin_requires_review"),
    ({"result_origin": "Inferred"}, "retained_origin_requires_review"), ({"knowledge_origin": "AI-Proposed"}, "retained_origin_requires_review"),
    ({"paper_type": "theoretical"}, "retained_origin_requires_review"), ({"evidence_type": "primary_theoretical"}, "retained_origin_requires_review"),
    ({"tc_regime": "photoinduced_nonequilibrium"}, "retained_regime_requires_review"), ({"source_role": "cited_result"}, "retained_regime_requires_review")])
async def test_explicit_original_origin_or_regime_cannot_be_overridden(db_session, changes, reason):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session, record_changes=changes)
    req, ctx = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    assert reason in ctx["subject"]["reason_codes"]
    with pytest.raises(DBAPIError, match="acceptance_unavailable"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["dft", "DFPT", "first-principles", "density functional theory", "scdft"])
async def test_computed_method_origin_cannot_use_observed_source_when_genre_is_absent(db_session, method):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session, source_method=method,
        record_changes={"measurement": method, "paper_type": None, "evidence_type": None})
    req, ctx = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    assert "retained_origin_requires_review" in ctx["subject"]["reason_codes"]
    with pytest.raises(DBAPIError, match="acceptance_unavailable"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)


@pytest.mark.asyncio
async def test_malformed_selected_paper_is_held_even_with_negative_other_source(db_session):
    curator, reviewer, material, _, raw, t, _, eid, index = await fixture(db_session)
    malformed = " malformed-paper:"+uuid4().hex+" "
    held = "held-paper:"+uuid4().hex
    for paper, status in [(malformed, "published"), (held, "withdrawn")]:
        await add(db_session, "papers", id=paper, source="arxiv", title="Synthetic identifier control", authors=[], abstract="Synthetic only", status=status)
    raw = {**raw, "paper_id": malformed}
    mt = review.Base.metadata.tables["materials"]
    await db_session.execute(sa.update(mt).where(mt.c.id==material).values(records=[raw, {**raw, "paper_id": held}]))
    admitted = await db_session.scalar(sa.text("SELECT public.sclib_material_field_review_admission_v1(:m,0)"), {"m": material})
    assert not admitted["eligible"] and admitted["visibility_version"] == "material-visibility/2.0.0"
    # A rehashed submitted identity cannot avoid the independent SQL bound.
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    req["items"][0]["source_identity"]["paper_id"] = malformed
    with pytest.raises(DBAPIError, match="selector_shape"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["curator_grant", "curator_session", "reviewer_grant", "reviewer_session"])
async def test_late_authority_change_withholds_value_and_keeps_history(db_session, authority):
    curator, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    await db_session.commit()
    actor = curator if authority.startswith("curator") else reviewer
    if authority.endswith("grant"):
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
    else:
        u = review.Base.metadata.tables["users"]
        await db_session.execute(sa.update(u).where(u.c.id==actor["id"]).values(session_version=u.c.session_version+1))
        await db_session.commit()
    # A different current reader can still inspect preserved private history.
    reader = await research_operator()
    h = await review.history(db_session, actor_user_id=reader["id"], target_id=t["target_id"])
    assert h["total"] == 1 and not h["entries"][0]["field_fidelity_accepted"]
    assert h["entries"][0]["effective_value"] is None and h["entries"][0]["effective_value_canonical_json"] is None
    expected = "target_authority_held" if authority.startswith("curator") else "reviewer_authority_unavailable"
    assert expected in h["entries"][0]["reason_codes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role,change", [("capture", "grant"), ("capture", "session"), ("import", "grant"), ("import", "session"),
    ("association", "grant"), ("association", "session")])
async def test_distinct_source_or_association_authority_loss_is_individually_held(db_session, role, change):
    from tests.test_material_field_cases import association
    target_actor, capture_actor, association_actor = await research_operator(), await research_operator(), await research_operator()
    importer, reviewer, _, paper, _, t, _, eid, index = await fixture(db_session, target_curator=target_actor, capture_curator=capture_actor)
    expression = await review.expressions.expression(db_session, actor_user_id=association_actor["id"], revision_id=eid)
    a_req = association(t, expression, paper)
    ap = await cases.operate(db_session, actor_user_id=association_actor["id"], request=a_req)
    assoc = await cases.operate(db_session, actor_user_id=association_actor["id"], request=a_req, dry_run=False, expected_preview_sha256=ap["preview_sha256"])
    context = await review.context(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion",
        expression_revision_id=eid, component_index=index, association_id=assoc["receipt_id"])
    assert context["subject"]["eligible"]
    assert context["subject"]["target_user_id"] == str(target_actor["id"])
    assert context["subject"]["association_user_id"] == str(association_actor["id"])
    assert context["subject"]["capture_user_id"] == str(capture_actor["id"])
    assert context["subject"]["importer_user_id"] == str(importer["id"])
    assert digest(__import__("json").loads(context["subject_canonical_json"])) == context["subject_sha256"]
    req = {"version": review.contract.VERSION, "profile_version": review.contract.PROFILE,
        "request_key": "distinct-authority:"+uuid4().hex, "items": [deepcopy(context["item_template"])]}
    req["items"][0].update(decision="accept", source_inspection_attested=True, checks={k: "satisfied" for k in review.contract.CHECKS},
        rationale="Synthetic distinct capture, importer, target and association authors inspected.")
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    await db_session.commit()
    actor = {"capture": capture_actor, "import": importer, "association": association_actor}[role]
    if change == "grant":
        await revoke_research_grant(grant_id=actor["grant_id"], revoked_by=actor["grantor_id"])
    else:
        users = review.Base.metadata.tables["users"]
        await db_session.execute(sa.update(users).where(users.c.id==actor["id"]).values(session_version=users.c.session_version+1))
        await db_session.commit()
    effective = await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion")
    assert not effective["field_fidelity_accepted"] and effective["effective_value"] is None
    assert effective["effective_value_canonical_json"] is None
    reasons = effective["decision"]["reason_codes"]
    assert "target_authority_held" not in reasons and "reviewer_authority_unavailable" not in reasons
    expected = "association_held" if role == "association" else "source_expression_held"
    assert expected in reasons
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(review.table(1)).where(review.table(1).c.target_id==review.identifier(t["target_id"]))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path,value", [("source_inspection_attested", None), ("source_inspection_attested", 1),
    ("decision", None), ("checks", {k: None for k in review.contract.CHECKS}), ("rationale", "short"),
    ("predecessor", {"id": str(uuid4()), "record_sha256": "a"*64}), ("resolves_decision_id", str(uuid4()))])
async def test_independent_sql_rejects_rehashed_nullable_or_unbound_shapes(db_session, path, value):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    req["items"][0][path] = value
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, req)
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_clarification_requires_exact_resolution_and_predecessor_head(db_session):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    req["items"][0]["decision"] = "request_clarification"
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    next_req, ctx = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    assert next_req["items"][0]["resolves_decision_id"] == next_req["items"][0]["predecessor"]["id"]
    mutant = deepcopy(next_req)
    mutant["items"][0]["resolves_decision_id"] = None
    with pytest.raises(DBAPIError, match="exact_head_required"):
        async with db_session.begin_nested():
            await sql_request_insert(db_session, reviewer, mutant)
    p2 = await review.operate(db_session, actor_user_id=reviewer["id"], request=next_req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=next_req, dry_run=False, expected_preview_sha256=p2["preview_sha256"])
    effective = await review.effective(db_session, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion")
    assert effective["field_fidelity_accepted"]
    assert effective["decision"]["id"] != next_req["items"][0]["predecessor"]["id"]
    with pytest.raises(DBAPIError, match="exact_head_required"):
        async with db_session.begin_nested():
            stale = deepcopy(req)
            stale["request_key"] += ":stale"
            await sql_request_insert(db_session, reviewer, stale)


@pytest.mark.asyncio
async def test_private_api_default_off_role_preview_commit_recovery_and_exact_value(db_session, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from config import get_settings
    from main import app
    curator, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "source_property_pending_enabled", False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        disabled = await client.get(PREFIX+"/capabilities", headers=reviewer["headers"])
        assert disabled.status_code == 404 and "no-store" in disabled.headers["cache-control"]
        monkeypatch.setattr(get_settings(), "source_property_pending_enabled", True)
        anonymous = await client.get(PREFIX+"/capabilities")
        assert anonymous.status_code == 401 and "no-store" in anonymous.headers["cache-control"]
        read_only = await client.get(PREFIX+"/capabilities", headers=curator["headers"])
        assert read_only.status_code == 200 and not read_only.json()["can_write"]
        denied = await client.post(PREFIX+"/operations/preview", headers=curator["headers"], json={"request": req})
        assert denied.status_code == 403
        preview = await client.post(PREFIX+"/operations/preview", headers=reviewer["headers"], json={"request": req})
        assert preview.status_code == 200, preview.text
        assert preview.json()["dry_run"] and "no-store" in preview.headers["cache-control"]
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(review.table(0)).where(review.table(0).c.request_key==req["request_key"])) == 0
        await db_session.rollback()
        commit = await client.post(PREFIX+"/operations/commit", headers=reviewer["headers"],
            json={"request": req, "expected_preview_sha256": preview.json()["preview_sha256"]})
        assert commit.status_code == 200, commit.text
        outcome = await client.get(PREFIX+"/operations/outcome", headers=reviewer["headers"],
            params={"request_key": req["request_key"], "expected_request_sha256": commit.json()["request_sha256"]})
        assert outcome.status_code == 200 and outcome.json()["receipt_sha256"] == commit.json()["receipt_sha256"]
        from sqlalchemy.ext.asyncio import AsyncSession

        from models.db import get_engine
        async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as private_read:
            await private_read.execute(sa.text("SET TRANSACTION READ ONLY"))
            assert (await review.effective(private_read, actor_user_id=reviewer["id"], target_id=t["target_id"], field_id="tc_criterion"))["field_fidelity_accepted"]
        effective = await client.get(PREFIX+"/targets/"+t["target_id"]+"/effective", headers=reviewer["headers"], params={"field_id": "tc_criterion"})
        assert effective.status_code == 200, effective.text
        assert effective.json()["field_fidelity_accepted"]
        assert cases.text_sha(effective.json()["effective_value_canonical_json"]) == req["items"][0]["expected_candidate_sha256"]
        assert all(effective.json()[k] == v for k,v in review.contract.AUTHORITY.items())
        strict = await client.post(PREFIX+"/operations/preview", headers={**reviewer["headers"], "Content-Type": "application/json"},
            content='{"request":{},"request":{}}')
        assert strict.status_code >= 400 and "no-store" in strict.headers["cache-control"]


@pytest.mark.asyncio
async def test_0085_nonempty_history_refuses_downgrade_and_is_immutable(db_session):
    _, reviewer, _, _, _, t, _, eid, index = await fixture(db_session)
    req, _ = await request_for(db_session, reviewer, t, eid, "tc_criterion", index)
    p = await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    await review.operate(db_session, actor_user_id=reviewer["id"], request=req, dry_run=False, expected_preview_sha256=p["preview_sha256"])
    before = await state(db_session)
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="Refusing downgrade"):
        await connection.run_sync(lambda c: migration85(c, "downgrade"))
    for table in review.TABLE_ORDER:
        for sql in ("UPDATE public."+table+" SET record_sha256=record_sha256", "DELETE FROM public."+table, "TRUNCATE public."+table+" CASCADE"):
            with pytest.raises(DBAPIError, match="append-only"):
                async with db_session.begin_nested():
                    await db_session.execute(sa.text(sql))
    assert await state(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("path,sha,entry_index,field,component", [
    ("/private/tmp/sclib-field-cases-genuine-pt-packages-r2-20261002/pt_resistivity_onset_zero.json", "4620f292957f04f6fbf7e7009f80205e2fdb707cc3ec548a20fae7954b3c1994", 0, "tc_criterion", 1),
    ("/private/tmp/sclib-scientific-completion-ranks97-166-199-20261002-r1/packages-r1/1603.02892.source-expression-v2.json", "f503220bce5941786798573a6d3f6acbfdd858d4101a35ab367026484566cd28", 1, "tc_criterion", 1),
    ("/private/tmp/sclib-scientific-completion-ranks97-166-199-20261002-r1/packages-r2-caption-scope/1501.06203.source-expression-v2.json", "34bb4c106b5d97c0f883b3bdda25046f031a513b6fbeb16d6688c6feab55bd82", 0, "pressure_gpa", 0)])
async def test_pinned_genuine_packets_remain_refusal_or_clarification_not_real_native_acceptance(db_session, path, sha, entry_index, field, component):
    import json
    from hashlib import sha256
    from pathlib import Path

    source = Path(path)
    if not source.is_file():
        pytest.skip("Pinned local source packet is unavailable; no genuine-source assertion made.")
    data = source.read_bytes()
    assert sha256(data).hexdigest() == sha
    package = json.loads(data)
    assert package["source"]["rights_status"] == "unresolved"
    curator, reviewer, _, _, _, t, _, _, _ = await fixture(db_session)
    key = "genuine-pending:"+uuid4().hex
    preview = await review.expressions.import_package(db_session, actor_user_id=curator["id"], request_key_value=key, package=package)
    saved = await review.expressions.import_package(db_session, actor_user_id=curator["id"], request_key_value=key, package=package,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    eid = str(review.expressions._stable("revision", saved["receipt_id"], entry_index))
    req, ctx = await request_for(db_session, reviewer, t, eid, field, component)
    assert "source_expression_held" in ctx["subject"]["reason_codes"] and not ctx["subject"]["eligible"]
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="acceptance_unavailable"):
        await review.operate(db_session, actor_user_id=reviewer["id"], request=req)
    assert await state(db_session) == before
    assert source.read_bytes() == data
