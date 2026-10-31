"""Lossless original-text windows with explicit coverage, context and provenance."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from .contract import canonical, digest
from .sources import Block, Bundle, private_write, save_bundle, sha

WINDOW_VERSION = "materials-original-windows/2"
ADJACENT_WINDOW_VERSION = "materials-original-windows/3"


def spans(text: str, max_chars=4000):
    """Non-overlapping targets cover every character; dense tables get <=3 rows."""
    if not 1000 <= max_chars <= 12000:
        raise ValueError("invalid window size")
    start, end, table_rows = 0, 0, 0
    for line in text.splitlines(keepends=True):
        if end > start and end - start + len(line) > max_chars:
            yield start, end
            start, table_rows = end, 0
        end += len(line)
        while end - start > max_chars:
            yield start, start + max_chars
            start += max_chars
        if "&" in line and re.search(r"\d", line) and ("\\\\" in line or r"\tabularnewline" in line):
            table_rows += 1
        if table_rows >= 3:
            yield start, end
            start, table_rows = end, 0
    if end > start:
        yield start, end


def make_windows(root: Path, parent: Bundle, *, max_chars=4000, adjacent_pages=False, context_chars=1600):
    parent_hash = digest(parent.model_dump())
    if any(note.startswith("SOURCE_WINDOW ") for note in parent.acquisition_notes):
        raise ValueError("cannot recursively window an existing window")
    if adjacent_pages and not 200 <= context_chars <= 4000:
        raise ValueError("invalid adjacent context size")
    window_version = ADJACENT_WINDOW_VERSION if adjacent_pages else WINDOW_VERSION
    pages = {}
    if adjacent_pages:
        for block in parent.blocks:
            match = re.fullmatch(r"pdf_page:(\d+)", block.locator)
            if not match: continue
            key = (block.document_id, int(match[1]))
            if key in pages: raise ValueError("ambiguous PDF page context")
            pages[key] = block
    records, excluded = [], []
    for block in parent.blocks:
        if block.locator.lower().endswith(".bbl"):
            excluded.append({"block_id": block.id, "classification": "bibliography_context_only",
                             "sha256": block.sha256})
            continue
        offsets = list(spans(block.text, max_chars))
        if "".join(block.text[a:b] for a, b in offsets) != block.text:
            raise ValueError("window coverage gap")
        for start, end in offsets:
            records.append({"block": block, "start": start, "end": end})
    manifest = {"schema": window_version, "parent_bundle_sha256": parent_hash,
                "work_id": parent.work_id, "target_characters": sum(r["end"] - r["start"] for r in records),
                "bibliography_blocks": excluded, "windows": [],
                "all_nonbibliography_text_covered": True,
                "figure_table_visual_coverage_verified": False}
    if adjacent_pages:
        manifest["adjacent_page_context"] = {"max_chars_per_neighbor": context_chars,
            "same_document_only": True, "target_boundary_only": True, "counts_as_target_coverage": False}
    for index, record in enumerate(records):
        block, start, end = record["block"], record["start"], record["end"]
        context_spans = [(0, min(1800, len(block.text))), (max(0, start - 1200), start),
                         (end, min(len(block.text), end + 600))]
        table_start = block.text.rfind(r"\begin{tabular", 0, start)
        table_end = block.text.rfind(r"\end{tabular", 0, start)
        if table_start > table_end:
            context_spans.append((table_start, min(start, table_start + 1100)))
        # Context supplies surrounding text, not a second alias of TARGET.
        # Subtract the target interval, then merge overlap between contexts.
        surrounding=[]
        for a,b in context_spans:
            surrounding.extend((left,right) for left,right in
                ((a,min(b,start)),(max(a,end),b)) if right>left)
        merged=[]
        for a,b in sorted(surrounding):
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
            else:merged.append((a,b))
        pieces = [("target", start, end)]
        pieces.extend((f"context-{i}", a, b) for i, (a, b) in enumerate(merged))
        selected = [Block(id=f"{block.id}:w{index}:{role}", document_id=block.document_id,
                          ordinal=i, locator=f"{role}:{block.locator}:chars[{a}:{b}]",
                          text=block.text[a:b], sha256=sha(block.text[a:b].encode()))
                    for i, (role, a, b) in enumerate(pieces) if block.text[a:b].strip()]
        adjacent_slices = []
        match = re.fullmatch(r"pdf_page:(\d+)", block.locator)
        if adjacent_pages and match:
            page = int(match[1])
            for delta, touches in [(-1, start == 0), (1, end == len(block.text))]:
                neighbor = pages.get((block.document_id, page + delta)) if touches else None
                if neighbor is None: continue
                a, b = ((max(0, len(neighbor.text) - context_chars), len(neighbor.text)) if delta < 0
                        else (0, min(context_chars, len(neighbor.text))))
                if not neighbor.text[a:b].strip(): continue
                role = "context-previous-page" if delta < 0 else "context-next-page"
                selected.append(Block(id=f"{neighbor.id}:w{index}:{role}", document_id=block.document_id,
                    ordinal=len(selected), locator=f"{role}:{neighbor.locator}:chars[{a}:{b}]",
                    text=neighbor.text[a:b], sha256=sha(neighbor.text[a:b].encode())))
                adjacent_slices.append({"source_block_id": neighbor.id, "source_block_sha256": neighbor.sha256,
                    "role": role, "start_char": a, "end_char": b})
        documents = [deepcopy(d) for d in parent.documents if d.id == block.document_id]
        for document in documents:
            document.coverage = "partial"
            document.parser += f":{window_version}"
        note_data = {"version": window_version, "parent_bundle_sha256": parent_hash,
                          "window_index": index, "window_count": len(records),
                          "source_block_id": block.id, "source_block_sha256": block.sha256,
                          "start_char": start, "end_char": end}
        if adjacent_pages:
            note_data.update(adjacent_page_context=adjacent_slices, context_chars=context_chars)
        note = canonical(note_data)
        bundle = Bundle(version=parent.version, work_id=parent.work_id, title=parent.title,
                        family=parent.family, source_status=parent.source_status,
                        supplement_status=(parent.supplement_status
                                           if parent.supplement_status != "included"
                                           or any(d.role == "supplement" for d in documents)
                                           else "not_checked"), documents=documents, blocks=selected,
                        acquisition_notes=[*parent.acquisition_notes, "SOURCE_WINDOW " + note])
        identifier, _ = save_bundle(root, bundle)
        row = {"bundle_sha256": identifier, "source_block_id": block.id,
               "start_char": start, "end_char": end, "window_index": index}
        if adjacent_pages: row["adjacent_page_context"] = adjacent_slices
        manifest["windows"].append(row)
    name = "manifest-v3.json" if adjacent_pages else "manifest.json"
    private_write(root / "windows" / parent_hash / name, canonical(manifest).encode())
    return manifest
