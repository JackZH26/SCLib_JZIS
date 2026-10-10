"""Prepare version-pinned public arXiv sources; never label gold or freeze cases."""

from __future__ import annotations

import hashlib
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx

from .blocks import make_blocks, parse_source
from .contract import digest


class AbstractMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.licenses, self.html_links = {}, [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").startswith("citation_"):
            self.meta[attrs["name"]] = attrs.get("content", "")
        if tag == "a" and attrs.get("title") == "Rights to this article":
            self.licenses.append(attrs.get("href"))
        if tag == "a" and "/html/" in attrs.get("href", ""):
            self.html_links.append(attrs["href"])


class ArxivSources:
    def __init__(self, root: Path, *, interval_seconds=3.0, client=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.client = client or httpx.Client(
            timeout=90,
            follow_redirects=True,
            headers={
                "User-Agent": "SCLib-research-pilot/3.0 (50-paper bounded source preparation)"
            },
        )
        self.interval, self.last_request = interval_seconds, 0.0

    def fetch(self, url: str, path: Path, *, limit=64 * 1024**2):
        if path.exists():
            return path.read_bytes()
        wait = self.interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.monotonic()
        with self.client.stream("GET", url) as response:
            response.raise_for_status()
            if response.url.host not in {"arxiv.org", "export.arxiv.org"}:
                raise ValueError("source_redirect_outside_arxiv")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError("source_download_size_limit")
                chunks.append(chunk)
            data = b"".join(chunks)
        if not data:
            raise ValueError("source_download_empty")
        # No partial file can masquerade as a completed capture after interruption.
        import os
        import tempfile

        fd, temporary = tempfile.mkstemp(prefix=".source-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        finally:
            os.unlink(temporary)
        return data

    def prepare(self, paper: dict):
        identifier = paper["paper_id"].removeprefix("arxiv:")
        if not re.fullmatch(r"\d{4}\.\d{4,5}", identifier):
            raise ValueError("pilot_requires_modern_arxiv_identifier")
        directory = self.root / identifier
        directory.mkdir(exist_ok=True, mode=0o700)
        abstract = self.fetch(
            f"https://arxiv.org/abs/{identifier}", directory / "abstract.html", limit=1024**2
        )
        text = abstract.decode("utf-8")
        parser = AbstractMetadata()
        parser.feed(text)
        if parser.meta.get("citation_arxiv_id") != identifier:
            raise ValueError("abstract_paper_identity_mismatch")
        versions = [int(v) for v in re.findall(r"\[v(\d+)\]", text)]
        if not versions:
            raise ValueError("source_version_unresolved")
        version = identifier + "v" + str(max(versions))
        # Fetch the exact version's abstract to bind its title and license as well.
        pinned = self.fetch(
            f"https://arxiv.org/abs/{version}", directory / f"{version}.abs.html", limit=1024**2
        )
        pinned_parser = AbstractMetadata()
        pinned_parser.feed(pinned.decode("utf-8"))
        license_url = pinned_parser.licenses[0] if len(set(pinned_parser.licenses)) == 1 else None
        pdf_path = directory / f"{version}.pdf"
        pdf = self.fetch(f"https://arxiv.org/pdf/{version}", pdf_path)
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("pdf_endpoint_did_not_return_pdf")
        source_path = pdf_path
        if parser.html_links:
            try:
                html_path = directory / f"{version}.html"
                html = self.fetch(f"https://arxiv.org/html/{version}", html_path)
                if b"ltx_document" in html or b"ltx_article" in html:
                    source_path = html_path
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {404, 410}:
                    raise
        document = parse_source(source_path, source_id=paper["paper_id"] + ":" + version)
        body = {
            **paper,
            "source_version": version,
            "source_url": f"https://arxiv.org/{'html' if source_path.suffix == '.html' else 'pdf'}/{version}",
            "source_license": license_url or "unresolved",
            "main_text_sha256": document["source_sha256"],
            "content_manifest_sha256": document["manifest_sha256"],
            "source_format": document["source_format"],
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "source_bytes": document["source_bytes"],
            "coverage": {
                "parser_status": document["coverage_status"],
                "text_records": len(document["records"]),
                "planned_blocks": len(make_blocks(document)),
                "source_gaps": document["gaps"],
                "ner_status": "not_run",
            },
            "supplement_status": "pending_source_scope_review",
            "transfer_allowed": False,
            "cloud_inference_allowed": False,
            "license_review_status": "recorded_not_adjudicated",
            "verified_case_tags": [],
            "verified_independent_materials": [],
            "work_identity_status": "external_arxiv_verified_sclib_work_mapping_pending",
        }
        return body, document, source_path


def prepare_corpus(selection, root: Path, *, progress=print):
    from .cli import write

    client = ArxivSources(root / "sources")
    papers, failures = [], []
    try:
        for index, paper in enumerate(selection["papers"], 1):
            try:
                metadata, document, source = client.prepare(paper)
                document_path = (
                    root
                    / "documents"
                    / (
                        metadata["source_version"]
                        + "."
                        + document["parser_version"].replace("/", "-")
                        + ".json"
                    )
                )
                if not document_path.exists():
                    write(document_path, document)
                elif digest(__import__("json").loads(document_path.read_bytes())) != digest(
                    document
                ):
                    raise ValueError("existing_document_capture_conflict")
                metadata["private_document_path"] = str(document_path)
                metadata["private_source_path"] = str(source)
                content_path = root / "content-addressed" / (document["manifest_sha256"] + ".json")
                if not content_path.exists():
                    write(content_path, document)
                elif digest(__import__("json").loads(content_path.read_bytes())) != digest(
                    document
                ):
                    raise ValueError("existing_content_addressed_document_conflict")
                papers.append(metadata)
                progress(
                    {
                        "paper_id": paper["paper_id"],
                        "index": index,
                        "status": "source_prepared",
                        "format": metadata["source_format"],
                        "blocks": metadata["coverage"]["planned_blocks"],
                    }
                )
            except (ValueError, httpx.HTTPError, OSError) as exc:
                failures.append({"paper_id": paper["paper_id"], "error_class": type(exc).__name__})
                progress(
                    {
                        "paper_id": paper["paper_id"],
                        "index": index,
                        "status": "source_failed",
                        "error_class": type(exc).__name__,
                    }
                )
    finally:
        client.client.close()
    body = {
        "version": "materials-ner-corpus/1",
        "status": "prepared_pending_review",
        "selection_sha256": digest(selection),
        "papers": papers,
        "source_failures": failures,
        "scientific_acceptance": False,
    }
    return {**body, "manifest_sha256": digest(body)}


def stage_development(manifest, root: Path, *, sources=None, progress=lambda row: None):
    """Fetch the original pinned development captures on the private node.

    This does not fetch the latest version, grant cloud permissions, resolve
    supplements, or turn a prepared candidate set into a frozen experiment.
    """
    from copy import deepcopy
    from .cli import write

    owned = sources is None
    sources = sources or ArxivSources(root / "sources")
    papers = deepcopy(manifest["papers"])
    failures, staged = [], []
    try:
        for paper in papers:
            if paper["split"] != "development":
                continue
            try:
                identifier = paper["paper_id"].removeprefix("arxiv:")
                version = paper["source_version"]
                fmt = paper["source_format"]
                if (
                    not re.fullmatch(r"\d{4}\.\d{4,5}", identifier)
                    or not re.fullmatch(re.escape(identifier) + r"v[1-9]\d*", version)
                    or fmt not in {"pdf", "html"}
                    or paper["source_url"] != f"https://arxiv.org/{fmt}/{version}"
                ):
                    raise ValueError("development_source_must_be_original_pinned_arxiv_url")
                directory = root / "sources" / identifier
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = directory / f"{version}.{fmt}"
                data = sources.fetch(paper["source_url"], path)
                if (
                    len(data) != paper["source_bytes"]
                    or hashlib.sha256(data).hexdigest() != paper["main_text_sha256"]
                ):
                    raise ValueError("development_original_source_hash_mismatch")
                document = parse_source(path, source_id=paper["paper_id"] + ":" + version)
                if document["manifest_sha256"] != paper["content_manifest_sha256"]:
                    raise ValueError("development_parsed_capture_differs_from_prepared_input")
                document_path = root / "documents" / (document["manifest_sha256"] + ".json")
                if not document_path.exists():
                    write(document_path, document)
                elif digest(__import__("json").loads(document_path.read_bytes())) != digest(
                    document
                ):
                    raise ValueError("existing_development_document_conflict")
                paper["private_document_path"] = str(document_path)
                paper["private_source_path"] = str(path)
                staged.append(paper["paper_id"])
                progress({"paper_id": paper["paper_id"], "status": "development_source_staged"})
            except (ValueError, KeyError, httpx.HTTPError, OSError) as exc:
                code = str(exc) if type(exc) is ValueError else type(exc).__name__
                failures.append({"paper_id": paper["paper_id"], "error": code})
                progress({"paper_id": paper["paper_id"], "status": "development_source_failed"})
    finally:
        if owned:
            sources.client.close()
    body = {
        "version": "materials-ner-development-staging/1",
        "status": "development_staged_pending_review",
        "prepared_input_manifest_sha256": manifest["manifest_sha256"],
        "papers": papers,
        "staged_development_papers": staged,
        "source_failures": failures,
        "source_scope_frozen": False,
        "scientific_acceptance": False,
    }
    return {**body, "manifest_sha256": digest(body)}
