"""Result/original coordination with an exact reviewed-link consumer.

Catalogue proximity never creates a link. Positive pair metadata is consumed
only from the current append-only reviewer ledger in the same repeatable-read
snapshot that rechecks every selected source.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from models.scientific_mixed import MixedEvidenceAssociation, ScientificMixedEvidence
from services import index_retrieval, retrieval_currentness
from services import scientific_result_passage
from services.scientific_query_lookup import ScientificLookupInputs, result_query


def is_mixed_request(interpretation):
    # Preserve the grammar's comparison intent and exact multi-target selector.
    # Numeric comparisons also receive separately labeled original candidates;
    # this does not claim a user asked "why" or that experiments are comparable.
    return interpretation.intent == "mixed" or interpretation.intent == "comparison" and result_query(interpretation)


def _original_hash(source_json, pin):
    return hashlib.sha256(json.dumps(["mixed-original-input/1", source_json, asdict(pin)],
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenMixedOriginal:
    """Private point-in-time source DTO/pin seal, not source authentication.

    Constructed together from admitted retrieval inputs before any later await.
    Public projections are new copies, not mutable aliases reused after a fresh
    pin check. This hash protects local consistency, not a public trust boundary.
    """
    selection_pin: retrieval_currentness.SelectionPin
    _source_json: str = field(repr=False)
    _input_sha256: str = field(repr=False)

    def __post_init__(self):
        source = self.source
        if (source.packing_info is None or source.packing_info.chunk_id != self.selection_pin.chunk_id
                or source.paper_id != self.selection_pin.paper_id or source.evidence_provenance.get("chunk_kind") != "original_passage"
                or source.evidence_provenance.get("permission_status") == "restricted"
                or source.evidence_provenance.get("currentness") == "stale"):
            raise ValueError("Mixed original presentation must match its selected original identity")

    @property
    def source(self):
        from models.search import AskSource

        if (type(self.selection_pin) is not retrieval_currentness.SelectionPin or not self.selection_pin.has_evidence_pin
                or self.selection_pin.grouping_sha256 is None or type(self._source_json) is not str
                or len(self._source_json.encode("utf-8")) > 2 * 1024 * 1024
                or _original_hash(self._source_json, self.selection_pin) != self._input_sha256):
            raise ValueError("Mixed original presentation seal changed")
        return AskSource.model_validate_json(self._source_json)


def freeze_original(source, selection_pin):
    source_json = source.model_dump_json()
    return FrozenMixedOriginal(selection_pin, source_json, _original_hash(source_json, selection_pin))


def combined_pins(inputs, original_pins, *, max_selected_inputs):
    if type(inputs) is not ScientificLookupInputs or type(max_selected_inputs) is not int or not 1 <= max_selected_inputs <= 20:
        raise ValueError("Validated mixed lookup inputs and a bounded shared limit are required")
    result = tuple(inputs.selection_pins) + tuple(original_pins)
    expected_generation = index_retrieval.pin_sha256(inputs.generation_pin)
    if (len(result) > max_selected_inputs or len({pin.chunk_id for pin in result}) != len(result)
            or any(type(pin) is not retrieval_currentness.SelectionPin or not pin.has_evidence_pin
                   or pin.grouping_sha256 is None or pin.generation_pin_sha256 != expected_generation for pin in result)):
        raise ValueError("Mixed inputs must be unique, typed and pinned to the same generation and grouping")
    return result


async def resolve_mixed_associations(db, inputs, sources, *, max_selected_inputs):
    """Explain every pair; only a current exact reviewer record can establish one."""
    if type(inputs) is not ScientificLookupInputs or inputs.outcome.status.status != "completed":
        raise ValueError("Completed prepared result lookup is required")
    outcome = inputs.outcome
    parents = {parent.parent_result_revision_id: parent for parent in inputs.parents}
    if len(parents) != len(outcome.results) or len(outcome.results) + len(sources) > max_selected_inputs:
        raise ValueError("Complete bounded mixed parent and passage inventories are required")
    candidates = []
    for row in outcome.results:
        parent = parents[row.binding.parent_result_revision_id]
        for source in sources:
            evidence, packing = source.evidence_provenance, source.packing_info
            if (packing is None or evidence.get("chunk_kind") != "original_passage"
                    or evidence.get("permission_status") == "restricted" or evidence.get("currentness") == "stale"):
                raise ValueError("Unheld typed original passages are required for explanation candidates")
            candidates.append((parent, source, evidence, packing))
    links = await scientific_result_passage.resolve_current_links(db, [
        (parent.parent_result_revision_id, evidence["evidence_revision_id"])
        for parent, _, evidence, _ in candidates
    ])
    associations = []
    for parent, source, evidence, packing in candidates:
        same = parent.paper_id == source.paper_id and parent.source_snapshot_sha256 == packing.source_snapshot_sha256
        link = links.get((parent.parent_result_revision_id, evidence["evidence_revision_id"]))
        associations.append(MixedEvidenceAssociation(parent_result_revision_id=parent.parent_result_revision_id,
            result_source_snapshot_sha256=parent.source_snapshot_sha256, source_index=source.index,
            source_vector_id=packing.chunk_id, source_evidence_revision_id=evidence["evidence_revision_id"],
            source_evidence_record_sha256=evidence["evidence_record_sha256"], source_content_sha256=evidence["content_sha256"],
            catalogue_relation="same_snapshot" if same else "not_same_snapshot",
            status="established" if link else "not_established",
            reason_code="reviewed_result_passage_bridge_current" if link else "reviewed_result_passage_bridge_missing",
            **(link or {})))
    reasons = ["numerical_explanation_not_established"]
    if not associations or any(item.status == "not_established" for item in associations):
        reasons.append("reviewed_result_passage_bridge_missing")
    if not outcome.results:
        reasons.append("no_matching_extraction")
    if not sources:
        reasons.append("no_original_context")
    if len(outcome.results) == max_selected_inputs:
        reasons.append("combined_source_limit")
    return ScientificMixedEvidence(status="completed", result_count=len(outcome.results), source_count=len(sources),
        max_selected_inputs=max_selected_inputs, associations=associations, reason_codes=reasons)


def mixed_answer(report):
    if report.status != "completed":
        return ("Mixed scientific retrieval is unavailable or its selected evidence changed. "
                "Both numerical records and original explanation candidates have been withheld. Please ask again.")
    linked = sum(item.status == "established" for item in report.associations)
    text = ("Source-linked extraction records and original explanation candidates are shown separately. "
            "Numerical or causal explanation is not established. ")
    if linked:
        text += (f"{linked} exact result-passage pair{'s have' if linked != 1 else ' has'} a current reviewed link; "
                 "that review records the claim/sample-to-passage relation only and is not scientific acceptance or a causal conclusion. ")
    if linked != len(report.associations):
        text += "At least one displayed pair has no current reviewed claim/sample-to-passage link. "
    text += ("Sharing a paper, catalogue snapshot, Work, formula or reported sample name does not establish that relationship. "
             "No model-generated numerical or causal synthesis was performed.")
    if not report.result_count:
        text += " No eligible extraction matched all interpreted conditions; this is not evidence of absent superconductivity."
    if not report.source_count:
        text += " No original explanation context was selected within the shared source and byte limits."
    return text
