#!/usr/bin/env python3
"""Resolve held arXiv PDF wrappers from already captured original archives.

No download or model call. No archive path is extracted to a filesystem path:
only referenced regular PDF members are copied to their content hash. Old
bundles and model attempts stay immutable. Publication/visual coverage remains
unverified, and supplement roles inferred from filenames are explicitly noted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tarfile
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import canonical  # noqa: E402
from ingestion.materials_ner.sources import (MAX_SOURCE_BYTES, load_bundle, parse_local,
    private_write, save_bundle, sha)  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.absolute()
    path = root / "source-body-resolution-queue.json"
    state = json.loads(path.read_bytes())
    for work, held in state["held_original_bundles"].items():
        if held.get("resolution", {}).get("state") == "resolved":
            continue
        bundle = load_bundle(root / "bundles" / f'{held["bundle_sha256"]}.json')
        source = bundle.documents[0]
        archive_path = root / "sources" / source.source_sha256
        if sha(archive_path.read_bytes()) != source.source_sha256:
            raise ValueError("original archive hash mismatch")
        references = list(dict.fromkeys(re.findall(
            r"\\includepdf(?:\[[^\]]*\])?\s*\{([^}]+)\}",
            "\n".join(block.text for block in bundle.blocks))))
        if not 1 <= len(references) <= 25:
            raise ValueError("no bounded PDF references")
        merged = bundle.model_copy(deep=True)
        merged.documents, merged.blocks = [], []
        members, hashes, total = [], set(), 0
        with tarfile.open(archive_path, "r:*") as archive:
            for reference in references:
                member = archive.getmember(reference)
                total += member.size
                if (not member.isfile() or not reference.lower().endswith(".pdf")
                        or member.size > MAX_SOURCE_BYTES or total > MAX_SOURCE_BYTES):
                    raise ValueError("PDF member outside source bounds")
                stream = archive.extractfile(member)
                raw = stream.read(MAX_SOURCE_BYTES + 1)
                if len(raw) != member.size or not raw.startswith(b"%PDF"):
                    raise ValueError("invalid PDF member capture")
                member_hash = sha(raw)
                target = root / "sources" / member_hash
                if target.exists():
                    if sha(target.read_bytes()) != member_hash:
                        raise ValueError("immutable PDF capture collision")
                else:
                    private_write(target, raw)
                members.append({"member": reference, "sha256": member_hash, "bytes": len(raw)})
                if member_hash in hashes:
                    continue
                hashes.add(member_hash)
                part = parse_local(target, work_id=work, title=bundle.title,
                    source_uri=source.source_uri + "#archive_member=" + quote(reference, safe=""),
                    publication_version=source.publication_version, family=bundle.family,
                    processing_permission=source.processing_permission)
                if "suppl" in reference.lower():
                    part.documents[0].role = "supplement"
                    merged.acquisition_notes.append(
                        "Supplement role inferred from archive filename; completeness unverified: " + reference)
                merged.documents.extend(part.documents)
                merged.blocks.extend(part.blocks)
                merged.acquisition_notes.extend(part.acquisition_notes)
        merged.supplement_status = "not_checked"
        merged.acquisition_notes.append("PDF_WRAPPER_RESOLUTION " + canonical({
            "parent_bundle_sha256": held["bundle_sha256"],
            "archive_sha256": source.source_sha256, "members": members,
            "wrapper_page_selection_applied": False,
            "scope": "full embedded PDF members; publication rendering and visual coverage unverified"}))
        new_hash, _ = save_bundle(root, merged)
        held["resolution"] = {"state": "resolved", "new_bundle_sha256": new_hash,
                              "members": members, "blocks": len(merged.blocks),
                              "text_characters": sum(len(b.text) for b in merged.blocks),
                              "scientific_acceptance": False}
        private_write(path, canonical(state).encode())
        print(canonical({"work_id": work, **held["resolution"]}), flush=True)
    state.update(state="resolved", completed_at=datetime.now(timezone.utc).isoformat(),
                 model_calls=0, network_calls=0)
    private_write(path, canonical(state).encode())


if __name__ == "__main__":
    main()
