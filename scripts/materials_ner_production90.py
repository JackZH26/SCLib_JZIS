"""Versioned result admission above immutable NER and amendment history.

Batch qualification is not expert adjudication. This policy uses existing
canonical tables and JSON metadata; it does not change historical review states.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

POLICY = 'production90/1'
GLOBAL_INFORMATIONAL = {'incomplete_extraction', 'coverage_inventory_mismatch'}
IDENTITY_HOLDS = {'formula_assignment_conflict', 'formula_assertion_conflict',
                  'source_composition_identity_unresolved', 'film_B_40_vs_45_identity_unresolved'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_pin(pin):
    data = Path(pin['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ValueError('production90_input_changed')
    if 'bytes' in pin and len(data) != pin['bytes']:
        raise ValueError('production90_input_size_changed')
    return json.loads(data)


def triage_amendment(entry, *, catalogue_identity_resolved):
    from ingestion.materials_ner.review_amendments import verify, tc_mapping
    a, parent = read_pin(entry['amendment']), read_pin(entry['parent'])
    verify(a, parent)
    mapping = {r['source_result_id']: r for r in tc_mapping(a)['records']}
    rows = []
    for rid in a['selected_result_ids']:
        result = next(r for r in a['graph']['results'] if r['id'] == rid)
        m = mapping[rid]
        issues = set(m['holds']) & IDENTITY_HOLDS
        if not catalogue_identity_resolved:
            issues.add('catalogue_composition_equivalence_unresolved')
        if result['quantity_kind'] != 'tc' or result['quantity']['status'] != 'reported':
            issues.add('outside_explicit_tc_scope')
        if result['origin'] != 'observed' or result['source_role'] != 'primary':
            issues.add('outside_initial_primary_experimental_scope')
        # Selected result and directly referenced entities remain accountable.
        prefixes = ['/results/' + str(a['graph']['results'].index(result))]
        for group, key in [('samples', 'sample_id'), ('states', 'state_id'), ('protocols', 'protocol_id')]:
            entity = next(x for x in a['graph'][group] if x['id'] == result[key])
            prefixes.append('/' + group + '/' + str(a['graph'][group].index(entity)))
        for issue in a['validation']['issues']:
            path = issue['path']
            if path == '/' and issue['code'] not in GLOBAL_INFORMATIONAL:
                issues.add(issue['code'])
            elif any(path == p or path.startswith(p + '/') for p in prefixes):
                issues.add(issue['code'])
        rows.append(dict(work_id=a['work_id'], result_id=rid, amendment_id=a['amendment_id'],
            status='held' if issues else 'eligible_for_source_audit', holds=sorted(issues),
            historical_holds=m['holds'], history=entry,
            scope='primary_experimental_explicit_tc', policy=POLICY))
    return rows


def freeze_sample(rows, *, seed, limit=50):
    """Predeclared paper-balanced selection; all retained rows in a small batch.

Paper balancing is intentional. Larger-batch precision must use population
weights and disclose the strata; high-risk extras are reported separately.
"""
    eligible = [r for r in rows if r['status'] == 'eligible_for_source_audit']
    if len(eligible) > limit:
        raise ValueError('large_batch_requires_predeclared_weighted_sampling_plan')
    selected = sorted(eligible, key=lambda r: digest([seed, r['work_id'], r['result_id']]))
    body = dict(policy=POLICY, method='census_of_retained_records', seed=seed,
        created_at=datetime.now(timezone.utc).isoformat(), population_sha256=digest(rows),
        input_results=len(rows), eligible_results=len(eligible), held_results=len(rows)-len(eligible),
        records=[dict(work_id=r['work_id'], result_id=r['result_id'], amendment_id=r['amendment_id'])
                 for r in selected], independent_gold=False)
    return {**body, 'selection_sha256': digest(body)}


def qualify(selection, audit):
    body = {k:v for k,v in selection.items() if k != 'selection_sha256'}
    if digest(body) != selection['selection_sha256']:
        raise ValueError('audit_selection_changed')
    if audit['selection_sha256'] != selection['selection_sha256'] or audit['reviewer_kind'] != 'model':
        raise ValueError('audit_selection_or_authorship_mismatch')
    native = selection.get('schema') == 'materials-native-tc-sample/1'
    fields = ('work_id', 'result_id', 'run_id', 'projection_sha256') if native else ('work_id', 'result_id', 'amendment_id')
    expected = {tuple(r[k] for k in fields) for r in selection['records']}
    actual = [tuple(r[k] for k in fields) for r in audit['records']]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('audit_does_not_cover_frozen_sample')
    counts = dict(correct=0, incorrect=0, indeterminate=0)
    for r in audit['records']:
        if r['verdict'] not in counts or not r['source_evidence'] or not r['rationale']:
            raise ValueError('source_audit_required')
        for evidence in r['source_evidence']:
            original = read_pin(evidence['original_source'])
            blocks = original.get('bundle', original)['blocks']
            block = next(x for x in blocks if x['id'] == evidence['block_id'])
            if block['text'][evidence['start_char']:evidence['end_char']] != evidence['quote']:
                raise ValueError('audit_quote_mismatch')
        counts[r['verdict']] += 1
    n = len(actual)
    if n == 0:
        raise ValueError('empty_source_audit')
    precision = counts['correct']/n
    z = 1.959963984540054
    center = (precision + z*z/(2*n))/(1+z*z/n)
    half = z*math.sqrt(precision*(1-precision)/n+z*z/(4*n*n))/(1+z*z/n)
    report = dict(policy=POLICY, sample_size=n, **counts, observed_precision=precision,
        wilson_95=[max(0,center-half), min(1,center+half)], threshold=0.9,
        qualified=precision>=0.9, selection_sha256=selection['selection_sha256'],
        audit_sha256=digest(audit), reviewer_kind='model', independent_gold=False,
        core_tuple_scope='Retained primary experimental Tc and retained interpretive context.',
        statistical_scope='Census of this selected development tranche; not a whole-corpus accuracy estimate.',
        model_accuracy_scope=('Luna results after deterministic per-result selection and optional metadata omissions; no material, numeric value or condition edits.'
            if native else 'Assistant-amended records; not unaided Luna extraction accuracy.'),
        recall=None, full_paper_recall_measured=False)
    if native and selection.get('method')=='paper_stratified_without_replacement':
        from materials_ner_tc_sampling import weighted_precision
        weighted=weighted_precision(selection,audit['records'])
        report.update(observed_precision=weighted,qualified=weighted>=0.9,
            unweighted_sample_precision=precision,estimator='Paper-stratified population-size-weighted correct proportion.',
            strata=selection['strata'],wilson_95_scope='Unweighted audited sample only; not a design-based population interval.',
            statistical_scope='This frozen batch only; paper-stratified sampling does not establish whole-corpus accuracy.',
            population_confidence_interval_95=None,
            population_interval_status='Not estimated; no confidence-interval lower-bound admission gate.')
    if native and selection.get('method')=='simple_random_without_replacement':
        from materials_ner_tc_sampling import verify
        verify(selection)
        report.update(estimator='Correct records divided by all randomly sampled records; indeterminate records are not correct.',
            statistical_scope='This frozen prospective window only; model source-check estimate, not expert gold or whole-corpus accuracy.',
            wilson_95_scope='Descriptive interval for the audited random sample; no confidence-interval admission gate.')
    return report


def canonical_plan(request, *, selection, audit):
    """Reuse canonical identity/evidence checks, adding honest policy metadata."""
    from materials_ner_canonical_bridge import prepare
    report = qualify(selection, audit)
    if not report['qualified']:
        raise ValueError('production90_batch_below_threshold')
    plan = prepare(request)
    allowed = {(r['work_id'],r['result_id'],r['amendment_id']):r for r in audit['records']}
    for row in plan['rows']['material_claims']:
        key = (plan['source_work_id'],row['result_key'],plan['amendment_id'])
        verdict = allowed.get(key)
        if verdict is None or verdict['verdict'] != 'correct':
            raise ValueError('known_bad_or_unaudited_record_in_census')
        row['extraction_metadata']['production_admission'] = dict(policy=POLICY,
            quality_status='model_source_checked', batch_qualified=True, per_record_checked=True,
            reviewer_kind='model', independent_expert_review=False,
            selection_sha256=report['selection_sha256'], audit_sha256=report['audit_sha256'],
            source_scope='selected_source_assertion', complete_paper=False)
    plan['production_admission'] = report
    return plan
