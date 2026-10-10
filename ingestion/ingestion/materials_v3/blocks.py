"""Ordered full-source blocks, immutable byte hashes, explicit image gaps."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import tiktoken

from . import PARSER_VERSION
from .contract import digest


class SourceError(ValueError):
    pass


class ArticleHTML(HTMLParser):
    """Keep article text, math alternatives, captions and entire table context."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.records, self.stack = [], [], []
        self.skip = 0
        self.table = 0
        self.table_kinds = []
        self.math_skips = []

    def flush(self, kind="text"):
        text = "".join(self.parts).strip()
        self.parts = []
        if text:
            self.records.append(
                {
                    "kind": kind,
                    "text": text,
                    "table_id": f"table-{self.table}" if kind == "table" else None,
                }
            )

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "nav"}:
            self.skip += 1
        if tag == "math":
            self.math_skips.append(bool(attrs.get("alttext")) and not self.skip)
        self.stack.append(tag)
        if self.skip:
            return
        if tag == "table":
            if not self.table_kinds:
                self.flush()
                classes = attrs.get("class", "").split()
                kind = (
                    "equation"
                    if any(c.startswith(("ltx_equation", "ltx_eqn")) for c in classes)
                    else "table"
                )
                if kind == "table":
                    self.table += 1
            else:
                kind = self.table_kinds[0]
            self.table_kinds.append(kind)
        elif (
            tag in {"p", "h1", "h2", "h3", "h4", "section", "figure"} and "table" not in self.stack
        ):
            self.flush()
        if tag == "math" and attrs.get("alttext"):
            self.parts.append(" " + attrs["alttext"] + " ")
            self.skip += 1
        if tag == "img":
            self.parts.append(" [IMAGE: " + attrs.get("alt", "unresolved figure") + "] ")
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        if tag in {"tr", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        skipped_math = tag == "math" and self.math_skips and self.math_skips.pop()
        if (tag in {"script", "style", "nav"} or skipped_math) and self.skip:
            self.skip -= 1
        if not self.skip and tag == "table":
            if self.table_kinds:
                kind = self.table_kinds.pop()
                if not self.table_kinds:
                    self.flush(kind)
        elif (
            not self.skip
            and tag in {"p", "h1", "h2", "h3", "h4", "figure"}
            and "table" not in self.stack
        ):
            self.flush("caption" if tag == "figure" else "text")
        if tag in self.stack:
            self.stack = self.stack[: len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def parse_source(path: Path, *, source_id: str, source_format=None) -> dict:
    """No network or DB calls. Original bytes are never rewritten."""
    data = path.read_bytes()
    if not data or len(data) > 128 * 1024 * 1024:
        raise SourceError("source_empty_or_exceeds_128MiB")
    sha = hashlib.sha256(data).hexdigest()
    kind = source_format or path.suffix.lower().lstrip(".")
    records, gaps = [], []
    if kind in {"txt", "text", "md"}:
        records = [{"kind": "text", "text": data.decode("utf-8")}]
    elif kind in {"html", "htm"}:
        parser = ArticleHTML()
        parser.feed(data.decode("utf-8"))
        parser.flush()
        records = parser.records
        if b"<img" in data:
            gaps.append({"kind": "figures_require_visual_review", "status": "not_digitized"})
    elif kind == "xml":
        root = ET.fromstring(data)

        # Walk document order; select maximal paragraph/table/caption nodes only.
        def walk(node):
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"p", "para", "table", "table-wrap", "caption", "title"}:
                records.append(
                    {
                        "kind": "table" if "table" in tag else "text",
                        "text": " ".join(node.itertext()),
                        "table_id": node.get("id"),
                    }
                )
            else:
                for child in node:
                    walk(child)

        walk(root)
        if not records:
            raise SourceError("xml_has_no_supported_article_nodes")
    elif kind == "pdf":
        from pypdf import PdfReader

        class WarningCapture(logging.Handler):
            page = None
            thread_id = threading.get_ident()

            def emit(self, record):
                if record.thread == self.thread_id and len(gaps) < 1000:
                    item = {
                        "kind": "pdf_parser_warning",
                        "page": self.page,
                        "message": record.getMessage()[:300],
                        "status": "requires_review",
                    }
                    if item not in gaps:
                        gaps.append(item)

        handler, logger = WarningCapture(logging.WARNING), logging.getLogger("pypdf")
        logger.addHandler(handler)
        try:
            reader = PdfReader(path)
            for number, page in enumerate(reader.pages, 1):
                handler.page = number
                text = (
                    page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False)
                    or ""
                )
                records.append({"kind": "pdf_page", "text": text, "page": number})
                if not text.strip():
                    gaps.append({"kind": "ocr_required", "page": number, "status": "unprocessed"})
        finally:
            logger.removeHandler(handler)
        gaps.append({"kind": "pdf_tables_figures_visual_review", "status": "not_verified"})
    else:
        raise SourceError("unsupported_source_format")
    records = [r for r in records if r["text"].strip()]
    if not records:
        raise SourceError("no_extractable_text")
    offset = 0
    for i, record in enumerate(records):
        record.update(
            source_id=source_id,
            source_sha256=sha,
            source_start=offset,
            source_end=offset + len(record["text"]),
            record_index=i,
        )
        offset += len(record["text"]) + 1
    manifest = {
        "parser_version": PARSER_VERSION,
        "source_id": source_id,
        "source_sha256": sha,
        "source_format": kind,
        "source_bytes": len(data),
        "records": records,
        "gaps": gaps,
        "coverage_status": "text_extracted_with_gaps"
        if gaps
        else "machine_readable_text_extracted",
    }
    manifest["manifest_sha256"] = digest(manifest)
    return manifest


def _pack_text_records(records, encoder, max_tokens):
    """Pack adjacent text/equations/pages while retaining every original locator."""
    packed = []
    for record in records:
        if packed and record["kind"] != "table" and packed[-1]["kind"] != "table":
            previous = packed[-1]
            joined = previous["text"] + "\n" + record["text"]
            if len(encoder.encode(joined, disallowed_special=())) <= max_tokens:
                previous.update(text=joined, source_end=record["source_end"])
                if previous["kind"] != record["kind"] or record["kind"] == "pdf_page":
                    previous["kind"] = "source_text"
                    previous["page"] = None
                previous["source_record_spans"].append(
                    {
                        k: record.get(k)
                        for k in ("source_start", "source_end", "page", "table_id", "record_index")
                    }
                )
                continue
        packed.append(
            {
                **record,
                "source_record_spans": [
                    {
                        k: record.get(k)
                        for k in ("source_start", "source_end", "page", "table_id", "record_index")
                    }
                ],
            }
        )
    return packed


def make_blocks(document: dict, *, max_tokens=5000) -> list[dict]:
    """Split every record without losing characters. No prefix/section ceiling."""
    if max_tokens < 128:
        raise SourceError("block_budget_too_small")
    encoder = tiktoken.get_encoding("cl100k_base")
    blocks = []
    for record in _pack_text_records(document["records"], encoder, max_tokens):
        text = record["text"]
        boundaries = [0] + [m.end() for m in re.finditer(r"\n|[.!?](?=\s)", text)] + [len(text)]
        segments = [
            {"start": record["source_start"] + lo, "end": record["source_start"] + hi}
            for lo, hi in zip(boundaries, boundaries[1:])
            if hi > lo
        ]
        start = 0
        while start < len(text):
            lo, hi = start + 1, len(text)
            # Character boundaries avoid splitting multibyte scientific symbols.
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(encoder.encode(text[start:mid], disallowed_special=())) <= max_tokens:
                    lo = mid
                else:
                    hi = mid - 1
            end = lo
            part = text[start:end]
            position = {
                "source_sha256": record["source_sha256"],
                "start": record["source_start"] + start,
                "end": record["source_start"] + end,
                "parser_version": PARSER_VERSION,
            }
            block = {
                **record,
                "text": part,
                "source_start": position["start"],
                "source_end": position["end"],
                "block_id": "b-" + digest(position)[:24],
                "tokens_common": len(encoder.encode(part, disallowed_special=())),
            }
            block["source_segments"] = [
                s for s in segments if s["end"] > position["start"] and s["start"] < position["end"]
            ]
            # Whole-table headers accompany fragments but are separately labelled context.
            if record["kind"] == "table" and start:
                block["context_note"] = (
                    "Fragment of table; unresolved row/header relations must be retained."
                )
            blocks.append(block)
            start = end
    return blocks


def block_inputs(block: dict, document: dict, *, context_chars=900) -> list[dict]:
    """Bounded exact-source context; every character is still visited as a target."""
    text = "\n".join(r["text"] for r in document["records"])
    lo, hi = block["source_start"], block["source_end"]
    spans = [
        (max(0, lo - context_chars), lo, "preceding_source"),
        (hi, min(len(text), hi + context_chars), "following_source"),
    ]
    if block["kind"] == "table":
        record = next(r for r in document["records"] if r["record_index"] == block["record_index"])
        start, end = record["source_start"], record["source_end"]
        # Context includes the table's beginning and end rather than guessing a
        # header/footnote association from proximity. Model links still need quotes.
        spans += [
            (start, min(start + context_chars, end), "table_beginning"),
            (max(start, end - context_chars), end, "table_ending"),
        ]
    inputs = [{**block, "block_role": "target"}]
    seen = set()
    for start, end, role in spans:
        if end <= start or (start >= lo and end <= hi) or (start, end) in seen:
            continue
        seen.add((start, end))
        intersecting = [
            r for r in document["records"] if r["source_end"] > start and r["source_start"] < end
        ]
        if not intersecting:
            continue
        position = {"source": block["source_sha256"], "start": start, "end": end, "role": role}
        inputs.append(
            {
                "block_id": "context-" + digest(position)[:24],
                "text": text[start:end],
                "source_sha256": block["source_sha256"],
                "source_start": start,
                "source_end": end,
                "kind": "source_context",
                "block_role": "context",
                "context_note": role,
                "page": intersecting[0].get("page") if len(intersecting) == 1 else None,
                "table_id": intersecting[0].get("table_id") if len(intersecting) == 1 else None,
                "source_record_spans": [
                    {
                        k: r.get(k)
                        for k in ("source_start", "source_end", "page", "table_id", "record_index")
                    }
                    for r in intersecting
                ],
            }
        )
    return inputs


def verify_document(document: dict):
    expected = document.get("manifest_sha256")
    body = {k: v for k, v in document.items() if k != "manifest_sha256"}
    if expected != digest(body):
        raise SourceError("document_manifest_hash_mismatch")


def coverage(document: dict, blocks: list[dict], terminal: dict[str, str]) -> dict:
    missing = [
        b["block_id"]
        for b in blocks
        if terminal.get(b["block_id"]) not in {"validated", "empty", "split"}
    ]
    return {
        "source_sha256": document["source_sha256"],
        "input_blocks": len(blocks),
        "uncompleted_blocks": missing,
        "source_gaps": document["gaps"],
        "machine_text_complete": not missing,
        "end_to_end_complete": not missing and not document["gaps"],
        "no_claim_found_allowed": not missing and not document["gaps"],
    }
