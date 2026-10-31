"""Private exact-result read context; this endpoint does not accept decisions."""
from services.materials_review_subject import capture_subject, capture_context_subject
from services.research_release_manifest import canonical, digest
from services.scientific_result_dossier import _admit, _locator, _number, _text, MAX_RESPONSE_BYTES
from services.scientific_result_subject import require, ScientificSubjectError, VERSION_V3

VERSION = "materials-result-review-context/1.1.0"
CONTEXT_VERSION = "materials-result-review-context/1.2.0"
CONDITIONS_VERSION = "materials-result-review-context/1.3.0"
OUTCOMES_VERSION = "materials-result-review-context/1.4.0"
OBSERVATIONS_VERSION = "materials-result-review-context/1.5.0"
REPORTED_FIELD_VERSION = "materials-result-review-context/1.6.0"
PROPERTIES_VERSION = "materials-result-review-context/1.7.0"
DEVICE_DESCRIPTORS_VERSION = "materials-result-review-context/1.8.0"


def _quantity(q):
    result={k:_number(q[k]) for k in ("value","lower","upper")}
    result.update({k:_text(q[k],80) for k in ("status","relation","unit")})
    result["approximate"]=q["approximate"]
    u=q["uncertainty"]
    result["uncertainty"]=None if u is None else {"kind":_text(u["kind"],80),
        **{k:_number(u[k]) for k in ("minus","plus","level")}}
    return result


def _conditional(value):
    return {"condition":_text(value["condition"],80),
        "tc_bound":None if value["tc_bound"] is None else _quantity(value["tc_bound"])}


def _outcome(value):
    result={"version":_text(value["version"],80),"kind":_text(value["kind"],80)}
    if value["kind"]=="tc":result["quantity"]=_quantity(value["quantity"])
    elif value["kind"]=="conditional_tc":result["conditional"]=_conditional(value["conditional"])
    else:
        result.update({"target":_text(value["target"],80),"observable":_text(value["observable"],80),
            "window":{"availability":_text(value["window"]["availability"],80),
                "condition_ids":[_text(x,100) for x in value["window"]["condition_ids"]]}})
        if "conditional" in value:result["conditional"]=_conditional(value["conditional"])
    return result


def _definition(row, kind):
    payload=row["extraction_metadata" if kind=="claim" else "raw"].get("result_semantics")
    if payload is None:
        return {"criterion":row["tc_definition"],"parameters":[],"qualifiers":[]} if kind=="claim" else None
    parameters=[]
    for parameter in payload["definition"]["parameters"]:
        q=parameter["quantity"]
        quantity={k:_number(q[k]) for k in ("value","lower","upper")}
        quantity.update({k:_text(q[k],80) for k in ("status","relation","unit")})
        require(type(q["approximate"]) is bool,"scientific_context_quantity_shape")
        quantity["approximate"]=q["approximate"]
        uncertainty=q["uncertainty"]
        if uncertainty is not None:
            uncertainty={"kind":_text(uncertainty["kind"],80),
                **{k:_number(uncertainty.get(k)) for k in ("minus","plus","level")}}
        quantity["uncertainty"]=uncertainty
        parameters.append({"kind":_text(parameter["kind"],80),"quantity":quantity})
    return {"version":_text(payload["version"],80),"criterion":_text(payload["definition"]["criterion"],80),
        "parameters":parameters,"qualifiers":[{"kind":_text(q["kind"],80),"stage":_text(q["stage"],80)}
                                                for q in payload["qualifiers"]]}


def _observation_outcome(value):
    result=_outcome(value)
    result.update({k:_text(value[k],120) for k in ('result_key','existence','source_role')})
    result['citation_status']='retained' if value['cited_source_raw'] is not None else 'not_reported'
    result['sensitivities']=[{'role':_text(item['role'],80),'quantity_kind':_text(item['quantity_kind'],80),
        'quantity':_quantity(item['quantity'])} for item in value['sensitivities']]
    result['task_exclusions']=['not_point_tc','independent_scientific_review_pending']
    if value['target']!='superconductivity':
        result['task_exclusions'].append('device_non_detection_is_not_superconductivity_negative_label')
    return result


async def review_context(db, *, actor_user_id, result_kind, result_id):
    # Existing live user/grant policy applies before exposing result identities.
    await _admit(db,actor_user_id)
    try:
        subject=await capture_subject(db,result_kind=result_kind,result_id=result_id)
    except ScientificSubjectError as exc:
        if str(exc) not in {"materials_context_review_contract_required","materials_conditions_review_contract_required"}:raise
        subject=await capture_context_subject(db,result_kind=result_kind,result_id=result_id)
    data=subject.data;target=data["target"]
    rows={(r["table"],r["row_id"]):r["snapshot"] for r in data["rows"]}
    table="material_claims" if result_kind=="claim" else "event_properties"
    row=rows[table,target["result_id"]];event=rows["research_events",target["event_id"]]
    state=rows["material_states",target["state_id"]]
    numeric=("value_kelvin","value_lower_kelvin","value_upper_kelvin","pressure_gpa","minimum_temperature_k") if result_kind=="claim" else ("value","lower","upper")
    text=("property_type","result_status","value_relation","tc_definition","pressure_state") if result_kind=="claim" else ("property_key","registry_version","component_key","relation","unit")
    result={**{k:_number(row[k]) for k in numeric},**{k:_text(row[k],120) for k in text},
            "definition":_definition(row,result_kind)}
    if result_kind=="claim":
        result["unit"]="K"
        result["evidence_role"]=_text(row["evidence_role"],80)
        for key,limit in (("measurement_method",100),("sample_form",50)):
            # Missing source fields stay null; no normalized method is guessed.
            result[key]=None if row[key] is None else _text(row[key],limit)
    occurrences=[]
    for (name,_),occurrence in sorted(rows.items()):
        if name!="claim_source_occurrences" or result_kind!="claim" or occurrence["claim_id"]!=target["result_id"]:continue
        revision=rows["source_revisions",occurrence["source_revision_id"]]
        capture=rows["source_captures",occurrence["capture_id"]]
        occurrences.append({"occurrence_id":occurrence["id"],"binding_status":occurrence["binding_status"],
            "source_revision_id":revision["id"],"capture_id":capture["id"],"bytes_sha256":capture["bytes_sha256"],
            "version_status":revision["version_status"],"provider_revision":revision["provider_revision"],
            "representation":capture["representation"],"locator":_locator(occurrence["locator"])})
    typed_conditions=any(name=="material_states" and value["condition_schema_version"] in {"materials-conditions/1","materials-conditions/2","materials-conditions/3"} for (name,_),value in rows.items())
    conditions_v2=any(name=="material_states" and value["condition_schema_version"]=="materials-conditions/2" for (name,_),value in rows.items())
    descriptors_v3=any(name=="material_states" and value["condition_schema_version"]=="materials-conditions/3" for (name,_),value in rows.items())
    definitions_v2=any((name=="material_claims" and value["extraction_metadata"].get("result_semantics",{}).get("version")=="materials-result-semantics/2") or (name=="event_properties" and value["raw"].get("result_semantics",{}).get("version")=="materials-result-semantics/2") for (name,_),value in rows.items())
    typed_outcomes=any(name=="material_claims" and "materials_outcome" in value["extraction_metadata"] for (name,_),value in rows.items())
    typed_observations=any(name=="event_properties" and "observation_outcome" in value["raw"] for (name,_),value in rows.items())
    adopted_properties=any(name=="event_properties" and value["registry_version"]=="materials-properties/3" for (name,_),value in rows.items())
    descriptor={"version":DEVICE_DESCRIPTORS_VERSION if descriptors_v3 or definitions_v2 else PROPERTIES_VERSION if adopted_properties else REPORTED_FIELD_VERSION if conditions_v2 else OBSERVATIONS_VERSION if typed_observations else OUTCOMES_VERSION if typed_outcomes else CONDITIONS_VERSION if typed_conditions else CONTEXT_VERSION if subject.version==VERSION_V3 else VERSION,"subject_sha256":subject.sha256,"target":target,
        "review_write_available":False,"source_scope":"exact_result_and_forward_dependencies"}
    result={**descriptor,"descriptor_sha256":digest(descriptor),"subject_id":str(subject.subject_id),
        "result_row_sha256":subject.result_row_sha256,"result":result,
        "event":{k:event[k] for k in ("event_type","knowledge_origin")},
        "state":{k:_number(state[k]) if k in {"pressure_gpa","temperature_k"} else state[k]
                 for k in ("id","sample_id","resolution","pressure_status","pressure_gpa","temperature_role","temperature_k")},
        "source_occurrences":occurrences,"artifacts":data["artifacts"],
        "support_artifact_ids":data["support_artifact_ids"],
        "inventory":{"row_count":len(data["rows"]),"artifact_count":len(data["artifacts"])},
        "authority":{"scientific_accepted":False,"ml_training_approved":False,"public_release":False},
        "review_status":"not_determined_by_this_read",
        "source_text_disclosed":False}
    if subject.version==VERSION_V3:
        # Only selected root-event assertions appear in this display. The exact
        # subject also retains predecessor and dependency rows for audit.
        selected=event["context"].get("materials_context")
        result["scientific_context"]={"subject_version":subject.version,"selection":selected,
            "compositions":[],"protocol":None,"sample_relations":[]}
        if selected:
            for key in selected["composition_ids"]:
                value=rows["sample_compositions",key]
                result["scientific_context"]["compositions"].append({k:value[k] for k in
                    ("id","sample_id","revision","composition_basis","composition_schema_version","source_artifact_id","record_sha256")})
            if selected["protocol_id"]:
                value=rows["research_protocols",selected["protocol_id"]]
                result["scientific_context"]["protocol"]={k:value[k] for k in
                    ("id","work_id","revision","method_class","protocol_schema_version","source_artifact_id","record_sha256")}
            for key in selected["relation_ids"]:
                value=rows["sample_relations",key]
                result["scientific_context"]["sample_relations"].append({k:value[k] for k in
                    ("id","from_sample_id","to_sample_id","revision","relation_kind","relation_schema_version","source_artifact_id","record_sha256")})
    if state["condition_schema_version"] in {"materials-conditions/1","materials-conditions/2","materials-conditions/3"}:
        conditions=state["conditions"]
        result["state"]["condition_schema_version"]=state["condition_schema_version"]
        result["state"]["conditions"]={"pressure":{k:conditions["pressure"][k] for k in ("availability","regime","condition_id")},
            "temperature_condition_id":conditions["temperature_condition_id"],
            "items":[{**{k:c[k] for k in ("id","kind","role","window_position")},"quantity":_quantity(c["quantity"])} for c in conditions["items"]]}
        if state["condition_schema_version"] in {"materials-conditions/2","materials-conditions/3"}:
            # This route has always excluded source wording. Expose its retained
            # status and exact artifact/state pin without broadening disclosure.
            result["state"]["condition_evidence"]={"source_artifact_id":state["source_artifact_id"],
                "context_sha256":state["context_sha256"],"source_text_disclosed":False}
            for c,view in zip(conditions["items"],result["state"]["conditions"]["items"]):
                view["source_context"]={k:{"availability":"retained" if c[k] is not None else "not_reported",
                    "disclosed":False} for k in ("basis_raw","orientation_raw")}
                if c["kind"] in {"reported_magnetic_field","reported_displacement_field"}:
                    view["field_convention"]="unresolved"
                    view["normalized_quantity"]=None
                    view["task_exclusions"]=["displacement_field_convention_unresolved" if c["kind"]=="reported_displacement_field" else "magnetic_field_convention_unresolved"]
    if result_kind=="property" and "source_quantity" in row["raw"]:
        result["result"]["source_quantity"]=_quantity(row["raw"]["source_quantity"]["quantity"])
        if row["registry_version"]=="materials-properties/3":
            from models.materials_properties_v3 import normalized_uncertainty
            result["result"]["normalized_uncertainty"]=normalized_uncertainty(
                row["property_key"],row["raw"]["source_quantity"]["quantity"])
            result["result"]["approximate"]=row["raw"]["source_quantity"]["quantity"]["approximate"]
            result["result"]["task_exclusions"]=["not_point_tc","independent_scientific_review_pending",
                "tc_derived_quantity_not_an_independent_tc_feature" if row["property_key"]=="tc_pressure_slope"
                else "resistivity_feature_role_requires_review"]
        supports=row["raw"].get("condition_support")
        result["result"]["condition_support"]={"version":supports["version"],"targets":[
            {k:edge[k] for k in ("state_id","condition_id","relation")} for edge in supports["targets"]]} if supports else None
    if result_kind=="claim" and "materials_outcome" in row["extraction_metadata"]:
        result["result"]["outcome"]=_outcome(row["extraction_metadata"]["materials_outcome"])
    if result_kind=="property" and "observation_outcome" in row["raw"]:
        result["result"]["outcome"]=_observation_outcome(row['raw']['observation_outcome'])
    require(len(canonical(result))<=MAX_RESPONSE_BYTES,"scientific_context_response_limit")
    return result
