"""Check new relation semantics while preserving all reported assertions."""
from math import isclose

from .quantities import normalize
from .evidence_policy import required, raw_fields


def validate_raw_literals(extraction, issue):
    """A source-raw string must occur in evidence bound to that assertion.

    An object-level binding may support its nested raw fields; a sibling field,
    another sample or an unbound occurrence elsewhere in the paper may not.
    Whitespace layout is allowed, but spelling, hyphenation and words are not
    silently repaired. Numerical raw expressions retain their quantity checks.
    """
    for group in ("samples", "states", "protocols", "results"):
        for index, entity in enumerate(getattr(extraction, group)):
            for field, raw in raw_fields(entity.model_dump()):
                if field == "/definition/criterion_raw":
                    continue  # Existing criterion-specific check and error code.
                bindings = [e for e in entity.evidence
                            if field == e.field or field.startswith(e.field.rstrip("/") + "/")]
                path = f"/{group}/{index}" + field
                if not bindings:
                    issue("source_literal_evidence_missing", path)
                elif not isinstance(raw, str) or not raw.strip() or not any(
                        " ".join(raw.split()) in " ".join(e.quote.split()) for e in bindings):
                    issue("source_literal_not_in_field_evidence", path)


def same_quantity(kind, left, right):
    if left.status != "reported" or right.status != "reported": return False
    a, b = (normalize(kind, q)["normalized"] for q in (left, right))
    for key in ("relation", "unit", "approximate"):
        if a[key] != b[key]: return False
    def same_number(x,y):
        return x is y if x is None or y is None else isclose(x,y,rel_tol=1e-12,abs_tol=1e-15)
    if any(not same_number(a.get(k),b.get(k)) for k in ("value","lower","upper")): return False
    if (a["uncertainty"] is None) != (b["uncertainty"] is None): return False
    if a["uncertainty"] is not None:
        if a["uncertainty"]["kind"] != b["uncertainty"]["kind"]: return False
        if not same_number(a["uncertainty"].get("level"), b["uncertainty"].get("level")): return False
        if any(not same_number(a["uncertainty"][k], b["uncertainty"][k]) for k in ("minus","plus")): return False
    return True


def validate_pressure_consistency(extraction, issue):
    """Review contradictory or unselected operative pressure conditions.

    This checks the graph's own assertions. It never derives ambient pressure
    from a number or chooses a measurement setting from synthesis, scan or
    extrapolation context. Equal unit-converted quantities can repeat without
    creating a false conflict; incompatible alternatives still need review.
    """
    for index, state in enumerate(extraction.states):
        declaration = state.pressure
        operative = [c for c in state.conditions if c.kind == 'pressure'
                     and c.role in {'measurement', 'simulation'}
                     and c.quantity.status == 'reported']
        if not operative:
            continue
        path = f'/states/{index}/pressure'
        if declaration.condition_id is None:
            if declaration.availability in {'not_reported', 'not_applicable'}:
                issue('pressure_declaration_contradicts_reported_condition', path)
            else:
                issue('pressure_condition_selection_requires_review', path)
            continue
        # Native validation has already checked reference ownership, kind,
        # role and availability. Retain its errors rather than repairing it.
        selected = next(c for c in state.conditions if c.id == declaration.condition_id)
        for condition in operative:
            if condition.id == selected.id:
                continue
            try:
                equivalent = same_quantity('pressure', selected.quantity, condition.quantity)
            except ValueError:
                equivalent = False
            if not equivalent:
                issue('pressure_state_alternatives_require_review', path)
                break


def validate_relations(extraction, evidence_for, issue):
    states={s.id:s for s in extraction.states}
    results={r.id:r for r in extraction.results}
    protocols={p.id:p for p in extraction.protocols}
    def literal(entity, path):
        if not any(e.field=="/relation_raw" and " ".join(entity.relation_raw.split()) in " ".join(e.quote.split())
                   for e in entity.evidence):
            issue("relation_raw_not_in_field_evidence", path+"/relation_raw")
    for index, relation in enumerate(extraction.sample_relations):
        path=f"/sample_relations/{index}"
        evidence_for(relation,path,required('sample_relation', relation))
        literal(relation,path)
    for index, support in enumerate(extraction.condition_supports):
        path=f"/condition_supports/{index}"
        evidence_for(support,path,required('condition_support', support))
        literal(support,path)
        result=results[support.result_id]
        condition=next(c for c in states[support.state_id].conditions if c.id==support.condition_id)
        if result.quantity_kind != condition.kind:
            issue("condition_support_quantity_kind_mismatch",path+"/result_id")
        else:
            try:
                if not same_quantity(condition.kind,result.quantity,condition.quantity):
                    issue("condition_support_quantity_mismatch",path+"/result_id")
            except ValueError:
                issue("condition_support_quantity_unresolved",path+"/result_id")
        if result.origin not in {"observed","model_derived"}:
            issue("condition_measurement_origin_unresolved",path+"/result_id")
        if not protocols[result.protocol_id].method:
            issue("condition_measurement_method_unresolved",path+"/result_id")
    for index, result in enumerate(extraction.results):
        if result.quantity_kind=="thickness" and result.definition.criterion not in {"not_applicable","fit_parameter","unspecified"}:
            issue("specimen_thickness_transition_criterion_mismatch",f"/results/{index}/definition/criterion")
        if (result.quantity_kind=="thickness" and result.origin in {"observed","model_derived"}
                and any(c.kind=="thickness" and c.role=="sample_geometry" for c in states[result.state_id].conditions)
                and not any(s.result_id==result.id for s in extraction.condition_supports)):
            # Require a disposition, never infer an edge from equal values. A
            # disagreement may be faithful source data and needs explicit review.
            issue("geometry_condition_support_requires_review",f"/results/{index}")


def connected_samples(extraction, used_samples):
    connected=set(used_samples)
    while True:
        previous=len(connected)
        for relation in extraction.sample_relations:
            pair={relation.from_sample_id,relation.to_sample_id}
            if pair & connected: connected.update(pair)
        if len(connected)==previous: return connected
