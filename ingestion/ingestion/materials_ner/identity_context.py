"""Literal original title/abstract context with preserved source coordinates.

No TeX is executed and no title-to-specimen applicability is inferred. This
preparation step precedes reference attachment and fresh inventory generation.
"""
import re

from .contract import digest
from .document_context import attach_context, build_inventory
from .reference_context import visible_source
from .sources import sha, verify_bundle

VERSION = 'materials-identity-context/1'
POLICY = 'literal_tex_identity_context_v1'
COMMAND = re.compile(r'(?<!\\)\\(title|abstract)(?![A-Za-z@])')
ABSTRACT = re.compile(r'(?<!\\)\\begin\s*\{abstract\}')
END_ABSTRACT = re.compile(r'(?<!\\)\\end\s*\{abstract\}')


def _argument_end(text, start):
    """Read one balanced literal argument; return None for unsupported syntax."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text) and text[start] == '[':
        end = text.find(']', start + 1)
        if end < 0 or '[' in text[start + 1:end]:
            return None
        start = end + 1
        while start < len(text) and text[start].isspace():
            start += 1
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] not in '{}':
            continue
        previous = index - 1
        while previous >= 0 and text[previous] == '\\':
            previous -= 1
        if (index - previous - 1) % 2:
            continue
        depth += 1 if text[index] == '{' else -1
        if depth == 0:
            return index + 1
    return None


def build_index(parent, *, max_fragment_chars=12000):
    verify_bundle(parent)
    if any(n.startswith('SOURCE_WINDOW ') for n in parent.acquisition_notes):
        raise ValueError('identity_context_requires_original_parent')
    if type(max_fragment_chars) is not int or not 1 <= max_fragment_chars <= 50000:
        raise ValueError('identity_context_fragment_budget_invalid')
    tex = {d.id for d in parent.documents if d.source_kind == 'original_tex'}
    candidates, holds, unsupported = [], [], []
    for block in parent.blocks:
        if block.document_id not in tex or not block.locator.lower().endswith('.tex'):
            unsupported.append(dict(source_block_id=block.id, reason='unsupported_source_representation_or_member'))
            continue
        visible = visible_source(block.text)
        regions = [(m, m[1], _argument_end(visible, m.end())) for m in COMMAND.finditer(visible)]
        for match in ABSTRACT.finditer(visible):
            end = END_ABSTRACT.search(visible, match.end())
            nested = ABSTRACT.search(visible, match.end(), end.start() if end else len(visible))
            regions.append((match, 'abstract', end.end() if end and not nested else None))
        for match, kind, end in regions:
            if end is None or end - match.start() > max_fragment_chars:
                holds.append(dict(source_block_id=block.id, start_char=match.start(), kind=kind,
                                  reason='unclosed_or_unsupported_literal' if end is None else 'fragment_budget_exceeded'))
                continue
            candidates.append(dict(kind=kind, source_block_id=block.id, document_id=block.document_id,
                                   source_locator=block.locator, source_block_sha256=block.sha256,
                                   start_char=match.start(), end_char=end,
                                   text_sha256=sha(block.text[match.start():end].encode())))
    selected, decisions = [], []
    for document in parent.documents:
        for kind in ('title', 'abstract'):
            matches = [c for c in candidates if c['document_id'] == document.id and c['kind'] == kind]
            document_blocks = {b.id for b in parent.blocks if b.document_id == document.id}
            unresolved = [h for h in holds if h['source_block_id'] in document_blocks and h['kind'] == kind]
            status = ('unresolved_literal' if unresolved else 'unique_literal' if len(matches) == 1
                      else 'ambiguous_literals' if matches else 'no_supported_literal')
            decisions.append(dict(document_id=document.id, kind=kind, status=status,
                                  candidate_count=len(matches), unresolved_count=len(unresolved)))
            if status != 'unique_literal':
                continue
            candidate = matches[0]
            selected.append({k: candidate[k] for k in ('source_block_id', 'start_char', 'end_char')} |
                            dict(purpose='identity_' + kind,
                                 selection_basis=POLICY + ': unique supported original literal; specimen and result applicability remain unverified.'))
    # A title nested inside an abstract or another unusual layout is ambiguous;
    # do not trim or silently prioritize either candidate.
    conflicting = {i for i, a in enumerate(selected) for j, b in enumerate(selected) if i != j
                   and a['source_block_id'] == b['source_block_id']
                   and a['start_char'] < b['end_char'] and b['start_char'] < a['end_char']}
    for index in sorted(conflicting):
        holds.append(dict(selected[index], reason='overlapping_identity_literals'))
    inventory = build_inventory(parent, [s for i, s in enumerate(selected) if i not in conflicting],
                                selector_kind='heading_scan')
    return dict(schema=VERSION, policy=POLICY, work_id=parent.work_id,
                parent_bundle_sha256=digest(parent.model_dump()), max_fragment_chars=max_fragment_chars,
                candidates=candidates, decisions=decisions, holds=holds, unsupported_blocks=unsupported,
                selection_inventory=inventory, scientific_acceptance=False,
                all_identity_context_identified=False, sample_or_result_applicability_verified=False,
                limitations=['Literal TeX title/abstract syntax only; no macro expansion, include order or conditional evaluation.',
                             'Duplicate, unclosed and oversized regions remain unresolved; no first-match choice or silent truncation.',
                             'Metadata title is not substituted for original source text; absence of a supported match is not paper-level absence.',
                             'These passages supply context, not new result targets, measured composition or specimen applicability.'])


def attach_identity(parent, window, index, *, max_context_chars=12000):
    if index != build_index(parent, max_fragment_chars=index['max_fragment_chars']):
        raise ValueError('identity_context_index_mismatch')
    if any(n.startswith(('REFERENCE_CONTEXT ', 'SOURCE_REFERENCE_RESOLUTION ')) for n in window.acquisition_notes):
        raise ValueError('identity_context_must_precede_reference_attachment')
    enriched, attachment = attach_context(parent, window, index['selection_inventory'],
                                          max_context_chars=max_context_chars, attachment_kind='identity')
    proof = dict(schema=VERSION, policy=POLICY, index_sha256=digest(index), attachment=attachment,
                 added_characters=attachment['added_characters'], scientific_acceptance=False,
                 counts_as_target_coverage=False, sample_or_result_applicability_verified=False)
    return enriched, proof


def verify_attachment(parent, base, enriched, index, *, max_context_chars=12000):
    expected, proof = attach_identity(parent, base, index, max_context_chars=max_context_chars)
    if expected.model_dump() != enriched.model_dump():
        raise ValueError('identity_context_attachment_mismatch')
    return proof
