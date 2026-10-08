"""Build bounded, retrospective research checks from the frozen public source set.

No fitting, solver, network, database or scientific publication occurs here.
Known source outcomes are deliberately excluded from prospective holdout credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'frontend/public/research-hypotheses/source-computed-candidates-2026-10-07.json'
OUT = ROOT / 'docs/data/discovery-batches-20261008'

# Purposeful coverage, not top-Tc selection or a statistically representative sample.
CASES = [
    ('TiNb2Mo', 'ordered_vs_experimental_alloy', 'Compare exact ordered source identity with the BCC experimental alloy; never transfer its measured Tc.'),
    ('HfNbTa', 'phase_and_disorder', 'Keep the ordered hexagonal source and the experimental BCC alloy as separate states.'),
    ('TiZr', 'energy_and_sampling_tradeoff', 'Retain the printed fine-energy disadvantage and unequal q meshes even when risk_tags is empty.'),
    ('NaAuH3', 'harmonic_to_anharmonic_transfer', 'Test whether the harmonic scalar-model benefit survives justified anharmonic/SOC follow-up; presently unresolved.'),
    ('Cr2Re', 'magnetism_and_competing_phase', 'Separate actual contrary phase priors from an unmeasured magnetic ground state; do not reject from Cr content alone.'),
    ('N2TiZr', 'relaxation_history_and_stress', 'Retain both the earlier failed and later converged optimization and the fine anisotropic stress.'),
    ('Be4ZrRh', 'nonmonotonic_electron_count', 'Do not convert nominal electron count or a finite electronic envelope into mobile carriers or active-orbital bandwidth.'),
    ('Nb6GaSb', 'opposite_comparator', 'Retain loss against AlNb6Sb alongside benefit against GaNb6Rh; one favorable comparison is not universal superiority.'),
    ('YZr3N4', 'coupled_chemical_geometry', 'Keep chemical, mass, volume and model effects coupled; a source gain does not isolate geometric causality.'),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def build(source: Path = SOURCE):
    raw = source.read_bytes()
    catalogue = json.loads(raw)
    rows = catalogue['candidates']
    if len(rows) != 103 or len({row['id'] for row in rows}) != 103:
        raise ValueError('Expected the frozen 103-state source catalogue')
    by_formula = {row['formula']: (index, row) for index, row in enumerate(rows)}
    cases = []
    for formula, purpose, falsifier in CASES:
        index, c = by_formula[formula]
        if c['formal_RPS'] is not None or c['experimental_superconductivity'] is not None:
            raise ValueError('Source authority changed; reassess benchmark projection')
        cases.append({
            'id': 'source-check:' + c['source_state'], 'kind': 'retrospective_source_pair',
            'formula': formula, 'target_state': c['source_state'], 'control_state': c['control_state'],
            'source_pointer': f'/candidates/{index}',
            'source_record_sha256': sha(encoded(c)),
            'purpose': purpose, 'research_question': c['next_action'],
            'known_source_tc': c['source_tc'], 'known_lambda_difference': c['lambda_difference'],
            'countercontrols_count': len(c['countercontrols']),
            'countercontrols_pointer': f'/candidates/{index}/countercontrols',
            'risk_summary': c['risk_summary'], 'ambient_scope': c['ambient_scope'],
            'acceptance_rule': falsifier, 'evaluation_type': 'identity_and_inference_regression',
            'future_replication': {'status': 'not_run', 'numerical_tolerance': None,
                                   'prerequisites': ['exact source input/UPF/runtime association',
                                                     'freeze observable-specific tolerance and resource envelope before execution']},
            'eligible_as_unseen_test': False, 'promote_evidence_level': False,
        })
    anchors = [
        {'id': 'anchor:nb2timo-bcc', 'formula': 'Nb2TiMo', 'related_source_state': 'agm001228974',
         'url': 'https://arxiv.org/abs/2412.08361v1', 'locator': 'Abstract',
         'reviewed_scope': 'primary_abstract', 'phase': 'experimental BCC alloy',
         'reported_tc_k': 3.22, 'reported_tc_relation': 'approximately',
         'measurement_methods': ['resistivity', 'magnetization', 'specific heat'],
         'acceptance_rule': 'Same reduced composition does not establish the same ordered structure or sample; source theoretical Tc remains separate.'},
        {'id': 'anchor:hfnbta-bcc', 'formula': 'HfNbTa', 'related_source_state': 'agm001271506',
         'url': 'https://arxiv.org/abs/2602.19376v1', 'locator': 'Abstract',
         'reviewed_scope': 'primary_abstract', 'phase': 'experimental BCC alloy',
         'reported_tc_k': None, 'reported_tc_relation': 'not_extracted_from_this_scope',
         'measurement_methods': [],
         'acceptance_rule': 'Preserve the BCC experimental prior; the abstract does not supply an extracted numeric Tc and does not identify the ordered hexagonal source state.'},
        {'id': 'anchor:mgb2-al-c', 'formula': 'MgB2 with Al or C substitution', 'related_source_state': None,
         'url': 'https://doi.org/10.1103/PhysRevB.71.144512', 'locator': 'Abstract',
         'reviewed_scope': 'primary_abstract', 'phase': 'partially substituted polycrystalline samples',
         'reported_tc_k': None, 'reported_tc_relation': 'qualitative_suppression',
         'measurement_methods': ['temperature-dependent upper critical field'],
         'acceptance_rule': 'Al and C substitution both suppress Tc in the reported samples while Hc2 responses differ; more nominal electrons is not a positive Tc label. Exact ordered simulation states remain unlinked.'},
    ]
    for item in anchors:
        cases.append({**item, 'kind': 'experimental_identity_anchor', 'reviewed_on': '2026-10-08',
                      'evaluation_type': 'source_identity_and_counterexample',
                      'sample_to_simulation_association': 'unestablished',
                      'eligible_as_unseen_test': False, 'promote_evidence_level': False})
    return {
        'schema_version': 'discovery-benchmark-suite/1.0.0', 'version': '2026-10-08-v1',
        'status': 'prepared_retrospective_checks_not_executed_replications',
        'source': {'path': SOURCE.relative_to(ROOT).as_posix(), 'sha256': sha(raw),
                   'catalogue_version': catalogue['version'], 'dataset': catalogue['dataset_source']},
        'counts': {'cases': len(cases), 'source_pairs': len(CASES), 'experimental_identity_anchors': len(anchors),
                   'new_calculations': 0, 'new_material_discoveries': 0},
        'selection': {'method': 'purposeful failure-mode coverage', 'outcomes_known_at_selection': True,
                      'representative_of_all_superconductors': False,
                      'prospective_holdout_credit': False},
        'prospective_protocol': {
            'freeze_before_results': ['host/action groups', 'exact target/control inputs', 'observables and scope',
                                     'tolerances', 'baselines', 'resource envelope', 'success/falsification decisions'],
            'baselines': ['random within same eligible pool', 'source-Tc heuristic', 'simple-physics heuristic', 'proposed policy'],
            'metrics': ['independently supported states per actual cost', 'top-k follow-up success with explicit denominator',
                        'response-direction accuracy', 'cost to falsification', 'out-of-domain abstention'],
            'failure_handling': 'Keep failed, unselected, unconverged and censored cases; unknown Tc is never zero.'},
        'cases': cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = encoded(build())
    outputs = {'benchmark-suite-v1.json': content,
               'benchmark-suite-v1.sha256': (sha(content) + '  benchmark-suite-v1.json\n').encode()}
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            (OUT / name).write_bytes(data)
    else:
        for name, data in outputs.items():
            if (OUT / name).read_bytes() != data:
                raise SystemExit('Stale benchmark projection: ' + name)
    print(json.dumps({'cases': 12, 'source_pairs': 9, 'anchors': 3, 'new_calculations': 0,
                      'suite_sha256': sha(content), 'status': 'written' if args.write else 'checked'}))


if __name__ == '__main__':
    main()
