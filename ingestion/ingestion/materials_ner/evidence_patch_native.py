"""Evidence repairs at native procedure and result-definition owners only."""
from .evidence_patch import EvidencePatch, output_schema
from . import evidence_patch_shared as shared
from .validation import pointer_exists
from .wire_v7 import NativeExtraction


def build_targets(compact, validation):
    found = {}
    for target in shared.build_targets(compact, validation):
        kind, identifier, field = target["entity"], target["entity_id"], target["field"]
        if kind == "result" and field.startswith("/definition/"):
            kind, field = "definition", field[len("/definition"):]
            if field.startswith("/parameters/") and field.endswith("/quantity"):
                field = field[:-len("/quantity")]
        found.setdefault((kind, identifier, field), set()).update(target["issue_codes"])
    maps, targets = compact.entity_maps(), []
    for index, ((kind, identifier, field), codes) in enumerate(sorted(found.items()), 1):
        entity = maps[kind][identifier]
        body = entity.result if kind == "result" else entity
        present = field in shared.VIRTUAL.get(kind, set()) or pointer_exists(body.model_dump(), field)
        targets.append({"id": f"E{index}", "entity": kind, "entity_id": identifier,
            "field": field, "field_present": present, "issue_codes": sorted(codes),
            "permitted_action": "bind" if present else "remove_invalid_pointer"})
    return targets


def render(bundle, compact, targets, inventory=None):
    return shared.render(bundle, compact, targets, inventory) + (
        "\nDefinition evidence belongs only to its observation. An invalid procedure "
        "parameter pointer must be removed only at that procedure. Do not reuse it "
        "automatically for result thresholds. Verify each requested definition "
        "parameter independently against its actual source and subject.")


apply_patch = shared.apply_patch


def verify_extraction(receipt, bundle, raw_output):
    return shared.verify_extraction(receipt, bundle, raw_output,
        wire_model=NativeExtraction, target_builder=build_targets)
