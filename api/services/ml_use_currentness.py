"""Current full-audit comparison for exact private ML input reconstruction.

Only the caller's authenticated administrative audit boundary admits inspection.
The companion's claimed capture identity is rechecked as evidence, never used
as the caller's authenticated identity or as a write/approval authority.
"""
from __future__ import annotations

import asyncio
import hashlib
from importlib.resources import files

from services.ml_audited_dataset import canonical, digest
from services.ml_feature_companion import decode_companion_artifacts
from services.ml_label_capture import (
    EXPORT_SCOPE,
    MlLabelCaptureError,
    MlLabelCaptureUnavailable,
    recheck_ml_label_companion,
)
from services.ml_review_projection import parse_subject
from services.ml_review_source_observation import parse, raw_sha
from services.ml_use_preflight import MlUsePreflightConflict, match, preflight_ml_use
from services.ml_use_reconstruction import decode_envelope

VERSION = "ml-use-current-reconstruction/1.0.0"
INVENTORY_VERSION = "ml-use-captured-dependency-inventory/1.0.0"
MAX_ROWS = 4000
MAX_REPRESENTATIONS = 16000
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SECONDS = 30


def _require(condition):
    if not condition:
        raise ValueError("ml_use_currentness_invalid")


def dependency_inventory(inputs, artifacts, registered):
    """Project verified/recaptured inputs only; no standalone permission proof.

    Different wire encodings and temporal scopes remain distinct. In particular,
    subject membership pins cover a container hash plus identity, not a fabricated
    standalone row-content checksum. All source text stays out of the report.
    """
    rows, bytes_inventory, representations = {}, {}, 0

    def add(table, row_id, pin, encoding, scope, origin, *, container=None):
        nonlocal representations
        key = table, row_id
        versions = rows.setdefault(key, {})
        signature = encoding, scope, pin, container
        if signature not in versions:
            representations += 1
            _require(len(rows) <= MAX_ROWS and representations <= MAX_REPRESENTATIONS)
            versions[signature] = set()
        versions[signature].add(origin)
        _require(len(versions[signature]) <= 32)

    def byte_ref(pin, origin, *, size=None):
        item = bytes_inventory.setdefault(pin, {"sha256": pin, "uploaded_size_bytes": None, "origins": set()})
        if size is not None:
            _require(item["uploaded_size_bytes"] in {None, size})
            item["uploaded_size_bytes"] = size
        item["origins"].add(origin)
        _require(len(bytes_inventory) <= MAX_ROWS and len(item["origins"]) <= MAX_REPRESENTATIONS)

    def subject(text, pin, origin, scope):
        body = parse_subject(text, expected_sha256=pin)
        members = [{"table": row["table"], "row_id": row["row_id"]} for row in body["rows"]]
        # Native import metadata lives beside, not inside, the subject's row
        # snapshots. Preserve those references without claiming full SQL rows.
        if native := body["native_import"]:
            members.extend([{"table": "scientific_import_outcomes", "row_id": native["outcome_id"]},
                            {"table": "scientific_import_packages", "row_id": native["package_id"]}])
            members.extend({"table": "scientific_import_files", "row_id": item["file_id"]}
                           for item in native["source_files"])
        for row in members:
            member = {"subject_sha256": pin, "table": row["table"], "row_id": row["row_id"]}
            add(row["table"], row["row_id"], digest(member), "scientific-subject-membership/1.0.0",
                scope, origin, container=pin)
        for row in body["artifacts"]:
            if row["bytes_sha256"] is not None:
                byte_ref(row["bytes_sha256"], origin)

    def sql_rows(wires, origin):
        for row in wires:
            _require(raw_sha(row["row_text"]) == row["row_sha256"])
            add(row["table"], row["row_id"], row["row_sha256"],
                "scientific-adjudication-canonical/1.0.0", "current_observation", origin)
            if row["table"] == "scientific_result_subjects":
                data = parse(row["row_text"])
                subject(data["basis_json"], data["subject_sha256"],
                        "audit_subject:" + row["row_id"], "historical_subject")

    def lifecycle(values, origin):
        for item in values:
            _require(raw_sha(item["snapshot_text"]) == item["snapshot_sha256"])
            add("papers" if item["kind"] == "paper" else "works", item["row_id"], item["snapshot_sha256"],
                "source-lifecycle-jsonb-text/1.0.0", "current_observation", origin)

    for row in registered["requirements"]:
        add(row["table"], row["row_id"], row["row_sha256"], "research-release-canonical/1.0.0",
            "current_observation", "registered_dependency_closure")
    for origin, wires in (("frozen_manifest", inputs["manifest"]["rows"]),
                          ("feature_source_companion", inputs["companion"]["source_rows"])):
        for row in wires:
            add(row["table"], row["row_id"], row["row_sha256"], "research-release-canonical/1.0.0",
                "historical_input", origin)
    for binding in inputs["companion"]["bindings"]:
        add("ml_feature_source_bindings", binding["id"], binding["record_sha256"], "ml-feature-binding-record/1.0.0",
            "current_observation", "registered_feature_binding")
    review = inputs["review_companion"]["observation"]
    label = inputs["label_companion"]["observation"]
    sql_rows(review["audit_rows"], "review_audit")
    sql_rows(review["source_observation"]["rows"], "review_sources")
    sql_rows(label["rows"], "label_sources")
    lifecycle(review["source_observation"]["lifecycle"], "review_lifecycle")
    lifecycle(label["lifecycle"], "label_lifecycle")
    for prop in review["properties"]:
        if prop["current_subject_text"] is not None:
            subject(prop["current_subject_text"], prop["current_subject_sha256"],
                    "current_subject:" + prop["property_id"], "current_observation")
    for origin, payloads in (("capsule_artifacts", artifacts),
                             ("feature_companion_artifacts", decode_companion_artifacts(inputs["companion"]))):
        for pin, payload in payloads.items():
            _require(hashlib.sha256(payload).hexdigest() == pin)
            byte_ref(pin, origin, size=len(payload))
    result = {"version": INVENTORY_VERSION, "rows": [{"table": key[0], "row_id": key[1],
        "representations": [{"encoding": encoding, "scope": scope, "sha256": pin,
                              "container_sha256": container, "origins": sorted(origins)}
             for (encoding, scope, pin, container), origins in sorted(versions.items())]}
        for key, versions in sorted(rows.items())],
        "artifact_digests": [{**item, "origins": sorted(item["origins"])} for _, item in sorted(bytes_inventory.items())],
        "input_pins": registered["input_pins"], "row_count": len(rows), "representation_count": representations,
        "artifact_digest_count": len(bytes_inventory), "independent_support_count": None,
        "scope": "registered_closure_and_exact_recaptured_companion_audit_inventory",
        "external_dependency_completeness_proven": False, "source_permission_granted": False}
    _require(len(canonical(result)) <= MAX_RESPONSE_BYTES)
    return result


async def inspect_current_inputs(db, *, actor_user_id, raw, reconstruction):
    """Caller owns one fresh UTC read-only RR/SERIALIZABLE bounded snapshot.

    `reconstruction` is supplied by the server-owned worker, never an HTTP field.
    The independently authenticated requester may differ from a prior capturer.
    Current audit-eligibility of that declared capturer is checked by the existing
    capture service; it does not prove a historical session or signed capture act.
    """
    _require(type(raw) is bytes)
    # Detach the worker observation before the first await.
    from services.ml_audited_dataset import loads
    reconstruction = loads(canonical(reconstruction))
    envelope, inputs, artifacts = decode_envelope(raw)
    _require(reconstruction["request_sha256"] == envelope["expected_request_sha256"]
             and reconstruction["envelope_sha256"] == hashlib.sha256(raw).hexdigest()
             and reconstruction["input_pins"] == envelope["request"]["input_pins"]
             and reconstruction["all_eight_input_bytes_verified"] is True
             and reconstruction["dataset_and_preparation_rebuilt"] is True)
    source_pin = hashlib.sha256(files("services").joinpath("ml_use_currentness.py").read_bytes()).hexdigest()
    async with asyncio.timeout(MAX_SECONDS):
        args = {key: envelope[key] for key in ("request", "expected_request_sha256",
                "expected_requester_grant_id", "expected_curator_grant_id")}
        registered = await preflight_ml_use(db, actor_user_id=actor_user_id, **args)
        pins = envelope["request"]["input_pins"]
        identity = inputs["review_companion"]["observation"]["capture_admission"]
        try:
            compared = await recheck_ml_label_companion(db,
                actor_user_id=identity["actor_user_id"], expected_actor_grant_id=identity["actor_grant_id"],
                export_scope=EXPORT_SCOPE, base_manifest=inputs["manifest"],
                expected_base_manifest_sha256=pins["manifest_sha256"], source_companion=inputs["companion"],
                expected_source_companion_sha256=pins["companion_sha256"], review_companion=inputs["review_companion"],
                expected_review_companion_sha256=pins["review_companion_sha256"], artifact_bytes=artifacts,
                label_companion=inputs["label_companion"], expected_label_companion_sha256=pins["label_companion_sha256"])
        except MlLabelCaptureUnavailable:
            raise TimeoutError("ml_use_currentness_unavailable") from None
        except MlLabelCaptureError:
            raise MlUsePreflightConflict("ml_use_companion_observation_changed") from None
        match(compared["observation_sha256"] == inputs["label_companion"]["observation_sha256"])
        inventory = dependency_inventory(inputs, artifacts, registered)
        result = {**registered, "version": VERSION, "online_private_input_reconstruction_verified": True,
            "companion_observations_rechecked_online": True, "reconstruction": reconstruction,
            "review_observation_sha256": inputs["review_companion"]["observation_sha256"],
            "label_observation_sha256": inputs["label_companion"]["observation_sha256"],
            "historical_capture_session_authenticated": False,
            "companion_capture_identity_claim": identity,
            "dependency_inventory": inventory, "dependency_inventory_sha256": digest(inventory),
            "currentness_implementation_sha256": source_pin}
        result["blockers"] = sorted(set(result["blockers"]) - {"private_input_bytes_not_rebuilt_online"})
        _require(hashlib.sha256(files("services").joinpath("ml_use_currentness.py").read_bytes()).hexdigest() == source_pin)
        _require(len(canonical(result)) <= MAX_RESPONSE_BYTES)
        return result
