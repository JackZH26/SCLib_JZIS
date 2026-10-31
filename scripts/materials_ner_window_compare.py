"""Audit paired input representations in original source coordinates.

This module never accepts, merges, or promotes a scientific result. A repeated
numeric occurrence is a review candidate, not evidence of duplicate experiments.
"""
from __future__ import annotations

from collections import defaultdict
import json
import re

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import sha


def _blocks(bundle):
    rows = bundle["blocks"]
    result = {b["id"]: b for b in rows}
    if len(rows) != len(result):
        raise ValueError("ambiguous block identity")
    for block in rows:
        if sha(block["text"].encode()) != block["sha256"]:
            raise ValueError("block content drift")
    return result


def block_projection(parent, child, local_block_id):
    """Return a proven source slice, allowing target and every context role."""
    original, local = _blocks(parent), _blocks(child)
    if child["work_id"] != parent["work_id"]:
        raise ValueError("work identity mismatch")
    block = local[local_block_id]
    parent_docs = {d["id"]: d for d in parent["documents"]}
    child_docs = {d["id"]: d for d in child["documents"]}
    if len(child_docs) != len(child["documents"]) or len(parent_docs) != len(parent["documents"]):
        raise ValueError("ambiguous document identity")
    identity = ("id", "source_uri", "source_sha256", "source_kind", "role",
                "publication_version", "version_status", "processing_permission",
                "redistribution_permission")
    for document in child_docs.values():
        prior = parent_docs.get(document["id"])
        if prior is None or any(document[k] != prior[k] for k in identity):
            raise ValueError("document identity mismatch")
    if block["document_id"] not in child_docs:
        raise ValueError("unresolved source document")
    if digest(parent) == digest(child):
        source, offset, role = original[local_block_id], 0, "whole"
    else:
        notes = [json.loads(n.removeprefix("SOURCE_WINDOW "))
                 for n in child["acquisition_notes"] if n.startswith("SOURCE_WINDOW ")]
        if len(notes) != 1 or notes[0]["parent_bundle_sha256"] != digest(parent):
            raise ValueError("window parent mismatch")
        note = notes[0]
        target_source = original[note["source_block_id"]]
        if target_source["sha256"] != note["source_block_sha256"]:
            raise ValueError("window source hash mismatch")
        targets = [b for b in local.values() if b["locator"].startswith("target:")]
        if len(targets) != 1:
            raise ValueError("ambiguous target")
        target = targets[0]
        expected_locator = (f"target:{target_source['locator']}:chars["
                            f"{note['start_char']}:{note['end_char']}]")
        if (target["locator"] != expected_locator or
                target["document_id"] != target_source["document_id"] or
                not 0 <= note["start_char"] < note["end_char"] <= len(target_source["text"]) or
                target["text"] != target_source["text"][note["start_char"]:note["end_char"]]):
            raise ValueError("target mapping mismatch")
        match = re.fullmatch(r"(target|context-\d+|context-previous-page|context-next-page|context-document|revision-context):(.+):chars\[(\d+):(\d+)\]", block["locator"])
        if not match:
            raise ValueError("unsupported source slice locator")
        role, locator, start, end = match.groups()
        candidates = [b for b in original.values() if b["document_id"] == block["document_id"] and b["locator"] == locator]
        if len(candidates) != 1:
            raise ValueError("ambiguous original locator")
        source = candidates[0]
        offset, end = int(start), int(end)
        if not 0 <= offset < end <= len(source["text"]) or source["text"][offset:end] != block["text"]:
            raise ValueError("slice content mismatch")
    return {"block_id": source["id"], "block_sha256": source["sha256"],
            "document_id": source["document_id"], "locator": source["locator"],
            "offset": offset, "input_role": role}


def project_evidence(parent, child, location):
    block = _blocks(child)[location["block_id"]]
    for name in ("block_sha256", "document_id", "locator"):
        expected = block["sha256"] if name == "block_sha256" else block[name]
        if location[name] != expected:
            raise ValueError("evidence identity mismatch")
    start, end = location["start_char"], location["end_char"]
    if not 0 <= start < end <= len(block["text"]):
        raise ValueError("evidence outside local block")
    quote = block["text"][start:end]
    if sha(quote.encode()) != location["quote_sha256"]:
        raise ValueError("evidence quote drift")
    mapped = block_projection(parent, child, block["id"])
    offset = mapped.pop("offset")
    return dict(mapped, start_char=start + offset, end_char=end + offset,
                quote=quote, quote_sha256=location["quote_sha256"], field_path=location["path"])


def literal_occurrences(text, raw):
    """Whitespace-only matching; preserve all matches and never choose nearest."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    indices = [i for i, c in enumerate(text) if not c.isspace()]
    flat = "".join(text[i] for i in indices)
    needle = "".join(raw.split())
    found, start = [], 0
    while (at := flat.find(needle, start)) >= 0:
        end = at + len(needle)
        # Do not resolve 40 to the tail of 140, or 8.8 to the tail of 18.8.
        partial = ((needle[0].isdigit() and at and (flat[at-1].isdigit() or flat[at-1] == ".")) or
                   (needle[-1].isdigit() and end < len(flat) and (flat[end].isdigit() or flat[end] == ".")))
        if not partial:
            found.append((indices[at], indices[end-1] + 1))
        start = at + 1
    return found


def result_coordinates(parent, packet, row_index):
    """Reconcile quantity or qualitative non-detection field evidence."""
    row = packet["rows"]["results"][row_index]
    result = row["payload"]
    non_detection = result.get("quantity_kind") == "non_detection"
    path = f"/results/{row_index}/" + ("quantity_kind" if non_detection else "quantity")
    locations = [x for x in packet["receipt"].get("validation", {}).get("resolved_evidence", []) if x["path"] == path]
    projected, seen, anchors = [], set(), {}
    raw = result["quantity"]["raw"]
    if non_detection:
        qualifiers = [q for q in result.get("qualifiers", []) if q["kind"] == "non_detection"]
        raw = qualifiers[0]["raw"] if len(qualifiers) == 1 else None
    for location in locations:
        evidence = project_evidence(parent, packet["bundle"], location)
        key = (evidence["document_id"], evidence["block_id"], evidence["start_char"], evidence["end_char"])
        if key not in seen:
            projected.append(evidence)
            seen.add(key)
        for a, b in literal_occurrences(evidence["quote"], raw):
            anchor = {k: evidence[k] for k in ("document_id", "block_id", "block_sha256", "locator")}
            anchor.update(start_char=evidence["start_char"] + a, end_char=evidence["start_char"] + b,
                          literal=evidence["quote"][a:b])
            anchors[(anchor["block_id"], anchor["start_char"], anchor["end_char"])] = anchor
    values = list(anchors.values())
    return {"field_evidence": projected, "literal_anchors": values,
            "anchor_status": "unique" if len(values) == 1 else "ambiguous" if values else "unresolved",
            "scientific_identity_established": False}


def possible_repeated_occurrences(records):
    groups = defaultdict(list)
    for record in records:
        coordinate = record["coordinates"]
        if coordinate["anchor_status"] != "unique":
            continue
        anchor = coordinate["literal_anchors"][0]
        key = (record["work_id"], anchor["document_id"], anchor["block_id"],
               anchor["block_sha256"], anchor["start_char"], anchor["end_char"])
        groups[key].append(record["record_id"])
    return [{"original_occurrence": list(key), "record_ids": rows, "automatically_merged": False}
            for key, rows in groups.items() if len(rows) > 1]


def covered_characters(intervals):
    """Union source intervals without adding context twice."""
    groups = defaultdict(list)
    for block_id, start, end in intervals:
        if not 0 <= start < end:
            raise ValueError("invalid coverage interval")
        groups[block_id].append((start, end))
    count = 0
    for rows in groups.values():
        stop = -1
        for start, end in sorted(rows):
            count += max(0, end - max(start, stop))
            stop = max(stop, end)
    return count
