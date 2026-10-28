"""Conservative admission of evidence-only automatic extraction repairs.

Both model drafts are retained. Scientific field changes need a separate
source-reviewed revision; a lower error count cannot authorize rewriting facts.
"""
from .contract import digest


def scientific_payload(compact):
    def strip(value):
        if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if k!="evidence"}
        if isinstance(value,list):return [strip(v) for v in value]
        return value
    body=compact.model_dump()
    result={k:strip(v) for k,v in body.items() if k not in {"limitations","observations"}}
    result["processed_block_ids"]=sorted(body["processed_block_ids"])
    result["unread_block_ids"]=sorted(body["unread_block_ids"])
    result["observations"]={o["id"]:strip(o) for o in body["observations"]}
    return result


def issue_keys(compact,validation):
    keys=set()
    for issue in validation["issues"]:
        path=issue["path"].split("/")
        if len(path)>2 and path[1] in {"samples","states","protocols","results"} and path[2].isdigit():
            index=int(path[2])
            if hasattr(compact,"validation_entity_ids"):
                identifiers=compact.validation_entity_ids()[path[1]]
                if index<len(identifiers):path[2]=identifiers[index]
                keys.add((issue["code"],"/".join(path)))
                continue
            rows=(getattr(compact,path[1]) if compact.schema_version=="materials-ner-shared/1"
                  and path[1]!="results" else compact.observations)
            if index<len(rows):path[2]=rows[index].id
        keys.add((issue["code"],"/".join(path)))
    return keys


def assess_repair(before,before_validation,after,after_validation):
    old,new=scientific_payload(before),scientific_payload(after)
    introduced=issue_keys(after,after_validation)-issue_keys(before,before_validation)
    reasons=[]
    if old!=new:reasons.append("scientific_payload_changed_requires_source_review")
    if introduced:reasons.append("new_validation_issues")
    return {"schema":"materials-repair-selection/1","admitted":not reasons,
            "reason_codes":reasons,"introduced_issues":[{"code":c,"path":p} for c,p in sorted(introduced)],
            "before_scientific_payload_sha256":digest(old),"after_scientific_payload_sha256":digest(new),
            "policy":"Only evidence changes with no new validation issue can be selected automatically.",
            "scientific_acceptance":False}
