"""Finite original-text numeric occurrences with reversible character locations.

No model-supplied number enters this parser. Parsing source syntax does not prove
specimen ownership, physical meaning, independence or scientific acceptance.
Unsupported syntax and units without source support remain explicitly unresolved.
"""
from dataclasses import dataclass
import re

from .contract import Quantity
from .quantities import NUMBER, PAREN_NUMBER, lexical, parse_source_numeric
from .sources import sha

POLICY = 'complete-source-numeric-occurrence/1'


@dataclass
class View:
    text: str
    ranges: list[tuple[int,int]]

    def replace(self, pattern, replacement, flags=0):
        pieces=[];ranges=[];end=0
        for m in re.finditer(pattern,self.text,flags):
            pieces.append(self.text[end:m.start()]);ranges.extend(self.ranges[end:m.start()])
            value=replacement(m) if callable(replacement) else replacement
            pieces.append(value)
            location=(self.ranges[m.start()][0],self.ranges[m.end()-1][1])
            ranges.extend([location]*len(value));end=m.end()
        pieces.append(self.text[end:]);ranges.extend(self.ranges[end:])
        self.text=''.join(pieces);self.ranges=ranges

    def span(self,start,end):
        return self.ranges[start][0],self.ranges[end-1][1]


def source_view(text, *, pdf_unicode=False):
    view=View(text,[(i,i+1) for i in range(len(text))])
    # Wrapper contents retain the complete wrapper's original location.
    view.replace(r'\\(?:textrm|mathrm|text|mbox)\{([^{}]*)\}',lambda m:lexical(m[1]))
    view.replace(r'(?<!\\)\$', '')
    view.replace(r'\\[,;!]', ' ')
    for command,value in [(r'approx|simeq|sim|cong','≈'),(r'lesssim','≈≤'),(r'gtrsim','≈≥'),
                          (r'leq?','≤'),(r'geq?','≥'),(r'pm','±'),(r'AA|angstrom','Å'),
                          (r'mu','μ'),(r'Omega','Ω')]:
        view.replace(r'\\(?:'+command+r')(?![A-Za-z])',value)
    view.replace(r'\\%', '%')
    view.replace('−','-')
    if pdf_unicode:
        # Opt in: historical catalogs retain their original lexical policy.
        # The one-character substitution keeps the exact source occurrence.
        view.replace('∼','≈')
        view.replace('µ','μ')
        view.replace('Ω','Ω')
    view.replace(r'\^\{\s*([+-]?\d+)\s*\}',lambda m:'^'+m[1])
    view.replace(rf'({NUMBER})\s*(?:\\times|\\cdot|×|·)\s*10\s*\^\s*([+-]?\d+)',
                 lambda m:m[1]+'e'+m[2])
    view.replace(r'([+-])\s+(?=\d|\.\d)',lambda m:m[1])
    view.replace(rf'\bbetween\s+({NUMBER})\s+and\s+({NUMBER})',lambda m:m[1]+' to '+m[2],flags=re.I)
    for phrase,symbol in [(r'cannot\s+exceed|does\s+not\s+exceed|at\s+most|not\s+exceeding','≤'),
            (r'more\s+than|greater\s+than|above','>'),(r'less\s+than|below','<'),
            (r'at\s+least|not\s+less\s+than','≥'),(r'about|around|approximately|roughly|nearly','≈')]:
        view.replace(r'\b(?:'+phrase+r')\s+(?=[+\-\d.(])',symbol,flags=re.I)
    return view


# Explicit tokens only. An unknown unit is not assigned a registered dimension.
UNIT_WORD = r'(?:angstroms?|μ_?\{?B\}?|emu|mol|kHz|MHz|GHz|Hz|kG|mT|μT|GPa|MPa|kPa|Pa|kOe|Oe|meV|eV|mK|nm|mm|cm|pm|μm|Pr|Cu|K|T|G|Å|%|J|A|V|Ω|s|m)'
WORD = re.compile(UNIT_WORD+r'(?![A-Za-z])')
PDF_WORD = re.compile(r'(?:μΩ|nA|pA|μA|mA|'+UNIT_WORD+r')(?![A-Za-z])')
NUMERIC = re.compile(rf'(?<![\w.\\])(?P<prefix>(?:≈\s*[<>≤≥]|[≈<>≤≥~])\s*)?'
    rf'(?P<open>\()?\s*(?P<number>{PAREN_NUMBER}|{NUMBER})'
    rf'(?P<error>\s*±\s*{NUMBER})?'
    rf'(?P<interval>\s*(?:to|–|—|--|-)\s*{NUMBER})?'
    rf'(?P<close>\))?')


def unit_extent(text,start, *, pdf_unicode=False):
    """Consume complete known-token compounds, never a bare denominator prefix."""
    cursor=start;word=PDF_WORD if pdf_unicode else WORD
    while cursor<len(text) and (text[cursor].isspace() or text[cursor]=='~'):cursor+=1
    beginning=cursor;stack=[];seen=False;last=None
    while cursor<len(text):
        if text[cursor] in '([':
            stack.append(text[cursor]);cursor+=1;continue
        m=word.match(text,cursor)
        if m:
            seen=True;cursor=m.end()
            exponent=re.match(r'\s*(?:\^[+-]?\d+|[+-]\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)' if pdf_unicode else r'\^[+-]?\d+',text[cursor:])
            if exponent:cursor+=exponent.end()
            if not stack:last=cursor
        else:break
        while cursor<len(text) and text[cursor] in ')]' and stack:
            if (stack[-1],text[cursor]) not in {('(',')'),('[',']')}:break
            stack.pop();cursor+=1
            if not stack:last=cursor
        gap=re.match(r'[\s~]*' if pdf_unicode else r'[ \t~]*',text[cursor:]);candidate=cursor+gap.end()
        if candidate<len(text) and text[candidate] in '/.*·-':
            following=candidate+1
            while following<len(text) and text[following].isspace():following+=1
            if word.match(text,following) or text[following:following+1] in {'(','['}:
                cursor=following;continue
            # A slash with unknown symbolic denominator must stay unresolved.
            if text[candidate]=='/' and re.match(r'[A-Za-z\\μ]',text[following:]):
                return beginning,last,True
        if word.match(text,candidate):cursor=candidate;continue
        if stack and text[candidate:candidate+1] in {')',']'}:
            cursor=candidate
            while cursor<len(text) and stack and text[cursor] in ')]':
                if (stack[-1],text[cursor]) not in {('(',')'),('[',']')}:break
                stack.pop();cursor+=1
                if not stack:last=cursor
            break
        if not stack and text[candidate:candidate+1] in {')',']'}:break
        break
    return beginning,last, bool(stack)


def source_fragment(text,view,start,end):
    a,b=view.span(start,end)
    return dict(start_char=a,end_char=b,quote=text[a:b],quote_sha256=sha(text[a:b].encode()))


def source_candidates(text, *, pdf_unicode=False):
    view=source_view(text,pdf_unicode=pdf_unicode);value=view.text;rows=[];covered=0
    for match in NUMERIC.finditer(value):
        if match.start()<covered:continue
        # Do not turn isotope labels, subscripts or equation powers into results.
        before=value[max(0,match.start()-25):match.start()]
        if re.search(r'[_^]\{?\s*$',before):continue
        start,end=match.start(),match.end()
        # Leading whitespace belongs to context, not the source number.
        while start<end and value[start].isspace():start+=1
        prefix=match['prefix'] or ''
        issues=[]
        if re.search(r'\bbetween\b',before,re.I):
            issues.append('unsupported_range_member_requires_review')
        if re.search(rf'{NUMBER}\s*(?:[+*/-]|\bto|±)\s*$',before):
            issues.append('continuation_from_previous_numeric_requires_review')
        if re.search(UNIT_WORD+r'\s*(?:to|--?|–|—)\s*$',before):
            issues.append('continuation_from_previous_numeric_requires_review')
        if match['open'] and re.search(rf'(?:[+-]|{PAREN_NUMBER}|{NUMBER})\s*$',before):
            issues.append('numeric_parenthesis_context_requires_review')
        # A malformed/second parenthesis can prevent the regex from consuming
        # its opening delimiter. Do not promote its interior as another value.
        if re.search(rf'(?:{PAREN_NUMBER}|{NUMBER})\s*\(\s*$',before):
            issues.append('numeric_parenthesis_context_requires_review')
        if bool(match['open'])!=bool(match['close']):
            # A parenthesis may belong to the prose enclosing the expression.
            if match['close'] and not match['open']:end-=1
            else:issues.append('unbalanced_numeric_parenthesis')
        unit_start,unit_end,incomplete_unit=unit_extent(value,end,pdf_unicode=pdf_unicode)
        end=unit_end or end
        if incomplete_unit:issues.append('incomplete_source_unit')
        following=value[end:]
        if re.match(r'\s*(?:\\times|\\cdot|×|\^|±)',following):issues.append('numeric_expression_continues')
        if re.match(rf'\s*(?:to|--?|–|—)\s*{NUMBER}',following):issues.append('numeric_expression_continues')
        if prefix.strip()=='~':issues.append('tex_tilde_approximation_requires_review')
        # Standalone +/- terms are uncertainty evidence, never nominal values.
        uncertainty_prefix=re.search(r'±\s*$',before)
        kind='uncertainty' if uncertainty_prefix else 'value'
        if uncertainty_prefix:start=match.start()-len(before)+uncertainty_prefix.start()
        interval=match['interval'] or ''
        if interval:interval=re.sub(r'^\s*(?:to|–|—|--|-)', ' to ',interval)
        numeric=prefix+match['number']+(match['error'] or '')+interval
        parsed=parse_source_numeric(numeric)
        if parsed['status']!='parsed' or parsed['errors']:issues.append('unsupported_numeric_shape')
        literal=source_fragment(text,view,start,end)
        unit=source_fragment(text,view,unit_start,unit_end) if unit_end else None
        source_unit=lexical(unit['quote']) if unit else None
        evidence={'raw':literal}
        if unit:evidence['unit']=unit
        shape=None
        if parsed['status']=='parsed' and not parsed['errors']:
            shape={k:parsed[k] for k in ['relation','value','lower','upper','approximate']}
            error=parsed['uncertainty']
            shape.update(unit=source_unit,uncertainty=None if error is None else dict(kind='reported_unspecified',
                minus=error,plus=error,level=None,raw=literal['quote']))
        if kind=='uncertainty' and (shape is None or shape['relation']!='exact' or shape['value']<0):
            issues.append('unsupported_uncertainty_term')
        if re.match(r'\s*/\s*\d',following):issues.append('shared_numeric_ratio_requires_review')
        if not source_unit:issues.append('source_unit_not_stated')
        quantity=None
        if kind=='value' and shape and not issues:
            quantity=Quantity(status='reported',raw=literal['quote'],**shape).model_dump()
        rows.append(dict(kind=kind,**literal,source_unit=source_unit,syntax_shape=shape,quantity=quantity,
            evidence=evidence,issues=issues,view_start=start,view_end=end,
            scientific_acceptance=False))
        covered=end
    # A finite comma/and list inherits an explicit bound. Approximation on
    # later members is deliberately held because its prose scope needs review.
    for index,first in enumerate(rows):
        shape=first['syntax_shape']
        if first['kind']!='value' or not shape or (shape['relation']=='exact' and not shape['approximate']):continue
        members=[first]
        for candidate in rows[index+1:]:
            bridge=value[members[-1]['view_end']:candidate['view_start']]
            if (not re.fullmatch(r'\s*(?:,\s*(?:and\s+)?|and\s+)\s*',bridge)
                    or candidate['kind']!='value' or not candidate['syntax_shape']
                    or candidate['syntax_shape']['relation']!='exact'
                    or candidate['source_unit']!=first['source_unit']):break
            members.append(candidate)
        if len(members)<2:continue
        group=source_fragment(text,view,first['view_start'],members[-1]['view_end'])
        for member in members[1:]:
            if shape['relation'] in {'lt','le','gt','ge'}:
                number=member['syntax_shape']['value'];member['syntax_shape'].update(
                    relation=shape['relation'],value=None,lower=number if shape['relation'] in {'gt','ge'} else None,
                    upper=number if shape['relation'] in {'lt','le'} else None)
                member['evidence']['relation']=group
                if not member['issues']:
                    member['quantity']=Quantity(status='reported',raw=member['quote'],**member['syntax_shape']).model_dump()
            if shape['approximate']:
                member['issues'].append('shared_approximation_scope_requires_review');member['quantity']=None
                member['evidence']['approximate']=group
        first['shared_prefix_group']=group
    for row in rows:
        row.pop('view_start');row.pop('view_end')
        if row['quantity'] is None:
            row['unresolved_quantity']=Quantity(status='not_extracted',raw=row['quote']).model_dump()
    return rows


def shared_prefix_shape(quote,raw):
    """Only a uniquely located member of a finite explicit bound list qualifies."""
    rows=[r for r in source_candidates(quote) if r['quote']==raw and 'relation' in r['evidence']]
    return rows[0]['syntax_shape'] if len(rows)==1 and not rows[0]['issues'] else None
