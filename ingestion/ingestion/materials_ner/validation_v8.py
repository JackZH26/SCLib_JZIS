"""Target-specific scope and source checks; no semantic auto-correction."""
import re

from .quantities import normalize, quantity_source_issues
from .evidence_policy import required


def validate_non_detection(result, state, protocol, path, evidence_for, issue, normalized):
    selected=[(i,q) for i,q in enumerate(result.qualifiers) if q.kind=='non_detection']
    if len(selected)!=1:
        issue('non_detection_single_target_required',path);return
    index,negative=selected[0];prefix=f'/qualifiers/{index}'
    if result.origin!='observed' or protocol.method_class=='calculation':
        issue('non_detection_requires_observed_measurement',path)
    if protocol.method_class=='unspecified' or not protocol.method:
        issue('non_detection_method_unresolved',path)
    # These conservative conflicts request source review. They do not reinterpret
    # a sentence, assign a target, or certify the absence of other conflicts.
    raw=negative.raw.replace('$','')
    if negative.target=='superconductivity' and re.search(r'supercurrent|(?:0|zero)\s*(?:--?|–|−)\s*(?:\\pi|π|pi)',raw,re.I):
        issue('device_non_detection_misclassified_as_superconductivity',path+prefix)
    conditions={c.id:c for c in state.conditions}
    for identifier in negative.window_condition_ids:
        condition=conditions.get(identifier)
        if condition is None:
            issue('non_detection_window_owner_mismatch',path+prefix);continue
        allowed=(condition.kind=='temperature' and condition.role=='detection_window') if negative.target=='superconductivity' else (
            condition.kind in {'temperature','thickness','pressure','magnetic_flux_density','magnetic_field_strength','mu0_h'}
            and condition.role in {'detection_window','study_extent'})
        if not allowed or condition.quantity.status!='reported':
            issue('non_detection_window_role_or_quantity_mismatch',path+prefix)
        if (condition.quantity.status=='reported' and condition.quantity.relation=='exact'
                and condition.window_position not in {'lower_limit','upper_limit'}):
            # "At 4.5 nm" is a specimen/setting point. It cannot establish a
            # scan extent merely by being placed in a detection_window field.
            issue('non_detection_point_is_not_scan_window',path+prefix)
    if negative.window_condition_ids:evidence_for(result,path,required('non_detection_window',result))
    conditional=next((q for q in result.qualifiers if q.kind=='conditional_existence'
                      and getattr(q,'tc_bound',None) is not None),None)
    if negative.target=='superconductivity' and conditional:
        bound=conditional.tc_bound
        if bound.status=='reported' and bound.relation in {'lt','le'}:
            for offset,condition in enumerate(state.conditions):
                q=condition.quantity
                if (condition.id not in negative.window_condition_ids or condition.kind!='temperature'
                        or condition.role!='detection_window' or condition.window_position!='lower_limit'
                        or q.status!='reported' or q.relation!='exact'):
                    continue
                try:
                    endpoint=normalize('temperature',q)['normalized']['value']
                    threshold=normalize('tc',bound)['normalized']['upper']
                except (ValueError,KeyError):
                    continue
                if abs(endpoint-threshold)>1e-12*max(1,abs(threshold)):
                    continue
                wording=' '.join(conditional.raw.split()); expression=' '.join(bound.raw.split())
                quotes=[' '.join(e.quote.split()) for e in state.evidence if e.field==f'/conditions/{offset}']
                if quotes and all(wording in quote and expression in quote for quote in quotes):
                    issue('conditional_bound_window_requires_source_review',path)
    for offset,sensitivity in enumerate(negative.sensitivities):
        field=f'{prefix}/sensitivities/{offset}'
        evidence_for(result,path,[f for f in required('non_detection_sensitivity',result) if f==field])
        wording=' '.join(sensitivity.raw.split())
        if not any(e.field==field and wording in ' '.join(e.quote.split()) for e in result.evidence):
            issue('sensitivity_raw_not_in_field_evidence',path+field)
        if sensitivity.quantity.status!='reported':
            issue('reported_sensitivity_quantity_required',path+field)
        if sensitivity.role!='measurement_step' and re.search(r'\b(?:step|increment)\b',wording,re.I):
            issue('measurement_step_is_not_detection_threshold',path+field)
        try:
            normalized[path+field+'/quantity']=normalize(sensitivity.quantity_kind,sensitivity.quantity)
            for code in quantity_source_issues(sensitivity.quantity_kind,sensitivity.quantity,result.evidence,field):
                issue(code,path+field)
        except ValueError as error:issue(str(error),path+field)
