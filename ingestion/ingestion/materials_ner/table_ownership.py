"""Compile exact cell/row/header/footnote candidates from a retained TeX ledger.

This is an opt-in source-structure audit, not a semantic extractor. The caller
must declare the marker convention; proximity never establishes ownership.
Only simple ampersand-separated rows and explicit footnotemark commands are
supported. Unsupported TeX stays unresolved instead of being silently repaired.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

POLICY = 'materials-table-ownership/1'


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _witness(block, start, end):
    text=block.text[start:end]
    return dict(block_id=block.id,block_sha256=_hash(block.text),start_char=start,end_char=end,
                quote=text,quote_sha256=_hash(text))


def _source(blocks, value):
    _require(isinstance(value,dict),'table_source_shape')
    block=blocks.get(value.get('block_id'))
    _require(block is not None,'table_source_block')
    start,end=value.get('start_char'),value.get('end_char')
    _require(type(start) is int and type(end) is int and 0<=start<end<=len(block.text),'table_source_bounds')
    expected=_witness(block,start,end)
    _require(all(value.get(k)==v for k,v in expected.items()),'table_source_changed')
    return block,expected


def _cells(block, start, end):
    raw=block.text[start:end]
    _require(raw.endswith('\\\\') and '\n' not in raw and '\\&' not in raw,'table_row_unsupported')
    body=raw[:-2]
    _require(not any(x in body for x in ('\\multicolumn','\\multirow','\\begin{')),'table_spanning_cell_unsupported')
    cells=[];offset=start
    for part in body.split('&'):
        a=offset+len(part)-len(part.lstrip());b=offset+len(part.rstrip())
        cells.append(None if a==b else _witness(block,a,b));offset+=len(part)+1
    return cells


def _definitions(block, source):
    """Read explicit small-text definitions without capturing isotope labels."""
    result={};text=source['quote'];base=source['start_char']
    for m in re.finditer(r'(?m)^[ \t]*(\$\^\{([a-z]|[1-9][0-9]*)\}\$)\{\\small\b',text):
        label=m.group(2);start=m.start(1);brace=m.end(1);depth=0;end=None
        for i in range(brace,len(text)):
            if i and text[i-1]=='\\':continue
            if text[i]=='{':depth+=1
            if text[i]=='}':
                depth-=1
                if depth==0:end=i+1;break
        _require(end is not None,'table_footnote_unclosed')
        _require(label not in result,'table_footnote_duplicate_definition')
        result[label]=_witness(block,base+start,base+end)
    return result


def compile_ownership(bundle, ledger, *, marker_convention):
    _require(marker_convention in {'numeric','numeric_to_lower_alpha'},'table_marker_convention_required')
    blocks={block.id:block for block in bundle.blocks};out=[];seen=set();locations=set()
    for row in ledger:
        _require(type(row.get('id')) is str and row['id'] and row['id'] not in seen,'table_cell_identity')
        seen.add(row['id']);sources={}
        for key in ('source_cell','source_row','source_header','row_label','table_footnotes'):
            block,w=_source(blocks,row[key]);sources[key]=w
        _require(len({v['block_id'] for v in sources.values()})==1,'table_cross_block_binding')
        block=blocks[sources['source_cell']['block_id']];source_row=sources['source_row']
        parsed=_cells(block,source_row['start_char'],source_row['end_char'])
        col=row.get('column')
        _require(type(col) is int and 2<=col<=len(parsed),'table_column_index')
        _require(parsed[col-1]==sources['source_cell'] and parsed[0]==sources['row_label'],'table_row_column_binding')
        place=(block.id,sources['source_cell']['start_char'],sources['source_cell']['end_char'])
        _require(place not in locations,'table_duplicate_cell');locations.add(place)
        header=sources['source_header'];a=block.text.rfind('\n',0,header['start_char'])+1
        b=block.text.find('\n',header['end_char'])
        _require(b>=0,'table_header_line')
        headers=_cells(block,a,b)
        _require(len(headers)==len(parsed) and headers[col-1]==header,'table_header_column_binding')
        # Row, header and notes must belong to the same enclosing table.
        begin=block.text.rfind('\\begin{tabular}',0,source_row['start_char'])
        end=block.text.find('\\end{tabular}',source_row['end_char'])
        table_end=block.text.find('\\end{table',end)
        notes=sources['table_footnotes']
        _require(0<=begin<header['start_char']<source_row['start_char']<end<notes['start_char']<notes['end_char']<=table_end,
                 'table_context_ownership')
        _require('\\end{tabular}' not in block.text[begin:source_row['end_char']], 'table_context_ownership')
        marks=list(re.finditer(r'\\footnotemark\[([1-9][0-9]*)\]',sources['source_cell']['quote']))
        _require(sources['source_cell']['quote'].count('\\footnotemark')==len(marks),'table_footnote_marker_unsupported')
        _require(row.get('footnote_markers')==[m.group(1) for m in marks],'table_footnote_marker_changed')
        definitions=_definitions(block,notes);links=[]
        for m in marks:
            number=int(m.group(1))
            _require(marker_convention!='numeric_to_lower_alpha' or number<=26,'table_marker_out_of_range')
            label=chr(96+number) if marker_convention=='numeric_to_lower_alpha' else str(number)
            _require(label in definitions,'table_footnote_definition_missing')
            start=sources['source_cell']['start_char']+m.start()
            links.append(dict(marker=m.group(1),label=label,marker_source=_witness(block,start,start+len(m.group())),
                              definition_source=definitions[label]))
        out.append(dict(id=row['id'],column=col,source_cell=sources['source_cell'],source_row=source_row,
            row_label=sources['row_label'],source_header=header,footnotes=links))
    return dict(policy=POLICY,marker_convention=marker_convention,cells=out,
                construction_mode='deterministic_source_structure',scientific_acceptance=False,ml_eligible=False)


def select_cell(compiled, cell_id, *, row_label, column_header, footnote_label=None):
    """Reject a proposed row/column/footnote join that disagrees with the source."""
    _require(compiled.get('policy')==POLICY,'table_policy')
    matches=[c for c in compiled['cells'] if c['id']==cell_id]
    _require(len(matches)==1,'table_cell_identity')
    cell=matches[0]
    _require(cell['row_label']['quote']==row_label and cell['source_header']['quote']==column_header,
             'table_selection_owner_mismatch')
    _require(footnote_label is None or footnote_label in {f['label'] for f in cell['footnotes']},
             'table_selection_footnote_mismatch')
    return deepcopy(cell)


def verify_ownership(bundle, ledger, compiled):
    expected=compile_ownership(bundle,ledger,marker_convention=compiled.get('marker_convention'))
    _require(compiled==expected,'table_compiled_ownership_changed')
    return expected
