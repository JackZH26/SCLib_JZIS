"""Auxiliary PDF regions mapped to immutable source positions, never ownership.

Only whitespace and alphabetic end-of-line hyphen removal are considered when
matching parser regions. Every match retains the exact original substring. A
repeated short label remains ambiguous; page geometry cannot choose its owner.
"""
import re
from collections import Counter

from .contract import canonical, digest
from . import pdf_layout

VERSION = 'materials-pdf-spatial-view/1'


def _compact(text):
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    return ''.join(text[i] for i in positions), positions


def _variants(text):
    yield 'whitespace_equivalent', _compact(text)[0]
    # This is a labelled parser-matching heuristic, not a repaired source quote.
    joined = re.sub(r'(?<=[A-Za-z])-\n(?=[A-Za-z])', '', text)
    if joined != text:
        yield 'alphabetic_line_wrap_equivalent', _compact(joined)[0]


def _matches(text, blocks):
    for policy, needle in _variants(text):
        found = []
        if not needle:
            continue
        for block in blocks:
            haystack, positions = _compact(block.text)
            offset = 0
            while (offset := haystack.find(needle, offset)) != -1:
                start, end = positions[offset], positions[offset + len(needle) - 1] + 1
                found.append(dict(block_id=block.id, start_char=start, end_char=end,
                    quote=block.text[start:end], locator=block.locator))
                offset += 1
        if found:
            return policy, found
    return 'none', []


def _hint(region, width):
    if re.match(r'^(?:Figure|Fig\.)\s*\d+[.:]', region['text']):
        return 'caption_like'
    if (len(region['lines']) >= 3 and len(region['text']) >= 160
            and region['box'][2] - region['box'][0] > width * .3):
        return 'prose_like'
    return 'short_label_or_other'


def build(layout, original, catalog, target_block_ids):
    blocks = {b.id: b for b in original.blocks}
    texts = catalog['texts']
    # Every original character remains available in the unchanged T catalog.
    for key, block in blocks.items():
        rows = sorted((t for t in texts.values() if t['block_id'] == key), key=lambda t: t['start_char'])
        cursor = 0
        for row in rows:
            if row['start_char'] != cursor or block.text[cursor:row['end_char']] != row['quote']:
                raise ValueError('spatial_source_text_partition_changed')
            cursor = row['end_char']
        if cursor != len(block.text):
            raise ValueError('spatial_source_text_partition_incomplete')
    pages = []
    if layout is not None:
        pdf_layout.verify(layout, original)
        target_pages = {p['page'] for p in layout['pages'] if set(p['original_block_ids']) & set(target_block_ids)}
        displayed = {p for t in target_pages for p in (t - 1, t, t + 1)}
        for page in layout['pages']:
            regions = []
            page_blocks = [blocks[k] for k in page['original_block_ids']]
            for region in page['blocks']:
                policy, matches = _matches(region['text'], page_blocks)
                unique = len(matches) == 1
                mapped = []
                for match in matches:
                    ids = [k for k, t in texts.items() if t['block_id'] == match['block_id']
                        and t['start_char'] < match['end_char'] and t['end_char'] > match['start_char']]
                    mapped.append(dict(match, text_ids=ids))
                left, _, right, _ = region['box']
                center = (left + right) / 2 / page['width']
                narrow = right - left <= page['width'] * .65
                band = 'left_half' if narrow and center < .45 else 'right_half' if narrow and center > .55 else 'crosses_midline'
                regions.append(dict(id=region['id'], box=list(region['box']), horizontal_band=band,
                    appearance_hint=_hint(region, page['width']), auxiliary_text=region['text'],
                    mapping_status='unique' if unique else 'ambiguous' if matches else 'unmapped',
                    matching_policy=policy, original_matches=mapped, selectable_as_position_witness=unique,
                    scientific_role_verified=False, ownership_verified=False))
            # An inspection order only: it creates no paragraph joins or events.
            order = {'crosses_midline': 0, 'left_half': 1, 'right_half': 2}
            regions.sort(key=lambda r: (order[r['horizontal_band']], r['box'][1], r['box'][0], r['id']))
            pages.append(dict(page=page['page'], width=page['width'], height=page['height'],
                target=page['page'] in target_pages, displayed=page['page'] in displayed, regions=regions))
    body = dict(schema=VERSION, original_bundle_sha256=digest(original.model_dump()),
        catalog_sha256=catalog['catalog_sha256'], layout_sha256=None if layout is None else layout['layout_sha256'],
        target_block_ids=list(target_block_ids), pages=pages,
        original_block_aliases={f'B{n}': key for n, key in enumerate(blocks, 1)},
        mapping_counts=dict(Counter(r['mapping_status'] for p in pages for r in p['regions'])),
        original_source_modified=False, all_original_text_preserved=True,
        order_is_spatial_inspection_only=True, semantic_reading_order_verified=False,
        geometry_establishes_subject_identity=False, scientific_acceptance=False)
    return dict(body, view_id=digest(body))


def verify(view, layout, original, catalog, target_block_ids):
    expected = build(layout, original, catalog, target_block_ids)
    if expected != view:
        raise ValueError('spatial_view_reconstruction_mismatch')
    return expected


def render(view):
    pages = []
    aliases = {value: key for key, value in view['original_block_aliases'].items()}
    for page in view['pages']:
        if not page['displayed']:
            continue
        regions = []
        for region in page['regions']:
            source = region['original_matches'][0] if region['selectable_as_position_witness'] else None
            mapped = None if source is None else [aliases[source['block_id']], source['start_char'],
                source['end_char'], source['text_ids'], source['quote']]
            regions.append([region['id'], [round(v, 1) for v in region['box']], region['horizontal_band'],
                region['appearance_hint'], region['mapping_status'], region['matching_policy'],
                mapped, None if source else region['auxiliary_text']])
        pages.append(dict(page=page['page'], target=page['target'], regions=regions))
    return '\n'.join(['COMPACT SPATIAL SOURCE VIEW: ' + view['view_id'],
        'Regions are grouped by page half and vertical position for inspection, not a verified reading order. '
        'Prose-like/caption-like are appearance hints, not scientific roles. Each unique region maps to an '
        'exact original substring with its original T locations. Alphabetic line-wrap matching is explicitly '
        'labelled; the displayed source quote is never the modified parser text. Ambiguous or unmapped '
        'labels are unselectable as region witnesses; their original text remains in the full T catalog. '
        'Inspect column and page continuations before assigning a paragraph to a run. A plot label in the '
        'other column or a nearby caption does not establish that paragraph\'s specimen, method or pressure. '
        'No region join, curve digitization or ownership relation is generated by this view.',
        'REGION COLUMNS: [id, box, band, appearance, mapping, matching_policy, '
        'original_source [block_alias,start,end,T_ids,exact_quote] or null, auxiliary_text_if_unmapped].',
        'ORIGINAL BLOCK ALIASES: ' + canonical(view['original_block_aliases']), canonical(pages)])
