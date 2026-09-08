"""I/O-free complementary excerpt selection, never evidence adjudication.

The caller must first admit actual immutable chunk/evidence identities, source
and material visibility, permission and currentness. Work links are supplied
only by the trusted accepted-mapping resolver. This module does not infer them.
Every selected ID denotes an unchanged complete chunk with its own citation/pin.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable

from models.evidence_packing import (
    EvidencePackingExclusion,
    EvidencePackingPlan,
    EvidencePackingSelection,
    EvidencePackingSummary,
    PackingCandidate,
)

VERSION = "evidence-packing/1.0.0"
MAX_CANDIDATES = 300
MAX_PAYLOAD_BUDGET = 16 * 1024 * 1024
MAX_MEASURED_BYTES = 64 * 1024 * 1024


class EvidencePackingError(ValueError):
    """No complete bounded and internally consistent packing plan is available."""


def _candidates(values):
    if type(values) not in {list, tuple} or len(values) > MAX_CANDIDATES:
        raise EvidencePackingError("A bounded admitted candidate sequence is required")
    result = [PackingCandidate.model_validate(value.model_dump() if isinstance(value, PackingCandidate) else value,
                                              strict=True) for value in values]
    if len({value.chunk_id for value in result}) != len(result):
        raise EvidencePackingError("Repeated chunk identities are ambiguous")
    bindings = {}
    for value in result:
        # The same paper cannot acquire two current accepted Work mappings in
        # one admitted inventory. Null is unknown, not a distinct accepted map.
        if value.paper_id in bindings and bindings[value.paper_id] != value.accepted_work_id:
            raise EvidencePackingError("Conflicting accepted Work diversity bindings")
        bindings[value.paper_id] = value.accepted_work_id
    return result


def _digest(domain, body):
    payload = json.dumps([VERSION, domain, body], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _groups(candidate):
    source_basis = "source_snapshot" if candidate.source_snapshot_sha256 is not None else "legacy_paper"
    source = _digest("source-group", [source_basis, candidate.paper_id, candidate.source_snapshot_sha256])
    if candidate.accepted_work_id is not None:
        basis, identity = "accepted_work_mapping", candidate.accepted_work_id
    else:
        basis, identity = source_basis, source
    return {"source_group_id": "src:" + source, "source_group_basis": source_basis,
            "diversity_group_id": "div:" + _digest("diversity-group", [basis, identity]), "group_basis": basis}


def packing_group_ids(candidate) -> dict[str, str]:
    """Domain-separated opaque grouping, from an admitted immutable identity."""
    return _groups(_candidates([candidate])[0])


def _describe(selected):
    sources, diversity, result = set(), set(), []
    for position, candidate in enumerate(selected, 1):
        groups = _groups(candidate)
        reason = ("source_diversity" if groups["diversity_group_id"] not in diversity else
                  "source_coverage" if groups["source_group_id"] not in sources else "complementary_role")
        result.append(EvidencePackingSelection(position=position, chunk_id=candidate.chunk_id,
            **groups, source_snapshot_sha256=candidate.source_snapshot_sha256,
            role_hint=candidate.role_hint, selection_reason=reason))
        sources.add(groups["source_group_id"])
        diversity.add(groups["diversity_group_id"])
    return result


def describe_selection(candidates, ordered_ids) -> list[EvidencePackingSelection]:
    """Use the exact same metadata for trial-cost and final-prompt construction."""
    values = _candidates(candidates)
    if (type(ordered_ids) not in {list, tuple} or len(ordered_ids) > 20
            or any(type(value) is not str for value in ordered_ids) or len(set(ordered_ids)) != len(ordered_ids)):
        raise EvidencePackingError("An ordered unique citation inventory is required")
    by_id = {value.chunk_id: value for value in values}
    if any(value not in by_id for value in ordered_ids):
        raise EvidencePackingError("Selected chunk is outside the admitted inventory")
    return _describe([by_id[value] for value in ordered_ids])


def pack_evidence(candidates, *, cost: Callable[[tuple[str, ...]], int], byte_budget: int,
                  max_chunks: int = 20, max_per_source: int = 3, max_per_work: int = 3) -> EvidencePackingPlan:
    """Rank-stable diversity first, source coverage second, complements last.

    ``cost`` is a pure trusted callback over the complete proposed ordered ID
    tuple, including final citation metadata, envelope, question and system
    bytes. It MUST measure UTF-8 serialization, not a sum of excerpt estimates
    or provider-token claim. Failure/malformed/non-monotone costs fail closed.
    Global exact-content deduplication is a conservative context-redundancy
    heuristic. It can omit another paper's distinct attribution/conditions for
    the same text; it establishes neither source equivalence nor replication.
    """
    for value, maximum in ((byte_budget, MAX_PAYLOAD_BUDGET), (max_chunks, 20), (max_per_source, 3), (max_per_work, 3)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise EvidencePackingError("Invalid bounded packing budget")
    if not callable(cost):
        raise EvidencePackingError("A complete-payload cost callback is required")
    values = _candidates(candidates)
    groups = {value.chunk_id: _groups(value) for value in values}
    selected, selected_ids, content = [], set(), set()
    source_counts, work_counts = Counter(), Counter()
    diversity_seen, source_roles = set(), {}
    measured = {}
    budget_rejected = set()

    def measure(ids):
        if ids not in measured:
            try:
                result = cost(ids)
            except Exception:
                raise EvidencePackingError("Complete-payload accounting is unavailable") from None
            if type(result) is not int or not 0 <= result <= MAX_MEASURED_BYTES:
                raise EvidencePackingError("Invalid complete-payload UTF-8 byte count")
            measured[ids] = result
        return measured[ids]

    payload_bytes = measure(())
    baseline = payload_bytes

    def reason(candidate, *, complement=False):
        group = groups[candidate.chunk_id]
        source_id, diversity_id = group["source_group_id"], group["diversity_group_id"]
        if candidate.content_sha256 in content:
            return "duplicate_content"
        if source_counts[source_id] >= (1 if candidate.source_snapshot_sha256 is None else max_per_source):
            return "source_limit"
        if candidate.accepted_work_id is not None and work_counts[diversity_id] >= max_per_work:
            return "work_limit"
        if complement and source_counts[source_id]:
            if candidate.chunk_kind != "original_passage" or candidate.role_hint == "other":
                return "not_complementary_original"
            if candidate.role_hint in source_roles.get(source_id, set()):
                return "role_already_represented"
        if len(selected) >= max_chunks:
            return "chunk_limit"
        return None

    def admit(candidate, *, complement=False):
        nonlocal payload_bytes
        if candidate.chunk_id in selected_ids or reason(candidate, complement=complement) is not None:
            return False
        proposal = tuple([item.chunk_id for item in selected] + [candidate.chunk_id])
        size = measure(proposal)
        if size <= payload_bytes:
            raise EvidencePackingError("Adding a complete source did not increase its serialized byte count")
        if size > byte_budget:
            budget_rejected.add(candidate.chunk_id)
            return False
        selected.append(candidate)
        selected_ids.add(candidate.chunk_id)
        content.add(candidate.content_sha256)
        group = groups[candidate.chunk_id]
        source_counts[group["source_group_id"]] += 1
        work_counts[group["diversity_group_id"]] += 1
        diversity_seen.add(group["diversity_group_id"])
        source_roles.setdefault(group["source_group_id"], set()).add(candidate.role_hint)
        payload_bytes = size
        return True

    if baseline <= byte_budget:
        for candidate in values:
            if groups[candidate.chunk_id]["diversity_group_id"] not in diversity_seen:
                admit(candidate)
        for candidate in values:
            if not source_counts[groups[candidate.chunk_id]["source_group_id"]]:
                admit(candidate)
        for candidate in values:
            admit(candidate, complement=True)
    exclusions = []
    for candidate in values:
        if candidate.chunk_id in selected_ids:
            continue
        disposition = "base_payload_budget" if baseline > byte_budget else reason(candidate, complement=True)
        if disposition is None:
            disposition = "payload_budget" if candidate.chunk_id in budget_rejected else "chunk_limit"
        exclusions.append(EvidencePackingExclusion(chunk_id=candidate.chunk_id, reason_code=disposition))
    return EvidencePackingPlan(status="base_budget_exceeded" if baseline > byte_budget else "packed" if selected else "empty",
        selected=_describe(selected), excluded=exclusions, candidate_count=len(values), selected_count=len(selected),
        source_group_count=len(source_counts), diversity_group_count=len(diversity_seen), payload_bytes=payload_bytes,
        byte_budget=byte_budget, max_chunks=max_chunks, max_per_source=max_per_source, max_per_work=max_per_work)


def public_summary(plan) -> EvidencePackingSummary:
    """Remove all candidate identifiers; never republish a withheld old plan."""
    value = EvidencePackingPlan.model_validate(plan.model_dump() if isinstance(plan, EvidencePackingPlan) else plan, strict=True)
    counts = dict(sorted(Counter(item.reason_code for item in value.excluded).items()))
    reasons = []
    if value.candidate_count == 0:
        reasons.append("no_admitted_candidates")
    if "base_payload_budget" in counts or value.status == "base_budget_exceeded":
        reasons.append("base_payload_budget_exceeded")
    if "payload_budget" in counts:
        reasons.append("payload_budget_excluded")
    if any(reason in counts for reason in ("chunk_limit", "source_limit", "work_limit")):
        reasons.append("selection_limits_applied")
    if "duplicate_content" in counts:
        reasons.append("duplicate_content_removed")
    if any(reason in counts for reason in ("role_already_represented", "not_complementary_original")):
        reasons.append("complementarity_not_established")
    return EvidencePackingSummary(**{name: getattr(value, name) for name in (
        "status", "candidate_count", "selected_count", "source_group_count", "diversity_group_count", "payload_bytes",
        "byte_budget", "max_chunks", "max_per_source", "max_per_work")}, reason_counts=counts, reason_codes=reasons)
