"""Restrict the existing source-span catalogue to frozen TARGET/CONTEXT ranges.

Selection never creates a quote: all bytes and offsets come from original text.
Source spans are neutral partitions, not reference answers or scientific labels.
"""
from .contract import digest
import re
from .evidence import source_spans, selected_quotes, CATALOG_VERSION
from .sources import sha, verify_bundle
from . import paper_coverage, reader_scope
from .source_audit import _mask_comments

VERSION='materials-scoped-source-spans/2'
LEGACY_VERSION='materials-scoped-source-spans/1'
LINE_VERSION='materials-scoped-source-spans/3'
LINE_ALGORITHM='materials-original-line-spans/1'


def original_line_spans(text):
    """Partition source addresses at physical lines, preserving all characters.

    Reading/ownership ranges do not change. Blank lines stay with an adjacent
    content line; long lines reuse the existing bounded splitter. This is not
    sentence, formula, table-cell or scientific-claim interpretation.
    """
    start=cursor=0;content_seen=False
    lines=[]
    for match in re.finditer(r'[^\r\n]*(?:\r\n|\r|\n|$)',text):
        line=match[0]
        if not line:continue
        if line.strip():
            if content_seen:lines.append((start,cursor));start=cursor
            content_seen=True
        cursor+=len(line)
    if cursor>start:lines.append((start,cursor))
    for a,z in lines:
        for left,right in source_spans(text[a:z]):yield a+left,a+right


def comment_intervals(text):
    """Use the existing TeX comment policy, preserving complete comment ranges.

    Comparing individual characters would leave spaces inside comments eligible.
    The existing mask identifies the first changed character (the unescaped %);
    the entire remainder of that line, except its newline, is unpublished.
    """
    masked=_mask_comments(text);offset=0;result=[]
    for line in text.splitlines(keepends=True):
        end=offset+len(line)
        if text[offset:end]!=masked[offset:end]:
            start=next(i for i in range(offset,end) if text[i]!=masked[i])
            result.append((start,offset+len(line.rstrip('\r\n'))))
        offset=end
    return result


def build(bundle,scope,*,version=VERSION):
    if version not in {VERSION,LEGACY_VERSION,LINE_VERSION}:raise ValueError('scoped_catalog_version')
    reader_scope.shape(scope)
    verify_bundle(bundle)
    blocks={b.id:b for b in bundle.blocks};documents={d.id:d for d in bundle.documents}
    spans={};seen=[];excluded=[];comments={}
    for passage in scope['passages']:
        block=blocks.get(passage['block_id']);left,right=passage['start_char'],passage['end_char']
        if (block is None or type(left) is not int or type(right) is not int or not 0<=left<right<=len(block.text)
                or passage['role'] not in {'target','context'}):raise ValueError('scoped_catalog_bounds')
        if any(b==block.id and max(a,left)<min(z,right) for b,a,z in seen):raise ValueError('scoped_catalog_overlap')
        seen.append((block.id,left,right))
        if block.id not in comments:
            comments[block.id]=comment_intervals(block.text) if version!=LEGACY_VERSION and documents[block.document_id].source_kind=='original_tex' else []
        omissions=comments[block.id]
        cuts=[(max(left,a),min(right,z)) for a,z in omissions if max(left,a)<min(right,z)]
        cursor=left;segments=[]
        for a,z in cuts:
            if cursor<a:segments.append((cursor,a))
            excluded.append(dict(block_id=block.id,start_char=a,end_char=z,role=passage['role'],
                reason='unpublished_tex_comment',text_sha256=sha(block.text[a:z].encode())))
            cursor=z
        if cursor<right:segments.append((cursor,right))
        for start,end in segments:
            splitter=original_line_spans if version==LINE_VERSION else source_spans
            for a,z in splitter(block.text[start:end]):
                a,z=start+a,start+z;text=block.text[a:z]
                spans[f'E{len(spans)+1:04}']=dict(block_id=block.id,start_char=a,end_char=z,
                    text=text,text_sha256=sha(text.encode()),role=passage['role'])
    if not spans or len(spans)>1000:raise ValueError('scoped_catalog_size')
    if version!=LEGACY_VERSION and not any(s['text'].strip() for s in spans.values()):raise ValueError('scoped_catalog_no_published_text')
    catalog=dict(schema=version,source_span_algorithm=LINE_ALGORITHM if version==LINE_VERSION else CATALOG_VERSION,bundle_sha256=digest(bundle.model_dump()),
        scope_sha256=digest(scope),spans=spans,semantic_annotations=False,reference_answers_used=False)
    if version!=LEGACY_VERSION:
        catalog.update(excluded_source_ranges=excluded,publication_boundary_policy='existing_tex_percent_comment_mask',
            complete_publication_review=False)
    return catalog


def selected(catalog,identifiers,bundle,scope,coverage):
    if catalog!=build(bundle,scope,version=catalog.get('schema')):raise ValueError('scoped_catalog_drift')
    paper_coverage.verify(coverage,bundle)
    if not identifiers or len(set(identifiers))!=len(identifiers):raise ValueError('scoped_catalog_duplicate_or_empty')
    if any(identifier not in catalog['spans'] for identifier in identifiers):raise ValueError('scoped_catalog_unknown_id')
    anchors=[]
    # Preserve role boundaries while reusing the existing adjacent-span join.
    # A token crossing a catalogue boundary can be quoted without inventing text.
    for role in ['target','context']:
        selected_ids=[i for i in identifiers if catalog['spans'][i]['role']==role]
        if not selected_ids:continue
        for anchor in selected_quotes(catalog,selected_ids):
            if not paper_coverage.inside(anchor,[s for s in scope['passages'] if s['role']==role]):
                raise ValueError('scoped_catalog_role_boundary')
            if not paper_coverage.published(anchor,coverage,bundle):raise ValueError('scoped_catalog_not_published')
            anchors.append(anchor)
    return anchors
