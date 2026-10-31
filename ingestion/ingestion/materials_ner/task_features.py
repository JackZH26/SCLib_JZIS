"""Task-specific proposal feature dispositions, never training authorization.

This reuses source conditions, support edges and result dependencies. Numeric
coincidence is a review signal, not a claim that a scientific fact is wrong.
No condition is flattened into a scalar by discarding its bounds or uncertainty.
"""
from copy import deepcopy
from math import isclose

from .contract import digest
from .quantities import normalize

VERSION = 'materials-ner-task-features/1'
CONTROL_KINDS = ('pressure','magnetic_flux_density','magnetic_field_strength','mu0_h',
                 'strain','carrier_density','gate_voltage')
GEOMETRY_KINDS = ('thickness','radius')
OUTCOME_KINDS = frozenset({'tc','non_detection','model_temperature_scale','superfluid_stiffness','hc2','hc2_field_strength'})
TC_CRITERIA = frozenset({'onset','midpoint','zero_resistance','offset','diamagnetic_onset','heat_capacity_anomaly'})
TASKS = {
    'T1-composition-tc': dict(target='observed_point_tc',origin='observed',condition_features={},
        temperature_policy='All state temperatures excluded from the composition-only feature budget.'),
    'T2-conditions-tc': dict(target='observed_point_tc',origin='observed',
        condition_features={'measurement':CONTROL_KINDS,'sample_geometry':GEOMETRY_KINDS},
        temperature_policy='All state temperatures excluded from this Tc prediction feature budget; equality with Tc alone is not scientific error.'),
    'T3-computed-tc': dict(target='computed_point_tc',origin='computed',
        condition_features={'simulation':CONTROL_KINDS,'sample_geometry':GEOMETRY_KINDS},
        temperature_policy='State temperatures excluded. Computation model and independently computed physical inputs require separate protocol/input qualification.'),
    'T4-superconductivity-non-detection': dict(target='not_detected_in_reported_window',origin='observed',
        condition_features={'measurement':CONTROL_KINDS,'sample_geometry':GEOMETRY_KINDS,
            'detection_window':('temperature',*CONTROL_KINDS)},
        temperature_policy='Only explicitly referenced detection-window temperatures are candidate inputs; the target is not an intrinsic nonsuperconductor label.'),
}


def task_specifications():
    return deepcopy(TASKS)


POLICY_SHA256 = digest(dict(version=VERSION,tasks=TASKS,outcome_kinds=sorted(OUTCOME_KINDS),
    observed_tc_criteria=sorted(TC_CRITERIA),
    dependency_policy='derived_from ancestry excludes outcomes; same_measurement outcome links in either direction require review; compares_with is not causal',
    coincidence_policy='normalized equal point Tc and temperature is a diagnostic only'))


ADOPTED_VERSION = 'materials-ner-task-features/2'
ADOPTED_OUTCOME_KINDS = OUTCOME_KINDS | {'tc_pressure_slope'}
ADOPTED_POLICY_SHA256 = digest(dict(previous_policy=POLICY_SHA256,version=ADOPTED_VERSION,
    outcome_kinds=sorted(ADOPTED_OUTCOME_KINDS),resistivity_policy='No automatic resistivity feature or label admission.'))

PRESSURE_VERSION = 'materials-ner-task-features/3'
PRESSURE_POLICY_SHA256 = digest(dict(previous_policy=ADOPTED_POLICY_SHA256, version=PRESSURE_VERSION,
    pressure_policy='Retain the source declaration and missingness; qualitative ambient is never numeric zero. Categorical feature use requires task review.'))

EXTRAPOLATION_VERSION = 'materials-ner-task-features/4'
EXTRAPOLATION_OUTCOME_KINDS = ADOPTED_OUTCOME_KINDS | {'inverse_square_penetration_depth'}
EXTRAPOLATION_POLICY_SHA256 = digest(dict(previous_policy=PRESSURE_POLICY_SHA256, version=EXTRAPOLATION_VERSION,
    outcome_kinds=sorted(EXTRAPOLATION_OUTCOME_KINDS),
    extrapolation_policy='Extrapolation targets are not measured controls or detection windows. No inverse-square penetration-depth feature or label admission.'))


DEVICE_VERSION = 'materials-ner-task-features/5'
DEVICE_POLICY_SHA256 = digest(dict(previous_policy=EXTRAPOLATION_POLICY_SHA256,version=DEVICE_VERSION,
    descriptor_policy='Retain twist geometry and reported displacement; no new automatic feature admission or field-convention conversion.'))

def _quantity(kind,quantity):
    try:return normalize(kind,quantity)['normalized']
    except (ValueError,KeyError):return None


def _input_dependencies(start,result_map,outcome_kinds=OUTCOME_KINDS):
    """Keep causal ancestry separate from noncausal comparison links."""
    pending=list(start);seen=set();outcomes=set();shared=set()
    while pending:
        key=pending.pop()
        if key in seen:continue
        seen.add(key);result=result_map.get(key)
        if result is None:continue
        if result.quantity_kind in outcome_kinds:outcomes.add(key)
        for edge in result.dependencies:
            if edge.relation=='derived_from':pending.append(edge.result_id)
            elif edge.relation=='same_measurement' and result_map[edge.result_id].quantity_kind in outcome_kinds:
                shared.add(edge.result_id)
        # Unlike derived_from, sharing one measurement is symmetric. The link
        # may be recorded on the outcome rather than on the supporting input.
        for other_id,other in result_map.items():
            if other.quantity_kind in outcome_kinds and any(
                    e.relation=='same_measurement' and e.result_id==key for e in other.dependencies):
                shared.add(other_id)
    return dict(support_result_ids=sorted(start),derived_ancestor_result_ids=sorted(seen),
        outcome_ancestor_result_ids=sorted(outcomes),shared_outcome_result_ids=sorted(shared))


def _label(result,state,protocol,task):
    reasons=[];label=None;negative=None
    if result.source_role!='primary':reasons.append('label_not_primary')
    if result.origin!=task['origin']:reasons.append('label_origin_outside_task')
    if task['target']=='not_detected_in_reported_window':
        negatives=[q for q in getattr(result,'qualifiers',[]) if q.kind=='non_detection']
        if result.quantity_kind!='non_detection' or len(negatives)!=1:
            reasons.append('not_single_non_detection_result')
        else:
            negative=negatives[0]
            if getattr(negative,'target',None)!='superconductivity':reasons.append('non_detection_target_not_superconductivity')
            ids=getattr(negative,'window_condition_ids',[])
            own={getattr(c,'id',None):c for c in state.conditions}
            if (getattr(negative,'window_status',None)!='reported' or not ids
                    or any(i not in own or own[i].role!='detection_window'
                        or own[i].kind!='temperature' or _quantity(own[i].kind,own[i].quantity) is None
                        or (own[i].quantity.relation=='exact' and getattr(own[i],'window_position',None)
                            not in {'lower_limit','upper_limit'}) for i in ids)):
                reasons.append('non_detection_window_unresolved')
            if getattr(negative,'observable','unspecified')=='unspecified':reasons.append('non_detection_observable_unresolved')
            if not reasons:label=dict(kind=task['target'],observable=negative.observable,window_condition_ids=ids,
                intrinsic_superconductivity_status='not_established',tc_kelvin=None)
    else:
        if result.quantity_kind!='tc':reasons.append('label_not_tc')
        q=_quantity('tc',result.quantity) if result.quantity_kind=='tc' else None
        if not q or q['relation']!='exact':reasons.append('label_not_point_tc')
        if q and q['approximate']:reasons.append('approximate_label_requires_task_policy')
        criterion=result.definition.criterion if hasattr(result,'definition') else protocol.criterion
        if task['origin']=='observed' and criterion not in TC_CRITERIA:reasons.append('observed_tc_criterion_unresolved')
        if any(x.kind=='conditional_existence' for x in getattr(result,'qualifiers',[])):
            reasons.append('conditional_existence_is_not_established_label')
        if not reasons:label=dict(kind=task['target'],quantity=q,criterion=criterion)
    return label,sorted(set(reasons)),negative


def assess_tasks(extraction,bundle,validation):
    """Read-only, version-pinned assessment of all four proposed ML tasks."""
    if (validation.get('extraction_sha256')!=digest(extraction.model_dump())
            or validation.get('bundle_sha256')!=digest(bundle.model_dump())):
        raise ValueError('task_feature_validation_binding_mismatch')
    adopted = extraction.schema_version in {'materials-ner/12', 'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}
    pressure_native = extraction.schema_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}
    descriptor_native = extraction.schema_version == 'materials-ner/15'
    extrapolation_native = extraction.schema_version in {'materials-ner/14', 'materials-ner/15'}
    outcome_kinds = EXTRAPOLATION_OUTCOME_KINDS if extrapolation_native else ADOPTED_OUTCOME_KINDS if adopted else OUTCOME_KINDS
    states={s.id:(i,s) for i,s in enumerate(extraction.states)}
    samples={s.id:s for s in extraction.samples};protocols={p.id:p for p in extraction.protocols}
    results={r.id:r for r in extraction.results};support={}
    for edge in getattr(extraction,'condition_supports',[]):
        support.setdefault((edge.state_id,edge.condition_id),set()).add(edge.result_id)
    rows=[]
    for result in extraction.results:
        si,state=states[result.state_id];sample=samples[result.sample_id];diagnostics=[];conditions=[]
        target=_quantity('tc',result.quantity) if result.quantity_kind=='tc' else None
        for ci,condition in enumerate(state.conditions):
            path=f'/states/{si}/conditions/{ci}';key=getattr(condition,'id',None)
            normalized=_quantity(condition.kind,condition.quantity)
            if descriptor_native:
                normalized=validation['normalized'].get(path+'/quantity',{}).get('normalized')
            issues=[i for i in validation['issues'] if i['path']==path or i['path'].startswith(path+'/')]
            provenance=_input_dependencies(support.get((state.id,key),set()),results,outcome_kinds)
            match=bool(target and normalized and condition.kind=='temperature' and target['relation']==normalized['relation']=='exact'
                and target.get('value') is not None and normalized.get('value') is not None
                and target['unit']==normalized['unit'] and isclose(target['value'],normalized['value'],rel_tol=1e-12,abs_tol=1e-12))
            if match:diagnostics.append(dict(code='tc_value_matches_state_temperature',condition_path=path,
                scientific_error_established=False,numeric_coincidence_alone_is_not_proof=True))
            conditions.append((condition,dict(condition_id=key,condition_index=ci,state_id=state.id,source_path=path,
                kind=condition.kind,role=condition.role,source_value_status=condition.quantity.status,
                normalized=normalized,technical_issues=issues,provenance=provenance,coincides_with_tc=match)))
        tasks={}
        for task_id,task in TASKS.items():
            label,label_reasons,negative=_label(result,state,protocols[result.protocol_id],task)
            dispositions=[];candidates=[]
            for condition,entry in conditions:
                reasons=[];allowed=condition.kind in task['condition_features'].get(condition.role,())
                if not allowed:reasons.append('condition_outside_task_feature_budget')
                if extrapolation_native and condition.role == 'extrapolation_target':
                    reasons.append('extrapolation_target_is_not_measured_control')
                if condition.kind=='temperature' and task['target']!='not_detected_in_reported_window':
                    reasons.append('temperature_not_an_input_for_this_tc_task')
                if condition.role=='detection_window' and task['target']=='not_detected_in_reported_window':
                    if negative is None or entry['condition_id'] not in getattr(negative,'window_condition_ids',[]):
                        reasons.append('condition_not_in_label_detection_window')
                if condition.kind == 'reported_magnetic_field':
                    reasons.append('magnetic_field_convention_unresolved')
                elif condition.kind == 'reported_displacement_field':
                    reasons.append('displacement_field_convention_unresolved')
                elif entry['normalized'] is None:reasons.append('source_quantity_unavailable_or_invalid')
                if entry['technical_issues']:reasons.append('feature_source_validation_failed')
                if entry['provenance']['outcome_ancestor_result_ids']:reasons.append('feature_has_outcome_ancestor')
                if entry['provenance']['shared_outcome_result_ids']:reasons.append('feature_shares_outcome_measurement_requires_review')
                if label_reasons:reasons.append('result_outside_task_label_scope')
                item={k:v for k,v in entry.items() if k!='normalized'}
                item.update(disposition='excluded' if reasons else 'candidate_requires_review',reason_codes=sorted(set(reasons)),eligible_for_training=False)
                dispositions.append(item)
                if not reasons:candidates.append(dict(source_path=entry['source_path'],condition_id=entry['condition_id'],kind=condition.kind,
                    role=condition.role,quantity=deepcopy(entry['normalized']),window_position=getattr(condition,'window_position',None)))
            tasks[task_id]=dict(label_candidate=label,label_scope_reason_codes=label_reasons,
                composition_source_ref=dict(sample_id=sample.id,extraction_sha256=validation['extraction_sha256']),
                composition_features_status='not_adjudicated',condition_candidates=candidates,condition_dispositions=dispositions,
                technical_validation_passed=validation['valid'],scientific_review_status='pending',
                grouping_and_temporal_qualification='pending',eligible_for_training=False)
            if pressure_native:
                declaration = state.pressure.model_dump()
                reasons = ['categorical_pressure_task_review_required']
                if task_id == 'T1-composition-tc':
                    reasons.append('condition_outside_task_feature_budget')
                if declaration['availability'] != 'reported':
                    reasons.append('pressure_declaration_unresolved')
                if label_reasons:
                    reasons.append('result_outside_task_label_scope')
                tasks[task_id]['pressure_declaration'] = dict(source_path=f'/states/{si}/pressure',
                    source_value=declaration, missing=declaration['availability'] != 'reported',
                    numeric_value_imputed=False, reason_codes=reasons, eligible_for_training=False)
        rows.append(dict(result_id=result.id,diagnostics=diagnostics,tasks=tasks))
    return dict(schema=DEVICE_VERSION if descriptor_native else EXTRAPOLATION_VERSION if extrapolation_native else PRESSURE_VERSION if pressure_native else ADOPTED_VERSION if adopted else VERSION,
        policy_sha256=DEVICE_POLICY_SHA256 if descriptor_native else EXTRAPOLATION_POLICY_SHA256 if extrapolation_native else PRESSURE_POLICY_SHA256 if pressure_native else ADOPTED_POLICY_SHA256 if adopted else POLICY_SHA256,extraction_sha256=validation['extraction_sha256'],
        bundle_sha256=validation['bundle_sha256'],validation_sha256=digest(validation),
        task_definitions=task_specifications(),results=rows,
        absent_conditions_policy='No implicit ambient pressure, zero, or inferred source absence; no imputation performed.',
        source_graph_modified=False,training_matrix_created=False,scientific_acceptance=False,ml_training_eligible=False)


def verify_assessment(assessment,extraction,bundle,validation,config):
    """Verify new audits without rewriting historical validation or approvals."""
    adopted = extraction.schema_version in {'materials-ner/12', 'materials-ner/13'}
    version, policy = (ADOPTED_VERSION, ADOPTED_POLICY_SHA256) if adopted else (VERSION, POLICY_SHA256)
    if extraction.schema_version == 'materials-ner/13':
        version, policy = PRESSURE_VERSION, PRESSURE_POLICY_SHA256
    if extraction.schema_version in {'materials-ner/14','materials-ner/15'}:
        version, policy = EXTRAPOLATION_VERSION, EXTRAPOLATION_POLICY_SHA256
    if extraction.schema_version == 'materials-ner/15':
        version, policy = DEVICE_VERSION, DEVICE_POLICY_SHA256
    if (config.get('task_feature_version')!=version
            or config.get('task_feature_policy_sha256')!=policy):
        raise ValueError('task_feature_policy_pin_mismatch')
    if digest(assessment)!=digest(assess_tasks(extraction,bundle,validation)):
        raise ValueError('task_feature_assessment_mismatch')
