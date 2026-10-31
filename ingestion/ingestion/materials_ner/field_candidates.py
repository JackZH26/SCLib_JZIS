"""Contiguous source candidates and exact quantity names, not semantic approval.

Percent-comment handling is finite. It does not execute TeX conditionals/macros
or establish publication status. All ranges remain in the unmodified block.
"""
import re
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from functools import lru_cache
from threading import RLock

from .field_quantity import strict_unit

POLICY = 'active-source-field-candidates/1'

# Lexical positions only. No model choices, resolved scientific values or
# validation decisions are cached. Dense/large blocks use the identical scan
# without retaining it. Return containers are always fresh and caller-owned.
_MAX_SOURCE_CHARS = 1_000_000
_MAX_MATH_RANGES = 32_768
_MAX_MATH_ENTRIES = 8
_math_cache = OrderedDict()
_math_lock = RLock()


def _scan_active_ranges(text, *, tex=True):
    """Split at percent comments, recognizing odd/even escaped backslashes.

    Call on a complete source block, before intersecting its catalog spans. A
    span beginning halfway through a commented line must not reactivate it.
    """
    if not tex:
        return [(0, len(text))] if text else []
    ranges = []
    cursor = offset = 0
    for line in text.splitlines(keepends=True):
        for i, char in enumerate(line):
            if char != '%':
                continue
            j = i - 1
            while j >= 0 and line[j] == '\\':
                j -= 1
            if (i - 1 - j) % 2:
                continue
            start = offset + i
            if cursor < start:
                ranges.append((cursor, start))
            cursor = offset + len(line.rstrip('\r\n'))
            break
        offset += len(line)
    if cursor < len(text):
        ranges.append((cursor, len(text)))
    return ranges


@lru_cache(maxsize=8)
def _cached_active_ranges(text, tex):
    # Cache immutable lexical coordinates, never caller-owned mutable lists,
    # model decisions or validation results. The exact source text and mode are
    # both part of the key; changed source bytes require a fresh scan.
    return tuple(_scan_active_ranges(text, tex=tex))


def _active_index(text, tex):
    if len(text) > _MAX_SOURCE_CHARS:
        return tuple(_scan_active_ranges(text, tex=tex))
    return _cached_active_ranges(text, tex)


def active_ranges(text, *, tex=True):
    """Return fresh source ranges without rescanning a block for every span."""
    return list(_active_index(text, tex))


def active_span_ranges(text, start, end, *, tex=True):
    if not 0 <= start <= end <= len(text):
        raise ValueError('source_span_out_of_bounds')
    ranges = _active_index(text, tex)
    # The immediately preceding range can contain start; later ranges are
    # already ordered and disjoint. Do not scan unrelated source comments.
    offset = max(0, bisect_right(ranges, (start, len(text))) - 1)
    result = []
    for index in range(offset, len(ranges)):
        a, b = ranges[index]
        if a >= end:
            break
        left, right = max(start, a), min(end, b)
        if left < right:
            result.append((left, right))
    return result


def _scan_math_ranges(text, tex, dollar_escape_parity):
    """Preserve historical global delimiter pairing, including comment holds."""
    result = []
    opened = None
    for region, (a, b) in enumerate(_active_index(text, tex)):
        for match in re.finditer(r'(?<!\$)\$(?!\$)', text[a:b]):
            position = a + match.start()
            preceding = position - 1
            while preceding >= 0 and text[preceding] == '\\':
                preceding -= 1
            backslashes = position - 1 - preceding
            if (backslashes % 2) if dollar_escape_parity else (backslashes > 0):
                continue
            if opened is None:
                opened = (position, region)
            else:
                left, opening_region = opened
                if opening_region == region:
                    result.append((left, position + 1))
                opened = None
    return tuple(result)


def _math_index(text, tex, dollar_escape_parity):
    key = (text, tex, dollar_escape_parity)
    with _math_lock:
        cached = _math_cache.get(key)
        if cached is not None:
            _math_cache.move_to_end(key)
            return cached
    ranges = _scan_math_ranges(text, tex, dollar_escape_parity)
    if len(text) <= _MAX_SOURCE_CHARS and len(ranges) <= _MAX_MATH_RANGES:
        with _math_lock:
            _math_cache[key] = ranges
            _math_cache.move_to_end(key)
            while len(_math_cache) > _MAX_MATH_ENTRIES:
                _math_cache.popitem(last=False)
    return ranges


def text_candidates(text, start, end, *, tex=True, dollar_escape_parity=False):
    """Sentence-like clauses and math tokens, never joined across comments."""
    result = []
    for a, b in active_span_ranges(text, start, end, tex=tex):
        part = text[a:b]
        segments = []
        cursor = a
        for match in re.finditer(r'(?<!\d)[.!?]\s+(?=[A-Z\\])', part):
            segments.append((cursor, a + match.start() + 1, 'clause'))
            cursor = a + match.end()
        segments.append((cursor, b, 'clause'))
        for left, right, kind in segments:
            while left < right and text[left].isspace():
                left += 1
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                result.append(dict(kind=kind, start_char=left, end_char=right,
                                   quote=text[left:right]))
    # Index the entire original block once, then select complete contained
    # expressions. Starting inside math or a comment cannot open a new token.
    ranges = _math_index(text, tex, dollar_escape_parity)
    offset = bisect_left(ranges, (start,))
    for index in range(offset, len(ranges)):
        left, right = ranges[index]
        if left >= end:
            break
        if right <= end:
            result.append(dict(kind='math', start_char=left, end_char=right,
                               quote=text[left:right]))
    return result


def select_name(candidate, literal, *, unit=None):
    """Locate an exact unique subphrase; a unit does not name the quantity.

    Ambiguous symbols such as K remain possible names when they differ from
    this occurrence's source unit. Domain meaning still requires source review.
    """
    if not isinstance(literal, str) or not literal.strip() or len(literal) > 160:
        raise ValueError('quantity_name_literal_invalid')
    quote = candidate['quote']
    starts = [m.start() for m in re.finditer(re.escape(literal), quote)]
    if len(starts) != 1:
        raise ValueError('quantity_name_literal_not_unique_in_candidate')
    token = strict_unit(literal)
    if token in {'%', 'percent', 'percentage', 'Hz', 'kHz', 'MHz', 'GHz', 'THz'} or (
            unit is not None and token is not None and token == strict_unit(unit)):
        raise ValueError('unit_only_quantity_name')
    if not re.search(r'[A-Za-z\u0370-\u03ff]', literal):
        raise ValueError('quantity_name_has_no_symbol_or_words')
    offset = starts[0]
    return dict(candidate, quote=literal,
                start_char=candidate['start_char'] + offset,
                end_char=candidate['start_char'] + offset + len(literal),
                context=dict(candidate))
