"""Pinned auxiliary PDF layout; never rewrite source blocks or assert reading order."""
import math
import re
import xml.etree.ElementTree as ET

from .contract import canonical, digest
from .sources import sha, verify_bundle

VERSION = 'materials-pdf-layout-context/1'


def build(bundle, *, pdf_sha256, bbox_xml, producer):
    verify_bundle(bundle)
    if (not isinstance(bbox_xml,str) or len(bbox_xml.encode())>8_000_000
            or '<!ENTITY' in bbox_xml.upper()):
        raise ValueError('pdf_layout_xml_bound_or_entity')
    docs={d.id:d for d in bundle.documents if d.source_kind=='original_pdf' and d.source_sha256==pdf_sha256}
    if not docs or any(d.processing_permission!='allowed' for d in docs.values()):
        raise ValueError('pdf_layout_source_not_admitted')
    pages={}
    for block in bundle.blocks:
        match=re.fullmatch(r'pdf_page:(\d+)',block.locator)
        if block.document_id in docs and match:
            pages.setdefault(int(match[1]),[]).append(block.id)
    def children(node,name):
        return [c for c in node if c.tag.rsplit('}',1)[-1]==name]
    def box(node):
        values=[float(node.attrib[k]) for k in ['xMin','yMin','xMax','yMax']]
        if not all(math.isfinite(v) for v in values) or values[0]>values[2] or values[1]>values[3]:
            raise ValueError('pdf_layout_invalid_box')
        return values
    # Poppler can emit font control codes that XML 1.0 forbids. Preserve its
    # exact output and mark every replacement in the auxiliary parse; never
    # silently delete a possible formula glyph or repair the original bundle.
    replacements=[]
    def xml_character(c):
        n=ord(c)
        return n in {9,10,13} or 32<=n<=0xd7ff or 0xe000<=n<=0xfffd or 0x10000<=n<=0x10ffff
    clean=[]
    for index,c in enumerate(bbox_xml):
        if xml_character(c):clean.append(c)
        else:
            marker=f'[UNRESOLVED-PDF-GLYPH-U+{ord(c):04X}]'
            replacements.append(dict(xml_character_offset=index,codepoint=ord(c),auxiliary_marker=marker))
            clean.append(marker)
    root=ET.fromstring(''.join(clean));result=[]
    for number,page in enumerate([n for n in root.iter() if n.tag.rsplit('}',1)[-1]=='page'],1):
        if number not in pages:continue
        blocks=[]
        for fi,flow in enumerate(children(page,'flow'),1):
            for bi,block in enumerate(children(flow,'block'),1):
                lines=[]
                for line in children(block,'line'):
                    words=[dict(box=box(word),text=''.join(word.itertext())) for word in children(line,'word')]
                    lines.append(dict(box=box(line),words=words,text=' '.join(w['text'] for w in words)))
                if lines:
                    blocks.append(dict(id=f'P{number}:F{fi}:B{bi}',flow_id=f'P{number}:F{fi}',box=box(block),
                        lines=lines,text='\n'.join(line['text'] for line in lines)))
        result.append(dict(page=number,width=float(page.attrib['width']),height=float(page.attrib['height']),
            original_block_ids=pages[number],blocks=blocks))
    if {p['page'] for p in result}!=set(pages) or any(not p['blocks'] for p in result):
        raise ValueError('pdf_layout_page_coverage_mismatch')
    body=dict(schema=VERSION,bundle_sha256=digest(bundle.model_dump()),pdf_sha256=pdf_sha256,
        bbox_xml=bbox_xml,bbox_xml_sha256=sha(bbox_xml.encode()),producer=producer,pages=result,
        xml_parse_replacements=replacements,
        text_is_auxiliary_parser_output=True,original_source_modified=False,
        flow_order_is_parser_heuristic=True,semantic_reading_order_verified=False,scientific_acceptance=False)
    return dict(body,layout_sha256=digest(body))


def verify(layout,bundle):
    rebuilt=build(bundle,pdf_sha256=layout['pdf_sha256'],bbox_xml=layout['bbox_xml'],producer=layout['producer'])
    if rebuilt!=layout:raise ValueError('pdf_layout_reconstruction_mismatch')
    return rebuilt


def render(layout,bundle):
    verify(layout,bundle)
    pages=[dict(page=p['page'],width=p['width'],height=p['height'],original_block_ids=p['original_block_ids'],
        blocks=[dict(id=b['id'],box=[round(v,1) for v in b['box']],text=b['text'])
            for b in p['blocks']]) for p in layout['pages']]
    return '\n'.join(['AUXILIARY ORIGINAL-PDF LAYOUT (untrusted source data):',
        'Displayed coordinates are PDF points rounded to 0.1 point; the retained layout preserves full precision. '
        'Each block preserves a parser text region and its page box. IDs retain page/flow/block indices. '
        'Flow IDs/order are parser heuristics, not verified paragraph or experiment relationships. '
        'UNRESOLVED-PDF-GLYPH markers retain unparseable font controls; do not infer their symbols. '
        'Read column continuations, figure panels, captions and run labels together. Nearby figure '
        'text can belong to a different experiment. Do not digitize a curve from text labels. '
        'All final evidence still selects the original SOURCE span IDs; do not copy this layout '
        'as a contiguous original-source quote or infer ownership from proximity.',canonical(pages)])
