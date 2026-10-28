"""Build a versioned reported-Tc training view from a canonical JSONL snapshot.

Only the features object is model input. Quotes, sample labels, Tc criteria,
review metadata and identifiers are deliberately outside that object. This
does not change scientific admission, infer stoichiometry or impute conditions.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from ingestion.materials_ner import reviewed_reader as rr


VERSION = 'materials-reported-tc-training-view/2'
# Metadata enrichment must not reshuffle previously published train/test groups.
SPLIT_NAMESPACE = 'materials-reported-tc-training-view/1'
FEATURES = ('formula_as_written', 'specimen_form', 'pressure_regime',
            'pressure_gpa', 'magnetic_flux_density_t')
UNKNOWN = (None, '', 'unresolved', 'unknown', 'not_reported')


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def write_rows(path, rows):
    rr.immutable(path, ''.join(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n'
                             for row in rows).encode())


def build(dataset, output):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    rows = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    dataset_pin = rr.reference(dataset)
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('duplicate_input_record_id')
    parent = {row['work_id']: row['work_id'] for row in rows}

    def find(work):
        while parent[work] != work:
            parent[work] = parent[parent[work]]
            work = parent[work]
        return work

    shared = {}
    for row in rows:
        if row['split_group'] != row['work_id']:
            raise ValueError('source_paper_group_mismatch')
        for kind, value in [('sample', row['sample_group']),
                            ('reuse', row['cross_paper_reused_sample_group'])]:
            if value in UNKNOWN:
                continue
            key = (kind, value)
            if key in shared:
                a, b = find(row['work_id']), find(shared[key])
                parent[max(a, b)] = min(a, b)
            else:
                shared[key] = row['work_id']

    included, excluded = [], []
    for row in rows:
        reasons = []
        if row.get('validity_status') not in ('pending', 'accepted'):
            reasons.append('claim_not_currently_usable')
        for key in ('paper_status', 'publication_status'):
            if row.get(key) in ('retracted', 'withdrawn', 'refuted'):
                reasons.append(key + '_' + row[key])
        if row['raw_record']['origin'] != 'observed' or row['raw_record']['source_role'] != 'primary':
            reasons.append('outside_primary_observed_label_scope')
        if row['value_relation'] != 'exact' or not finite(row['value_kelvin']):
            reasons.append('not_a_scalar_tc_label')
        formulas = [item['formula_raw'] for item in row['compositions']]
        if len(formulas) != 1 or not formulas[0]:
            reasons.append('single_as_written_formula_unavailable')
        if reasons:
            excluded.append(dict(record_id=row['id'], reasons=reasons,
                                 quantity_as_reported=row['quantity'], remains_in_source_dataset=True))
            continue
        regime = row['conditions']['pressure']['regime']
        features = dict(formula_as_written=formulas[0],
                        specimen_form=row['composition_context']['target_kind'], pressure_regime=regime)
        if row['pressure_gpa'] is not None:
            # A reported pressure can lack a categorical ambient/nonambient label.
            # Keep both source fields; do not infer that label from a zero value.
            if row['conditions']['pressure'].get('availability') != 'reported' or not finite(row['pressure_gpa']):
                raise ValueError('inconsistent_numeric_pressure')
            features['pressure_gpa'] = row['pressure_gpa']
        if row['magnetic_field_t'] is not None:
            if row['magnetic_field_t_source'] != 'typed_measurement_conditions' or not finite(row['magnetic_field_t']):
                raise ValueError('unbound_magnetic_field_feature')
            features['magnetic_flux_density_t'] = row['magnetic_field_t']
        component = find(row['work_id'])
        score = int(hashlib.sha256((SPLIT_NAMESPACE + ':' + component).encode()).hexdigest()[:16], 16) / 2**64
        split = 'train' if score < .8 else 'validation' if score < .9 else 'test'
        quality = row['quality']
        included.append(dict(record_id=row['id'], features=features,
            target=dict(tc_kelvin=row['value_kelvin']),
            target_context=dict(criterion=row['tc_definition'], method=row['measurement_method'],
                approximate=row['quantity']['approximate'], reported_tc_unit=row['quantity']['unit'],
                uncertainty_as_reported=row['quantity']['uncertainty']),
            groups=dict(work_id=row['work_id'], sample_group=row['sample_group'],
                        split_component=component, split=split),
            provenance=dict(paper_id=row['paper_id'], source_versions=row['publication_versions'],
                dataset_version=dataset_pin['sha256'], quality_status=quality['quality_status'],
                admission_route=quality.get('admission_route', 'qualified_batch'),
                batch_qualified=quality['batch_qualified'], per_record_checked=quality['per_record_checked'],
                source_scope=quality['source_scope'], complete_paper=quality['complete_paper'],
                validity_status=row['validity_status'], paper_status=row.get('paper_status') or 'unknown',
                publication_status=row.get('publication_status') or 'unknown')))

    assignments = defaultdict(set)
    formula_splits = defaultdict(set)
    for row in included:
        assignments[row['groups']['split_component']].add(row['groups']['split'])
        formula_splits[''.join(row['features']['formula_as_written'].split())].add(row['groups']['split'])
        if set(row['features']) - set(FEATURES):
            raise ValueError('unexpected_training_feature')
    if any(len(splits) != 1 for splits in assignments.values()):
        raise ValueError('group_split_leakage')
    output.mkdir(parents=True, exist_ok=True)
    write_rows(output / 'TRAINING_ROWS.jsonl', included)
    write_rows(output / 'EXCLUDED_FROM_SCALAR_VIEW.jsonl', excluded)
    manifest = dict(schema=VERSION, source_dataset=dataset_pin, builder=rr.reference(__file__),
        rows=len(included), source_rows=len(rows), excluded_from_scalar_view=len(excluded),
        training_rows=rr.reference(output / 'TRAINING_ROWS.jsonl'),
        excluded_rows=rr.reference(output / 'EXCLUDED_FROM_SCALAR_VIEW.jsonl'),
        exclusion_counts=dict(Counter(reason for row in excluded for reason in row['reasons'])),
        feature_allowlist=list(FEATURES), composition_only_features=['formula_as_written'],
        feature_presence={key:sum(key in row['features'] for row in included) for key in FEATURES},
        target_context_is_not_model_input=True, source_text_is_not_model_input=True,
        provenance_is_not_model_input=True,
        publication_status_policy='Exclude known retracted, withdrawn or refuted papers and works. Unknown status remains unknown; no independent retraction audit is implied.',
        quality_status_counts=dict(Counter(row['provenance']['quality_status'] for row in included)),
        publication_status_counts=dict(Counter(row['provenance']['publication_status'] for row in included)),
        target='Reported sample transition temperature; not an intrinsic bulk-material constant.',
        split_namespace=SPLIT_NAMESPACE,
        split_policy='Deterministic 80/10/10 hash allocation by work and known shared/reused sample components.',
        split_rows=dict(Counter(row['groups']['split'] for row in included)),
        split_papers={split:len({row['groups']['work_id'] for row in included if row['groups']['split']==split})
                      for split in ['train','validation','test']},
        same_paper_versions_and_known_shared_samples_stay_together=True,
        known_cross_paper_reuse_rows=sum(row['cross_paper_reused_sample_group'] not in UNKNOWN for row in rows),
        literal_formula_groups_in_multiple_splits=sum(len(splits)>1 for splits in formula_splits.values()),
        split_scope='Held-out papers, not guaranteed unseen compositions. Formula aliases and unknown cross-paper sample reuse remain unresolved.',
        uncertainty_policy='Approximate point labels are retained and flagged. Bounds and intervals remain in the source dataset; no midpoint is created.',
        composition_policy='As-written formula text is a feature; normalized or measured stoichiometry is not inferred.',
        interpretation_policy='Inspect attribution and sample context in the source snapshot for task-specific selection. Specimen form is not proof of bulk superconductivity.',
        missing_condition_policy='Missing numeric conditions are omitted. Explicitly reported numeric pressure is retained even when its regime is unknown; unknown never supplies an ambient label or a zero value.',
        admission_policy_changed=False, independent_expert_review=False, predictive_model_trained=False)
    rr.put(output / 'MANIFEST.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.dataset, args.output)
    print(json.dumps({key:result[key] for key in ['rows','source_rows','excluded_from_scalar_view',
        'feature_presence','split_rows','split_papers','literal_formula_groups_in_multiple_splits']}))
