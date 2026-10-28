"""Coordinate-preserving active-source witnesses; no scientific inference."""
from .evidence import source_catalog
from .field_candidates import active_ranges,active_span_ranges,text_candidates
from .validation import resolve_quote
from .sources import sha

POLICY='active-coordinate-witness/1'


def positioned_witness(bundle, item, *, source_format_aware=False):
    """Retain an exact active occurrence, including a non-unique short token."""
    block = next((b for b in bundle.blocks if b.id == item['block_id']), None)
    if block is None:
        raise ValueError('source_occurrence_block_missing')
    start, end = item['start_char'], item['end_char']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block.text)
            or block.text[start:end] != item['quote']):
        raise ValueError('source_occurrence_coordinate_mismatch')
    tex = True
    if source_format_aware:
        document = next((d for d in bundle.documents if d.id == block.document_id), None)
        if document is None:
            raise ValueError('source_occurrence_document_missing')
        tex = document.source_kind == 'original_tex'
    if not any(a <= start and end <= b for a, b in active_ranges(block.text, tex=tex)):
        raise ValueError('source_occurrence_comment_crossing')
    return dict(block_id=block.id, quote=block.text[start:end], start_char=start, end_char=end)


def active_catalog(bundle):
    original=source_catalog(bundle);catalog=dict(original,spans={})
    blocks={b.id:b for b in bundle.blocks}
    for span in original['spans'].values():
        block=blocks[span['block_id']]
        for a,b in active_span_ranges(block.text,span['start_char'],span['end_char']):
            if not block.text[a:b].strip():continue
            catalog['spans']['C'+str(len(catalog['spans'])+1)]=dict(span,start_char=a,end_char=b,text=block.text[a:b],text_sha256=sha(block.text[a:b].encode()))
    return catalog


def witness(bundle,item):
    """Expand a repeated quote only around the supplied original occurrence.

    Uniqueness uses the same whitespace semantics as native validation. No
    comment gap or block boundary may be bridged to manufacture a witness.
    """
    block=next((b for b in bundle.blocks if b.id==item['block_id']),None)
    if block is None:raise ValueError('source_occurrence_block_missing')
    start,end=item['start_char'],item['end_char']
    if not 0<=start<end<=len(block.text) or block.text[start:end]!=item['quote']:
        raise ValueError('source_occurrence_coordinate_mismatch')
    ranges=active_ranges(block.text)
    if not any(a<=start and end<=b for a,b in ranges):raise ValueError('source_occurrence_comment_crossing')
    candidates=[item]+text_candidates(block.text,0,len(block.text))
    candidates += [dict(s,quote=s['text']) for s in active_catalog(bundle)['spans'].values() if s['block_id']==block.id]
    choices=[]
    for c in candidates:
        a,b=c['start_char'],c['end_char'];q=c['quote']
        if not(a<=start and end<=b) or block.text[a:b]!=q:continue
        if not any(x<=a and b<=y for x,y in ranges):continue
        try:left,right=resolve_quote(block.text,q)
        except ValueError:continue
        if left==a+len(q)-len(q.lstrip()) and right==b-len(q)+len(q.rstrip()):choices.append(c)
    if not choices:raise ValueError('source_occurrence_witness_ambiguous')
    selected=min(choices,key=lambda c:len(c['quote']))
    return dict(block_id=block.id,quote=selected['quote'])
