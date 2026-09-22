"""Detached final-answer receipts and retained-member verification.

This records returned output, not the full provider request, deterministic
regeneration, scientific validation, or present-day source permissions. The
router owns authentication and atomic history/receipt insertion. This module
never commits, writes SQL, follows the active pointer, or hydrates current Chunk.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa

from models.answer_evidence import (
    EXCLUDED_RESPONSE_FIELDS,
    MAX_BYTES,
    VERSION,
    AnswerEvidenceBindings,
    AnswerEvidenceItem,
    SavedAnswerEvidenceReceipt,
    canonical,
    validate_body,
    validate_request,
    validate_response,
)
from models.db import Chunk
from models.index_read import generation_read_metadata
from models.search import AskRequest, AskResponse, AskSource
from services import index_retrieval
from services.authors import short as authors_short
from services.retrieval_currentness import SelectionPin
from services.scientific_query_lookup import ScientificLookupInputs

_SEAL_KEY = secrets.token_bytes(32)
_MEMBER_FIELDS = ("content_sha256", "chunk_revision_sha256", "vector_sha256", "source_snapshot_sha256",
                  "evidence_revision_id", "evidence_record_sha256")
_PIN_FIELDS = ("generation_id", "activation_event_id", "manifest_sha256")


class AnswerEvidenceError(ValueError):
    """Only static reason codes; no source, model, DB or credential payload."""


def _require(condition):
    if not condition:
        raise AnswerEvidenceError("answer_evidence_binding_unavailable")


def _hash(value):
    return hashlib.sha256(value.encode("utf-8") if type(value) is str else value).hexdigest()


def _seal(kind, payload):
    return hmac.new(_SEAL_KEY, kind.encode("ascii") + b"\0" + payload, hashlib.sha256).hexdigest()


def _json(payload):
    _require(type(payload) is str and len(payload.encode("utf-8")) <= MAX_BYTES)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result
    def constant(_value):
        raise AnswerEvidenceError("answer_evidence_nonfinite_number")
    result = json.loads(payload, object_pairs_hook=unique, parse_constant=constant)
    canonical(result)
    return result


@dataclass(frozen=True, slots=True)
class CapturedAnswerInputs:
    _json: str = field(repr=False)
    _signature: str = field(repr=False)

    def _read(self):
        _require(type(self._json) is str and type(self._signature) is str
                 and hmac.compare_digest(self._signature, _seal("capture", self._json.encode("utf-8"))))
        return _json(self._json)


@dataclass(frozen=True, slots=True)
class PreparedAnswerEvidence:
    _json: str = field(repr=False)
    _signature: str = field(repr=False)

    @property
    def document(self):
        _require(type(self._json) is str and type(self._signature) is str
                 and hmac.compare_digest(self._signature, _seal("prepared", self._json.encode("utf-8"))))
        result = _json(self._json)
        validate_body(result["request"], result["response"], result["bindings"])
        return result


def _snippet(text):
    text = " ".join(text.split())
    return text if len(text) <= 280 else text[:279].rstrip() + "…"


def _source_attribution(source, chunk):
    paper = index_retrieval.attribution(chunk)
    _require(source.paper_id == chunk.paper_id == paper.id and source.title == paper.title
        and source.arxiv_id == paper.arxiv_id and source.authors_short == authors_short(paper.authors or [])
        and source.year == (paper.date_submitted.year if paper.date_submitted else None)
        and source.section == chunk.section and source.snippet == _snippet(chunk.text))


def _item(kind, position, chunk_id, paper_id, text, pin, member, evidence):
    _require(type(pin) is SelectionPin and pin.chunk_id == chunk_id and pin.paper_id == paper_id)
    _require(type(text) is str and type(evidence) is dict)
    body = {"kind": kind, "position": position, "chunk_id": chunk_id, "paper_id": paper_id,
        "content_sha256": _hash(text), "member_record_sha256": None, "chunk_revision_sha256": None,
        "vector_sha256": None, "source_snapshot_sha256": None,
        "evidence_revision_id": evidence.get("evidence_revision_id"),
        "evidence_record_sha256": evidence.get("evidence_record_sha256"),
        "parent_result_revision_id": evidence.get("parent_result_revision_id"),
        "parent_result_sha256": evidence.get("parent_result_sha256"),
        "selection_input_sha256": pin.input_sha256,
        "selection_generation_pin_sha256": pin.generation_pin_sha256,
        "selection_grouping_sha256": pin.grouping_sha256, "has_evidence_pin": pin.has_evidence_pin}
    if member is not None:
        _require(type(member) is dict and member["vector_id"] == chunk_id and member["paper_id"] == paper_id
                 and member["snapshot_json"]["text"] == text and member["content_sha256"] == body["content_sha256"])
        # ScientificLookupInputs intentionally omits non-JSON vector bytes;
        # its member hash came from the actual bounded loader. Historical
        # verification always reloads and checks the real retained bytes.
        if kind == "source":
            _require(_hash(bytes(member["vector_bytes"])) == member["vector_sha256"])
        body.update({key: member[key] for key in _MEMBER_FIELDS})
        body["member_record_sha256"] = member["record_sha256"]
        _require(all(evidence.get(key) == body[key] for key in (
            "content_sha256", "evidence_revision_id", "evidence_record_sha256")))
    if evidence:
        _require(evidence["content_sha256"] == body["content_sha256"]
                 and evidence.get("permission_status") != "restricted" and evidence.get("currentness") != "stale")
    return AnswerEvidenceItem.model_validate(body, strict=True).model_dump(mode="json")


def capture_inputs(*, request, generation_pin=None, sources=(), chunks=(), selection_pins=(), scientific_inputs=None):
    """Called with the selected actual typed inputs before the provider await.

    The selection digest is an existing private SelectionPin observation; this
    helper does not claim its hash authenticates a source or reviewer. A sealed
    copy prevents later mutable aliases from changing the saved presentation.
    """
    try:
        _require(type(request) is AskRequest and type(sources) is tuple and type(chunks) is tuple
                 and type(selection_pins) is tuple and len(sources) == len(chunks) == len(selection_pins)
                 and len(sources) <= 20 and all(type(source) is AskSource for source in sources))
        request_value = validate_request(request.model_dump(mode="json"))
        if generation_pin is not None:
            _require(type(generation_pin) is dict and set(generation_pin) == {
                "generation_id", "activation_event_id", "profile", "resource", "manifest_sha256"})
        generation = generation_read_metadata(generation_pin).model_dump(mode="json")
        generation_hash = index_retrieval.pin_sha256(generation_pin) if generation_pin is not None else None
        items, source_values, result_values = [], [], []
        for position, (source, chunk, pin) in enumerate(zip(sources, chunks, selection_pins, strict=True), 1):
            _require(type(chunk) is (index_retrieval.GenerationChunk if generation_pin is not None else Chunk)
                     and source.index == position and type(pin) is SelectionPin
                     and pin.generation_pin_sha256 == generation_hash)
            if generation_pin is not None:
                _require(index_retrieval.pin_sha256(chunk.generation_pin) == generation_hash)
            _source_attribution(source, chunk)
            source_values.append(source.model_dump(mode="json"))
            items.append(_item("source", position, chunk.id, chunk.paper_id, chunk.text, pin,
                chunk.member if generation_pin is not None else None, source.evidence_provenance))
        if scientific_inputs is not None:
            _require(type(scientific_inputs) is ScientificLookupInputs)
            # Rerun the existing complete typed input invariants, rather than
            # accepting an arbitrary object offering .parents/.outcome.
            scientific_inputs.__post_init__()
            result_values = [result.model_dump(mode="json") for result in scientific_inputs.outcome.results]
            if result_values:
                _require(generation_pin is not None
                         and index_retrieval.pin_sha256(scientific_inputs.generation_pin) == generation_hash)
            for position, (result, parent) in enumerate(zip(result_values, scientific_inputs.parents, strict=True), 1):
                member = parent.member
                from services.scientific_query import interpret_scientific_query
                from services.scientific_query_results import select_record_results
                # Validate the returned scalar projection once at capture with
                # this implementation. A historical read later verifies the
                # saved output/refs without rerunning a newer result parser.
                projected = select_record_results(member["snapshot_json"]["materials_mentioned"],
                    interpret_scientific_query(request.question), scope_id=parent.paper_id)
                matching = [value.model_dump(mode="json") for value in projected
                    if value.result_id == result["result"]["result_id"] and value.record_index == result["result"]["record_index"]]
                _require(matching == [result["result"]])
                evidence = {**result["binding"], "permission_status": "unresolved", "currentness": "current"}
                items.append(_item("scientific_result", position, parent.vector_id, parent.paper_id,
                    member["snapshot_json"]["text"], parent.selection_pin, member, evidence))
        bindings = {"version": VERSION, "mode": "no_selected_evidence" if not items
            else "generation_bound" if generation_pin is not None else "snapshot_only",
            **{key: generation[key] for key in _PIN_FIELDS}, "items": items}
        AnswerEvidenceBindings.model_validate(bindings, strict=True)
        _require(len(items) <= request.max_sources)
        payload = canonical({"request": request_value, "generation": generation,
                             "sources": source_values, "results": result_values, "bindings": bindings})
        return CapturedAnswerInputs(payload.decode("utf-8"), _seal("capture", payload))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise AnswerEvidenceError("answer_evidence_capture_unavailable") from None


def finish_capture(captured, response):
    """Save exactly the validated final output; withdrawn input IDs are dropped."""
    try:
        _require(type(captured) is CapturedAnswerInputs and type(response) is AskResponse)
        inputs = captured._read()
        response_value = validate_response(response.model_dump(mode="json", exclude=EXCLUDED_RESPONSE_FIELDS))
        _require(response_value["retrieval_generation"] == inputs["generation"])
        bindings = inputs["bindings"]
        if response_value["sources"] or response_value["scientific_results"]:
            _require(response_value["sources"] == inputs["sources"] and response_value["scientific_results"] == inputs["results"])
        else:
            # Final abstention/no-source output must not resurrect private IDs
            # from stale or restricted pre-generation selections.
            bindings = {**bindings, "mode": "no_selected_evidence", "items": []}
        request_value, response_value, bindings = validate_body(inputs["request"], response_value, bindings)
        payload = canonical({"request": request_value, "response": response_value, "bindings": bindings})
        _require(len(payload) <= MAX_BYTES - 4096)  # room for the closed receipt envelope
        return PreparedAnswerEvidence(payload.decode("utf-8"), _seal("prepared", payload))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise AnswerEvidenceError("answer_evidence_final_binding_unavailable") from None


def binding_scope(bindings):
    if type(bindings) is AnswerEvidenceBindings:
        model = bindings
    else:
        model = AnswerEvidenceBindings.model_validate(bindings, strict=True)
    return {"no_selected_evidence": "no_selected_evidence", "generation_bound": "generation_members",
            "snapshot_only": "legacy_snapshot"}[model.mode]


async def receipt_fields(db, prepared):
    """Read-only preparation; root inserts this beside AskHistory atomically."""
    _require(type(prepared) is PreparedAnswerEvidence)
    await _session(db, readonly=False)
    value = prepared.document
    row = (await db.execute(sa.text("""SELECT
        public.sclib_answer_evidence_canonical_v1(CAST(:request AS jsonb)) AS request_json,
        public.sclib_answer_evidence_canonical_v1(CAST(:response AS jsonb)) AS response_json,
        public.sclib_answer_evidence_canonical_v1(CAST(:bindings AS jsonb)) AS bindings_json"""), {
            key: canonical(value[key]).decode("utf-8") for key in ("request", "response", "bindings")})).mappings().one()
    result = {key: row[key] for key in ("request_json", "response_json", "bindings_json")}
    _require(all(type(text) is str for text in result.values())
             and sum(len(text.encode("utf-8")) for text in result.values()) <= MAX_BYTES - 4096)
    parsed = {key: _json(result[key + "_json"]) for key in ("request", "response", "bindings")}
    validate_body(**parsed)
    result.update({key + "_sha256": _hash(result[key + "_json"]) for key in parsed})
    result.update(version=VERSION, generation_id=value["bindings"]["generation_id"],
                  activation_event_id=value["bindings"]["activation_event_id"])
    return result


async def _session(db, *, readonly):
    _require(not db.new and not db.dirty and not db.deleted)
    row = (await db.execute(sa.text("SELECT current_setting('transaction_isolation'),"
        "current_setting('transaction_read_only'),current_setting('TimeZone'),"
        "(SELECT setting::int FROM pg_settings WHERE name='statement_timeout')"))).one()
    _require(row[0] in {"repeatable read", "serializable"} and row[2] == "UTC"
             and type(row[3]) is int and 1 <= row[3] <= 10000 and (not readonly or row[1] == "on"))


async def _historical_members(db, bindings, response):
    """No active pointer or mutable Chunk/current source approval is consulted."""
    from services.index_generations import load_generation, load_generation_members
    if bindings.generation_id is None:
        return
    generation = await load_generation(db, generation_id=bindings.generation_id)
    _require(generation is not None and generation["manifest_sha256"] == bindings.manifest_sha256)
    activation = (await db.execute(sa.text("""SELECT generation_id,
        record_sha256=public.sclib_index_record_hash_v1(to_jsonb(e)) AS intact
        FROM index_activation_events e WHERE id=:id"""), {"id": UUID(bindings.activation_event_id)})).mappings().one_or_none()
    _require(activation is not None and activation["intact"] is True
             and str(activation["generation_id"]) == bindings.generation_id)
    historical_pin = {**generation, "activation_event_id": bindings.activation_event_id}
    items = bindings.items
    if not items:
        return
    members = await load_generation_members(db, generation_id=bindings.generation_id,
                                           vector_ids=[item.chunk_id for item in items])
    by_id = {member["vector_id"]: member for member in members}
    _require(set(by_id) == {item.chunk_id for item in items})
    evidence_rows = (await db.execute(sa.text("""SELECT to_jsonb(e) AS evidence,to_jsonb(x) AS parent,
        e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
        x.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS parent_intact
        FROM rag_evidence_revisions e LEFT JOIN rag_extraction_revisions x ON x.id=e.parent_extraction_revision_id
        WHERE e.id IN :ids""").bindparams(sa.bindparam("ids", expanding=True, type_=sa.Uuid())),
        {"ids": [UUID(item.evidence_revision_id) for item in items]})).mappings().all()
    evidence_by_id = {row["evidence"]["id"]: row for row in evidence_rows}
    for item in items:
        member = by_id[item.chunk_id]
        _require(member["record_sha256"] == item.member_record_sha256 and member["paper_id"] == item.paper_id
                 and item.selection_generation_pin_sha256 == index_retrieval.pin_sha256(historical_pin)
                 and all(member[key] == getattr(item, key) for key in _MEMBER_FIELDS))
        row = evidence_by_id.get(item.evidence_revision_id)
        _require(row is not None and row["evidence_intact"] is True)
        evidence, parent = row["evidence"], row["parent"]
        _require(evidence["record_sha256"] == item.evidence_record_sha256
                 and evidence["paper_id"] == item.paper_id and evidence["chunk_key"] == member["chunk_key"]
                 and evidence["content_sha256"] == item.content_sha256
                 and evidence["source_snapshot_sha256"] == item.source_snapshot_sha256)
        if parent is None:
            _require(item.parent_result_revision_id is None)
        else:
            _require(row["parent_intact"] is True and parent["id"] == item.parent_result_revision_id
                     and parent["record_sha256"] == item.parent_result_sha256
                     and parent["paper_id"] == item.paper_id and parent["source_snapshot_sha256"] == item.source_snapshot_sha256)
        if item.kind == "source":
            source = response["sources"][item.position - 1]
            paper, chunk = member["paper_snapshot_json"], member["snapshot_json"]
            _require(source["title"] == paper["title"] and source["arxiv_id"] == paper["arxiv_id"]
                and source["authors_short"] == authors_short(paper["authors"] or [])
                and source["year"] == (int(paper["date_submitted"][:4]) if paper["date_submitted"] else None)
                and source["section"] == chunk["section"] and source["snippet"] == _snippet(chunk["text"]))
        else:
            result = response["scientific_results"][item.position - 1]["result"]
            records = member["snapshot_json"]["materials_mentioned"]
            from services.rag_evidence_contract import canonical as evidence_canonical
            from services.rag_evidence_contract import input_record_sha256
            _require(parent is not None and 0 <= result["record_index"] < len(records)
                and input_record_sha256(records[result["record_index"]]) == parent["input_record_sha256"]
                and result["result_id"] == "legacy-result:" + _hash(evidence_canonical([item.paper_id, records[result["record_index"]]])))


async def verify_historical(db, storedrow):
    """Verify a real immutable stored row; caller separately authorizes its owner."""
    try:
        await _session(db, readonly=True)
        row = dict(storedrow)
        required = {"history_id", "version", "generation_id", "activation_event_id", "request_json", "response_json",
                    "bindings_json", "request_sha256", "response_sha256", "bindings_sha256", "record_sha256", "created_at"}
        _require(set(row) == required and row["version"] == VERSION)
        _require(all(type(row[key + "_json"]) is str for key in ("request", "response", "bindings")))
        _require(sum(len(row[key + "_json"].encode("utf-8")) for key in ("request", "response", "bindings")) <= MAX_BYTES)
        payload = {}
        for key in ("request", "response", "bindings"):
            _require(_hash(row[key + "_json"]) == row[key + "_sha256"])
            payload[key] = _json(row[key + "_json"])
        request, response, bindings_value = validate_body(**payload)
        bindings = AnswerEvidenceBindings.model_validate(bindings_value, strict=True)
        _require((str(row["generation_id"]) if row["generation_id"] is not None else None) == bindings.generation_id
                 and (str(row["activation_event_id"]) if row["activation_event_id"] is not None else None) == bindings.activation_event_id)
        # Check the supplied row is the exact persisted immutable receipt, not a
        # caller-made dictionary with freshly recalculated content hashes.
        intact = await db.scalar(sa.text("""SELECT record_sha256=:record
            AND record_sha256=public.sclib_answer_evidence_record_hash_v1(to_jsonb(r))
            AND request_sha256=:request AND response_sha256=:response AND bindings_sha256=:bindings
            FROM answer_evidence_receipts r WHERE history_id=:id"""), {
                "id": UUID(str(row["history_id"])), "record": row["record_sha256"],
                **{key: row[key + "_sha256"] for key in ("request", "response", "bindings")}})
        _require(intact is True)
        await _historical_members(db, bindings, response)
        return SavedAnswerEvidenceReceipt(version=VERSION, history_id=str(row["history_id"]),
            **{key: row[key] for key in ("record_sha256", "request_sha256", "response_sha256", "bindings_sha256")},
            request=request, response=response, bindings=bindings).model_dump(mode="json")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise AnswerEvidenceError("answer_evidence_historical_verification_unavailable") from None
