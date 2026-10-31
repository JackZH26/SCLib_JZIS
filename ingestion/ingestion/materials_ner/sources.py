"""Immutable source bundles, with explicit scope and no derived-text recycling."""
from __future__ import annotations

import hashlib
import gzip
import io
import importlib.metadata
import logging
import os
from pathlib import Path
import tarfile
import tempfile

from pydantic import Field
from typing import Literal

from .contract import StrictModel, canonical, digest

PARSER_VERSION = "materials-source-bundle/1.2.1"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
TEXT_ENCODINGS = ("utf-8", "cp1252", "iso-8859-1", "iso-8859-15")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def private_write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ner-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Block(StrictModel):
    id: str
    document_id: str
    ordinal: int
    locator: str
    text: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Document(StrictModel):
    id: str
    source_uri: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_kind: Literal["original_text", "original_pdf", "original_tex", "original_passage", "abstract"]
    role: Literal["main", "supplement", "abstract"]
    publication_version: str | None
    version_status: Literal["verified", "unresolved"]
    processing_permission: Literal["allowed", "unresolved", "restricted"]
    redistribution_permission: Literal["allowed", "unresolved", "restricted"]
    coverage: Literal["complete_document", "partial", "abstract_only"]
    parser: str


class Bundle(StrictModel):
    version: Literal["materials-source-bundle/1"]
    work_id: str
    title: str
    family: str | None
    source_status: Literal["current", "unresolved", "retracted", "corrected"]
    supplement_status: Literal["included", "not_available", "not_checked", "not_applicable"]
    documents: list[Document]
    blocks: list[Block]
    acquisition_notes: list[str]


def verify_bundle(bundle: Bundle):
    documents = {item.id: item for item in bundle.documents}
    if not documents or len(documents) != len(bundle.documents):
        raise ValueError("source document inventory is empty or ambiguous")
    if not bundle.blocks or len({block.id for block in bundle.blocks}) != len(bundle.blocks):
        raise ValueError("source block inventory is empty or ambiguous")
    for block in bundle.blocks:
        if block.document_id not in documents or sha(block.text.encode()) != block.sha256:
            raise ValueError("source block integrity failure")
    if {block.document_id for block in bundle.blocks} != set(documents):
        raise ValueError("an empty document must remain an acquisition failure")
    if bundle.supplement_status == "included" and not any(d.role == "supplement" for d in documents.values()):
        raise ValueError("supplement declared included without a supplement artifact")


def check_admission(bundle: Bundle) -> list[str]:
    verify_bundle(bundle)
    reasons = []
    if any(doc.processing_permission != "allowed" for doc in bundle.documents):
        reasons.append("source_processing_permission_unresolved")
    if all(doc.source_kind == "abstract" for doc in bundle.documents):
        reasons.append("abstract_only_not_full_paper_ner")
    if bundle.source_status == "retracted":
        reasons.append("retracted_source_requires_separate_historical_task")
    return reasons


def make_blocks(document_id: str, segments: list[tuple[str, str]]) -> list[Block]:
    # Preserve each source segment, including all whitespace. No text truncation.
    return [
        Block(id=f"{document_id}:b{index:05d}", document_id=document_id, ordinal=index,
              locator=location, text=text, sha256=sha(text.encode()))
        for index, (location, text) in enumerate(segments) if text.strip()
    ]


def parse_local(path: Path, *, work_id: str, title: str, source_uri: str,
                publication_version: str | None = None, family: str | None = None,
                processing_permission: str = "unresolved", text_encoding="utf-8", pdf_text_mode="layout") -> Bundle:
    if pdf_text_mode not in {"layout", "plain"}:
        raise ValueError("unsupported PDF text mode")
    if text_encoding not in TEXT_ENCODINGS:
        raise ValueError("encoding needs an explicit supported decoder")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source byte bound exceeded or empty")
    source_hash = sha(raw)
    segments = []
    notes = ["Supplement availability has not been checked.",
             "Source byte integrity does not establish publication version or scientific validity."]
    coverage = "complete_document"
    if text_encoding != "utf-8":
        notes.append(f"Explicit operator-selected text decoder: {text_encoding}; original bytes retained.")
    if raw.startswith(b"%PDF"):
        from pypdf import PdfReader
        pdf_warnings = []
        class WarningCapture(logging.Handler):
            def emit(self, record):
                pdf_warnings.append(record.getMessage())
        logger = logging.getLogger("pypdf")
        handler, propagate = WarningCapture(), logger.propagate
        logger.addHandler(handler)
        logger.propagate = False
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise ValueError("encrypted source needs an authorized text representation")
            empty_pages = []
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text(extraction_mode=pdf_text_mode)
                if not text.strip():
                    empty_pages.append(number)
                segments.append((f"pdf_page:{number}", text))
        finally:
            logger.removeHandler(handler)
            logger.propagate = propagate
        kind, parser = "original_pdf", "pypdf-" + pdf_text_mode
        coverage = "partial"
        notes.append("PDF text is a proposal representation; tables/equations require visual verification.")
        for package in ("pypdf", "fonttools"):
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = "not_installed"
            notes.append(f"PDF parser dependency: {package}={version}")
        if pdf_warnings:
            notes.append(f"PDF extraction warnings: {len(pdf_warnings)}; SHA256={digest(pdf_warnings)}")
            if any("Rotated" in warning for warning in pdf_warnings):
                notes.append("Rotated PDF text requires visual coverage review.")
            if any("fontTools" in warning or "encoding" in warning for warning in pdf_warnings):
                notes.append("PDF font encoding requires reparse/review.")
        if empty_pages:
            notes.append(f"Pages without recoverable text: {empty_pages}; OCR required.")
    elif tarfile.is_tarfile(io.BytesIO(raw)):
        total = 0
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            for member in archive:
                if not member.isfile() or not member.name.lower().endswith((".tex", ".txt", ".bbl")):
                    continue
                total += member.size
                if member.size > 8 * 1024 * 1024 or total > MAX_SOURCE_BYTES:
                    raise ValueError("expanded text exceeds archive bound")
                stream = archive.extractfile(member)
                text = stream.read().decode(text_encoding, errors="strict")
                segments.append((f"archive_member:{member.name}", text))
        kind, parser = "original_tex", "raw-tex-members"
        coverage = "partial"
        notes.append("All text members retained; main-file/SI relationships need source review.")
        notes.append("Archive figures and rendered tables/equations have not been visually verified.")
        empty_pages = []
    elif raw.startswith(b"\x1f\x8b"):
        # arXiv's .tar.gz path can contain one gzipped TeX file instead of a tar archive.
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(MAX_SOURCE_BYTES + 1)
        if len(expanded) > MAX_SOURCE_BYTES:
            raise ValueError("expanded text exceeds gzip bound")
        segments = [("gzip_member:0", expanded.decode(text_encoding, errors="strict"))]
        kind, parser, empty_pages = "original_tex", "raw-gzip-tex", []
        coverage = "partial"
        notes.append("Rendered TeX, figures and external dependencies require source review.")
    else:
        segments = [("text:0", raw.decode(text_encoding, errors="strict"))]
        kind, parser, empty_pages = "original_text", "decoded-exact", []
    identifier = "doc:" + source_hash[:20]
    document = Document(
        id=identifier, source_uri=source_uri, source_sha256=source_hash, source_kind=kind,
        role="main", publication_version=publication_version,
        # An operator-supplied version label is not a verified capture receipt.
        version_status="unresolved", processing_permission=processing_permission,
        redistribution_permission="unresolved",
        coverage=coverage, parser=f"{PARSER_VERSION}:{parser}:{text_encoding}",
    )
    bundle = Bundle(version="materials-source-bundle/1", work_id=work_id, title=title,
                    family=family, source_status="unresolved", supplement_status="not_checked",
                    documents=[document], blocks=make_blocks(identifier, segments),
                    acquisition_notes=notes)
    verify_bundle(bundle)
    return bundle


def inspect_chunks(chunks: list[dict]) -> dict:
    """Classify text provenance before allowing it near an extraction provider.

    Embeddings alone are never a source. Unattributed legacy chunks do not
    become original prose merely because they contain scientifically plausible text.
    """
    counts: dict[str, int] = {}
    usable, rejected = [], []
    for row in chunks:
        evidence = row.get("evidence") or {}
        kind = evidence.get("chunk_kind", row.get("chunk_kind", "legacy_unknown"))
        section = str(row.get("section", "")).lower()
        if section == "facts" or "extracted" in section and ("fact" in section or "material" in section):
            kind = "derived_fact"
        elif section == "abstract" and kind == "legacy_unknown":
            kind = "abstract"
        counts[kind] = counts.get(kind, 0) + 1
        text = row.get("text")
        reason = None
        if kind != "original_passage":
            reason = {"derived_fact": "circular_old_ner_output",
                      "abstract": "abstract_only",
                      "retained_legacy_snapshot": "derived_or_unresolved_legacy"}.get(
                          kind, "original_source_unproven")
        elif not isinstance(text, str) or not text:
            reason = "text_unavailable_embedding_is_not_text"
        elif evidence.get("content_sha256") != sha(text.encode()):
            reason = "content_hash_mismatch"
        elif not evidence.get("source_capture_id") or not evidence.get("source_locator"):
            reason = "original_capture_or_locator_missing"
        elif evidence.get("permission_status") != "allowed":
            reason = "processing_permission_unresolved"
        elif evidence.get("currentness") != "current":
            reason = "source_currentness_unresolved"
        if reason:
            rejected.append({"chunk_id": row.get("id"), "reason": reason})
        else:
            usable.append(row.get("id"))
    return {"schema": "materials-chunk-admission/1", "total": len(chunks), "kinds": counts,
            "usable_original_passages": usable, "rejected": rejected,
            "full_paper_coverage_verified": False,
            "conclusion": "partial_source_only" if usable else "needs_original_source",
            "scientific_acceptance": False}


def save_bundle(root: Path, bundle: Bundle) -> tuple[str, Path]:
    verify_bundle(bundle)
    body = bundle.model_dump()
    identifier = digest(body)
    path = root / "bundles" / f"{identifier}.json"
    raw = canonical(body).encode()
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("immutable source bundle collision")
    if not path.exists():
        private_write(path, raw)
    return identifier, path


def load_bundle(path: Path) -> Bundle:
    bundle = Bundle.model_validate_json(path.read_bytes())
    verify_bundle(bundle)
    return bundle
