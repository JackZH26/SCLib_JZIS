"""Whole-source text index and literal context selection, without entity guesses.

This is an input coverage artifact. It neither assigns a procedure to a result
nor claims that all relevant context or any image has been read scientifically.
"""
import json
import re

from .contract import canonical, digest
from .sources import Block, sha, verify_bundle

VERSION = "materials-document-context/1"
TEX_HEADING_POLICY = "plain_and_tex_headings_v1"
METHOD = re.compile(r"^(?:(?:[IVX]+|\d+)[.)]?\s+)?(?:experimental(?: section| methods| details| techniques)?|methods|materials and methods|sample preparation(?: and characterization)?|computational methods)\s*$", re.I)
STOP = re.compile(r"^(?:(?:[IVX]+|\d+)[.)]?\s+)?(?:results(?: and discussion)?|discussion|conclusions?|summary|acknowledg(?:e)?ments?|references|bibliography|supporting information|supplementary (?:materials?|information))\s*$", re.I)


def build_inventory(parent, selections, *, selector_kind="assistant"):
    verify_bundle(parent)
    if selector_kind not in {"assistant", "human", "heading_scan", "literal_reference_scan"}: raise ValueError("context_selector_invalid")
    if any(n.startswith("SOURCE_WINDOW ") for n in parent.acquisition_notes):
        raise ValueError("document_context_requires_original_parent")
    blocks = {b.id: b for b in parent.blocks}
    selected, occupied = [], {}
    for selection in selections:
        block = blocks[selection["source_block_id"]]
        start, end = selection["start_char"], selection["end_char"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block.text):
            raise ValueError("document_context_invalid_slice")
        if not selection["purpose"].strip() or not selection["selection_basis"].strip():
            raise ValueError("document_context_selection_reason_missing")
        if any(start < b and a < end for a, b in occupied.get(block.id, [])):
            raise ValueError("document_context_overlapping_selection")
        occupied.setdefault(block.id, []).append((start, end))
        selected.append(dict(selection, document_id=block.document_id, source_block_sha256=block.sha256,
                             source_locator=block.locator, text_sha256=sha(block.text[start:end].encode())))
    return {"schema": VERSION, "work_id": parent.work_id, "parent_bundle_sha256": digest(parent.model_dump()),
        "selector_kind": selector_kind, "documents": [d.model_dump() for d in parent.documents],
        "text_block_index": [{"block_id": b.id, "document_id": b.document_id, "locator": b.locator,
            "sha256": b.sha256, "characters": len(b.text), "selected_characters": sum(z-a for a,z in occupied.get(b.id, []))}
            for b in parent.blocks], "selections": selected,
        "all_supplied_text_blocks_indexed": True, "all_relevant_context_identified": False,
        "visual_coverage_verified": False, "scientific_acceptance": False,
        "coverage_limits": ["Text indexing is not scientific reading or complete context discovery.",
            "Only supplied source documents are indexed; missing supplements remain missing.",
            "Selected sections supply context only; applicability to each sample and procedure remains unverified."]}


def _tex_code(line):
    """Ignore comments for recognition only; never rewrite the stored source."""
    for index, character in enumerate(line):
        if character != '%': continue
        previous = index - 1
        while previous >= 0 and line[previous] == '\\': previous -= 1
        if (index - previous - 1) % 2 == 0: return line[:index].strip()
    return line.strip()


def _tex_method_selections(block):
    """Recognize literal section commands without evaluating TeX or includes.

    Multiline/custom-macro headings and conditional compilation are not fully
    interpreted. A member boundary never implies a cross-file section order.
    """
    selections = []; active_depth = start = None; offset = 0
    ignored_environment = None; false_depth = 0
    for line in block.text.splitlines(keepends=True):
        code = _tex_code(line)
        if ignored_environment:
            if code == '\\end{'+ignored_environment+'}': ignored_environment = None
            offset += len(line); continue
        environment = re.match(r'^\\begin\{(comment|verbatim\*?|lstlisting|minted)\}', code)
        if environment:
            ignored_environment = environment[1]; offset += len(line); continue
        if re.match(r'^\\iffalse\b', code):
            false_depth += 1; offset += len(line); continue
        if false_depth:
            if re.match(r'^\\if(?:[A-Za-z]+)?\b', code): false_depth += 1
            elif re.match(r'^\\fi\b', code): false_depth -= 1
            offset += len(line); continue
        command = re.match(r'^\\(section|subsection|subsubsection)(?:\*|\s|\[|\{)', code)
        depth = {'section':1,'subsection':2,'subsubsection':3}[command[1]] if command else None
        end_document = bool(re.match(r'^\\(?:appendix\b|end\{document\}|begin\{thebibliography\})', code))
        if start is not None and (end_document or depth is not None and depth <= active_depth):
            if offset > start:
                selections.append(dict(source_block_id=block.id,start_char=start,end_char=offset,
                    purpose='methods_section',selection_basis=TEX_HEADING_POLICY+': literal TeX methods heading through next same/higher section; exact source bytes retained.'))
            start = active_depth = None
        # A label may precede/follow the literal title, but arbitrary macros
        # are not executed or treated as recognized titles.
        title_line = re.sub(r'\\label\{[^{}\r\n]*\}', '', code)
        title = re.fullmatch(r'\\(?:section|subsection|subsubsection)\*?\s*(?:\[[^\]\r\n]*\]\s*)?\{([^{}]*)\}\s*',title_line)
        if command and title and METHOD.fullmatch(title[1].strip()) and start is None:
            start, active_depth = offset, depth
        offset += len(line)
    if start is not None and start < len(block.text):
        selections.append(dict(source_block_id=block.id,start_char=start,end_char=len(block.text),
            purpose='methods_section',selection_basis=TEX_HEADING_POLICY+': literal TeX methods heading through member end; include order and applicability remain unverified.'))
    return selections


def discover_inventory(parent, *, heading_policy="plain_v1"):
    """Conservative heading selection; unrecognized layouts remain disclosed gaps."""
    if heading_policy not in {"plain_v1", TEX_HEADING_POLICY}:
        raise ValueError("document_context_heading_policy_unknown")
    selections = []
    for document in parent.documents:
        active = False
        blocks = sorted((b for b in parent.blocks if b.document_id == document.id), key=lambda b:b.ordinal)
        if len({b.ordinal for b in blocks}) != len(blocks): raise ValueError("context_block_order_ambiguous")
        if heading_policy == TEX_HEADING_POLICY and document.source_kind == 'original_tex':
            for block in blocks: selections.extend(_tex_method_selections(block))
            continue
        for block in blocks:
            start, offset = (0 if active else None), 0
            for line in block.text.splitlines(keepends=True):
                heading = line.strip()
                if METHOD.fullmatch(heading) and not active:
                    active, start = True, offset
                elif STOP.fullmatch(heading) and active:
                    if offset > start:
                        selections.append({"source_block_id":block.id, "start_char":start, "end_char":offset,
                            "purpose":"methods_section", "selection_basis":"Recognized methods heading through next recognized major section; original text retained."})
                    active, start = False, None
                offset += len(line)
            if active and start < len(block.text):
                selections.append({"source_block_id":block.id, "start_char":start, "end_char":len(block.text),
                    "purpose":"methods_section", "selection_basis":"Recognized methods section, possibly continuing across source blocks; original text retained."})
    return build_inventory(parent, selections, selector_kind="heading_scan")


def verify_inventory(parent, inventory):
    keys = ("source_block_id", "start_char", "end_char", "purpose", "selection_basis")
    rebuilt = build_inventory(parent, [{k:s[k] for k in keys} for s in inventory["selections"]],
                              selector_kind=inventory["selector_kind"])
    if rebuilt != inventory: raise ValueError("document_context_inventory_mismatch")


def _subtract(start, end, covered):
    slices = [(start, end)]
    for a, b in sorted(covered):
        slices = [(left, right) for x, y in slices for left, right in
                  [(x, min(y,a)), (max(x,b),y)] if left < right]
    return slices


def attach_context(parent, window, inventory, *, max_context_chars=12000, attachment_kind="document"):
    verify_inventory(parent, inventory); verify_bundle(window)
    if attachment_kind not in {"document", "reference", "identity"}: raise ValueError("document_context_attachment_kind_unknown")
    marker = {"document": "DOCUMENT_CONTEXT ", "reference": "REFERENCE_CONTEXT ", "identity": "IDENTITY_CONTEXT "}[attachment_kind]
    if type(max_context_chars) is not int or not 1 <= max_context_chars <= 50000:
        raise ValueError("document_context_budget_invalid")
    notes = [json.loads(n[len("SOURCE_WINDOW "):]) for n in window.acquisition_notes if n.startswith("SOURCE_WINDOW ")]
    if (len(notes) != 1 or notes[0]["parent_bundle_sha256"] != inventory["parent_bundle_sha256"]
            or window.work_id != parent.work_id or any(n.startswith(marker) for n in window.acquisition_notes)):
        raise ValueError("document_context_window_parent_mismatch")
    sources = {(b.document_id,b.locator):b for b in parent.blocks}
    if len(sources) != len(parent.blocks): raise ValueError("document_context_source_locator_ambiguous")
    source_documents = {d.id:d.model_dump(exclude={"coverage", "parser"}) for d in parent.documents}
    if any(source_documents.get(d.id) != d.model_dump(exclude={"coverage", "parser"}) for d in window.documents):
        raise ValueError("document_context_document_identity_mismatch")
    covered = {}
    for block in window.blocks:
        match = re.fullmatch(r"[^:]+:(.+):chars\[(\d+):(\d+)\]", block.locator)
        if match:
            locator, a, b = match[1], int(match[2]), int(match[3])
        elif block.locator.startswith("context-identity:"):
            locator = block.locator[len("context-identity:"):]; a = 0; b = len(block.text)
        else: raise ValueError("document_context_window_locator_unknown")
        original = sources.get((block.document_id,locator))
        if original is None or original.text[a:b] != block.text:
            raise ValueError("document_context_window_bytes_mismatch")
        covered.setdefault(original.id, []).append((a,b))
    documents = {d.id for d in window.documents}
    planned, excluded = [], []
    originals = {b.id:b for b in parent.blocks}
    for selection in inventory["selections"]:
        if selection["document_id"] not in documents:
            excluded.append(selection); continue
        source = originals[selection["source_block_id"]]
        for a,b in _subtract(selection["start_char"], selection["end_char"], covered.get(source.id, [])):
            planned.append((source,a,b))
            covered.setdefault(source.id, []).append((a,b))
    if sum(b-a for _,a,b in planned) > max_context_chars:
        raise ValueError("document_context_budget_exceeded_no_silent_truncation")
    result = window.model_copy(deep=True); attached = []
    for index,(source,a,b) in enumerate(planned):
        identifier = f"{source.id}:{attachment_kind}-context:{index}"
        result.blocks.append(Block(id=identifier, document_id=source.document_id, ordinal=len(result.blocks),
            locator=f"context-document:{source.locator}:chars[{a}:{b}]", text=source.text[a:b], sha256=sha(source.text[a:b].encode())))
        attached.append({"block_id":identifier, "source_block_id":source.id, "start_char":a, "end_char":b,
                         "source_block_sha256":source.sha256, "text_sha256":sha(source.text[a:b].encode())})
    proof = {"schema":VERSION, "inventory_sha256":digest(inventory), "parent_bundle_sha256":digest(parent.model_dump()),
             "base_window_sha256":digest(window.model_dump()), "attached_slices":attached,
             "excluded_other_document_selections":excluded, "added_characters":sum(b-a for _,a,b in planned),
             "counts_as_target_coverage":False, "sample_or_procedure_applicability_verified":False}
    if attachment_kind != "document": proof["attachment_kind"] = attachment_kind
    result.acquisition_notes.append(marker + canonical(proof))
    verify_bundle(result)
    return result, proof
