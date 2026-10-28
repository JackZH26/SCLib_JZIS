"""Private source-result reading; no acceptance, identity assignment or writes."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import re

from sqlalchemy import text

from models import materials_ner_proposals_v1 as base, materials_ner_proposals_v2 as extension
from services.materials_proposal_storage import canonical, digest, verify_readback
from services.research_access import ResearchAccessDenied, active_grant
from services.scientific_result_dossier import _session

VERSION = "materials-proposal-review/1"
VISUAL_VERSION = "materials-proposal-review/2"
MAX_PACKET_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
AUTHORITY = dict(scientific_acceptance=False, ml_training_eligible=False, canonical_identity_assigned=False,
                 review_write_available=False, public_release=False)
GROUPS = ("samples", "states", "protocols", "sample_relations", "condition_supports")


class ProposalUnavailable(ValueError):
    pass


class ProposalIntegrityError(ValueError):
    pass


def require(condition, message="proposal_integrity_mismatch"):
    if not condition:
        raise ProposalIntegrityError(message)


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid_run_identifier")
    return value


def local_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_local_identifier")
    return value


async def admit(db, actor_user_id):
    await _session(db)
    for role in ("curator", "reviewer"):
        try:
            grant = await active_grant(db, actor_user_id, role=role)
            return dict(grant_id=str(grant["id"]), role=role, record_sha256=grant["record_sha256"])
        except ResearchAccessDenied:
            continue
    raise ResearchAccessDenied("proposal_review_role_required")


async def schema_ready(db):
    if (await db.execute(text("SELECT to_regclass('materials_ner_v1.schema_version')"))).scalar() is None:
        raise ProposalUnavailable("proposal_storage_unavailable")
    versions = dict((await db.execute(text("SELECT version,fingerprint FROM materials_ner_v1.schema_version"))).all())
    require(versions.get("materials-ner-proposals/1") == base.FINGERPRINT
            and versions.get(extension.VERSION) == extension.FINGERPRINT, "proposal_storage_version_mismatch")


async def capabilities(db, actor_user_id):
    grant = await admit(db, actor_user_id)
    await schema_ready(db)
    return dict(version=VERSION, can_read=True, role=grant["role"], authority=AUTHORITY)


def header(packet, created_at):
    receipt = packet["receipt"]
    return dict(run_id=packet["run_id"], packet_sha256=packet["packet_hash"], bundle_sha256=packet["bundle_hash"],
        work_id=packet["work_id"], title=packet["bundle"]["title"], created_at=created_at.isoformat(),
        worker_state=receipt["state"], result_count=len(packet["rows"]["results"]),
        model=receipt["config"]["model"], extraction_version=receipt.get("extraction", {}).get("schema_version"))


async def runs(db, actor_user_id, *, work_id=None, after=None, limit=10):
    await admit(db, actor_user_id)
    await schema_ready(db)
    if not 1 <= limit <= 25:
        raise ValueError("invalid_run_limit")
    if after is not None: identifier(after)
    if work_id is not None and re.fullmatch(r"arxiv:(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+/[0-9]{7})", work_id) is None:
        raise ValueError("invalid_work_identifier")
    rows = (await db.execute(text("""SELECT r.id AS run_id,r.packet_hash AS packet_sha256,
        r.bundle_id AS bundle_sha256,r.work_id,r.created_at,r.model,r.worker_state,
        b.payload->>'title' AS title,r.payload->'receipt'->'extraction'->>'schema_version' AS extraction_version,
        (SELECT count(*) FROM materials_ner_v1.results x WHERE x.run_id=r.id) AS result_count
        FROM materials_ner_v1.runs r JOIN materials_ner_v1.bundles b ON b.id=r.bundle_id
        WHERE (CAST(:work AS text) IS NULL OR r.work_id=:work)
          AND (CAST(:after AS text) IS NULL OR r.id>:after) ORDER BY r.id LIMIT :limit"""),
        dict(work=work_id, after=after, limit=limit+1))).mappings().all()
    items = [dict(r, created_at=r["created_at"].isoformat()) for r in rows[:limit]]
    return dict(version=VERSION, items=items, after=after, work_id=work_id,
        next_cursor=items[-1]["run_id"] if len(rows)>limit else None, authority=AUTHORITY)


async def retained_packet(db, run_id):
    identifier(run_id)
    metadata = (await db.execute(text("SELECT created_at,octet_length(payload::text) AS size "
        "FROM materials_ner_v1.runs WHERE id=:id"), {"id": run_id})).mappings().one_or_none()
    if metadata is None: raise ProposalUnavailable("proposal_run_unavailable")
    require(metadata["size"] <= MAX_PACKET_BYTES, "proposal_packet_limit")
    packet = (await db.execute(text("SELECT payload FROM materials_ner_v1.runs WHERE id=:id"), {"id": run_id})).scalar_one()
    require(packet["run_id"] == run_id and digest(packet["receipt"]) == run_id)
    require(digest({k:v for k,v in packet.items() if k!="packet_hash"}) == packet["packet_hash"])
    require(digest(packet["bundle"]) == packet["bundle_hash"])
    require(packet["work_id"] == packet["bundle"]["work_id"] == packet["receipt"]["work_id"])
    require(packet["receipt"]["bundle_sha256"] == packet["bundle_hash"])
    require(sum(len(v) for v in packet["rows"].values()) <= 2000 and len(packet["evidence"]) <= 20000,
            "proposal_graph_limit")
    try: await verify_readback(db, packet)
    except ValueError as error: raise ProposalIntegrityError("proposal_relational_readback_mismatch") from error
    return packet, metadata["created_at"]


def display_rows(packet, group):
    result = []
    for index, row in enumerate(packet["rows"].get(group, [])):
        # Keep all scientific fields. Evidence is read through exact source coordinates.
        body = deepcopy(row)
        body["payload"].pop("evidence", None)
        body["source_path"] = f"/{group}/{index}"
        result.append(body)
    return result


def source_item_accounting(packet):
    """Expose retained discovery and holds without declaring scientific recall."""
    receipt=packet['receipt'];inventory=receipt.get('inventory')
    if not isinstance(inventory,dict) or not isinstance(inventory.get('items'),list):
        return dict(version='materials-proposal-occurrences/1',available=False,
                    independent_recall_denominator=False,scientific_exclusion_approved=False)
    coverage=receipt.get('inventory_coverage',{});mapping=coverage.get('result_mapping',{})
    held=coverage.get('unextracted_items',[]);rows=[]
    duplicates=Counter(item['id'] for item in inventory['items'])
    for item in inventory['items']:
        iid=item['id'];results=[rid for rid,ids in mapping.items() if iid in ids]
        holds=[entry for entry in held if entry['item_id']==iid]
        status=('conflicting' if duplicates[iid]>1 or len(holds)>1 or (results and holds) else
                'emitted_multiple' if len(results)>1 else 'emitted' if results else 'held' if holds else 'missing')
        rows.append(dict(item_id=iid,value_as_written=item.get('value_raw'),quantity_as_written=item.get('quantity_name_raw'),
            sample_as_written=item.get('sample_raw'),status=status,result_ids=results,holds=deepcopy(holds)))
    journal=[];node=packet
    for depth in range(9):
        r=node['receipt'];audit=r.get('revision_audit',{})
        require(digest(r)==node['run_id'],'proposal_revision_identity_mismatch')
        for change in audit.get('changes',[]):
            if change.get('selection',{}).get('action')!='hold_observation':continue
            quotes=[];blocks={b['id']:b for b in node['bundle']['blocks']}
            for quote in change['source_quotes']:
                b=blocks.get(quote['block_id']);a,z=quote['start_char'],quote['end_char']
                require(b is not None and type(a) is int and type(z) is int and 0<=a<z<=len(b['text'])
                        and b['text'][a:z]==quote['quote'],'proposal_hold_source_mismatch')
                quotes.append(dict(quote=quote['quote'],document_id=b['document_id'],block_id=b['id'],
                    block_sha256=b['sha256'],locator=b['locator'],start_char=a,end_char=z,
                    quote_sha256=hashlib.sha256(quote['quote'].encode()).hexdigest()))
            journal.append(dict(revision_run_id=node['run_id'],observation_id=change['before']['id'],
                original_observation=deepcopy(change['before']),new_dispositions=deepcopy(change['after']['unextracted_items']),
                source_quotes=quotes,scientific_exclusion_approved=False,reviewer_kind='model'))
        parent=r.get('revision_parent')
        if parent is None:break
        node=parent
    else:raise ProposalIntegrityError('proposal_revision_ancestry_limit')
    original_ids={item['id'] for item in inventory['items']}
    additions=[dict(result_id=rid,item_ids=deepcopy(ids)) for rid,ids in mapping.items() if not set(ids)<=original_ids]
    return dict(version='materials-proposal-occurrences/1',available=True,original_item_count=len(rows),
        original_status_counts=dict(Counter(row['status'] for row in rows)),original_items=rows,
        additional_result_mappings=additions,all_unextracted_items=deepcopy(held),observation_hold_history=journal,
        inventory_sha256=digest(inventory),independent_recall_denominator=False,scientific_exclusion_approved=False)


async def run_detail(db, actor_user_id, run_id, *, after=None, limit=10):
    await admit(db, actor_user_id)
    await schema_ready(db)
    if after is not None: local_id(after)
    if not 1 <= limit <= 25: raise ValueError("invalid_result_limit")
    packet, created = await retained_packet(db, run_id)
    return detail_projection(packet, created, after=after, limit=limit)


def detail_projection(packet, created, *, after=None, limit=10):
    """Shared immutable scientific projection for paginated reading and export."""
    from services.materials_projector_review import project as projector_review
    projector_context = projector_review(packet)
    all_results = sorted(display_rows(packet, "results"), key=lambda row: row["local_id"])
    eligible = [r for r in all_results if after is None or r["local_id"] > after]
    selected = eligible[:limit]
    receipt, bundle = packet["receipt"], packet["bundle"]
    extraction = receipt.get("extraction", {})
    documents = [{key: doc.get(key) for key in ("id", "source_uri", "source_sha256", "source_kind", "role",
        "publication_version", "version_status", "processing_permission", "redistribution_permission", "coverage")}
        for doc in bundle["documents"]]
    return dict(version=VISUAL_VERSION if packet['receipt'].get('visual_support') is not None else VERSION,
        run=header(packet, created), after=after, results=selected,
        next_cursor=selected[-1]["local_id"] if len(eligible)>limit else None,
        entities={group:display_rows(packet, group) for group in GROUPS}, source_documents=documents,
        coverage=dict(source_status=bundle["source_status"], supplement_status=bundle["supplement_status"],
            outcome=extraction.get("outcome"), processed_block_ids=extraction.get("processed_block_ids", []),
            unread_block_ids=extraction.get("unread_block_ids", []), limitations=extraction.get("limitations", []),
            empty_reason=extraction.get("empty_reason"), evidence_count=len(packet["evidence"]),
            source_item_accounting=source_item_accounting(packet),
            **({'projector_review':projector_context} if projector_context is not None else {})),
        validation=dict(technical_valid=receipt.get("validation", {}).get("valid", False),
            issue_counts=dict(Counter(x["code"] for x in receipt.get("validation", {}).get("issues", []))),
            stage_errors=receipt.get("staged_errors", []), error_code=receipt.get("error_code")),
        training_exclusions=receipt.get("training_assessment", {}).get("results", []), authority=AUTHORITY)


def evidence_scope(packet, result_id):
    groups = packet["rows"]
    result = next((r["payload"] for r in groups["results"] if r["local_id"]==result_id), None)
    if result is None: raise ProposalUnavailable("proposal_result_unavailable")
    selected = {"results": {result_id}, "samples": {result["sample_id"]}, "states": {result["state_id"]},
                "protocols": {result["protocol_id"]}, "sample_relations": set(), "condition_supports": set()}
    for row in groups.get("sample_relations", []):
        p = row["payload"]
        if result["sample_id"] in (p["from_sample_id"],p["to_sample_id"]):
            selected["sample_relations"].add(row["local_id"])
            selected["samples"].update((p["from_sample_id"],p["to_sample_id"]))
    for row in groups.get("condition_supports", []):
        p = row["payload"]
        if p["state_id"]==result["state_id"]:
            selected["condition_supports"].add(row["local_id"])
            selected["results"].add(p["result_id"])
    for row in groups["results"]:
        if row["local_id"] in selected["results"]:
            selected["protocols"].add(row["payload"]["protocol_id"])
    return [f"/{group}/{index}" for group, ids in selected.items()
            for index, row in enumerate(groups.get(group, [])) if row["local_id"] in ids]


def passage(packet, ordinal, evidence):
    if evidence.get('kind') == 'visual_region':
        from services.materials_visual_evidence import passage as visual_passage
        return visual_passage(packet, ordinal, evidence)
    block = next((b for b in packet["bundle"]["blocks"] if b["id"]==evidence["block_id"]), None)
    require(block is not None, "evidence_block_missing")
    require(hashlib.sha256(block["text"].encode()).hexdigest()==block["sha256"]==evidence["block_sha256"])
    require(block["document_id"]==evidence["document_id"] and block["locator"]==evidence["locator"])
    start, end = evidence["start_char"], evidence["end_char"]
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(block["text"]))
    quote = block["text"][start:end]
    require(hashlib.sha256(quote.encode()).hexdigest()==evidence["quote_sha256"], "evidence_quote_mismatch")
    return dict(evidence, ordinal=ordinal, quote=quote)


async def evidence_page(db, actor_user_id, run_id, *, result_id, after=-1, limit=40):
    await admit(db, actor_user_id)
    await schema_ready(db)
    local_id(result_id)
    if not -1 <= after <= 20000 or not 1 <= limit <= 100: raise ValueError("invalid_evidence_page")
    packet, _ = await retained_packet(db, run_id)
    scope = evidence_scope(packet, result_id)
    matches = [(i,e) for i,e in enumerate(packet["evidence"]) if any(
        e["path"]==prefix or e["path"].startswith(prefix+"/") for prefix in scope)]
    following = [(i,e) for i,e in matches if i>after]
    items = [passage(packet,i,e) for i,e in following[:limit]]
    return dict(version=VISUAL_VERSION if packet['receipt'].get('visual_support') is not None else VERSION,
        run_id=run_id, packet_sha256=packet["packet_hash"], result_id=result_id,
        after=after, total_count=len(matches), scope_paths=scope, items=items,
        next_cursor=items[-1]["ordinal"] if len(following)>limit else None, authority=AUTHORITY)
