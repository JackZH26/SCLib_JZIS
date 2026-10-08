"""Project an auditable negative-result review from existing saved local receipts.

This reads results; it does not refit a model, rerun an encoder or score candidates.
"""
import argparse
import hashlib
import json
from pathlib import Path


def build(root):
    names = ['fixed80-v3-root-final-saved-acceptance-v1.json',
             'fixed80-v3-root-saved-numeric-review-v2.json',
             'model124-root-final-saved-acceptance-v1.json',
             'fixed80-v3-root-saved-numeric-review-v2.py']
    files = {n: (root / n).read_bytes() for n in names}
    acceptance, numeric, descriptors = [json.loads(files[n]) for n in names[:3]]
    if hashlib.sha256(files[names[1]]).hexdigest() != acceptance['root_numeric_review']['sha256']:
        raise ValueError('Numeric review differs from its accepted hash')
    if acceptance['proxy_validated'] or acceptance['child_transfer_validated'] or descriptors['proxy_approved']:
        raise ValueError('Source authority changed; reassess this negative-result review')
    # The saved arithmetic review explicitly selected metrics.test[k].MAE.
    if "f['metrics']['test'][k]['MAE']" not in files[names[3]].decode():
        raise ValueError('MAE definition no longer matches the saved reviewer')
    metrics = []
    for name, values in numeric['main_metrics_reviewed'].items():
        baseline, model = values['direct_train_median_raw'], values['raw']
        metrics.append({'model': name, 'raw_mae': model, 'train_median_baseline_raw_mae': baseline,
                        'relative_raw_mae_improvement': (baseline-model)/baseline,
                        'unit': 'K' if name.endswith('omega_log_K') else 'dimensionless',
                        'previously_seen_split': True, 'prospective_validation': False})
    return {'schema_version': 'discovery-model-negative-review/1.0.0', 'reviewed_on': '2026-10-08',
            'sources': [{'filename': n, 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)} for n, b in files.items()],
            'metrics': metrics,
            'findings': [
                'Both lambda models have worse raw MAE than the training-median baseline on the saved split.',
                'Both omega-log models improve raw MAE on that split; this does not validate calibration, child-state transfer or joint pairing utility.',
                'The numerical defect was repaired, but all four principal results are unchanged relative to v2.',
                'The mapping between source atoms and final EPC QE state remains unknown.',
                'Previously seen splits cannot acquire new prospective-holdout credit by rerunning evaluation.',
                '124 converged descriptor states out of 135 are retained; 11 failures remain exclusions, not negative-superconductor labels.'],
            'descriptor_readback': {k: descriptors[k] for k in ['source_states','converged_model_states_encoded','not_converged_retained_exclusions','encoded_retained_sites','finite_feature_values']},
            'unproven_failure_explanations': ['domain shift', 'label/state mismatch', 'small effective independent sample', 'model class or descriptor inadequacy'],
            'next_protocol': {
                'target': 'Predict a declared, matched-state response or follow-up utility before attempting absolute room-temperature Tc.',
                'row_unit': 'One explicit physical state, observable, method and source association; no composition-only joins.',
                'minimum_row_fields': ['state_id','parent_group','structure_group','composition_key','source_family','method','pressure','geometry_hash','label_value','label_unit','censoring','label_source_hash','extraction_status'],
                'labels': 'Unknown is null, not zero. Experimental and computed targets stay separate; failures and censored outcomes remain explicit.',
                'splits': 'Freeze connected host/structure/source groups before fitting. Use outer leave-family or time splits when sufficient independent groups exist; otherwise abstain from generalization claims.',
                'preprocessing': 'Fit imputers, scaling, feature selection, hyperparameters and calibration inside each training fold only.',
                'baselines': ['training median','composition-only','simple physics','current descriptor model'],
                'evaluation': ['group-level MAE with units','group bootstrap uncertainty','interval coverage and width','out-of-domain abstention','paired response direction','incremental utility per actual cost'],
                'go_no_go': 'Prospective evaluation must beat declared baselines with adequate independent-group uncertainty and target-domain coverage. No universal numerical improvement threshold is invented after observing results.',
                'thresholds_and_budget': None,
                'new_fit_status': 'not_run; identity repair and preregistered split manifest required'},
            'proxy_validated': False, 'child_transfer_validated': False, 'new_training': False,
            'candidate_score_written': False, 'formal_RPS': None}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-dir', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    data = (json.dumps(build(a.evidence_dir), ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)
    print(json.dumps({'output': str(a.output), 'sha256': hashlib.sha256(data).hexdigest(), 'models_reviewed': 4, 'new_fit': False}))
