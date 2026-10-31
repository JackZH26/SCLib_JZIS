"""Neutral original occurrences and pending native-graph correspondence.

This transport never imports a model's role labels or scientific reference
answers. Literal correspondence is an audit aid, not semantic qualification.
"""
from copy import deepcopy
import re

from . import paper_coverage, projection_binding, scoped_evidence
from .contract import canonical, digest

VERSION = 'materials-source-focus/1'
MAX_SELECTED = 8
MAX_INVENTORY = 64
INSTRUCTION = '''
Original occurrence focus is an explicit selection within TARGET. Enumerate the
listed source occurrences in the native graph where scientifically applicable;
use the complete original context to establish their meaning and dependencies.
The focus supplies locations and original expressions, not role or quantity
answers. Do not force every occurrence into a numeric material-result row.
Conditions, sample descriptors, qualitative or symbolic expressions and unresolved
claims must keep their proper native representation or an explicit limitation.
Never invent a scalar for vague language or infer an experimental value from an
equation. Preserve source-supported parent entities needed for a derivation;
additional context entities do not certify another independent observation.
Evidence and scientific fields use the existing native contract. Keep limitations
explicit for any focused occurrence not represented, referring to its source ID.
This selected inventory is partial and cannot certify a complete paper.
'''


def verify(body, bundle, scope, manifest, catalog):
    keys = {'schema', 'work_id', 'bundle_sha256', 'source_catalog_sha256',
            'all_occurrence_ids', 'occurrences'}
    if (not isinstance(body, dict) or set(body) != keys or body['schema'] != VERSION
            or body['work_id'] != bundle.work_id or body['bundle_sha256'] != digest(bundle.model_dump())
            or body['source_catalog_sha256'] != digest(catalog)):
        raise ValueError('source_focus_identity_or_shape')
    all_ids, selected = body['all_occurrence_ids'], body['occurrences']
    if (not isinstance(all_ids, list) or not 0 < len(all_ids) <= MAX_INVENTORY
            or any(not isinstance(key, str) or not re.fullmatch(r'E\d{4}:[1-9]\d*', key) for key in all_ids)
            or len(all_ids) != len(set(all_ids)) or not isinstance(selected, dict)
            or not 0 < len(selected) <= MAX_SELECTED or not set(selected) <= set(all_ids)):
        raise ValueError('source_focus_selection_invalid')
    spans = catalog['spans']
    supplied = scoped_evidence.selected(catalog, list(spans), bundle, scope, manifest)
    seen = set()
    for key, item in selected.items():
        if not isinstance(item, dict) or set(item) != {'owner', 'anchor', 'value_anchor'}:
            raise ValueError('source_focus_occurrence_shape')
        owner = item['owner']
        if (not isinstance(owner, str) or owner not in spans or spans[owner]['role'] != 'target'
                or not key.startswith(owner + ':')):
            raise ValueError('source_focus_owner_invalid')
        for anchor in [item['anchor'], *([item['value_anchor']] if item['value_anchor'] is not None else [])]:
            if not isinstance(anchor, dict):
                raise ValueError('source_focus_anchor_shape')
            paper_coverage.anchor(anchor, bundle)
            if not paper_coverage.inside(anchor, supplied) or not paper_coverage.published(anchor, manifest, bundle):
                raise ValueError('source_focus_anchor_outside_published_scope')
        value = item['value_anchor'] or item['anchor']
        if not paper_coverage.inside(value, [item['anchor']]):
            raise ValueError('source_focus_value_outside_anchor')
        span = spans[owner]
        if value['block_id'] != span['block_id'] or not span['start_char'] <= value['start_char'] < span['end_char']:
            raise ValueError('source_focus_owner_mismatch')
        if item['value_anchor'] is not None:
            block = next(block for block in bundle.blocks if block.id == value['block_id'])
            if not projection_binding.isolated_selector(block.text, value['start_char'], value['end_char'], '/quantity/raw'):
                raise ValueError('source_focus_clipped_literal')
        identity = digest(dict(anchor=item['anchor'], value_anchor=item['value_anchor']))
        if identity in seen:
            raise ValueError('source_focus_duplicate_occurrence')
        seen.add(identity)
    return body


def prompt(body):
    neutral = {key: dict(owner=item['owner'], quote=item['anchor']['quote'],
        value_raw=item['value_anchor']['quote'] if item['value_anchor'] else None)
        for key in body['all_occurrence_ids'] if key in body['occurrences']
        for item in [body['occurrences'][key]]}
    return INSTRUCTION + '\nORIGINAL OCCURRENCE FOCUS\n' + canonical(neutral)


def inventory(body):
    return dict(schema='materials-source-focus-inventory/1', focus_sha256=digest(body),
        occurrences=deepcopy(body['occurrences']), selected_count=len(body['occurrences']),
        all_occurrence_ids=body['all_occurrence_ids'],
        unselected_occurrence_ids=[key for key in body['all_occurrence_ids'] if key not in body['occurrences']],
        scientific_mapping_reviewed=False, source_completeness_established=False,
        scientific_acceptance=False, paper_completed=False)


def mapping(body, graph):
    """Retain even unmatched targets; exact literal addresses are candidates only."""
    rows = []
    for key in body['all_occurrence_ids']:
        if key not in body['occurrences']:
            continue
        occurrence = body['occurrences'][key]
        locked = occurrence['value_anchor'] or occurrence['anchor']
        candidates = []
        for group in projection_binding.GROUPS:
            for index, entity in enumerate(graph[group]):
                for evidence in entity['evidence']:
                    field = evidence['field']
                    if not field.endswith(('/raw', '_raw')) or 'start_char' not in evidence:
                        continue
                    if evidence['block_id'] != locked['block_id']:
                        continue
                    # No nearest-number matching, semantic inference or broad
                    # parent /quantity witness is treated as literal coverage.
                    if (paper_coverage.inside(evidence, [locked]) or paper_coverage.inside(locked, [evidence])):
                        candidates.append(dict(entity_path=f'/{group}/{index}', entity_id=entity['id'],
                            field=field, evidence=deepcopy(evidence)))
        rows.append(dict(id=key, candidates=candidates,
            disposition='literal_candidates_pending_review' if candidates else 'unrepresented_pending_review',
            scientific_mapping_reviewed=False))
    return dict(schema='materials-source-focus-mapping/1', focus_sha256=digest(body),
        graph_sha256=digest(graph), occurrences=rows, selected_count=len(rows),
        literal_candidate_count=sum(bool(row['candidates']) for row in rows),
        unrepresented_count=sum(not row['candidates'] for row in rows),
        scientific_acceptance=False, source_completeness_established=False, paper_completed=False)
