"""Explicit original-image reading scope; no scientific facts or label hints.

V1 prompts remain byte-for-byte unchanged. V2 names original text units and
image regions so printed labels can have explicit TARGET ownership.
"""
import math

from .contract import canonical
from . import page_images

VERSION = 'materials-reviewed-reader-scope/2'
LEGACY = 'materials-reviewed-reader-scope/1'


def shape(scope):
    fields = {'schema', 'preflight', 'passages', 'image_capture'}
    if scope.get('schema') == VERSION: fields.add('visual_scope')
    if scope.get('schema') not in {VERSION, LEGACY} or set(scope) != fields:
        raise ValueError('reader_scope_shape')


def region(rect):
    if (not isinstance(rect, list) or len(rect) != 4
            or any(type(x) not in {int, float} or not math.isfinite(x) for x in rect)
            or not 0 <= rect[0] < rect[2] <= 1 or not 0 <= rect[1] < rect[3] <= 1):
        raise ValueError('reader_visual_region_bounds')


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def visual_units(scope, capture, bundle):
    """Pure geometry/source replay, also used by portable projection receipts."""
    shape(scope)
    if scope['schema'] == LEGACY: return []
    units = scope['visual_scope']
    if not isinstance(units, list) or len(units) > 64:
        raise ValueError('reader_visual_scope_count')
    if capture is None:
        if scope['image_capture'] is not None or units: raise ValueError('reader_visual_capture_required')
        return []
    if scope['image_capture'] is None: raise ValueError('reader_visual_capture_unbound')
    page_images.verify(capture, bundle)
    pages = {p['image_id']: p for p in capture['pages']}; blocks = {b.id: b for b in bundle.blocks}
    result = []; seen_images = set()
    for unit in units:
        if (not isinstance(unit, dict) or set(unit) != {'image_id', 'role', 'region'}
                or unit['image_id'] not in pages or unit['role'] not in {'target', 'context'}):
            raise ValueError('reader_visual_scope_shape')
        region(unit['region']); page = pages[unit['image_id']]; seen_images.add(page['image_id'])
        for prior in result:
            a, b = prior['region'], unit['region']
            if (prior['image_id'] == unit['image_id'] and max(a[0], b[0]) < min(a[2], b[2])
                    and max(a[1], b[1]) < min(a[3], b[3])):
                raise ValueError('reader_visual_regions_overlap')
        if unit['role'] == 'target':
            # The current adapter supports whole original pages in the text
            # TARGET inventory; smaller visual rectangles may select within it.
            if not all(any(p['block_id'] == identifier and p['role'] == 'target'
                           and p['start_char'] == 0 and p['end_char'] == len(blocks[identifier].text)
                           for p in scope['passages']) for identifier in page['original_block_ids']):
                raise ValueError('reader_visual_target_requires_target_page')
        result.append(dict(unit, pdf_page=page['pdf_page'], pdf_sha256=page['pdf_sha256'],
            image_sha256=page['sha256'], width=page['width'], height=page['height'],
            original_block_ids=page['original_block_ids']))
    if seen_images != set(pages): raise ValueError('reader_visual_page_role_missing')
    return result


def render(scope, capture, bundle):
    units = visual_units(scope, capture, bundle)
    return '\n'.join([
        '\nORIGINAL SOURCE COORDINATE INDEX (scope metadata, not scientific conclusions)',
        'Image IDs P1, P2, ... follow the attachment order. Coordinates are normalized [left, top, right, bottom].',
        'A visual TARGET region is part of TARGET original source, including explicit printed labels that text extraction did not recover.',
        'Pixels outside a declared TARGET region are CONTEXT only. Do not digitize unlabelled curves.',
        'TARGET is a reading boundary, not a claim that all samples or traces share a method, criterion or condition.',
        canonical(units), 'END ORIGINAL SOURCE COORDINATE INDEX\n'])


def require_target(binding, scope, capture, bundle):
    """A text page or caption cannot override an explicitly CONTEXT image region."""
    if scope['schema'] != VERSION: return
    units = visual_units(scope, capture, bundle)
    if not any(u['role'] == 'target' and u['image_sha256'] == binding['image_sha256']
               and u['pdf_sha256'] == binding['source_sha256'] and u['pdf_page'] == binding['page']
               and contains(u['region'], binding['region']) for u in units):
        raise ValueError('reader_visual_evidence_outside_target_region')
