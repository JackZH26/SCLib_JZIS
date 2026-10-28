"""Opt-in inventory vocabulary for native quantity adoption, not a v1 rewrite."""
from typing import Literal, get_args
from . import typed_inventory as previous, quantities_v2
from .contract_v12 import ResultV12
from .contract import canonical

VERSION = 'materials-typed-source-inventory/2'
PROJECTION = 'materials-typed-inventory-projection/2'
VALIDATION = 'materials-typed-inventory-validation/2'
RESULT_KINDS = [k for k in get_args(ResultV12.model_fields['quantity_kind'].annotation) if k != 'non_detection']


class TypedInventoryV2(previous.TypedInventory):
    schema_version: Literal[VERSION]


TypedInventory = TypedInventoryV2


def output_schema(bundle=None):
    return previous.output_schema(bundle, model_type=TypedInventoryV2, result_kinds=RESULT_KINDS)


def inspect(model, bundle):
    if not isinstance(model, TypedInventoryV2):
        raise ValueError('adopted_inventory_requires_version_2')
    return previous.inspect(model, bundle, result_kinds=RESULT_KINDS,
        registry=quantities_v2.UNITS, validation_version=VALIDATION)


def project(model, bundle):
    if not isinstance(model, TypedInventoryV2):
        raise ValueError('adopted_inventory_requires_version_2')
    return previous.project(model, bundle, result_kinds=RESULT_KINDS, registry=quantities_v2.UNITS,
        projection_version=PROJECTION, validation_version=VALIDATION)


def render(bundle, layout=None):
    return previous.render(bundle, layout) + '\nADOPTED INVENTORY VERSION: ' + VERSION + '\n' + (
        'The v2 vocabulary additionally includes the following source-tested kinds and units. '
        'Keep normalization-reference specimens and conditions distinct from the pressure-series specimen. '
        'An aggregate slope from cited and current work retains mixed/unresolved provenance; do not invent '
        'separate measurements. Neither new kind is an automatic Tc feature or training label.\n') + canonical({
        k: dict(v, units=list(quantities_v2.UNITS[k][1])) for k, v in quantities_v2.DEFINITIONS.items()})


def verify_read(receipt, bundle):
    """Replay the actual first response, including a structurally invalid read."""
    from .frozen_inventory import parse
    from .sources import sha
    from .contract import digest
    config = receipt['config']
    if (config.get('inventory_link_projection_version') != PROJECTION
            or config.get('inventory_schema_sha256') != digest(output_schema())):
        raise ValueError('typed2_read_policy_mismatch')
    reads = receipt.get('inventory_reads', [])
    if not reads:
        if 'inventory' in receipt or 'typed_inventory' in receipt:
            raise ValueError('typed2_read_missing')
        return
    if len(reads) != 1:
        raise ValueError('typed2_read_count_invalid')
    read = reads[0]
    stages = [s for s in receipt.get('stages', []) if s['name'] == 'inventory']
    raw = read.get('raw_output')
    if (len(stages) != 1 or not isinstance(raw, str)
            or sha(raw.encode()) != stages[0].get('raw_output_sha256')
            or stages[0].get('schema_sha256') != digest(output_schema(bundle))
            or stages[0].get('prompt_sha256') != sha(render(bundle).encode())):
        raise ValueError('typed2_read_capture_mismatch')
    model = TypedInventoryV2.model_validate(parse(raw))
    validation = inspect(model, bundle)
    if (model.model_dump() != receipt.get('typed_inventory') or validation != read.get('validation')
            or validation != receipt.get('inventory_validation')):
        raise ValueError('typed2_read_validation_mismatch')
    if not validation['valid']:
        if 'inventory' in receipt or 'extraction' in receipt or read.get('link_projection'):
            raise ValueError('typed2_invalid_read_was_admitted')
        return
    inventory, proof = project(model, bundle)
    if inventory.model_dump() != receipt.get('inventory') or proof != read.get('link_projection'):
        raise ValueError('typed2_read_projection_mismatch')
