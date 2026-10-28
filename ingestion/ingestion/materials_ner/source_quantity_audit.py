"""Versioned source coupling audit for initial staged extraction.

This records finite lexical support and unresolved layouts without changing a
model graph, inventing missing results or assigning scientific/ML permission.
"""
from collections import Counter
import re

from .contract import digest
from . import quantity_raw_witness as raw_witness, quantity_name_witness as name_witness

POLICY = 'initial_source_quantity_support_v1'
POSITIONED_POLICY = 'initial_source_quantity_support_v2'


def quantity_paths(value, path=''):
    if isinstance(value,dict):
        if {'status','raw','unit','relation','value','uncertainty'} <= set(value):
            yield path,value
        else:
            for key,child in value.items():yield from quantity_paths(child,path+'/'+key)
    elif isinstance(value,list):
        for index,child in enumerate(value):yield from quantity_paths(child,path+'/'+str(index))


def audit(graph, bundle, *, policy=POLICY):
    if policy not in {POLICY, POSITIONED_POLICY}:
        raise ValueError('staged_source_quantity_audit_policy_unknown')
    before = graph.model_dump();records = []
    scientific = before
    table_sources = {}
    if policy == POSITIONED_POLICY:
        if graph.schema_version != 'materials-source-atoms-graph/2':
            raise ValueError('staged_positioned_audit_graph_mismatch')
        # Expansion independently verifies every original cell/header/unit and
        # exact result value. Operational proofs are not extra measurements.
        graph.expand(bundle)
        table_sources = {s.result_id:s for s in graph.table_value_sources}
        scientific = {k:v for k,v in before.items() if k != 'table_value_sources'}
    for path,quantity in quantity_paths(scientific):
        row = dict(path=path,quantity_sha256=digest(quantity),source_fragment_choices={},
                   matching_name_assignments={},scientific_acceptance=False,ml_training_eligible=False)
        if quantity['status'] != 'reported':
            row.update(status='not_a_reported_numeric_quantity',source_review_required=True)
            records.append(row);continue
        match = re.fullmatch(r'/observations/(\d+)/result/quantity',path)
        if match and table_sources:
            observation = graph.observations[int(match[1])]
            proof = table_sources[observation.id].binding
            row.update(status='table_value_header_unit_supported', source_review_required=True,
                table_value_binding_sha256=digest(proof), source_scope=proof['source'],
                quantity_name_raw=observation.result.quantity_name_raw)
            records.append(row);continue
        try:
            context = raw_witness.context(graph,path+'/raw',bundle)
            row.update(source_fragment_choices=(context or {}).get('choices',{}),
                source_scope=context,source_review_required=True)
            row['status'] = 'numeric_fragment_supported' if row['source_fragment_choices'] else 'numeric_fragment_unresolved'
            match = re.fullmatch(r'/observations/(\d+)/result/quantity',path)
            if match:
                result = graph.observations[int(match[1])].result
                names = name_witness.context(graph,path.rsplit('/',1)[0]+'/quantity_name_raw',bundle)
                matching = {key:choice for key,choice in names['choices'].items() if choice['name']==result.quantity_name_raw}
                row.update(quantity_name_raw=result.quantity_name_raw,matching_name_assignments=matching)
                row['status'] = ('name_and_numeric_assignment_supported' if matching and row['source_fragment_choices']
                                 else 'quantity_name_or_numeric_coupling_unresolved')
        except ValueError as error:
            row.update(status='source_scope_requires_review',source_review_required=True,diagnostic=str(error))
        records.append(row)
    assert before == graph.model_dump()
    return dict(policy=policy,graph_sha256=digest(before),bundle_sha256=digest(bundle.model_dump()),records=records,
        status_counts=dict(Counter(r['status'] for r in records)),scientific_graph_unchanged=True,
        unsupported_layout_is_not_absence=True,independent_gold=False,scientific_acceptance=False,ml_training_eligible=False,
        limitation='Finite explicit-unit fragments and inline name assignments. Support does not establish sample/procedure applicability; unresolved prose/tables retain their original results and require review.')
