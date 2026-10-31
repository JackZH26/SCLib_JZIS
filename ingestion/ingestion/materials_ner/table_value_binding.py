"""Bind an original table value to its own printed column unit and header.

This finite policy supports an explicit unit row immediately below a simple
TeX header. Missing units, spanning cells and unsupported numeric syntax are
holds, never inferred scientific values. Quantity kind and scientific ownership
are decisions outside this source-structure compiler.
"""
from copy import deepcopy
import re

from .contract import Quantity, digest
from .field_quantity import strict_unit
from .numeric_occurrences import source_candidates
from .source_occurrence import positioned_witness
from . import table_ownership as tables

POLICY = 'materials-table-value-binding/1'


def compile_binding(bundle, ownership, cell_id):
    if ownership.get('policy') != tables.POLICY:
        raise ValueError('table_value_ownership_policy')
    matches = [c for c in ownership['cells'] if c['id'] == cell_id]
    if len(matches) != 1:
        raise ValueError('table_value_cell_unknown_or_duplicate')
    cell = matches[0]; blocks = {b.id:b for b in bundle.blocks}
    for key in ('source_cell','source_row','source_header','row_label'):
        tables._source(blocks, cell[key])
    if len({cell[k]['block_id'] for k in ('source_cell','source_row','source_header','row_label')}) != 1:
        raise ValueError('table_value_cross_block')
    block = blocks[cell['source_cell']['block_id']]; text = block.text; column = cell['column']
    row = cell['source_row']; header = cell['source_header']
    values = tables._cells(block, row['start_char'], row['end_char'])
    start = text.rfind('\n', 0, header['start_char'])+1
    end = text.find('\n', header['end_char'])
    if end < 0 or type(column) is not int or not 2 <= column <= len(values):
        raise ValueError('table_value_column_invalid')
    headers = tables._cells(block, start, end)
    if (len(headers) != len(values) or headers[column-1] != header
            or values[column-1] != cell['source_cell'] or values[0] != cell['row_label']):
        raise ValueError('table_value_column_binding_mismatch')
    begin = text.rfind(r'\begin{tabular}', 0, row['start_char'])
    if not 0 <= begin < start < row['start_char'] or r'\end{tabular}' in text[begin:row['end_char']]:
        raise ValueError('table_value_table_scope_mismatch')
    unit_start = end+1; unit_end = text.find('\n', unit_start)
    if not unit_start < unit_end < row['start_char']:
        raise ValueError('table_value_unit_row_missing')
    units = tables._cells(block, unit_start, unit_end)
    # The historical row parser can return an empty quote for a whitespace-only
    # cell. Treat that as an empty label without changing old ownership proofs.
    if (len(units) != len(headers) or (units[0] is not None and units[0]['quote'].strip())
            or units[column-1] is None or not units[column-1]['quote'].strip()):
        raise ValueError('table_value_unit_row_missing')
    unit_cell = units[column-1]
    match = re.fullmatch(r'(?:\\ |[ \t])*\(([^()]*)\)(?:\\ |[ \t])*', unit_cell['quote'])
    if match is None or not match[1].strip():
        raise ValueError('table_value_unit_literal_unsupported')
    a = unit_cell['start_char']+match.start(1)+len(match[1])-len(match[1].lstrip())
    b = unit_cell['start_char']+match.end(1)-len(match[1])+len(match[1].rstrip())
    unit = tables._witness(block, a, b)
    if strict_unit(unit['quote']) is None:
        raise ValueError('table_value_unit_literal_unsupported')
    value_cell = cell['source_cell']
    raw = re.sub(r'(?:\\footnotemark\[[1-9][0-9]*\])+$', '', value_cell['quote']).rstrip()
    candidates = [v for v in source_candidates(raw) if v['kind'] == 'value'
        and v['start_char'] == 0 and v['end_char'] == len(raw)]
    if (len(candidates) != 1 or candidates[0]['syntax_shape'] is None
            or candidates[0]['source_unit'] is not None
            or candidates[0]['issues'] != ['source_unit_not_stated']):
        raise ValueError('table_value_numeric_shape_unresolved')
    source = candidates[0]
    value = tables._witness(block, value_cell['start_char'], value_cell['start_char']+len(raw))
    quantity = Quantity(status='reported', raw=raw,
        **dict(source['syntax_shape'], unit=unit['quote'])).model_dump()
    evidence = [dict(field=field, **positioned_witness(bundle, original))
        for field,original in [('/quantity_name_raw',header),('/quantity',value),('/quantity',unit),
                               ('/quantity/raw',value),('/quantity/unit',unit)]]
    return dict(policy=POLICY,bundle_sha256=digest(bundle.model_dump()),ownership_sha256=digest(ownership),
        cell_id=cell_id,column=column,quantity_name_raw=header['quote'],quantity=quantity,evidence=evidence,
        source=dict(value=value,unit=unit,unit_cell=unit_cell,unit_row=tables._witness(block,unit_start,unit_end),
                    header=deepcopy(header),row=deepcopy(row),row_label=deepcopy(cell['row_label'])),
        numeric_source=deepcopy(source),scientific_ownership_verified=False,
        scientific_acceptance=False,ml_training_eligible=False)


def verify_binding(binding, bundle, ownership):
    if binding != compile_binding(bundle, ownership, binding['cell_id']):
        raise ValueError('table_value_binding_changed')
    return binding
