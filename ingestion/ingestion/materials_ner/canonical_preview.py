"""Read-only canonical mapping audit; never allocates identities or writes rows.

The immutable proposal remains the lossless source graph. This preview maps the
two adopted property kinds and makes missing identity/event/review decisions
explicit instead of manufacturing foreign keys or merging equal results.
"""
from copy import deepcopy

from .contract import digest, parse_extraction
from .proposals import verify_packet
from . import quantities_v2

VERSION = 'materials-canonical-mapping-preview/1'
PRESSURE_VERSION = 'materials-canonical-mapping-preview/2'
TABLES = dict(samples='research_samples', states='material_states',
    protocols='research_protocols', sample_relations='sample_relations',
    condition_supports='event_properties.raw.condition_support')


def build(packet):
    verify_packet(packet)
    raw = packet['receipt'].get('extraction')
    graph = parse_extraction(raw) if raw is not None else None
    entities, results = [], []
    if graph is not None:
        for name, table in TABLES.items():
            for i, value in enumerate(getattr(graph, name, [])):
                entities.append(dict(source_path=f'/receipt/extraction/{name}/{i}',
                    source_id=value.id, candidate_destination=table,
                    disposition='retained_pending_explicit_mapping',
                    holds=['canonical_identity_or_relation_review_required']))
        for i, result in enumerate(graph.results):
            kind = result.quantity_kind
            path = f'/receipt/extraction/results/{i}'
            holds = ['independent_scientific_review_required', 'canonical_material_identity_required',
                     'physical_event_identity_required', 'source_artifact_registration_required']
            if not packet['receipt'].get('validation', {}).get('valid'):
                holds.append('extraction_validation_failed')
            if result.origin == 'unknown' or result.source_role == 'unknown':
                holds.append('scientific_attribution_unresolved')
            fields = None
            if kind in quantities_v2.ADDITIONS and result.quantity.status == 'reported':
                normalized = quantities_v2.normalize(kind, result.quantity)['normalized']
                fields = dict(property_key=kind, registry_version='materials-properties/3',
                    relation=normalized['relation'], value=normalized.get('value'),
                    lower=normalized.get('lower'), upper=normalized.get('upper'), unit=normalized['unit'],
                    uncertainty={},
                    raw=dict(source_quantity=dict(version='materials-source-quantity/1', quantity=result.quantity.model_dump()),
                        result_semantics=dict(version='materials-result-semantics/1',
                            definition=result.definition.model_dump(), qualifiers=result.model_dump()['qualifiers'],
                            result_key=result.id)))
            else:
                holds.append('property_mapping_not_implemented_for_this_kind_or_status')
            results.append(dict(source_path=path, source_result_id=result.id,
                source_sample_id=result.sample_id, source_state_id=result.state_id,
                source_protocol_id=result.protocol_id,
                normalized_readout=None if fields is None else normalized,
                candidate_destination='event_properties' if kind in quantities_v2.ADDITIONS else 'unmapped',
                candidate_fields=fields, source_name_path=path + '/quantity_name_raw',
                evidence_path=path + '/evidence', dependency_path=path + '/dependencies',
                disposition='hold', holds=holds, ready_to_insert=False))
    pressure_native = graph is not None and graph.schema_version == 'materials-ner/13'
    if pressure_native:
        for row in entities:
            if row['candidate_destination'] != 'material_states':
                continue
            state = next(s for s in graph.states if s.id == row['source_id'])
            row['candidate_fields'] = dict(condition_schema_version='materials-conditions/2',
                conditions=dict(items=[c.model_dump() for c in state.conditions],
                    pressure=state.pressure.model_dump(), temperature_condition_id=None))
            row['holds'].extend(['source_artifact_registration_required',
                'temperature_condition_selection_review_required', 'independent_scientific_review_required'])
            row['legacy_pressure_scalar_inferred'] = False
    body = dict(schema=PRESSURE_VERSION if pressure_native else VERSION, proposal_sha256=digest(packet), run_id=packet['run_id'],
        work_id=packet['work_id'], graph_sha256=None if raw is None else digest(raw),
        retained_graph_path='/receipt/extraction' if raw is not None else None,
        entities=entities, results=results, no_result_graph=graph is None,
        omitted_source_fields=0, source_graph_retained_in_proposal=True,
        canonical_ids_allocated=False, database_writes=False, scientific_acceptance=False,
        ml_training_eligible=False)
    return dict(body, preview_sha256=digest(body))


def verify(preview, packet):
    if preview != build(packet):
        raise ValueError('canonical_mapping_preview_mismatch')


def retained_graph(preview, packet):
    """Recover exactly the retained graph; candidate rows are not an inverse."""
    verify(preview, packet)
    return deepcopy(packet['receipt'].get('extraction'))
