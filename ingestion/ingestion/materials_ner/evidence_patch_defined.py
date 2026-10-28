"""Route evidence patches to shared procedures or individual result definitions."""
from .evidence_patch import EvidencePatch, output_schema
from . import evidence_patch_shared as shared
from .validation import pointer_exists
from .wire_v6 import DefinedExtraction


def build_targets(compact, validation):
    found = {}
    for target in shared.build_targets(compact.as_shared_v1(), validation):
        kind, identifier, field = target["entity"], target["entity_id"], target["field"]
        if kind == "protocol": kind, identifier, field = compact.source_protocol_field(identifier, field)
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
        "\nA definition target belongs only to its observation ID. A protocol target "
        "is shared procedure background. Never bind a generic procedure as evidence "
        "for an unsupported result criterion or threshold.")


apply_patch = shared.apply_patch


def verify_extraction(receipt, bundle, raw_output):
    shared.verify_extraction(receipt, bundle, raw_output,
                             wire_model=DefinedExtraction, target_builder=build_targets)
    if "extraction" in receipt:
        expected = DefinedExtraction.model_validate_json(raw_output).projection_manifest()
        if receipt.get("definition_projection") != expected:
            raise ValueError("result_definition_projection_manifest_mismatch")
