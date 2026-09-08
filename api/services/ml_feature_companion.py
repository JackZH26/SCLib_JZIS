"""Private, separately pinned input-source companions for immutable 0054 bases.

Offline verification authenticates neither a database observation nor a human
review. Exact source-binding declarations do not approve scientific applicability,
rights or model training. Database imports are lazy: verification is pure/offline.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from uuid import UUID, uuid5

from services import research_release_manifest as capsule
from services.ml_frozen_provenance import _registry_intact, _sql_values
from services.temporal_provenance import (
    SourceAvailabilityWitness,
    public_locator,
    result_temporal_provenance,
    utc_datetime,
)

VERSION = "ml-feature-companion/1.0.0"
REVIEW_VERSION = "ml-feature-source-review/1.0.0"
TABLE_NAME = "ml_feature_source_bindings"
MAX_BINDINGS = 500
MAX_ROWS = 1000
MAX_ARTIFACTS = 400
MAX_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_BYTES = 96 * 1024 * 1024
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False, "public_release": False,
             "reviewer_authority_authenticated": False, "database_observation_authenticated": False,
             "live_source_rights_checked": False}
_NAMESPACE = UUID("708c7f73-b2a5-4561-b5f9-dbb2b7ed903c")
_BINDING_FIELDS = {"id", "base_release_id", "base_manifest_sha256", "example_input_id", "source_revision_id",
    "capture_id", "work_id", "locator", "locator_sha256", "review_artifact_id", "review_artifact_kind",
    "review_artifact_sha256", "record_sha256", "created_at"}
_HELD = {"withdrawn", "retracted", "disputed", "corrected", "excluded"}


class FeatureCompanionError(ValueError):
    """An exact bounded companion cannot be verified; input text stays private."""


def _require(condition, reason="feature_companion_unavailable"):
    if not condition:
        raise FeatureCompanionError(reason)


def _hash(value):
    import re
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "feature_hash_required")
    return value


def _uuid(value):
    try:
        _require(type(value) is str and str(UUID(value)) == value, "feature_canonical_uuid_required")
    except (ValueError, AttributeError):
        raise FeatureCompanionError("feature_canonical_uuid_required") from None
    return value


def _bounded(value, maximum=MAX_DOCUMENT_BYTES):
    # Preflight all strings before JSON allocation; canonical performs closed
    # scalar, finite-number, depth and node checks as well.
    pending, total, count = [value], 0, 0
    while pending:
        item = pending.pop()
        count += 1
        _require(count + len(pending) <= 200000, "feature_node_limit")
        if type(item) is str:
            total += len(item.encode("utf-8"))
            _require(total <= maximum, "feature_byte_limit")
        elif type(item) is dict:
            pending.extend(item.keys()); pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    raw = capsule.canonical(value)
    _require(len(raw) <= maximum, "feature_byte_limit")
    return raw


def _plain(value):
    """Normalize native SQL timestamp/UUID values without changing JSON floats."""
    from datetime import date, datetime
    if isinstance(value, UUID): return str(value)
    if isinstance(value, datetime):
        parsed = utc_datetime(value)
        _require(parsed is not None)
        return parsed.isoformat().replace("+00:00", "Z")
    if isinstance(value, date): return value.isoformat()
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list): return [_plain(item) for item in value]
    return value


def binding_sha256(row):
    return capsule.digest({key: value for key, value in row.items()
                           if key not in {"record_sha256", "created_at", "locator"}})


def _base(base_manifest, expected_hash):
    _require(len(_bounded(base_manifest)) <= capsule.LIMITS["file_bytes"])
    _require(capsule.digest(base_manifest) == _hash(expected_hash), "feature_base_hash_mismatch")
    return capsule._rows(base_manifest["rows"])


def feature_input_pins(base_manifest, *, example_input_id):
    """Actual frozen foreign-key paths, never sample-name/formula association."""
    index = capsule._rows(base_manifest["rows"])
    def row(table, identifier):
        value = index.get((table, identifier))
        _require(value is not None, "feature_frozen_dependency_missing")
        return value["data"]
    def pin(table, identifier):
        if identifier is None: return None
        row(table, identifier)
        return {"table": table, "row_id": identifier, "row_sha256": index[(table, identifier)]["row_sha256"]}
    inp = row("ml_example_inputs", _uuid(str(example_input_id)))
    _require(inp["input_kind"] in {"property", "structure"}, "feature_input_kind_unsupported")
    example = row("ml_examples", inp["example_id"])
    label = row("material_claims", example["claim_id"])
    label_event = row("research_events", label["event_id"])
    label_state = row("material_states", label_event["state_id"])
    _require(label["material_id"] == example["material_id"] == label_event["material_id"] == label_state["material_id"])
    if inp["input_kind"] == "property":
        target_table, target_id = "event_properties", inp["input_property_id"]
        target = row(target_table, target_id)
        _require(target["event_id"] == inp["input_event_id"])
        event = row("research_events", target["event_id"])
        state = row("material_states", event["state_id"])
        _require(state["material_id"] == event["material_id"])
        structure_id = event["structure_id"]
    else:
        target_table, target_id = "structure_records", inp["input_structure_id"]
        row(target_table, target_id)
        event, state, structure_id = None, None, target_id
    return {"input": pin("ml_example_inputs", inp["id"]), "target": pin(target_table, target_id),
        "event": pin("research_events", event["id"]) if event else None,
        "state": pin("material_states", state["id"]) if state else None,
        "sample": pin("research_samples", state["sample_id"]) if state else None,
        "structure": pin("structure_records", structure_id),
        "producer_run": pin("research_runs", event["producer_run_id"]) if event else None,
        "label_claim": pin("material_claims", label["id"]), "label_event": pin("research_events", label_event["id"]),
        "label_state": pin("material_states", label_state["id"]),
        "label_sample": pin("research_samples", label_state["sample_id"]),
        "label_material": pin("materials", label["material_id"]),
        "label_structure": pin("structure_records", label_event["structure_id"])}


def _applicability(value):
    _require(type(value) is dict and set(value) == {"mode", "scope", "applicability_verified", "rationale", "uncertainty_note"})
    _require(value["mode"] in {"exact", "normal_state_surrogate"}
        and value["scope"] == "same_composition_pressure_field_phase" and value["applicability_verified"] is True)
    _require(all(type(value[key]) is str and value[key].strip() and len(value[key]) <= 2000
                 for key in ("rationale", "uncertainty_note")))
    return json.loads(_bounded(value, 16384))


def feature_source_review_payload(base_manifest, *, example_input_id, source_revision, capture, locator,
                                  scientific_context, applicability):
    """New review intent only: the caller must obtain an independent actual review."""
    revision = _sql_values("source_revisions", _plain(source_revision))
    capture = _sql_values("source_captures", _plain(capture))
    _require(_registry_intact("source_revisions", revision) and _registry_intact("source_captures", capture))
    _require(revision["id"] == capture["source_revision_id"] and revision["work_id"] is not None)
    safe = public_locator(locator)
    _require(type(locator) is dict and safe and safe == locator, "feature_exact_locator_required")
    _require(type(scientific_context) is dict and scientific_context, "feature_context_required")
    context = json.loads(_bounded(scientific_context, 16384))
    return {"version": REVIEW_VERSION, "base_manifest_sha256": capsule.digest(base_manifest),
        "pins": feature_input_pins(base_manifest, example_input_id=str(example_input_id)),
        "source_revision_id": revision["id"], "source_revision_record_sha256": revision["record_sha256"],
        "capture_id": capture["id"], "capture_record_sha256": capture["record_sha256"],
        "paper_id": revision["paper_id"], "work_id": revision["work_id"],
        "provider_revision": revision["provider_revision"], "source_version_public_at": revision["source_version_public_at"],
        "captured_at": capture["captured_at"], "bytes_sha256": capture["bytes_sha256"], "representation": capture["representation"],
        "locator": safe, "locator_sha256": capsule.digest(safe), "scientific_context": context,
        "applicability": _applicability(applicability), **AUTHORITY}


def _artifact_bytes(values):
    _require(type(values) is dict and len(values) <= MAX_ARTIFACTS)
    total, result = 0, {}
    for sha, raw in values.items():
        _hash(sha)
        _require(type(raw) is bytes and len(raw) <= capsule.LIMITS["file_bytes"])
        total += len(raw)
        _require(total <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == sha, "feature_artifact_bytes_mismatch")
        result[sha] = raw
    return result


def _base_bytes(base, artifacts):
    # Frozen verification derives exactly the expected byte inventory itself.
    expected = {entry["sha256"] for entry in base["artifacts"]}
    _require(expected <= artifacts.keys(), "feature_base_artifact_missing")
    return {sha: artifacts[sha] for sha in expected}


def _binding(row):
    _require(type(row) is dict and set(row) == _BINDING_FIELDS, "feature_binding_shape")
    for key in ("id", "base_release_id", "example_input_id", "source_revision_id", "capture_id", "work_id", "review_artifact_id"):
        _uuid(row[key])
    for key in ("base_manifest_sha256", "locator_sha256", "review_artifact_sha256", "record_sha256"):
        _hash(row[key])
    _require(row["review_artifact_kind"] == "review" and utc_datetime(row["created_at"]) is not None)
    _require(row["locator"] == public_locator(row["locator"]) and row["locator"]
        and row["locator_sha256"] == capsule.digest(row["locator"]))
    _require(row["record_sha256"] == binding_sha256(row), "feature_binding_hash_mismatch")


def _verified_row(binding, base, rows, artifacts):
    _binding(binding)
    def row(table, identifier):
        found = rows.get((table, identifier))
        _require(found is not None, "feature_source_row_missing")
        return found["data"]
    revision, capture = row("source_revisions", binding["source_revision_id"]), row("source_captures", binding["capture_id"])
    paper, work = row("papers", revision["paper_id"]), row("works", binding["work_id"])
    mapping = row("paper_work_map", paper["id"])
    _require(mapping["review_status"] == "accepted" and mapping["work_id"] == revision["work_id"] == binding["work_id"])
    _require(paper["status"] not in _HELD and work["publication_status"] not in _HELD, "feature_source_hold")
    review = row("evidence_artifacts", binding["review_artifact_id"])
    document = review["metadata"].get("ml_feature_source_review")
    _require(type(document) is dict and set(review["metadata"]) == {"ml_feature_source_review"})
    expected = feature_source_review_payload(base, example_input_id=binding["example_input_id"],
        source_revision=revision, capture=capture, locator=binding["locator"],
        scientific_context=document.get("scientific_context"), applicability=document.get("applicability"))
    flags = {"binding_verified", "version_resolved", "public_time_verified"}
    _require(set(document) == set(expected) | flags and all(type(document[key]) is bool for key in flags)
        and all(document[key] is False for key in AUTHORITY)
        and document["binding_verified"] is True and all(document[key] == value for key, value in expected.items()),
        "feature_exact_review_required")
    _require(review["kind"] == "review" and review["schema_version"] == REVIEW_VERSION
        and review["hash_status"] == "verified" and review["record_sha256"] == binding["review_artifact_sha256"]
        == capsule.digest(document) and artifacts.get(review["bytes_sha256"]) == capsule.canonical(document),
        "feature_review_bytes_mismatch")
    _require(artifacts.get(capture["bytes_sha256"]) is not None and capture["source_revision_id"] == revision["id"])
    capture_hashes = {item["data"]["bytes_sha256"] for (table, _), item in rows.items()
                      if table == "source_captures" and item["data"]["source_revision_id"] == revision["id"]
                      and item["data"]["representation"] == capture["representation"]}
    _require(capture_hashes == {capture["bytes_sha256"]}, "feature_conflicting_source_capture")
    witness = SourceAvailabilityWitness(claim_id=binding["example_input_id"], paper_id=paper["id"], work_id=work["id"],
        source_revision_id=revision["id"], source_version=revision["provider_revision"] or revision["revision_key"],
        capture_id=capture["id"], source_version_public_at=utc_datetime(revision["source_version_public_at"]),
        captured_at=utc_datetime(capture["captured_at"]), bytes_sha256=capture["bytes_sha256"],
        representation=capture["representation"], locator=dict(binding["locator"]),
        review_reference=binding["review_artifact_id"] + ":" + binding["review_artifact_sha256"],
        binding_verified=True, version_resolved=revision["version_status"] == "pinned" and document["version_resolved"],
        public_time_verified=revision["availability_status"] == "known_by" and document["public_time_verified"])
    return document, witness, {(kind, identifier) for kind, identifier in (
        ("paper", paper["id"]), ("work", work["id"]), ("source_revision", revision["id"]),
        ("capture", capture["id"]), ("feature_binding", binding["id"]))}


def _source_closure(rows, seeds):
    """Only actual captured foreign-key relationships, including bibliographic bridges."""
    found, pending = set(), set(seeds)
    while pending:
        key = pending.pop()
        if key in found: continue
        _require(key in rows, "feature_source_row_missing")
        found.add(key)
        pending.update(capsule.dependencies(key[0], rows[key]["data"]))
        if key[0] == "papers": pending.add(("paper_work_map", key[1]))
        if key[0] == "source_revisions":
            pending.update(other for other, row in rows.items() if other[0] == "source_captures"
                           and row["data"]["source_revision_id"] == key[1])
    return found


def verify_feature_companion(companion, *, base_manifest, expected_base_manifest_sha256, expected_companion_sha256):
    """Verify complete captured inventory; cannot prove DB completeness offline."""
    try:
        return _verify(companion, base_manifest, expected_base_manifest_sha256, expected_companion_sha256)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise FeatureCompanionError("feature_companion_verification_failed") from None


def _verify(value, base, base_hash, expected_hash):
    _base(base, base_hash)
    _require(type(value) is dict and set(value) == {"version", "base_release_id", "base_manifest_sha256", "bindings",
        "source_rows", "artifacts_base64", "inventory_sha256", "authority", "companion_sha256"})
    raw = _bounded(value)
    value = json.loads(raw)
    _require(value["version"] == VERSION and type(value["authority"]) is dict
        and set(value["authority"]) == set(AUTHORITY) and all(value["authority"][key] is False for key in AUTHORITY)
        and value["base_manifest_sha256"] == base_hash)
    _uuid(value["base_release_id"])
    _require(_hash(expected_hash) == capsule.digest(value)
        and value["companion_sha256"] == capsule.digest({key: item for key, item in value.items() if key != "companion_sha256"}),
        "feature_companion_hash_mismatch")
    encoded = value["artifacts_base64"]
    _require(type(encoded) is dict and len(encoded) <= MAX_ARTIFACTS)
    decoded = {}
    for sha, text in encoded.items():
        _require(type(text) is str and len(text) <= 4 * ((capsule.LIMITS["file_bytes"] + 2) // 3))
        payload = base64.b64decode(text, validate=True)
        _require(base64.b64encode(payload).decode("ascii") == text)
        decoded[sha] = payload
    artifacts = _artifact_bytes(decoded)
    capsule.verify_manifest(base, artifact_bytes=_base_bytes(base, artifacts), expected_manifest_sha256=base_hash)
    bindings = value["bindings"]
    _require(type(bindings) is list and len(bindings) <= MAX_BINDINGS
        and bindings == sorted(bindings, key=lambda item: item["id"]) and len({row["id"] for row in bindings}) == len(bindings))
    _require(value["inventory_sha256"] == capsule.digest(bindings), "feature_inventory_hash_mismatch")
    rows = capsule._rows(value["source_rows"]) if value["source_rows"] else {}
    _require(len(_bounded(value["source_rows"])) <= capsule.LIMITS["file_bytes"])
    for (table, _), envelope in rows.items():
        row = envelope["data"]
        if table in {"source_revisions", "source_captures"}:
            _require(_registry_intact(table, row), "feature_registry_record_hash_mismatch")
        if table == "papers": _require(row["status"] not in _HELD, "feature_source_hold")
        if table == "works": _require(row["publication_status"] not in _HELD, "feature_source_hold")
    result = {}
    seeds = set()
    for binding in bindings:
        _require(binding["base_release_id"] == value["base_release_id"] and binding["base_manifest_sha256"] == base_hash)
        binding_seeds = {("source_revisions", binding["source_revision_id"]), ("source_captures", binding["capture_id"]),
                         ("evidence_artifacts", binding["review_artifact_id"])}
        seeds.update(binding_seeds)
        document, witness, groups = _verified_row(binding, base, rows, artifacts)
        for table, row_id in _source_closure(rows, binding_seeds):
            kind = {"papers": "paper", "works": "work", "source_revisions": "source_revision",
                    "source_captures": "capture"}.get(table)
            if kind: groups.add((kind, row_id))
        identifier = binding["example_input_id"]
        if identifier not in result:
            result[identifier] = {"input_id": identifier, "target_ref": [document["pins"]["target"]["table"], document["pins"]["target"]["row_id"]],
                "pins": document["pins"], "scientific_context": document["scientific_context"], "applicability": document["applicability"],
                "witnesses": [], "review_documents": [], "group_keys": set(), "binding_ids": [], **AUTHORITY}
        out = result[identifier]
        _require(all(out[key] == document[key] for key in ("pins", "scientific_context", "applicability")), "feature_review_conflict")
        out["witnesses"].append(witness); out["review_documents"].append(document)
        out["group_keys"].update(groups); out["binding_ids"].append(binding["id"])
    # Source rows must be exactly the referenced metadata closure, including the
    # current accepted bibliographic mapping and all capture siblings inspected.
    used = _source_closure(rows, seeds)
    _require(used == rows.keys(), "feature_source_inventory_not_exact")
    expected_bytes = set(_base_bytes(base, artifacts))
    for (table, _), row in rows.items():
        if table in {"source_captures", "evidence_artifacts"} and row["data"]["bytes_sha256"] is not None:
            expected_bytes.add(row["data"]["bytes_sha256"])
    _require(expected_bytes == artifacts.keys(), "feature_artifact_inventory_not_exact")
    for identifier, out in result.items():
        out["temporal"] = result_temporal_provenance(claim_id=identifier, witnesses=out["witnesses"])
        out["witnesses"] = tuple(out["witnesses"])
        out["review_documents"] = tuple(out["review_documents"])
        out["group_keys"] = tuple(sorted(out["group_keys"]))
        out["binding_ids"] = tuple(out["binding_ids"])
    return result


def decode_companion_artifacts(companion):
    """Byte-integrity helper only; call verify_feature_companion for authority boundaries."""
    _bounded(companion)
    encoded = companion.get("artifacts_base64")
    _require(type(encoded) is dict and len(encoded) <= MAX_ARTIFACTS)
    decoded = {}
    for sha, text in encoded.items():
        _require(type(text) is str and len(text) <= 4 * ((capsule.LIMITS["file_bytes"] + 2) // 3))
        payload = base64.b64decode(text, validate=True)
        _require(base64.b64encode(payload).decode("ascii") == text)
        decoded[sha] = payload
    return _artifact_bytes(decoded)


async def _session(db, *, write=False):
    import sqlalchemy as sa
    _require(not (db.new or db.dirty or db.deleted), "feature_clean_session_required")
    isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
    _require(isolation == "serializable" if write else isolation in {"serializable", "repeatable read"}, "feature_stable_snapshot_required")
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))


async def _release(db, base_id=None, base_hash=None):
    import sqlalchemy as sa

    from models.db import Base
    from services.research_freeze import _bundle_hash, _stored, _verify_pins
    table = Base.metadata.tables["research_releases"]
    if base_id is None:
        ids = (await db.execute(sa.select(table.c.id).where(table.c.manifest_sha256 == base_hash).limit(2))).scalars().all()
        _require(len(ids) == 1, "feature_exact_release_required")
        base_id = ids[0]
    release = await _stored(db, "research_releases", UUID(str(base_id)))
    _require(release is not None)
    await _verify_pins(db, release)
    _require(release["bundle_sha256"] == _bundle_hash(release["manifest"]))
    notices = Base.metadata.tables["research_release_notices"]
    _require(not (await db.execute(sa.select(notices.c.id).where(notices.c.release_id == release["id"]).limit(1))).first(), "feature_base_notice_hold")
    return release


async def _fetch(db, table_name, identifiers, *, column=None, budget=None):
    from services.research_freeze import _fetch as fetch
    return await fetch(db, table_name, identifiers=identifiers, column=column, byte_budget=budget)


async def _source_rows(db, bindings):
    roots = set()
    for row in bindings:
        roots.update({("source_revisions", str(row["source_revision_id"])), ("source_captures", str(row["capture_id"])),
                      ("evidence_artifacts", str(row["review_artifact_id"]))})
    found, pending, budget = {}, roots, {}
    while pending:
        _require(len(found) + len(pending) <= MAX_ROWS)
        grouped = defaultdict(set)
        for table, identifier in pending: grouped[table].add(identifier)
        current = []
        for table, ids in grouped.items():
            rows = await _fetch(db, table, ids, budget=budget)
            _require({row["row_id"] for row in rows} == ids)
            current.extend(rows)
        papers = {row["row_id"] for row in current if row["table"] == "papers"}
        current.extend(await _fetch(db, "paper_work_map", papers, column="paper_id", budget=budget))
        revisions = {row["row_id"] for row in current if row["table"] == "source_revisions"}
        current.extend(await _fetch(db, "source_captures", revisions, column="source_revision_id", budget=budget))
        pending = set()
        for row in current:
            key = row["table"], row["row_id"]
            _require(key not in found or found[key] == row)
            found[key] = row
            pending.update(capsule.dependencies(row["table"], row["data"]))
        pending -= found.keys()
    _require(len(found) <= MAX_ROWS)
    from services.source_lifecycle import resolve_paper_lifecycle, resolve_work_lifecycle
    from services.source_visibility import source_visibility
    for table, resolver in (("papers", resolve_paper_lifecycle), ("works", resolve_work_lifecycle)):
        keys = sorted(key[1] for key in found if key[0] == table)
        for start in range(0, len(keys), 300):
            states = await resolver(db, keys[start:start + 300])
            _require(len(states) == len(keys[start:start + 300])
                and all(source_visibility(state)["reported_claim_filter_eligible"] for state in states.values()), "feature_live_source_hold")
    return [found[key] for key in sorted(found)]


async def register_feature_source_binding(db, *, base_release_id, example_input_id, source_revision_id,
        capture_id, locator, review_artifact_id, expected_review_sha256, source_bytes, review_bytes, dry_run=True):
    """Trusted internal writer; validates actual bytes, owns savepoint only."""
    import sqlalchemy as sa

    from models.db import Base
    from models.ml_feature_companion_v1 import LOCK_FUNCTION
    _require(type(dry_run) is bool)
    ids = {key: _uuid(str(value)) for key, value in {"base_release_id": base_release_id, "example_input_id": example_input_id,
        "source_revision_id": source_revision_id, "capture_id": capture_id, "review_artifact_id": review_artifact_id}.items()}
    locator = json.loads(_bounded(locator, 16384))
    _hash(expected_review_sha256)
    _require(type(source_bytes) is bytes and type(review_bytes) is bytes)
    artifacts = _artifact_bytes({hashlib.sha256(raw).hexdigest(): raw for raw in (source_bytes, review_bytes)})
    await _session(db, write=True)
    nested = await db.begin_nested()
    try:
        await db.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        release = await _release(db, ids["base_release_id"])
        revisions = await _fetch(db, "source_revisions", {ids["source_revision_id"]})
        _require(len(revisions) == 1, "feature_source_revision_missing")
        revision = revisions[0]["data"]
        values = {**ids, "base_manifest_sha256": release["manifest_sha256"], "work_id": revision["work_id"],
            "locator": locator, "locator_sha256": capsule.digest(locator), "review_artifact_kind": "review",
            "review_artifact_sha256": expected_review_sha256}
        _require(values["work_id"] is not None)
        identifier = str(uuid5(_NAMESPACE, capsule.digest(values)))
        values["id"] = identifier
        dummy = {**values, "record_sha256": binding_sha256(values), "created_at": "2000-01-01T00:00:00Z"}
        rows = await _source_rows(db, [values])
        _verified_row(dummy, release["manifest"], capsule._rows(rows), artifacts)
        table = Base.metadata.tables[TABLE_NAME]
        actual = (await db.execute(sa.select(table).where(table.c.id == UUID(identifier)))).mappings().one_or_none()
        replayed = actual is not None
        if actual is not None:
            _require(all(_plain(actual[key]) == value for key, value in values.items()), "feature_binding_replay_conflict")
            _binding(_plain(actual))
        else:
            sql_values = {key: UUID(value) if key.endswith("_id") or key == "id" else value for key, value in values.items()}
            actual = (await db.execute(table.insert().values(**sql_values).returning(table))).mappings().one()
        result = {"binding_id": str(actual["id"]), "record_sha256": actual["record_sha256"], "dry_run": dry_run,
                  "replayed": replayed, "committed": False, **AUTHORITY}
        if dry_run or replayed: await nested.rollback()
        else: await nested.commit()
        return result
    except BaseException:
        if nested.is_active: await nested.rollback()
        raise


async def capture_feature_companion(db, *, base_manifest, expected_base_manifest_sha256, artifact_bytes):
    """Capture every persisted binding for this base in one stable DB snapshot."""
    import sqlalchemy as sa

    from models.db import Base
    base_manifest = json.loads(_bounded(base_manifest))
    _base(base_manifest, expected_base_manifest_sha256)
    artifacts = _artifact_bytes(artifact_bytes)
    capsule.verify_manifest(base_manifest, artifact_bytes=_base_bytes(base_manifest, artifacts),
                            expected_manifest_sha256=expected_base_manifest_sha256)
    await _session(db)
    release = await _release(db, base_hash=expected_base_manifest_sha256)
    _require(release["manifest"] == base_manifest)
    table = Base.metadata.tables[TABLE_NAME]
    body = sa.func.to_jsonb(table.table_valued())
    sizes = (await db.execute(sa.select(sa.func.octet_length(sa.cast(body, sa.Text)))
        .where(table.c.base_release_id == release["id"]).limit(MAX_BINDINGS + 1))).scalars().all()
    _require(len(sizes) <= MAX_BINDINGS and sum(sizes) <= capsule.LIMITS["file_bytes"])
    bindings = (await db.execute(sa.select(body).where(table.c.base_release_id == release["id"])
        .order_by(table.c.id).limit(MAX_BINDINGS + 1))).scalars().all()
    _require(len(bindings) == len(sizes))
    rows = await _source_rows(db, bindings)
    expected = set(_base_bytes(base_manifest, artifacts))
    for row in rows:
        if row["table"] in {"source_captures", "evidence_artifacts"} and row["data"]["bytes_sha256"]:
            expected.add(row["data"]["bytes_sha256"])
    _require(expected == artifacts.keys(), "feature_complete_exact_artifacts_required")
    companion = {"version": VERSION, "base_release_id": str(release["id"]), "base_manifest_sha256": expected_base_manifest_sha256,
        "bindings": bindings, "source_rows": rows, "artifacts_base64": {sha: base64.b64encode(raw).decode("ascii") for sha, raw in sorted(artifacts.items())},
        "inventory_sha256": capsule.digest(bindings), "authority": dict(AUTHORITY)}
    companion["companion_sha256"] = capsule.digest(companion)
    verify_feature_companion(companion, base_manifest=base_manifest, expected_base_manifest_sha256=expected_base_manifest_sha256,
                             expected_companion_sha256=capsule.digest(companion))
    return companion
