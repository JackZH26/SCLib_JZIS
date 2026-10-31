"""Prepare an explicit-Tc pass from an already byte/version-bound original.

Source partitioning is an automatic reading aid, not a scientific review. The
immutable source, original offsets, comments, exclusions and unresolved graphics
remain available. No extraction result or reference answer is used here.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re

from ingestion.materials_ner import reviewed_reader as rr, paper_coverage, source_audit, production_tc


def prepare(preflight_pin, directory, *, evidence_transport='source_catalog', source_only=False):
    if evidence_transport not in {'source_catalog','quotes'}:
        raise ValueError('unsupported_tc_evidence_transport')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    preflight, bundle, _ = rr.source_input(preflight_pin)
    author=dict(kind='assistant', identity='Production-90 deterministic source partition',
                thread_id='01a159e0-3847-7a80-a4f5-91961c1676db')
    coverage=paper_coverage.seed(preflight_pin,author=author,created_at=datetime.now(timezone.utc).isoformat())
    docs={d.id:d for d in bundle.documents};roles=[];passages=[]
    for block in bundle.blocks:
        raw=block.text
        if not raw:continue
        def role(a,z,kind,note):
            if a==z:return
            roles.append(dict(block_id=block.id,start_char=a,end_char=z,role=kind,note=note,
                anchors=[dict(block_id=block.id,start_char=a,end_char=min(a+100,z),quote=raw[a:min(a+100,z)])]))
            if kind in {'main','supplement'}:
                passages.append(dict(block_id=block.id,start_char=a,end_char=z,role='target'))
        if docs[block.document_id].source_kind=='original_pdf':
            # Published PDF text is eligible evidence. Primary/cited status is
            # determined per result, never inferred from this publication role.
            role(0,len(raw),'main','Automatically included original published PDF page text; primary/cited attribution remains result-level. Figures are not digitized.')
        elif block.locator.endswith(('.bbl','.bib')):
            role(0,len(raw),'bibliography','Bibliographic archive member; not a primary-result target.')
        else:
            masked=source_audit._mask_comments(raw)
            begin=list(re.finditer(r'\\begin\{document\}',masked))
            end=list(re.finditer(r'\\end\{document\}',masked))
            if len(begin)!=1 or len(end)!=1 or begin[0].start()>=end[0].start():
                role(0,len(raw),'unreviewed','No single complete TeX document boundary; requires a separate source route.')
                continue
            a,z=begin[0].start(),end[0].start()
            if re.search(r'\\(?:input|include)\s*\{',masked[a:z]):
                raise ValueError('tc_preparation_unexpanded_tex_includes_require_pdf')
            if re.search(r'\\(?:if(?:false|true|defined|x)?\b|else\b|fi\b)',masked[a:z]):
                role(0,len(raw),'unreviewed','Conditional TeX body requires a rendered-PDF route.')
                continue
            bib=re.search(r'\\(?:begin\{thebibliography\}|bibliography\{)',masked[a:z])
            boundary=a+bib.start() if bib else z
            role(0,a,'excluded','TeX preamble; preserved outside the published-body target.')
            role(a,boundary,'main','Explicit TeX document body; percent comments remain excluded by the existing evidence compiler.')
            if bib:role(boundary,z,'bibliography','Explicit bibliography boundary; later supplements, if present, require a separate source route.')
            role(z,len(raw),'excluded','TeX end-document trailer; preserved outside the published-body target.')
    if not passages:raise ValueError('tc_preparation_no_supported_original_body')
    coverage=paper_coverage.build(bundle=bundle,**{k:(roles if k=='roles' else coverage[k]) for k in
        ['source','roles','visuals','dependencies','supplement','assertions','author','created_at']})
    rr.put(directory/'COVERAGE.json',coverage)
    rr.put(directory/'SCOPE.json',dict(schema='materials-reviewed-reader-scope/2',preflight=preflight_pin,
        passages=passages,image_capture=None,visual_scope=[]))
    # Native /13 already represents the supported Tc scope and is compatible
    # with the existing canonical quantity/condition mapping.
    request=dict(schema='materials-source-projector-input/1',
        scope=rr.reference(directory/'SCOPE.json'),coverage=rr.reference(directory/'COVERAGE.json'))
    if evidence_transport=='source_catalog':request['evidence_transport']='source_catalog'
    rr.put(directory/'PROJECTOR.json',request)
    rr.put(directory/'REQUEST.json',dict(schema=production_tc.INPUT_SCHEMA,
        projector_input=rr.reference(directory/'PROJECTOR.json')))
    p=production_tc.prepare(directory/'REQUEST.json') if not source_only else None
    return dict(work_id=bundle.work_id,input=rr.reference(directory/'REQUEST.json'),
        input_tokens_estimate=p['input_tokens_estimate'] if p else None,source_roles=len(roles),target_passages=len(passages),
        coverage_scope='available_original_text_explicit_tc',source_preflight=preflight_pin)
