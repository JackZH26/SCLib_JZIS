"""Internal, pending-only adoption of source-backed Tc amendments.

No catalogue identities, reviews, normalization or measurements are inferred.
The caller supplies pinned existing catalogue rows. Every result is a separate
source assertion; its event ID is not an independent-experiment identifier.
The existing canonical contracts own units, conditions and outcome projections.
This module has no production CLI or public write endpoint.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'api'), str(ROOT / 'ingestion')]
from ingestion.materials_ner.review_amendments import verify, tc_mapping
from models.db import Base
from services.source_registry import (import_source_provenance_bundle,
    provenance_sha256 as digest, SOURCE_REGISTRY_VERSION, _json)

VERSION = 'materials-amendment-canonical/1'
TABLES = ('evidence_artifacts', 'research_samples', 'sample_compositions',
          'material_states', 'research_protocols', 'research_events',
          'material_claims', 'event_evidence')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pinned(ref):
    require(set(ref) == {'path', 'sha256'}, 'pinned_file_shape')
    data = Path(ref['path']).read_bytes()
    require(hashlib.sha256(data).hexdigest() == ref['sha256'], 'pinned_file_changed')
    return data


def uid(*parts):
    return str(uuid5(NAMESPACE_URL, json.dumps([VERSION, *parts], separators=(',', ':'))))


def _entity_rows(amendment):
    graph = amendment['graph']
    selected = set(amendment['selected_result_ids'])
    results = [r for r in graph['results'] if r['id'] in selected]
    require(0 < len(results) <= 64, 'bounded_tc_slice_required')
    for r in results:
        require(r['quantity_kind'] == 'tc' and r['origin'] == 'observed'
                and r['source_role'] == 'primary' and not r['dependencies']
                and r['quantity']['status'] == 'reported', 'unsupported_tc_candidate')
    chosen = {'results': results}
    for group, key in [('samples', 'sample_id'), ('states', 'state_id'), ('protocols', 'protocol_id')]:
        ids = {r[key] for r in results}
        chosen[group] = [x for x in graph[group] if x['id'] in ids]
        require({x['id'] for x in chosen[group]} == ids, 'missing_selected_dependency')
    prefixes = [f'/{g}/{graph[g].index(x)}' for g, xs in chosen.items() for x in xs]
    require(not any(any(i['path'] == p or i['path'].startswith(p + '/') for p in prefixes)
                    for i in amendment['validation']['issues']), 'selected_dependency_invalid')
    return chosen


def prepare(request, *, source_objects=None):
    """Verify frozen files and produce a deterministic, reviewable insertion plan."""
    read = pinned if source_objects is None else source_objects.read
    require(set(request) == {'parent', 'amendment', 'provenance', 'source_files',
                            'bindings', 'captured_at', 'source_kinds'}, 'request_shape')
    parent = json.loads(read(request['parent']))
    a = json.loads(read(request['amendment']))
    verify(a, parent)
    require(a['graph']['schema_version'] == 'materials-ner/13', 'unsupported_graph')
    chosen = _entity_rows(a)
    bindings = request['bindings']
    require(set(bindings) == {'purpose', 'work', 'paper', 'snapshot', 'samples'}, 'binding_shape')
    require(bindings['purpose'] in {'disposable_rehearsal', 'pending_candidates'}, 'binding_purpose')
    require(set(bindings['samples']) == {x['id'] for x in chosen['samples']}, 'sample_bindings_required')
    require(set(request['source_kinds']) == {x['id'] for x in chosen['results']}
            and set(request['source_kinds'].values()) <= {'prose', 'abstract', 'table'}, 'source_kind_bindings_required')
    require(datetime.fromisoformat(request['captured_at']).tzinfo is not None, 'capture_timezone_required')
    for anchor in [bindings[k] for k in ('work', 'paper', 'snapshot')] + list(bindings['samples'].values()):
        require(set(anchor) == {'id', 'row_sha256'} and re.fullmatch('[a-f0-9]{64}', anchor['row_sha256']),
                'pinned_catalogue_anchor_required')
    prov = json.loads(read(request['provenance']))
    records = [x for x in prov['records'] if x['amendment_id'] == a['amendment_id']]
    require(len(records) == 1 and records[0]['work_id'] == a['work_id'], 'block_provenance_identity')
    sources = {x['sha256']: x for x in request['source_files']}
    for ref in sources.values():
        read(ref)
    provenance = {b['block_id']: b for b in records[0]['blocks']}
    blocks = {b['id']: b for b in a['bundle']['blocks']}
    require(set(provenance) == set(blocks), 'block_provenance_coverage')
    checked = {}
    for key, p in provenance.items():
        b = blocks[key]
        require(p['block_sha256'] == b['sha256'] and p['locator'] == b['locator'], 'block_provenance_mismatch')
        ref = p['representation_input']
        if ref['sha256'] not in checked:
            source_input = json.loads(read(ref))
            source_bundle = source_input.get('bundle', source_input)
            checked[ref['sha256']] = {x['id']: x for x in source_bundle['blocks']}
        original_block = checked[ref['sha256']].get(key)
        require(original_block is not None and original_block['sha256'] == b['sha256']
                and original_block['text'] == b['text'], 'representation_block_mismatch')
        require(p['representation_document']['source_sha256'] in sources, 'original_source_bytes_required')
        require(re.fullmatch(r'v[1-9][0-9]*', p['effective_publication_version']), 'pinned_source_version_required')
    scope = [a['amendment_id'], bindings['purpose'], bindings['work']['id'],
             bindings['paper']['id'], bindings['snapshot']['id'],
             sorted((k, v['id']) for k, v in bindings['samples'].items())]
    target = lambda group, key: uid(scope, group, key)
    rows = {t: [] for t in TABLES}
    registry = {'version': SOURCE_REGISTRY_VERSION, 'source_revisions': [],
                'source_captures': [], 'claim_source_occurrences': []}
    editorial_id = uid(a['amendment_id'], 'editorial-source')
    rows['evidence_artifacts'].append(dict(id=editorial_id, kind='literature_locator',
        schema_version='materials-proposal-amendment/1', source='assistant_editorial_amendment',
        record_sha256=a['amendment_id'], bytes_sha256=request['amendment']['sha256'],
        hash_status='verified', access='restricted', uri=request['amendment']['path'],
        metadata={'amendment_id': a['amendment_id'], 'author': a['author'],
            'parent_packet_hash': a['parent_packet_hash'], 'source_provenance': request['provenance'],
            'is_original_paper': False, 'independent_review': False}))
    source_ids = {}
    for p in provenance.values():
        doc = p['representation_document']
        source_hash = doc['source_sha256']; version = p['effective_publication_version']
        key = (source_hash, version)
        if key in source_ids:
            continue
        kind = {'original_tex': 'arxiv_source', 'original_pdf': 'pdf'}.get(doc['source_kind'])
        require(kind is not None, 'original_source_kind_not_supported')
        revision = uid(bindings['paper']['id'], version, 'source-revision')
        capture = uid(revision, source_hash, request['captured_at'], 'capture')
        artifact = uid(a['work_id'], version, source_hash, 'original-source')
        source_ids[key] = (revision, capture, artifact)
        revision_row = dict(id=revision, paper_id=bindings['paper']['id'], work_id=bindings['work']['id'],
            revision_key='arxiv:' + version, provider_revision=version, version_status='pinned',
            source_version_public_at=None, availability_status='unknown', availability_basis='unknown',
            metadata_sha256=digest({'source_work_id': a['work_id'], 'provider_revision': version}))
        if revision_row not in registry['source_revisions']:
            registry['source_revisions'].append(revision_row)
        registry['source_captures'].append(dict(id=capture, source_revision_id=revision,
            capture_key=digest({'bytes': source_hash, 'local_verification_at': request['captured_at']}),
            captured_at=request['captured_at'], bytes_sha256=source_hash, representation=kind))
        metadata = {'source_work_id': a['work_id'], 'provider_revision': version,
                    'source_kind': doc['source_kind'], 'redistribution_permission': doc['redistribution_permission']}
        rows['evidence_artifacts'].append(dict(id=artifact, kind='literature_locator',
            schema_version='original-source/1', source=a['work_id'], source_version=version,
            bytes_sha256=source_hash, record_sha256=digest(metadata), hash_status='verified',
            access='restricted', uri=sources[source_hash]['path'], metadata=metadata))
    compositions = {}
    for s in chosen['samples']:
        sid = target('sample', s['id']); material = bindings['samples'][s['id']]['id']
        require(s['formula_raw'] is not None, 'formula_missing_requires_separate_adoption')
        context = {k: deepcopy(s[k]) for k in ('identity_resolution', 'target_kind', 'form_raw',
                   'substrate_raw', 'additional_formula_assertions', 'formula_unavailability')}
        rows['research_samples'].append(dict(id=sid, material_id=material, work_id=bindings['work']['id'],
            sample_label=s['label'], preparation={}, composition_context=context, source_artifact_id=editorial_id))
        assertions = [(s['formula_raw'], s['composition_basis'],
                       {'variables': s['variables'], 'isotopes': s['isotopes']})]
        # Do not silently carry variable assignments into a conflicting formula.
        assertions += [(x['formula_raw'], x['basis'], {'variables': [], 'isotopes': []})
                       for x in s['additional_formula_assertions']]
        compositions[s['id']] = []
        for i, (formula, basis, payload) in enumerate(assertions):
            cid = target('composition', [s['id'], i]); compositions[s['id']].append(cid)
            rows['sample_compositions'].append(dict(id=cid, sample_id=sid, formula_raw=formula,
                composition_basis=basis, composition_schema_version='materials-composition/1',
                composition_payload=payload, source_artifact_id=editorial_id, record_sha256='0' * 64))
    for s in chosen['states']:
        rows['material_states'].append(dict(id=target('state', s['id']),
            material_id=bindings['samples'][s['sample_id']]['id'], sample_id=target('sample', s['sample_id']),
            resolution='source_scoped', condition_schema_version='materials-conditions/2',
            pressure_status='not_reported', temperature_role='unknown', context_sha256='0' * 64,
            conditions={'items': s['conditions'], 'pressure': s['pressure'], 'temperature_condition_id': None},
            source_artifact_id=editorial_id))
    for p in chosen['protocols']:
        rows['research_protocols'].append(dict(id=target('protocol', p['id']), work_id=bindings['work']['id'],
            method_class=p['method_class'], method_raw=p['method'], observable=p['observable'],
            details_raw=p['details_raw'], parameters=p['parameters'], protocol_schema_version='materials-protocol/1',
            source_artifact_id=editorial_id, record_sha256='0' * 64))
    mappings = {m['source_result_id']: m for m in tc_mapping(a)['records']}
    results = []
    for r in chosen['results']:
        m = mappings[r['id']]; event = target('event', r['id']); claim = target('claim', r['id'])
        state = next(x for x in chosen['states'] if x['id'] == r['state_id'])
        protocol = next(x for x in chosen['protocols'] if x['id'] == r['protocol_id'])
        require(state['sample_id'] == r['sample_id'], 'sample_state_owner_mismatch')
        annotation = dict(amendment_id=a['amendment_id'], source_result_id=r['id'],
            purpose=bindings['purpose'], physical_event_identity='unresolved',
            independent_measurement_count=None, state_label=state['label'],
            preparation_raw=state['preparation_raw'], protocol_context_uses=protocol['context_uses'],
            unadopted_qualifiers=m['unmapped_qualifiers'],
            pending_sample_relation_ids=[x['id'] for x in a['graph']['sample_relations']
                if r['sample_id'] in (x['from_sample_id'], x['to_sample_id'])],
            condition_supports_retained_in_amendment=bool(a['graph']['condition_supports']),
            source_holds=m['holds'])
        context = {'materials_context': {'version': 'materials-context/1',
            'composition_ids': compositions[r['sample_id']], 'protocol_id': target('protocol', r['protocol_id']),
            'relation_ids': []}, 'editorial_origin': annotation}
        rows['research_events'].append(dict(id=event, material_id=bindings['samples'][r['sample_id']]['id'],
            state_id=target('state', r['state_id']), event_type='measurement', knowledge_origin='Observed',
            record_sha256=digest(context), review_status='pending', validity_status='pending',
            decision_artifact_id=None, context=context))
        raw = {k: v for k, v in r.items() if k != 'evidence'}
        raw['amendment_id'] = a['amendment_id']
        meta = {'materials_outcome': {'version': 'materials-claim-outcome/1', 'kind': 'tc', 'quantity': r['quantity']},
            'result_semantics': m['result_semantics'], 'state_semantics': {'version': 'materials-state-link/1'},
            'editorial_origin': {'amendment_id': a['amendment_id'], 'author': a['author'],
                'parent_run_id': a['parent_run_id'], 'identity_binding_sha256': digest(bindings)}}
        row = dict(m['candidate_fields'], id=claim, event_id=event, result_key=r['id'], interpretation_revision=1,
            material_id=bindings['samples'][r['sample_id']]['id'], paper_id=bindings['paper']['id'],
            work_id=bindings['work']['id'], source_snapshot_id=bindings['snapshot']['id'],
            source_kind=request['source_kinds'][r['id']], source_locator={'amendment_id': a['amendment_id'],
                'result_pointer': f"/graph/results/{a['graph']['results'].index(r)}"},
            raw_record=raw, extraction_metadata=meta, source_record_hash=digest(raw), extractor_version=VERSION)
        row.update(magnetic_field_t=None, minimum_temperature_k=None)
        # The outcome contract projects the selected protocol's controlled class.
        # Its complete source wording is retained separately as method_raw.
        row['measurement_method'] = None if protocol['method_class'] == 'unspecified' else protocol['method_class']
        rows['material_claims'].append(row)
        prefixes = [f'/{g}/{a["graph"][g].index(x)}' for g, xs in chosen.items() for x in xs
                    if x['id'] == (r['id'] if g == 'results' else r[g[:-1] + '_id'])]
        result_prefix = f"/results/{a['graph']['results'].index(r)}"
        seen = set()
        event_links = {}
        for e in a['validation']['resolved_evidence']:
            if not any(e['path'] == p or e['path'].startswith(p + '/') for p in prefixes):
                continue
            p = provenance[e['block_id']]; doc = p['representation_document']
            revision, capture, artifact = source_ids[(doc['source_sha256'], p['effective_publication_version'])]
            coordinate = {'section_path': 'parsed-block:' + p['representation_input']['sha256'] + '#' + e['block_id'],
                          'char_start': e['start_char'], 'char_end': e['end_char']}
            page = re.search(r'pdf_page:(\d+)', e['locator'])
            if page:
                coordinate['page'] = int(page.group(1))
            # char offsets are explicitly relative to a pinned parsed block, never PDF byte offsets.
            locator = dict(coordinate, block_sha256=e['block_sha256'], quote_sha256=e['quote_sha256'],
                original_locator=e['locator'], representation_input=p['representation_input'],
                parser=doc['parser'], amendment_id=a['amendment_id'])
            link_id = target('evidence', [r['id'], artifact, digest(locator)])
            if link_id not in event_links:
                event_links[link_id] = dict(id=link_id, event_id=event, artifact_id=artifact,
                    link_type='source', locator={**locator, 'field_paths': []})
            event_links[link_id]['locator']['field_paths'].append(e['path'])
            if e['path'].startswith(result_prefix + '/') and (capture, digest(coordinate)) not in seen:
                # Only result occurrences are claim witnesses; context has its own event evidence.
                seen.add((capture, digest(coordinate)))
                registry['claim_source_occurrences'].append(dict(id=target('occurrence', [r['id'], capture, digest(coordinate)]),
                    claim_id=claim, work_id=bindings['work']['id'], source_revision_id=revision, capture_id=capture,
                    occurrence_key=digest(coordinate), locator=coordinate, binding_status='pending',
                    review_artifact_id=None, review_artifact_sha256=None))
        require(seen, 'result_occurrence_required')
        for link in event_links.values():
            link['locator']['field_paths'] = sorted(set(link['locator']['field_paths']))
            rows['event_evidence'].append(link)
        results.append(dict(source_result_id=r['id'], claim_id=claim, event_id=event,
                            scientific_acceptance=False, ml_training_eligible=False))
    # The same field may occur more than once in a legacy envelope. Identical links are one row.
    for name, values in rows.items():
        unique = {}
        for row in values:
            require(row['id'] not in unique or unique[row['id']] == row, 'planned_identity_conflict')
            unique[row['id']] = row
        rows[name] = list(unique.values())
    return {'version': VERSION, 'amendment_id': a['amendment_id'], 'source_work_id': a['work_id'],
            'bindings': deepcopy(bindings),
            'rows': rows, 'source_registry': registry, 'results': results,
            'scientific_acceptance': False, 'ml_training_eligible': False}


async def _catalogue(db, plan):
    b = plan['bindings']
    for name, anchor in [('works', b['work']), ('papers', b['paper']), ('source_snapshots', b['snapshot']),
                         *[('materials', x) for x in b['samples'].values()]]:
        table = Base.metadata.tables[name]
        key = UUID(anchor['id']) if isinstance(table.c.id.type, sa.Uuid) else anchor['id']
        row = (await db.execute(sa.select(table).where(table.c.id == key).with_for_update(read=True))).mappings().one_or_none()
        require(row is not None and digest(dict(row)) == anchor['row_sha256'], 'catalogue_binding_changed')
        if name == 'papers':
            require(row['source'] == 'arxiv' and row['arxiv_id'] == plan['source_work_id'].removeprefix('arxiv:'),
                    'paper_source_identity_mismatch')
        if name == 'works' and row['canonical_arxiv_id'] is not None:
            require(row['canonical_arxiv_id'] == plan['source_work_id'].removeprefix('arxiv:'),
                    'work_source_identity_mismatch')
        if name == 'source_snapshots':
            require(row['status'] == 'building', 'writable_building_snapshot_required')


async def _put(db, name, values):
    table = Base.metadata.tables[name]
    typed = {k: UUID(v) if v is not None and isinstance(table.c[k].type, sa.Uuid) else v for k, v in values.items()}
    inserted = (await db.execute(insert(table).values(**typed).on_conflict_do_nothing(index_elements=['id'])
                                 .returning(table.c.id))).scalar_one_or_none() is not None
    actual = (await db.execute(sa.select(table).where(table.c.id == typed['id']))).mappings().one()
    derived = {'material_states': {'context_sha256', 'pressure_status', 'temperature_role'},
               'sample_compositions': {'record_sha256'}, 'research_protocols': {'record_sha256'}}.get(name, set())
    mismatched = [k for k, v in values.items() if k not in derived and _json(actual[k]) != _json(v)]
    require(not mismatched, 'canonical_insert_or_verify_mismatch:' + name + ':' + ','.join(mismatched))
    return inserted, _json(dict(actual))


async def apply(db, request, *, dry_run=True, source_objects=None):
    """Savepoint atomic; never commit the outer transaction or change any review."""
    require(type(dry_run) is bool, 'dry_run_boolean')
    plan = prepare(request, source_objects=source_objects)
    read = pinned if source_objects is None else source_objects.read
    amendment = json.loads(read(request['amendment']))
    return await _apply_plan(db, plan, amendment, dry_run=dry_run)


async def _apply_plan(db, plan, amendment, *, dry_run):
    """Internal SQL phase after source validation; catalogue pins stay live."""
    require(type(dry_run) is bool, 'dry_run_boolean')
    transaction = await db.begin_nested()
    try:
        await db.execute(sa.text('SELECT pg_advisory_xact_lock(1002401)'))
        await _catalogue(db, plan)
        stored = (await db.execute(sa.text('SELECT payload FROM materials_ner_v1.amendments WHERE id=:id'),
                                   {'id': plan['amendment_id']})).scalar_one_or_none()
        require(stored == amendment, 'stored_amendment_required')
        readback = {}; counts = Counter()
        for name in TABLES:
            readback[name] = []
            for row in plan['rows'][name]:
                inserted, actual = await _put(db, name, row)
                counts['inserted' if inserted else 'verified_existing'] += 1
                readback[name].append(actual)
        registry = await import_source_provenance_bundle(db, plan['source_registry'], dry_run=False)
        report = dict(version=VERSION, plan_sha256=digest(plan), dry_run=dry_run, committed=False,
            **counts, registry=registry, results=plan['results'], readback=readback,
            scientific_acceptance=False, ml_training_eligible=False)
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
        return report
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
