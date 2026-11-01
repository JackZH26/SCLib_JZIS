"""Compile hash-bound Materials display annotations from retained paper sources.

Inputs are read-only. No TeX is executed and no network is used. The resulting
small registry ships with the API; raw assertions and frozen CSVs stay intact.
Run with the locked ingestion environment (pypdf is only needed by this tool).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from services.materials_source_notation import definitions, expand, sha256

FIELDS = ('formula','sample_label','sample_form','substrate','criterion_raw',
          'method_raw','measurement_context','pressure_raw','paper_title')


def display_fields(row):
    fields = {key:row.get(key) for key in FIELDS}
    fields['quantity_raw'] = (row.get('quantity') or {}).get('raw')
    fields.update({f'composition:{i}':x['formula'] for i,x in enumerate(row.get('compositions') or [])})
    return {key:value for key,value in fields.items() if isinstance(value,str)}


def pdf_glyphs(bundle, cache):
    from pypdf import PdfReader
    from pypdf._codecs import _symbol_encoding
    from fontTools.ttLib import TTFont
    from io import BytesIO
    observations = collections.defaultdict(set)
    refs = []
    for doc in bundle['documents']:
        if doc['source_kind'] != 'original_pdf':
            continue
        path=cache/'sources'/doc['source_sha256']
        if not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=doc['source_sha256']:
            raise ValueError('PDF source hash mismatch')
        reader=PdfReader(path)
        font_names={}
        def embedded_name(font):
            if not font:
                return ''
            key=id(font)
            if key not in font_names:
                base=str(font.get('/BaseFont','')).split('+')[-1].lstrip('/')
                try:
                    desc=font.get('/DescendantFonts',[font])[0].get_object().get('/FontDescriptor')
                    desc=desc.get_object() if desc else {}
                    if '/FontFile2' in desc:
                        tt=TTFont(BytesIO(desc['/FontFile2'].get_object().get_data()))
                        family=tt['name'].getDebugName(1)
                        if family=='Symbol':
                            base='Symbol'
                except (KeyError, ValueError):
                    pass
                font_names[key]=base
            return font_names[key]
        for number,page in enumerate(reader.pages,1):
            def visit(text, cm, tm, font, size):
                for char in set(text):
                    if not '\ue000' <= char <= '\uf8ff':
                        continue
                    font_name=embedded_name(font)
                    code=ord(char)-0xf000
                    decoded=_symbol_encoding[code] if font_name in {'Symbol','SymbolMT','SymbolMT,Italic'} and 0<=code<256 else ''
                    if decoded=='\0' or decoded==char or any('\ue000'<=c<='\uf8ff' for c in decoded):
                        decoded=''
                    observations[char].add((font_name,decoded))
                    item=dict(character=f'U+{ord(char):04X}',font=font_name,
                              display=decoded,page=number,source_sha256=doc['source_sha256'])
                    if item not in refs:
                        refs.append(item)
            page.extract_text(visitor_text=visit)
    mapping={}
    for char,values in observations.items():
        if len(values)==1:
            font,decoded=next(iter(values))
            if decoded:
                mapping[char]=decoded
    return mapping,refs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-data',type=Path,required=True)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    args.report_dir.mkdir(parents=True,exist_ok=True)
    public=json.loads(args.public_data.read_text())
    review_path=Path(__file__).resolve().parents[1]/'api/services/notation_data/materials_display_reviewed_v1.json'
    reviewed=json.loads(review_path.read_text())['entries'] if review_path.is_file() else []
    needed={r['paper_id'] for r in public['items'] if any(
        '\\' in t or re.search('[\ue000-\uf8ff]',t) for t in display_fields(r).values())}
    needed.update(r['paper_id'] for r in reviewed)
    pins=collections.defaultdict(set)
    for line in args.dataset.open():
        row=json.loads(line)
        if row['paper_id'] in needed:
            pins[row['id']].update(e['source_representation_sha256'] for e in row['evidence']
                                  if e.get('source_representation_sha256'))
    bundles={}; glyph_cache={}; report=[]; records={}
    for row in public['items']:
        fields=display_fields(row)
        if row['paper_id'] not in needed or len(pins[row['id']])!=1:
            continue
        pin=next(iter(pins[row['id']]))
        if pin not in bundles:
            path=args.cache/'bundles'/(pin+'.json')
            if not path.is_file():
                path=args.dataset.parent.parent/'evidence'/(pin+'.json')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=pin:
                raise ValueError('Bundle hash mismatch')
            bundle=json.loads(raw)
            for block in bundle['blocks']:
                if sha256(block['text'])!=block['sha256']:
                    raise ValueError('Member hash mismatch')
            blocks=[b for b in bundle['blocks'] if b['locator'].lower().endswith(('.tex','.sty','.cls'))]
            bundles[pin]=(bundle,definitions(blocks))
        bundle,macros=bundles[pin]
        versions=sorted({d['publication_version'] for d in bundle['documents'] if d['publication_version']})
        if bundle['work_id']!=row['paper_id'] or (versions and versions!=row['source_versions']):
            report.append(dict(id=row['id'],issue='source_version_mismatch'))
            continue
        # Older retained GCS bundles lack a document revision. They are still
        # bound to this assertion by its exact evidence-bundle SHA, checked by
        # the API in addition to the assertion's publication versions.
        versions=row['source_versions']
        mapping={};font_refs=[]
        if any(re.search('[\ue000-\uf8ff]',v) for v in fields.values()):
            path=args.report_dir/(pin+'.fonts-v2.json')
            if pin not in glyph_cache:
                if path.is_file():
                    cached=json.loads(path.read_text())
                    glyph_cache[pin]=(cached['mapping'],cached['references'])
                else:
                    logging.getLogger('pypdf').setLevel(logging.ERROR)
                    glyph_cache[pin]=pdf_glyphs(bundle,args.cache)
                    path.write_text(json.dumps(dict(mapping=glyph_cache[pin][0],
                        references=glyph_cache[pin][1]),ensure_ascii=False,indent=2))
            mapping,font_refs=glyph_cache[pin]
            mapping={k:v for k,v in mapping.items() if all(ord(c)>=32 and ord(c)!=127 for c in v)}
        changed={};used={}
        for key,raw in fields.items():
            resolved,refs=expand(raw,macros)
            resolved=''.join(mapping.get(c,c) for c in resolved)
            if resolved==raw:
                continue
            changed[key]=dict(raw_sha256=sha256(raw),text=resolved)
            for ref in refs:
                used[ref['command']]=ref
        manual_refs=[]
        for correction in reviewed:
            key=correction['field'];raw=fields.get(key)
            if correction['paper_id']!=row['paper_id'] or correction['bundle_sha256']!=pin or correction['source_versions']!=versions:
                continue
            if raw is not None and sha256(raw)==correction['raw_sha256']:
                proof=correction['evidence']
                if not any(b['sha256']==proof['block_sha256'] and b['locator']==proof['locator'] for b in bundle['blocks']):
                    raise ValueError('Reviewed correction source mismatch')
                changed[key]=dict(raw_sha256=sha256(raw),text=correction['text'])
                if key == 'formula' and correction.get('note'):
                    changed[key]['note']=correction['note']
                manual_refs.append(proof)
        if changed:
            refs=[r for r in font_refs if chr(int(r['character'][2:],16)) in mapping and any(chr(int(r['character'][2:],16)) in fields[k] for k in changed)]
            records[row['id']]=dict(paper_id=row['paper_id'],source_versions=versions,
                bundle_sha256=pin,material_id=row['material_id'],fields=changed,
                definitions=sorted(used.values(),key=lambda x:x['command']),
                font_mappings=refs,reviewed_sources=manual_refs)
    payload=dict(version='materials-source-display/1',records=records)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    summary=dict(results=len(public['items']),annotated_results=len(records),
        papers=len({r['paper_id'] for r in records.values()}),
        fields=sum(len(r['fields']) for r in records.values()),
        macros=sorted({d['command'] for r in records.values() for d in r['definitions']}),
        issues=report)
    (args.report_dir/'COMPILE_REPORT.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
