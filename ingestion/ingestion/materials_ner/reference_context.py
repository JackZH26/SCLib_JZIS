"""Literal TeX reference context, without source-role or applicability inference.

This is a finite source scanner, not TeX execution. Only unique entries within
closed bibliography environments in the same supplied document are attachable.
"""
import json
import re

from .contract import canonical, digest
from .sources import sha, verify_bundle
from .document_context import build_inventory, attach_context

POLICY = 'literal_tex_reference_context_v1'
VERSION = 'materials-reference-context/1'
KEY = r'[A-Za-z0-9_:.+/-]+'
COMMAND = re.compile(r'(?<!\\)\\(?:cite|citep|citet|citealp|citeauthor|citeyear|autocite|parencite|textcite|onlinecite)\*?(?![A-Za-z@])')
ARGUMENT = re.compile(r'\s*(?:\[[^\]\r\n]*\]\s*){0,2}\{([^{}]*)\}')
ENVIRONMENT = re.compile(r'(?<!\\)\\begin\s*\{(thebibliography|references)\}')
ITEM_START = re.compile(r'(?<!\\)\\bibitem(?![A-Za-z@])')
# BibTeX wraps optional author/year labels across lines. A malformed label
# must not consume the next entry's closing bracket and acquire its key.
ITEM = re.compile(r'(?<!\\)\\bibitem\s*(?:\[(?:(?!\\bibitem(?![A-Za-z@]))[^\]])*\]\s*)?\{('+KEY+r')\}')


def _blank(text):
    return ''.join(c if c in '\r\n' else ' ' for c in text)


def _balanced_end(text,start):
    depth=0
    for i in range(start,len(text)):
        if text[i] not in '{}':continue
        n=i-1
        while n>=0 and text[n]=='\\':n-=1
        if (i-n-1)%2:continue
        depth += 1 if text[i]=='{' else -1
        if depth==0:return i+1
    return len(text)


def visible_source(text):
    """Mask common inactive/example syntax, preserving every source offset."""
    output=[]
    for line in text.splitlines(keepends=True):
        cut=len(line)
        for i,c in enumerate(line):
            if c!='%':continue
            n=i-1
            while n>=0 and line[n]=='\\':n-=1
            if (i-n-1)%2==0:cut=i;break
        output.append(line[:cut]+_blank(line[cut:]))
    visible=''.join(output)
    env=re.compile(r'(?<!\\)\\begin\s*\{(comment|verbatim\*?|lstlisting|minted)\}')
    position=0
    while match:=env.search(visible,position):
        end=re.search(r'\\end\s*\{'+re.escape(match[1])+r'\}',visible[match.end():])
        limit=match.end()+end.end() if end else len(visible)
        visible=visible[:match.start()]+_blank(visible[match.start():limit])+visible[limit:];position=limit
    verb=re.compile(r'(?<!\\)\\verb\*?([^A-Za-z\s])[^\r\n]*')
    position=0
    while match:=verb.search(visible,position):
        end=visible.find(match[1],match.start()+len('\\verb')+(1 if visible[match.start()+5:match.start()+6]=='*' else 0)+1)
        limit=end+1 if end>=0 and end<match.end() else match.end()
        visible=visible[:match.start()]+_blank(visible[match.start():limit])+visible[limit:];position=limit
    # Suppress entire false branches, including else: no conditional evaluation.
    conditional=re.compile(r'(?<!\\)\\(?:if[A-Za-z@]*|fi)(?![A-Za-z@])')
    start=None;depth=0;ranges=[]
    for match in conditional.finditer(visible):
        token=match[0]
        if start is None:
            if token=='\\iffalse':start=match.start();depth=1
        elif token=='\\fi':
            depth-=1
            if depth==0:ranges.append((start,match.end()));start=None
        else:depth+=1
    if start is not None:ranges.append((start,len(visible)))
    for a,b in ranges:visible=visible[:a]+_blank(visible[a:b])+visible[b:]
    macro=re.compile(r'(?<!\\)\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?\s*(?:\{\\[A-Za-z@]+\}|\\[A-Za-z@]+)\s*(?:\[[^\]\r\n]*\]\s*){0,2}(?=\{)|(?<!\\)\\(?:def|gdef|edef|xdef)\s*\\[A-Za-z@]+[^{}\r\n]*(?=\{)')
    position=0
    while match:=macro.search(visible,position):
        limit=_balanced_end(visible,match.end())
        visible=visible[:match.start()]+_blank(visible[match.start():limit])+visible[limit:];position=limit
    assert len(visible)==len(text)
    return visible


def build_index(parent):
    verify_bundle(parent)
    if any(n.startswith('SOURCE_WINDOW ') for n in parent.acquisition_notes):
        raise ValueError('reference_context_requires_original_parent')
    tex={d.id for d in parent.documents if d.source_kind=='original_tex'}
    entries=[];unclosed=[]
    for block in parent.blocks:
        if block.document_id not in tex:continue
        visible=visible_source(block.text)
        for environment in ENVIRONMENT.finditer(visible):
            end=re.search(r'\\end\s*\{'+environment[1]+r'\}',visible[environment.end():])
            if end is None:
                unclosed.append(dict(source_block_id=block.id,start_char=environment.start()));continue
            limit=environment.end()+end.start()
            matches=list(ITEM.finditer(visible,environment.end(),limit))
            for match in matches:
                following=ITEM_START.search(visible,match.end(),limit)
                stop=following.start() if following else limit
                entries.append(dict(key=match[1],source_block_id=block.id,document_id=block.document_id,
                    source_locator=block.locator,source_block_sha256=block.sha256,start_char=match.start(),end_char=stop,
                    text_sha256=sha(block.text[match.start():stop].encode())))
    return dict(schema=VERSION,policy=POLICY,parent_bundle_sha256=digest(parent.model_dump()),work_id=parent.work_id,
        entries=entries,unclosed_bibliography_regions=unclosed,scientific_acceptance=False,
        limitations=['Literal supported cite/bibitem syntax only; no TeX execution, macro expansion or include-order inference.',
            'Only complete bibliography environments within supplied source blocks are indexed; external bibliographies are not fetched.',
            'Unique byte location does not establish primary/cited attribution, specimen identity or scientific validity.'])


def attach_references(parent,window,index,*,max_context_chars=12000):
    if index!=build_index(parent):raise ValueError('reference_context_index_mismatch')
    verify_bundle(window)
    if any(n.startswith('SOURCE_REFERENCE_RESOLUTION ') for n in window.acquisition_notes):
        raise ValueError('reference_context_already_attached')
    documents={d.id:d for d in window.documents};citations=[];selections={}
    for block in window.blocks:
        if not block.locator.startswith('target:') or documents[block.document_id].source_kind!='original_tex':continue
        visible=visible_source(block.text)
        for command in COMMAND.finditer(visible):
            argument=ARGUMENT.match(visible,command.end())
            keys=[x.strip() for x in argument[1].split(',')] if argument else []
            if not keys or any(not re.fullmatch(KEY,k) for k in keys):
                citations.append(dict(block_id=block.id,start_char=command.start(),end_char=command.end(),
                    status='unsupported_syntax',keys=[]));continue
            for key in keys:
                candidates=[e for e in index['entries'] if e['document_id']==block.document_id and e['key']==key]
                status='unique_source_entry' if len(candidates)==1 else 'missing_source_entry' if not candidates else 'ambiguous_source_entry'
                citations.append(dict(block_id=block.id,start_char=command.start(),end_char=argument.end(),key=key,status=status,
                    raw=block.text[command.start():argument.end()],candidates=candidates))
                if len(candidates)==1:
                    e=candidates[0];identity=(e['source_block_id'],e['start_char'],e['end_char'])
                    selections[identity]=dict(source_block_id=e['source_block_id'],start_char=e['start_char'],end_char=e['end_char'],
                        purpose='referenced_entry',selection_basis=POLICY+': literal target citation key '+key+' has one supplied same-document entry; attribution is unverified.')
    selected=build_inventory(parent,list(selections.values()),selector_kind='literal_reference_scan')
    result,attachment=attach_context(parent,window,selected,max_context_chars=max_context_chars,attachment_kind='reference')
    proof=dict(schema=VERSION,policy=POLICY,index_sha256=digest(index),base_window_sha256=digest(window.model_dump()),
        citations=citations,selection_inventory=selected,attachment=attachment,added_characters=attachment['added_characters'],
        counts_as_target_coverage=False,source_role_verified=False,sample_or_procedure_applicability_verified=False,
        scientific_acceptance=False)
    result.acquisition_notes.append('SOURCE_REFERENCE_RESOLUTION '+canonical(proof))
    verify_bundle(result)
    return result,proof


def verified_edges(bundle):
    """Verify local citation/entry bytes before using a reference as context.

    Original-document uniqueness is the frozen index producer's claim. This
    check proves only the literal edge in the supplied input, never attribution.
    """
    from .evidence import source_catalog
    notes=[json.loads(n.removeprefix('SOURCE_REFERENCE_RESOLUTION ')) for n in bundle.acquisition_notes
           if n.startswith('SOURCE_REFERENCE_RESOLUTION ')]
    if not notes:return []
    if len(notes)!=1:raise ValueError('staged_reference_context_proof_ambiguous')
    proof=notes[0];attachment=proof['attachment'];verify_bundle(bundle)
    if proof['schema']!=VERSION or proof['policy']!=POLICY:raise ValueError('staged_reference_context_policy_unknown')
    attached={x['block_id'] for x in attachment['attached_slices']}
    base=bundle.model_copy(deep=True)
    base.blocks=[b for b in base.blocks if b.id not in attached]
    base.acquisition_notes=[n for n in base.acquisition_notes if not n.startswith(('REFERENCE_CONTEXT ','SOURCE_REFERENCE_RESOLUTION '))]
    markers=[json.loads(n.removeprefix('REFERENCE_CONTEXT ')) for n in bundle.acquisition_notes if n.startswith('REFERENCE_CONTEXT ')]
    if markers!=[attachment] or digest(base.model_dump())!=proof['base_window_sha256']:
        raise ValueError('staged_reference_context_base_mismatch')
    if attachment['base_window_sha256']!=proof['base_window_sha256']:
        raise ValueError('staged_reference_context_base_mismatch')
    blocks={b.id:b for b in bundle.blocks};catalog=source_catalog(bundle);edges=[]
    for citation in proof['citations']:
        if citation['status']!='unique_source_entry':continue
        block=blocks[citation['block_id']];a,b=citation['start_char'],citation['end_char']
        if not block.locator.startswith('target:') or not 0<=a<b<=len(block.text):
            raise ValueError('staged_reference_citation_outside_target')
        raw=block.text[a:b];visible=visible_source(block.text)
        command=COMMAND.match(visible,a);argument=ARGUMENT.match(visible,command.end()) if command else None
        if not argument or argument.end()!=b or citation['key'] not in [x.strip() for x in argument[1].split(',')] or raw!=citation['raw']:
            raise ValueError('staged_reference_citation_mismatch')
        if len(citation['candidates'])!=1:raise ValueError('staged_reference_entry_not_unique')
        entry=citation['candidates'][0];start,end=entry['start_char'],entry['end_char']
        if entry['key']!=citation['key'] or entry['document_id']!=block.document_id or not 0<end-start<=50000:
            raise ValueError('staged_reference_entry_scope_mismatch')
        # Reconstruct the original interval from every available context slice,
        # including overlap with context already present before enrichment.
        characters=[None]*(end-start);entry_spans=[]
        for local in bundle.blocks:
            if local.document_id!=entry['document_id']:continue
            match=re.fullmatch(r'[^:]+:(.+):chars\[(\d+):(\d+)\]',local.locator)
            if not match or match[1]!=entry['source_locator']:continue
            offset,limit=int(match[2]),int(match[3])
            if limit-offset!=len(local.text):raise ValueError('staged_reference_slice_size_mismatch')
            left,right=max(offset,start),min(limit,end)
            if left>=right:continue
            for i in range(left,right):
                value=local.text[i-offset]
                if characters[i-start] not in {None,value}:raise ValueError('staged_reference_slice_disagreement')
                characters[i-start]=value
            entry_spans.extend(s for s,v in catalog['spans'].items() if v['block_id']==local.id
                and offset+v['start_char']<end and start<offset+v['end_char'])
        if any(c is None for c in characters):raise ValueError('staged_reference_entry_bytes_missing')
        text=''.join(characters);items=list(ITEM.finditer(visible_source(text)))
        if sha(text.encode())!=entry['text_sha256'] or len(items)!=1 or items[0].start()!=0 or items[0][1]!=entry['key']:
            raise ValueError('staged_reference_entry_literal_mismatch')
        citation_spans=[s for s,v in catalog['spans'].items() if v['block_id']==block.id and v['start_char']<b and a<v['end_char']]
        # A span partition may put a post-sentence citation in the next span.
        # Preserve that immediate textual adjacency without searching for a
        # nearby value, crossing a blank paragraph, or claiming applicability.
        left=a
        while left>0 and block.text[left-1].isspace():left-=1
        gap=block.text[left:a]
        context_start=left-1 if (left>0 and gap.count('\n')<=1
            and visible[left-1]==block.text[left-1] and not visible[left-1].isspace()) else a
        context_spans=[s for s,v in catalog['spans'].items() if v['block_id']==block.id and v['start_char']<b and context_start<v['end_char']]
        edges.append(dict(key=entry['key'],citation_span_ids=citation_spans,citation_context_span_ids=context_spans,
            citation_context_start_char=context_start,citation_end_char=b,
            attachment_basis='Literal citation plus its immediately preceding character across whitespace within one paragraph; no semantic applicability inference.',
            entry_span_ids=sorted(set(entry_spans)),
            entry_text_sha256=entry['text_sha256'],source_index_sha256=proof['index_sha256'],
            scientific_attribution_verified=False))
    return edges
