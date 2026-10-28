"""Immutable lexical/layout elements for scientific decisions, not annotations.

No paper identifiers, target results or reference answers are used. Source token
ranges copy contiguous original bytes. Table cells retain lexical coordinates;
their scientific column roles and footnote applicability require reader decisions.
"""
from copy import deepcopy
import re

from .contract import Quantity, canonical, digest
from .sources import verify_bundle
from .field_candidates import active_ranges, text_candidates
from .numeric_occurrences import source_candidates
from .field_quantity import strict_unit

VERSION = 'materials-source-elements/1'
UNIT = re.compile(r'(?<![A-Za-z])(?:GPa|MPa|kbar|mT|mK|kHz|Hz|Oe|nm|K|T|%)(?![A-Za-z])')


def _split(text, delimiter):
    """Literal TeX separators outside braces, with escaped characters retained."""
    depth, cursor, i = 0, 0, 0
    while i < len(text):
        if depth == 0 and text.startswith(delimiter, i):
            yield cursor, i
            i += len(delimiter); cursor = i; continue
        if text[i] == '\\':
            i += 2; continue
        if text[i] == '{': depth += 1
        elif text[i] == '}': depth = max(0, depth - 1)
        i += 1
    if cursor < len(text): yield cursor, len(text)


def build(bundle):
    verify_bundle(bundle)
    elements, tables, blocks = {}, [], {}
    def add(prefix, block, start, end, **extra):
        if not 0 <= start < end <= len(block.text): raise ValueError('element_bounds_invalid')
        key = prefix + str(1 + sum(k.startswith(prefix) for k in elements))
        row = dict(id=key, block_id=block.id, start_char=start, end_char=end,
            text=block.text[start:end], target=block.locator.startswith('target:'), **extra)
        if prefix in {'C','L'}:
            row['tokens'] = [dict(start_char=start+m.start(), end_char=start+m.end(), text=m[0])
                             for m in re.finditer(r'\S+', row['text'])]
        elements[key] = row
        return key
    for block in bundle.blocks:
        document = next(d for d in bundle.documents if d.id == block.document_id)
        tex = document.source_kind == 'original_tex'
        blocks[block.id] = dict(locator=block.locator, sha256=block.sha256,
            target=block.locator.startswith('target:'))
        for part in text_candidates(block.text, 0, len(block.text), tex=tex):
            if part['kind']=='clause': add('C',block,part['start_char'],part['end_char'],kind='clause')
        # Context numbers are deliberately included, unlike the previous TARGET-only catalog.
        for left,right in active_ranges(block.text,tex=tex):
            for n in source_candidates(block.text[left:right],pdf_unicode=not tex):
                a,b=left+n['start_char'],left+n['end_char']
                shape=deepcopy(n['syntax_shape'])
                # A tightly adjacent approximation glyph belongs to this number,
                # even when PDF text joins it to the preceding prose word.
                prefix=re.search(r'(?:[∼≈]|\\(?:approx|simeq))\s*$',block.text[max(left,a-16):a])
                if prefix and shape:
                    a=max(left,a-16)+prefix.start();shape['approximate']=True
                issues=[x for x in n['issues'] if x!='source_unit_not_stated']
                add('Q',block,a,b,kind=n['kind'],shape=shape,source_unit=n['source_unit'],issues=issues)
            for match in UNIT.finditer(block.text,left,right):
                add('U',block,match.start(),match.end(),kind='unit',unit=strict_unit(match[0]))
        if not tex: continue
        pattern=re.compile(r'\\begin\{tabular\}\{[^{}]*\}(.*?)\\end\{tabular\}',re.S)
        for match in pattern.finditer(block.text):
            rows=[]
            for a,b in _split(match[1],r'\\'):
                a+=match.start(1);b+=match.start(1)
                # Structural line commands are retained in the enclosing clause.
                skip=re.match(r'(?:\s|\\hline|\\cline\{[0-9-]+\})*',block.text[a:b])
                a+=skip.end()
                while a<b and block.text[b-1].isspace(): b-=1
                if a>=b:continue
                cells=[]
                for c,d in _split(block.text[a:b],'&'):
                    c+=a;d+=a
                    while c<d and block.text[c].isspace():c+=1
                    while d>c and block.text[d-1].isspace():d-=1
                    if c==d: cells.append(None);continue
                    key=add('L',block,c,d,kind='table_cell')
                    elements[key]['numeric_ids']=[k for k,v in elements.items() if k.startswith('Q')
                        and v['block_id']==block.id and c<=v['start_char'] and v['end_char']<=d]
                    elements[key]['unit_ids']=[k for k,v in elements.items() if k.startswith('U')
                        and v['block_id']==block.id and c<=v['start_char'] and v['end_char']<=d]
                    elements[key]['footnote_markers']=re.findall(r'\\footnotemark\[([^\]]+)\]',block.text[c:d])
                    cells.append(key)
                rows.append(dict(row_index=len(rows),cells=cells))
            tables.append(dict(block_id=block.id,start_char=match.start(),end_char=match.end(),rows=rows,
                roles_inferred=False,footnote_applicability_inferred=False))
    # Structural containment only; it does not establish experimental relevance.
    for key,row in elements.items():
        if key.startswith(('Q','U')):
            row['containers']=[k for k,v in elements.items() if k.startswith(('C','L'))
                and row['block_id']==v['block_id'] and v['start_char']<=row['start_char']<row['end_char']<=v['end_char']]
    return dict(schema=VERSION,work_id=bundle.work_id,bundle_sha256=digest(bundle.model_dump()),
        blocks=blocks,elements=elements,tables=tables,scientific_acceptance=False)


def select(catalog, selection):
    """Select a whole element or an explicitly indexed contiguous token range."""
    row=catalog['elements'].get(selection['element_id'])
    if row is None:raise ValueError('unknown_source_element')
    first,last=selection['first_token'],selection['last_token']
    if (first is None)!=(last is None):raise ValueError('partial_token_range')
    a,b=row['start_char'],row['end_char']
    if first is not None:
        tokens=row.get('tokens',[])
        if type(first) is not int or type(last) is not int or not 0<=first<=last<len(tokens):
            raise ValueError('source_token_range_invalid')
        a,b=tokens[first]['start_char'],tokens[last]['end_char']
    return dict(block_id=row['block_id'],start_char=a,end_char=b,
        quote=row['text'][a-row['start_char']:b-row['start_char']])


def number(catalog, numeric_id, unit_id=None, *, dimensionless=False):
    row=catalog['elements'].get(numeric_id)
    if not row or not numeric_id.startswith('Q') or row['kind']!='value' or row['shape'] is None:
        raise ValueError('source_number_not_compilable')
    if row['issues']:raise ValueError('source_numeric_shape_requires_review')
    unit=row['source_unit'];unit_source=None
    if unit_id is not None:
        u=catalog['elements'].get(unit_id)
        if not u or u['kind']!='unit':raise ValueError('source_unit_selection_invalid')
        if unit is not None and strict_unit(unit)!=u['unit']:raise ValueError('source_unit_selection_conflict')
        unit=u['unit'];unit_source=select(catalog,dict(element_id=unit_id,first_token=None,last_token=None))
    if unit is None and dimensionless:unit='1'
    if unit is None:raise ValueError('source_number_unit_unresolved')
    quantity=Quantity(status='reported',raw=row['text'],**dict(row['shape'],unit=unit)).model_dump()
    witness=select(catalog,dict(element_id=numeric_id,first_token=None,last_token=None))
    return quantity,witness,unit_source


def render(catalog):
    lines=[f"WORK {catalog['work_id']}. Source coordinates are immutable. IDs are lexical, not scientific labels."]
    for key,row in catalog['elements'].items():
        role='TARGET' if row['target'] else 'CONTEXT'
        if key.startswith('C'):
            text=row['text']
            # Insert visible token indices without changing stored source bytes.
            for i,t in reversed(list(enumerate(row['tokens']))):
                pos=t['start_char']-row['start_char'];text=text[:pos]+f'<{i}>'+text[pos:]
            lines.append(f"{key} {role} BLOCK {row['block_id']}\n{text}")
        elif key.startswith(('Q','U')):
            lines.append(f"{key} {role} {row['text']!r} in {','.join(row['containers'])}"+
                (f" HOLD {','.join(row['issues'])}" if row.get('issues') else ''))
    for table in catalog['tables']:
        lines.append('TABLE '+table['block_id'])
        for row in table['rows']:
            cells=[]
            for key in row['cells']:
                if key is None:cells.append('EMPTY');continue
                e=catalog['elements'][key]
                cells.append(f"{key}: {e['text']} [numbers={','.join(e['numeric_ids'])}; units={','.join(e['unit_ids'])}]")
            lines.append(f"row {row['row_index']}: "+' | '.join(cells))
    return '\n'.join(lines)
