"""Finite literal direction fragments, never inferred axes or normalized prose."""
import re
from .evidence import source_catalog,selected_quotes

POLICY='declared_literal_source_v1'
_REL=r'(?:\$(?:\\perp|\\parallel)\$|\\perp|\\parallel|[⊥∥])'
_AXIS=r'(?:\$(?:ab|[abc])\$|(?:ab|[abc])(?:[- ](?:axis|plane))?)(?![A-Za-z])'
_PATTERN=re.compile(r'(?:(?:\$[HB]\$|\b[HB])\s*)?'+_REL+r'\s*'+_AXIS+
    r'|\b(?:parallel|perpendicular)\s+to\s+(?:the\s+)?'+_AXIS,re.I)


def context(path,bundle,source_span_ids):
    if not re.fullmatch(r'/states/\d+/conditions/\d+/orientation_raw',path):return None
    catalog=source_catalog(bundle);choices={}
    for quote in selected_quotes(catalog,source_span_ids):
        for match in _PATTERN.finditer(quote['quote']):
            start=quote['start_char']+match.start();end=quote['start_char']+match.end()
            spans=[s for s in quote['span_ids'] if catalog['spans'][s]['start_char']<end and catalog['spans'][s]['end_char']>start]
            choices[f'D{len(choices)+1}']=dict(raw=match.group(),block_id=quote['block_id'],
                start_char=start,end_char=end,source_span_ids=spans)
    return dict(policy=POLICY,choices=choices,scientific_direction_verified=False,
        limitation='Finite perpendicular/parallel direction syntax only. A source match does not prove its applicability to this result. Unsupported angles, planes or notation remain unresolved.')
