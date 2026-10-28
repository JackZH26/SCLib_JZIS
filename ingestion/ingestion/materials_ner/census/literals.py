"""Locate a unique complete source literal without changing source coordinates."""
import re

VERSION = 'materials-census-literal-locator/3'


def resolve_literal(text, raw):
    """Use the coverage whole-literal rule for both matching and addressing.

    Only whitespace layout may differ. Signs, decimal digits, TeX, units and
    Unicode remain literal; this function neither parses nor normalizes values.
    Repeated complete literals remain ambiguous, even if one looks plausible.
    """
    pieces, starts, ends = [], [], []
    for match in re.finditer(r'\S+', text):
        if pieces:
            pieces.append(' ')
            starts.append(match.start())
            ends.append(match.start())
        pieces.extend(match.group())
        starts.extend(range(match.start(), match.end()))
        ends.extend(range(match.start() + 1, match.end() + 1))
    needle = ' '.join((raw or '').split())
    if not needle:
        raise ValueError('literal_not_in_locked_source')
    pattern = r'(?<![\w.+−-])' + re.escape(needle) + r'(?!\w|\.\d)'
    # Include overlapping complete expressions when checking uniqueness.
    hits = list(re.finditer('(?=(' + pattern + '))', ''.join(pieces)))
    if not hits:
        raise ValueError('literal_not_in_locked_source')
    if len(hits) != 1:
        raise ValueError('ambiguous_literal_locator')
    match = hits[0]
    return starts[match.start(1)], ends[match.end(1) - 1]
