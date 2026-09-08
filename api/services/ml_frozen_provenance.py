"""Exact frozen source/dependency context, not scientific or ML authorization.

The caller first validates and independently pins a complete 0054 capsule.
This pure resolver rechecks captured row hashes and bytes, and reproduces the
existing 0052 source-occurrence review contract. It cannot authenticate a human
review, discover omitted external rows, or establish current live source rights.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType

from services.research_release_manifest import LIMITS, _dag, _rows, canonical, digest
from services.research_release_spec import SPEC
from services.temporal_provenance import (
    MAX_WITNESSES,
    SourceAvailabilityWitness,
    public_locator,
    result_temporal_provenance,
    utc_datetime,
)

VERSION = "ml-frozen-provenance/1.0.0"
SOURCE_REVIEW_VERSION = "source-occurrence-review/1.0.0"
RESULT_TABLES = frozenset({"material_claims", "event_properties"})
MAX_RESOLVED_EDGES = 10_000
MAX_CONTEXT_MEMBERSHIPS = 100_000
_HELD = frozenset({"retracted", "withdrawn", "corrected", "disputed", "excluded"})
ResultReference = tuple[str, str]


class FrozenProvenanceError(ValueError):
    """An exact bounded frozen-row or dependency binding is unavailable."""


def _require(condition, message):
    if not condition:
        raise FrozenProvenanceError(message)


def _sql_values(table, row):
    """Restore DB scalar semantics before the existing 0052 registry hash.

    0054 hashes original captured JSON; 0052 hashes native DB rows with UTC
    timestamps and float scalars. These are deliberately different digests.
    """
    result = dict(row)
    for key, declaration in SPEC[table]["fields"].items():
        value = result[key]
        if value is not None and declaration["type"] == "DATETIME":
            parsed = utc_datetime(value)
            _require(parsed is not None, "invalid frozen timestamp")
            result[key] = parsed.isoformat().replace("+00:00", "Z")
        elif value is not None and declaration["type"] in {"FLOAT", "DOUBLE PRECISION"}:
            result[key] = float(value)
    return result


def _registry_intact(table, row):
    value = _sql_values(table, row)
    return row["record_sha256"] == digest({key: item for key, item in value.items()
                                           if key not in {"created_at", "record_sha256"}})


def _review_payload(revision, capture, occurrence, claim):
    # Same closed source-occurrence-review/1.0.0 fields as source_registry;
    # importing that database writer here would violate the pure boundary.
    revision = _sql_values("source_revisions", revision)
    capture = _sql_values("source_captures", capture)
    claim = _sql_values("material_claims", claim)
    return {"version": SOURCE_REVIEW_VERSION, "claim_id": occurrence["claim_id"],
        "paper_id": revision["paper_id"], "work_id": occurrence["work_id"],
        "source_revision_id": revision["id"], "capture_id": capture["id"],
        "provider_revision": revision["provider_revision"],
        "source_version_public_at": revision["source_version_public_at"],
        "captured_at": capture["captured_at"], "bytes_sha256": capture["bytes_sha256"],
        "representation": capture["representation"], "locator_sha256": occurrence["locator_sha256"],
        "claim_record_sha256": digest({key: value for key, value in claim.items()
                                        if key not in {"created_at", "updated_at"}})}


@dataclass(frozen=True, slots=True)
class FrozenResultNode:
    ref: ResultReference
    row_sha256: str
    event_id: str | None
    event_revision: int | None
    material_id: str | None
    state_id: str | None
    sample_id: str | None
    structure_id: str | None
    knowledge_origin: str | None
    event_review_status: str | None
    event_validity_status: str | None
    dependency_complete: bool
    reason_codes: tuple[str, ...]
    group_keys: tuple[tuple[str, str], ...]
    witnesses: tuple[SourceAvailabilityWitness, ...]
    _json: str = field(repr=False)
    scientific_acceptance: bool = field(default=False, init=False)
    reviewer_authority_authenticated: bool = field(default=False, init=False)
    ml_training_approved: bool = field(default=False, init=False)

    @property
    def result_data(self): return json.loads(self._json)["result"]
    @property
    def event_data(self): return json.loads(self._json)["event"]
    @property
    def state_data(self): return json.loads(self._json)["state"]
    @property
    def sample_data(self): return json.loads(self._json)["sample"]
    @property
    def temporal(self): return json.loads(self._json)["temporal"]
    @property
    def source_audit(self): return json.loads(self._json)["source_audit"]


@dataclass(frozen=True, slots=True)
class FrozenResultDependency:
    event_evidence_id: str
    event_evidence_sha256: str
    output_ref: ResultReference
    input_ref: ResultReference | None
    input_event_id: str
    link_type: str
    same_material: bool
    same_state: bool


@dataclass(frozen=True, slots=True)
class FrozenResultContext:
    result_ref: ResultReference
    nodes: tuple[FrozenResultNode, ...]
    edges: tuple[FrozenResultDependency, ...]
    group_keys: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]
    version: str = field(default=VERSION, init=False)
    scientific_acceptance: bool = field(default=False, init=False)
    reviewer_authority_authenticated: bool = field(default=False, init=False)
    ml_training_approved: bool = field(default=False, init=False)

    @property
    def root(self):
        return next(node for node in self.nodes if node.ref == self.result_ref)


class _Resolver:
    def __init__(self, rows_index, artifact_bytes):
        _require(type(rows_index) is dict and 0 < len(rows_index) <= LIMITS["rows"], "frozen row index limit")
        _require(all(type(key) is tuple and len(key) == 2 and type(value) is dict
                     and key == (value.get("table"), value.get("row_id"))
                     for key, value in rows_index.items()), "frozen row index binding")
        raw = canonical(sorted(rows_index.values(), key=lambda item: (item["table"], item["row_id"])))
        _require(len(raw) <= LIMITS["file_bytes"], "frozen row byte limit")
        self.rows = _rows(json.loads(raw))
        _require(type(artifact_bytes) is dict and len(artifact_bytes) <= LIMITS["artifacts"], "artifact inventory limit")
        _require(all(type(key) is str and type(value) is bytes and len(value) <= LIMITS["file_bytes"]
                     for key, value in artifact_bytes.items())
                 and sum(map(len, artifact_bytes.values())) <= LIMITS["combined_bytes"], "artifact byte limit")
        self.artifacts = dict(artifact_bytes)
        self.bytes_checked = {}
        self.nodes, self.edges = {}, []
        self.retained_bytes = 0
        self.by_claim, self.by_event, self.capture_hashes = {}, {}, {}
        for (table, _), envelope in self.rows.items():
            data = envelope["data"]
            if table == "claim_source_occurrences":
                self.by_claim.setdefault(data["claim_id"], []).append(data)
            elif table == "event_evidence":
                self.by_event.setdefault(data["event_id"], []).append(envelope)
            elif table == "source_captures":
                self.capture_hashes.setdefault((data["source_revision_id"], data["representation"]), set()).add(data["bytes_sha256"])

    def row(self, table, identifier):
        value = self.rows.get((table, identifier)) if identifier is not None else None
        _require(value is not None, "missing exact frozen dependency")
        return value["data"]

    def bytes_match(self, sha):
        if sha not in self.bytes_checked:
            self.bytes_checked[sha] = sha in self.artifacts and hashlib.sha256(self.artifacts[sha]).hexdigest() == sha
        return self.bytes_checked[sha]

    def ancestry(self, table, identifier, parent, group_kind):
        seen = set()
        while identifier is not None:
            _require(identifier not in seen, "frozen ancestry cycle")
            seen.add(identifier)
            identifier = self.row(table, identifier)[parent]
        return {(group_kind, item) for item in seen}

    def event_group_keys(self, event):
        """Relational endpoints prevent split leakage, never prove causality.

        An event-only link can connect two surviving results through an excluded
        bridge. Preserve its actual event/state/sample/material keys even when
        no exact input result exists and scientific admission remains blocked.
        """
        material = event["material_id"]
        state = self.row("material_states", event["state_id"])
        _require(state["material_id"] == material, "dependency state material mismatch")
        keys = {("event", event["id"]), ("state", state["id"]), ("material", material)}
        keys.update(self.ancestry("materials", material, "parent_material_id", "material_ancestor"))
        if state["sample_id"]:
            sample = self.row("research_samples", state["sample_id"])
            _require(sample["material_id"] == material, "dependency sample material mismatch")
            keys.add(("sample", sample["id"]))
            if sample["work_id"]: keys.add(("work", sample["work_id"]))
        if event["structure_id"]:
            structure = self.row("structure_records", event["structure_id"])
            _require(structure["material_id"] == material, "dependency structure material mismatch")
            keys.update(self.ancestry("structure_records", event["structure_id"], "parent_structure_id", "structure_ancestor"))
        return keys

    def claim_sources(self, claim, groups):
        witnesses, audit, reasons = [], [], set()
        for occurrence in self.by_claim.get(claim["id"], []):
            revision = self.row("source_revisions", occurrence["source_revision_id"])
            capture = self.row("source_captures", occurrence["capture_id"])
            mapping = self.rows.get(("paper_work_map", revision["paper_id"]))
            mapping = mapping["data"] if mapping else None
            review = self.rows.get(("evidence_artifacts", occurrence["review_artifact_id"]))
            review = review["data"] if review else None
            failures = set()
            for table, value in (("source_revisions", revision), ("source_captures", capture),
                                 ("claim_source_occurrences", occurrence)):
                if not _registry_intact(table, value): failures.add("source_registry_record_hash_mismatch")
            if not (capture["source_revision_id"] == revision["id"]
                    and claim["work_id"] == occurrence["work_id"] == revision["work_id"]
                    and claim["work_id"] is not None):
                failures.add("source_result_work_binding_mismatch")
            if not (mapping and mapping["review_status"] == "accepted" and mapping["work_id"] == revision["work_id"]):
                failures.add("source_work_mapping_unresolved")
            locator = public_locator(occurrence["locator"])
            if not locator or locator != occurrence["locator"] or digest(locator) != occurrence["locator_sha256"]:
                failures.add("source_locator_binding_mismatch")
            if len(self.capture_hashes.get((revision["id"], capture["representation"]), set())) != 1:
                failures.add("source_version_capture_conflict")
            if not self.bytes_match(capture["bytes_sha256"]): failures.add("source_capture_bytes_unverified")
            expected = _review_payload(revision, capture, occurrence, claim)
            document = review.get("metadata", {}).get("source_provenance_review") if review and type(review["metadata"]) is dict else None
            flags = {"binding_verified", "version_resolved", "public_time_verified"}
            if not (review and occurrence["binding_status"] == "reviewed"
                    and occurrence["review_artifact_kind"] == "review" and review["kind"] == "review"
                    and review["schema_version"] == SOURCE_REVIEW_VERSION and review["hash_status"] == "verified"
                    and review["record_sha256"] == occurrence["review_artifact_sha256"]
                    and type(document) is dict and set(document) == {*expected, *flags}
                    and all(type(document.get(key)) is bool for key in flags)
                    and all(document.get(key) == value for key, value in expected.items())
                    and document["binding_verified"] is True
                    and digest(document) == review["record_sha256"]):
                failures.add("source_occurrence_review_binding_unresolved")
            if not (review and self.bytes_match(review["bytes_sha256"])
                    and type(document) is dict and self.artifacts[review["bytes_sha256"]] == canonical(document)):
                failures.add("source_review_bytes_do_not_bind_payload")
            paper = self.row("papers", revision["paper_id"])
            work = self.row("works", occurrence["work_id"])
            if paper["status"] in _HELD or work["publication_status"] in _HELD:
                failures.add("frozen_source_lifecycle_hold")
            valid = not failures
            witnesses.append(SourceAvailabilityWitness(
                claim_id=claim["id"], paper_id=revision["paper_id"], work_id=occurrence["work_id"],
                source_revision_id=revision["id"], source_version=revision["provider_revision"] or revision["revision_key"],
                capture_id=capture["id"], source_version_public_at=utc_datetime(revision["source_version_public_at"]),
                captured_at=utc_datetime(capture["captured_at"]), bytes_sha256=capture["bytes_sha256"],
                representation=capture["representation"], locator=MappingProxyType(locator),
                review_reference=f"{occurrence['review_artifact_id']}:{occurrence['review_artifact_sha256']}" if review else "pending",
                version_resolved=bool(valid and revision["version_status"] == "pinned" and document["version_resolved"]),
                binding_verified=valid,
                public_time_verified=bool(valid and revision["availability_status"] == "known_by" and document["public_time_verified"]),
            ))
            groups.update({("paper", revision["paper_id"]), ("work", occurrence["work_id"]),
                ("source_revision", revision["id"]), ("capture", capture["id"]), ("occurrence", occurrence["id"])})
            audit.append({"occurrence_id": occurrence["id"], "source_revision_id": revision["id"],
                "capture_id": capture["id"], "review_artifact_id": occurrence["review_artifact_id"],
                "captured_bytes_verified": self.bytes_match(capture["bytes_sha256"]),
                "review_binding_verified": valid, "reason_codes": sorted(failures)})
            reasons.update(failures)
        if len(witnesses) > MAX_WITNESSES:
            reasons.add("source_witness_inventory_limit")
        return tuple(witnesses[:MAX_WITNESSES + 1]), audit, reasons

    def node(self, ref):
        table, identifier = ref
        result = self.row(table, identifier)
        event = self.row("research_events", result["event_id"]) if result["event_id"] else None
        state = self.row("material_states", event["state_id"]) if event else None
        sample = self.row("research_samples", state["sample_id"]) if state and state["sample_id"] else None
        material = result.get("material_id") or (event["material_id"] if event else None)
        reasons = {"scientific_review_authority_not_authenticated", "live_source_currentness_not_checked"}
        groups = set()
        if material:
            groups.update(self.ancestry("materials", material, "parent_material_id", "material_ancestor"))
            groups.add(("material", material))
        if event:
            _require(event["material_id"] == material and state["material_id"] == material,
                     "result event state material mismatch")
            groups.add(("state", state["id"]))
            groups.update(self.event_group_keys(event))
            if sample:
                _require(sample["material_id"] == material, "sample material mismatch")
                groups.add(("sample", sample["id"]))
                if sample["work_id"]: groups.add(("work", sample["work_id"]))
            if event["structure_id"]:
                groups.update(self.ancestry("structure_records", event["structure_id"], "parent_structure_id", "structure_ancestor"))
            decision = self.rows.get(("evidence_artifacts", event["decision_artifact_id"]))
            if event["review_status"] != "approved": reasons.add("event_review_not_approved")
            if not (decision and decision["data"]["kind"] == "review"
                    and decision["data"]["hash_status"] == "verified" and self.bytes_match(decision["data"]["bytes_sha256"])):
                reasons.add("event_decision_artifact_unverified")
            reasons.add("event_scientific_decision_contract_unavailable")
            if event["validity_status"] != "accepted": reasons.add("event_validity_not_accepted")
        else:
            reasons.add("result_event_unresolved")
        witnesses, audit = (), []
        if table == "material_claims":
            for key in ("paper_id", "work_id"):
                if result[key]: groups.add(("paper" if key == "paper_id" else "work", result[key]))
            witnesses, audit, failures = self.claim_sources(result, groups)
            reasons.update(failures)
            if result["validity_status"] != "accepted": reasons.add("claim_validity_not_accepted")
        else:
            reasons.add("property_source_occurrence_contract_unavailable")
        temporal = result_temporal_provenance(claim_id=identifier,
            record=result if table == "material_claims" else None, witnesses=witnesses)
        if temporal["status"] != "known_by": reasons.add("result_availability_unresolved")
        if not any(kind == "work" for kind, _ in groups): reasons.add("work_identity_unresolved")
        if sample is None: reasons.add("sample_identity_unresolved")
        for envelope in self.by_event.get(result["event_id"], []):
            edge = envelope["data"]
            if edge["link_type"] == "source":
                artifact = self.row("evidence_artifacts", edge["artifact_id"])
                if artifact["hash_status"] != "verified" or not self.bytes_match(artifact["bytes_sha256"]):
                    reasons.add("event_source_artifact_unverified")
                continue
            input_ref = (("material_claims", edge["input_claim_id"]) if edge["input_claim_id"]
                         else ("event_properties", edge["input_property_id"]) if edge["input_property_id"] else None)
            source_event = self.row("research_events", edge["input_event_id"])
            groups.update(self.event_group_keys(source_event))
            same_material = event is not None and source_event["material_id"] == material
            same_state = event is not None and source_event["state_id"] == state["id"]
            if input_ref:
                _require(self.row(*input_ref)["event_id"] == source_event["id"], "exact dependency event mismatch")
            else:
                reasons.add("event_only_dependency_unresolved")
            if not same_material: reasons.add("cross_material_dependency_unresolved")
            if not same_state: reasons.add("cross_state_dependency_unresolved")
            _require(len(self.edges) < MAX_RESOLVED_EDGES, "resolved dependency edge limit")
            self.edges.append(FrozenResultDependency(edge["id"], envelope["row_sha256"], ref,
                input_ref, source_event["id"], edge["link_type"], same_material, same_state))
        payload = canonical({"result": result, "event": event, "state": state, "sample": sample,
                             "temporal": temporal, "source_audit": audit}).decode()
        self.retained_bytes += len(payload.encode("utf-8"))
        _require(self.retained_bytes <= LIMITS["combined_bytes"], "resolved context byte limit")
        return FrozenResultNode(ref, self.rows[ref]["row_sha256"], event["id"] if event else None,
            event["revision"] if event else None, material, state["id"] if state else None,
            sample["id"] if sample else None, event["structure_id"] if event else None,
            event["knowledge_origin"] if event else None, event["review_status"] if event else None,
            event["validity_status"] if event else None,
            not bool(reasons & {"event_only_dependency_unresolved", "cross_material_dependency_unresolved",
                                "cross_state_dependency_unresolved", "event_source_artifact_unverified"}),
            tuple(sorted(reasons)), tuple(sorted(groups)), witnesses, payload)


def resolve_result_context(rows_index, result_ref, artifact_bytes) -> FrozenResultContext:
    """Resolve exact result inputs from an independently verified frozen capsule.

    All event-level evidence edges are conservatively applied to each result in
    that event. Exact result references are traversed, not event timestamps or
    unrelated sibling values. Event-only links and cross-state inputs stay
    unresolved. Group keys prohibit leakage; they do not establish independence.
    """
    _require(type(result_ref) is tuple and len(result_ref) == 2
             and result_ref[0] in RESULT_TABLES and type(result_ref[1]) is str, "exact result reference required")
    contexts = resolve_result_contexts(rows_index, artifact_bytes)
    _require(result_ref in contexts, "missing exact frozen result")
    return contexts[result_ref]


def resolve_result_contexts(rows_index, artifact_bytes) -> dict[ResultReference, FrozenResultContext]:
    """Validate/hash once, resolve every result including nonselected bridges.

    Immutable node objects are shared among returned contexts. Every edge keeps
    its declared type; only derives_from imposes a directed causal DAG. Context
    reachability is bounded by the existing 1000-row capsule, with a 64 MiB
    retained JSON budget. This does not authenticate completeness outside it.
    """
    resolver = _Resolver(rows_index, artifact_bytes)
    for ref in sorted(key for key in resolver.rows if key[0] in RESULT_TABLES):
        resolver.nodes[ref] = resolver.node(ref)
    # Context/support links may cycle, but scientific derivation may not.
    graph = {}
    for edge in resolver.edges:
        if edge.link_type == "derives_from" and edge.input_ref is not None:
            graph.setdefault(edge.output_ref, set()).add(edge.input_ref)
    _dag(graph, "frozen result derivation")
    by_output = {}
    for edge in resolver.edges:
        by_output.setdefault(edge.output_ref, []).append(edge)
    result, memberships = {}, 0
    for root in sorted(resolver.nodes):
        selected, pending, edges = set(), [root], []
        while pending:
            ref = pending.pop()
            if ref in selected: continue
            _require(ref in resolver.nodes, "unresolved exact result dependency")
            selected.add(ref)
            dependencies = by_output.get(ref, [])
            edges.extend(dependencies)
            pending.extend(edge.input_ref for edge in dependencies if edge.input_ref is not None)
        nodes = tuple(resolver.nodes[key] for key in sorted(selected))
        groups = tuple(sorted({key for node in nodes for key in node.group_keys}))
        memberships += len(nodes) + len(edges) + len(groups)
        _require(memberships <= MAX_CONTEXT_MEMBERSHIPS, "expanded dependency context limit")
        result[root] = FrozenResultContext(root, nodes,
            tuple(sorted(edges, key=lambda edge: (edge.output_ref, edge.event_evidence_id))),
            groups,
            tuple(sorted({reason for node in nodes for reason in node.reason_codes})))
    return result
