"""Immutable source spans selected by the model, never retyped by it.

Offsets are into the locked window block. Its locator/manifest in turn binds it
to the original document. Span IDs are local to one hash-bound source catalog.
"""
from __future__ import annotations

import re

from .contract import digest
from .sources import Bundle, sha, verify_bundle

CATALOG_VERSION = "materials-source-spans/1"


def source_spans(text: str, max_chars=900):
    """Partition without deleting whitespace or breaking a short TeX row."""
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundaries = [m.end() for m in re.finditer(r"\n|(?<=[.!?])\s+", text[start:end])
                          if m.end() >= max_chars // 2]
            if boundaries:
                end = start + boundaries[-1]
            else:
                space = text.rfind(" ", start + max_chars // 2, end)
                if space >= 0:
                    end = space + 1
        yield start, end
        start = end


def source_catalog(bundle: Bundle) -> dict:
    verify_bundle(bundle)
    blocks, spans = {}, {}
    for number, block in enumerate(bundle.blocks, 1):
        alias = f"B{number}"
        blocks[alias] = {"block_id": block.id, "block_sha256": block.sha256,
                         "document_id": block.document_id, "locator": block.locator}
        for start, end in source_spans(block.text):
            identifier = f"S{len(spans) + 1}"
            text = block.text[start:end]
            spans[identifier] = {"block_alias": alias, "block_id": block.id,
                                 "start_char": start, "end_char": end,
                                 "text": text, "text_sha256": sha(text.encode())}
    return {"schema": CATALOG_VERSION, "bundle_sha256": digest(bundle.model_dump()),
            "blocks": blocks, "spans": spans}


def selected_quotes(catalog: dict, identifiers: list[str]) -> list[dict]:
    """Join adjacent selected spans, allowing a raw token to cross a boundary.

Never bridge an unselected span or two blocks. Unknown/duplicate references
are errors rather than guessed nearest matches.
"""
    if not identifiers or len(identifiers) != len(set(identifiers)):
        raise ValueError("empty_or_duplicate_source_span")
    if any(identifier not in catalog["spans"] for identifier in identifiers):
        raise ValueError("unknown_source_span")
    selected = set(identifiers)
    quotes = []
    for identifier, span in catalog["spans"].items():
        if identifier not in selected:
            continue
        if (quotes and quotes[-1]["block_id"] == span["block_id"]
                and quotes[-1]["end_char"] == span["start_char"]):
            quotes[-1]["quote"] += span["text"]
            quotes[-1]["end_char"] = span["end_char"]
            quotes[-1]["span_ids"].append(identifier)
        else:
            quotes.append({"block_id": span["block_id"], "quote": span["text"],
                           "start_char": span["start_char"], "end_char": span["end_char"],
                           "span_ids": [identifier]})
    return quotes


def equivalent_location_spans(catalog: dict, identifiers) -> set[str]:
    """Expand aliases only for identical bytes at the same document coordinates.

    Historical windows sometimes repeat a target interval as context. Text
    equality alone is insufficient: the same sentence on another page, in
    another source or at another offset is a different occurrence.
    """
    pattern = re.compile(r"^(?:target|context-\d+):(.+):chars\[(\d+):(\d+)\]$")
    keys = {}
    for identifier, span in catalog["spans"].items():
        block = catalog["blocks"][span["block_alias"]]
        match = pattern.fullmatch(block["locator"])
        if match is None:
            keys[identifier] = ("alias", identifier)
            continue
        offset, limit = int(match[2]), int(match[3])
        if span["end_char"] > limit - offset:
            keys[identifier] = ("invalid_coordinate_alias", identifier)
            continue
        keys[identifier] = (block["document_id"], match[1],
                            offset + span["start_char"], offset + span["end_char"],
                            span["text_sha256"])
    selected = {keys[i] for i in identifiers if i in keys}
    return {i for i, key in keys.items() if key in selected}
