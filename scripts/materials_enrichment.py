"""Offline materials enrichment and explicitly requested primary HTML capture.

`plan` verifies an independently pinned snapshot manifest and emits source-pinned
pending candidates plus a field coverage report. `import-candidates` idempotently
imports into a PRIVATE LOCAL candidate ledger, never the canonical database.
`capture-html` fetches an explicit allowed primary-source URL, freezes its bytes
and revision, and produces paragraph/table captures for a reviewed snapshot.
No subcommand reads credentials, connects to the DB, calls an LLM, or computes
scientific properties. Captured publisher text should stay in a private /tmp or
controlled source store; public reports omit excerpts by default.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services.claim_support import is_derived_source_hint  # noqa: E402
from services.material_enrichment import (  # noqa: E402
    AUTHORITY,
    EnrichmentError,
    build_enrichment_report,
    canonical,
    digest,
    pending_tc_records,
    text_digest,
    validate_candidate_identity,
)

SNAPSHOT_VERSION = "materials-enrichment-snapshot/1.0.0"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
ALLOWED_PRIMARY_HOSTS = {"arxiv.org", "journals.aps.org", "link.aps.org"}


def loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EnrichmentError("duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise EnrichmentError("nonfinite_json_number")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def jsonl(path):
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise EnrichmentError("snapshot_file_byte_limit")
    rows = [loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(type(row) is not dict for row in rows):
        raise EnrichmentError("snapshot_object_rows_required")
    return rows


def private_write(path, data):
    """Atomic private output; never overwrite a symlink or grant public rights."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EnrichmentError("output_symlink_refused")
    fd, temporary = tempfile.mkstemp(prefix=".enrichment-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_snapshot(materials_path, sources_path, output_dir, *, source_coverage=None):
    """Freeze explicit local exports; hashing establishes integrity, not authority."""
    output_dir = Path(output_dir)
    material_rows, source_rows = jsonl(Path(materials_path)), jsonl(Path(sources_path))
    # Validate the exact exported shape using the actual extractor.
    build_enrichment_report(material_rows, source_rows, source_coverage=source_coverage)
    files = {}
    for role, rows in (("materials", material_rows), ("sources", source_rows)):
        body = b"".join(canonical(row) + b"\n" for row in rows)
        filename = role + ".jsonl"
        files[role] = {"path": filename, "sha256": hashlib.sha256(body).hexdigest(),
                       "size_bytes": len(body), "rows": len(rows)}
        private_write(output_dir / filename, body)
    manifest = {"version": SNAPSHOT_VERSION, "files": files,
                "source_coverage": source_coverage or {}, "source_reviewed": False, **AUTHORITY}
    private_write(output_dir / "manifest.json", canonical(manifest))
    return digest(manifest)


def load_snapshot(manifest_path, expected_manifest_sha256):
    manifest_path = Path(manifest_path)
    if manifest_path.stat().st_size > 1024 * 1024:
        raise EnrichmentError("snapshot_manifest_byte_limit")
    manifest = loads(manifest_path.read_bytes())
    if digest(manifest) != expected_manifest_sha256:
        raise EnrichmentError("snapshot_manifest_changed")
    if manifest.get("version") != SNAPSHOT_VERSION or set(manifest.get("files", {})) != {"materials", "sources"}:
        raise EnrichmentError("snapshot_manifest_version_or_roles")
    if manifest.get("source_reviewed") is not False or any(manifest.get(k) is not False for k in AUTHORITY):
        raise EnrichmentError("snapshot_cannot_claim_authority")
    captures = {}
    total = 0
    for role, entry in manifest["files"].items():
        if type(entry) is not dict or set(entry) != {"path", "sha256", "size_bytes", "rows"}:
            raise EnrichmentError("snapshot_entry_invalid")
        name = entry["path"]
        if type(name) is not str or Path(name).name != name or not name.endswith(".jsonl"):
            raise EnrichmentError("snapshot_local_file_required")
        path = manifest_path.parent / name
        if path.is_symlink() or path.stat().st_size != entry["size_bytes"] or path.stat().st_size > MAX_BUNDLE_BYTES:
            raise EnrichmentError("snapshot_file_changed")
        body = path.read_bytes()
        total += len(body)
        if total > MAX_BUNDLE_BYTES or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise EnrichmentError("snapshot_file_changed")
        rows = [loads(line) for line in body.splitlines() if line.strip()]
        if len(rows) != entry["rows"] or any(type(row) is not dict for row in rows):
            raise EnrichmentError("snapshot_row_count_changed")
        captures[role] = rows
    return captures["materials"], captures["sources"], manifest.get("source_coverage", {})


def import_candidates(report, ledger_path):
    """Replay-safe private local ledger. This is not a production data importer."""
    if report.get("report_sha256") != digest({k: v for k, v in report.items() if k != "report_sha256"}):
        raise EnrichmentError("enrichment_report_changed")
    rows = report.get("candidates")
    if type(rows) is not list:
        raise EnrichmentError("candidate_rows_required")
    for candidate in rows:
        validate_candidate_identity(candidate)
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.is_symlink():
        raise EnrichmentError("candidate_ledger_symlink_refused")
    # Lock the dedicated sibling rather than the file that atomic replace changes.
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    if lock_path.is_symlink():
        raise EnrichmentError("candidate_lock_symlink_refused")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = jsonl(ledger_path) if ledger_path.exists() else []
        by_id = {}
        for candidate in existing:
            validate_candidate_identity(candidate)
            if candidate["candidate_id"] in by_id:
                raise EnrichmentError("duplicate_candidate_in_ledger")
            by_id[candidate["candidate_id"]] = candidate
        inserted = reused = 0
        for candidate in rows:
            key = candidate["candidate_id"]
            if key in by_id:
                if canonical(candidate) != canonical(by_id[key]):
                    raise EnrichmentError("candidate_identity_conflict")
                reused += 1
            else:
                by_id[key] = candidate
                inserted += 1
        if inserted:
            private_write(ledger_path, b"".join(canonical(by_id[key]) + b"\n" for key in sorted(by_id)))
        return {"inserted": inserted, "reused": reused, "ledger_candidates": len(by_id),
                "storage": "private_local_candidate_ledger", **AUTHORITY}


class _Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        if self.tag in {"script", "style", "nav", "footer", "button", "noscript"}:
            return ""
        if self.tag == "math" and self.attrs.get("alttext"):
            return self.attrs["alttext"]
        result = "".join(child if isinstance(child, str) else child.text() for child in self.children)
        return result + ("\n" if self.tag in {"p", "tr", "section", "div", "h1", "h2", "h3", "h4", "h5", "h6"} else " ")

    def descendants(self, tags):
        for child in self.children:
            if isinstance(child, _Node):
                if child.tag in tags:
                    yield child
                yield from child.descendants(tags)


class PrimaryHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", [])
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(_Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def _clean(text):
    text = re.sub(r"\\(?:mathrm|text|ce|rm|operatorname)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace(r"\AA", "Å").replace(r"\approx", "≈").replace(r"\sim", "~")
    text = re.sub(r"[${}_]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def html_captures(payload: bytes, *, paper_id, source_url, source_revision):
    """Capture exact parsed text and table coordinates; never infer publication time."""
    if type(payload) is not bytes or len(payload) > 8 * 1024 * 1024:
        raise EnrichmentError("primary_html_byte_limit")
    parser = PrimaryHTMLParser()
    parser.feed(payload.decode("utf-8"))
    documents = list(parser.root.descendants({"article"}))
    root = documents[0] if documents else parser.root
    capture_hash = hashlib.sha256(payload).hexdigest()
    captures = []
    for ordinal, node in enumerate(root.descendants({"p", "table", "figcaption"})):
        ancestors, parent = [], node.parent
        while parent is not None:
            ancestors.append(parent.tag)
            parent = parent.parent
        if any(tag in {"table", "nav", "footer", "figcaption"} for tag in ancestors):
            continue
        node_id = node.attrs.get("id") or "block-" + str(ordinal)
        text = _clean(node.text())
        if not text:
            continue
        if is_derived_source_hint(section=node.attrs.get("data-section"), paper_id=paper_id, text=text):
            continue
        source = {"id": f"primary:{paper_id}:{ordinal}", "paper_id": paper_id, "text": text,
                  "content_sha256": text_digest(text), "source_revision": source_revision,
                  "kind": "table" if node.tag == "table" else "original_passage",
                  "locator": {"xml_xpath": "//*[@id='" + node_id + "']"} if "id" in node.attrs else {"section": node_id},
                  "source_url": source_url, "capture_sha256": capture_hash,
                  "captured_at": datetime.now(UTC).isoformat(), "source_status": "unknown"}
        if node.tag == "table":
            table_rows = []
            for row in node.descendants({"tr"}):
                cells = [_clean(cell.text()) for cell in row.descendants({"th", "td"})]
                if cells:
                    table_rows.append(cells)
            if table_rows:
                # Only rectangular tables with a formula header are eligible for
                # deterministic column extraction. Spanning headings stay raw.
                width = max(len(row) for row in table_rows)
                header_index = next((i for i, row in enumerate(table_rows) if len(row) == width and any(re.search(r"[A-Z][a-z]?\d", cell) for cell in row)), None)
                if header_index is not None:
                    headers = table_rows[header_index]
                    # Header and caption spans support thermal rows whose unit
                    # is printed in the row label, outside the value cell.
                    text, caption_cell, header_cells = "", None, []
                    captions = list(node.descendants({"caption"}))
                    if len(captions) == 1 and _clean(captions[0].text()):
                        caption_text = _clean(captions[0].text())
                        text = caption_text + "\n"
                        caption_cell = {"text": caption_text, "char_start": 0, "char_end": len(caption_text)}
                    for i, header in enumerate(headers):
                        if i:
                            text += " | "
                        start = len(text)
                        text += header
                        header_cells.append({"text": header, "char_start": start, "char_end": len(text)})
                    text += "\n"
                    captured_rows = []
                    for cells in table_rows[header_index+1:]:
                        if len(cells) != width:
                            continue
                        captured_cells = []
                        for i, cell in enumerate(cells):
                            if i:
                                text += " | "
                            start = len(text)
                            # Empty cells require an actual textual placeholder,
                            # excluded later, keeping nonempty spans auditable.
                            cell = cell or "—"
                            text += cell
                            captured_cells.append({"text": cell, "char_start": start, "char_end": len(text)})
                        text += "\n"
                        captured_rows.append({"label": cells[0], "cells": captured_cells})
                    table = {"headers": headers, "rows": captured_rows}
                    rectangular = all(len(row) == width for row in table_rows[header_index:])
                    unspanned = all(cell.attrs.get("colspan", "1") == "1" and cell.attrs.get("rowspan", "1") == "1"
                                   for cell in node.descendants({"th", "td"}))
                    if rectangular and unspanned and all(headers) and not list(node.descendants({"table"})):
                        table["header_cells"] = header_cells
                        if caption_cell:
                            table["caption"] = caption_cell
                    source.update(text=text, content_sha256=text_digest(text), table=table)
                    source["locator"] = {"table": node_id}
        captures.append(source)
    return captures


def capture_primary_html(url, *, paper_id, source_revision, output_dir):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_PRIMARY_HOSTS or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise EnrichmentError("explicit_allowed_primary_https_url_required")
    # Redirects are revalidated before each request. urllib's automatic redirect
    # handling is disabled to prevent a primary host becoming an arbitrary URL.
    from urllib.error import HTTPError
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(NoRedirect())
    for _ in range(4):
        current = urlparse(url)
        if current.scheme != "https" or current.hostname not in ALLOWED_PRIMARY_HOSTS or current.username or current.password or current.port not in {None, 443}:
            raise EnrichmentError("primary_redirect_refused")
        request = Request(url, headers={"User-Agent": "SCLib-source-capture/1.0 (scientific metadata curation)", "Accept": "text/html"})
        try:
            with opener.open(request, timeout=30) as response:
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise EnrichmentError("primary_html_content_type_required")
                payload = response.read(8 * 1024 * 1024 + 1)
            break
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308} or not exc.headers.get("Location"):
                raise EnrichmentError("primary_source_fetch_failed") from None
            url = urljoin(url, exc.headers["Location"])
    else:
        raise EnrichmentError("primary_redirect_limit")
    captures = html_captures(payload, paper_id=paper_id, source_url=url, source_revision=source_revision)
    output_dir = Path(output_dir)
    private_write(output_dir / "source.html", payload)
    private_write(output_dir / "sources.jsonl", b"".join(canonical(source) + b"\n" for source in captures))
    manifest = {"version": "primary-source-html-capture/1.0.0", "paper_id": paper_id,
                "source_url": url, "source_revision": source_revision, "capture_sha256": hashlib.sha256(payload).hexdigest(),
                "source_captures": len(captures), "source_reviewed": False, "rights_reviewed": False, **AUTHORITY}
    private_write(output_dir / "capture.json", canonical(manifest))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--materials", required=True, type=Path)
    snapshot.add_argument("--sources", required=True, type=Path)
    snapshot.add_argument("--coverage", type=Path)
    snapshot.add_argument("--output-dir", required=True, type=Path)
    plan = sub.add_parser("plan")
    plan.add_argument("--manifest", required=True, type=Path)
    plan.add_argument("--expected-manifest-sha256", required=True)
    plan.add_argument("--output-dir", required=True, type=Path)
    plan.add_argument("--private-excerpts", action="store_true")
    imported = sub.add_parser("import-candidates")
    imported.add_argument("--report", required=True, type=Path)
    imported.add_argument("--ledger", required=True, type=Path)
    captured = sub.add_parser("capture-html")
    captured.add_argument("--paper-id", required=True)
    captured.add_argument("--url", required=True)
    captured.add_argument("--source-revision", required=True)
    captured.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            coverage = loads(args.coverage.read_bytes()) if args.coverage else {}
            result = {"manifest_sha256": create_snapshot(args.materials, args.sources, args.output_dir, source_coverage=coverage), **AUTHORITY}
        elif args.command == "plan":
            materials, sources, coverage = load_snapshot(args.manifest, args.expected_manifest_sha256)
            private = build_enrichment_report(materials, sources, source_coverage=coverage, include_evidence_text=True)
            # Full contexts are private; default published report is text-free.
            report = private if args.private_excerpts else build_enrichment_report(materials, sources, source_coverage=coverage, include_evidence_text=False)
            private_write(args.output_dir / "report.json", canonical(report))
            private_write(args.output_dir / "pending_tc_records.jsonl", b"".join(canonical(row) + b"\n" for row in pending_tc_records(private["candidates"])))
            if args.private_excerpts:
                private_write(args.output_dir / "candidates.jsonl", b"".join(canonical(row) + b"\n" for row in private["candidates"]))
            result = {"report_sha256": report["report_sha256"], "counts": report["counts"], **AUTHORITY}
        elif args.command == "import-candidates":
            result = import_candidates(loads(args.report.read_bytes()), args.ledger)
        else:
            result = capture_primary_html(args.url, paper_id=args.paper_id, source_revision=args.source_revision, output_dir=args.output_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (EnrichmentError, OSError, ValueError, UnicodeError):
        # Network exceptions and malformed inputs may contain source contents or
        # arbitrary user URLs. Use a static error rather than echoing them.
        print("Materials enrichment failed input validation or source capture; no canonical records were changed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
