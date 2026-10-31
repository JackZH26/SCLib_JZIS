"""Exact source-position choices for the opt-in durable catalog stage.

Tokens are locators, not normalized text. Selecting endpoints copies the
original contiguous bytes; it never joins phrases or assigns scientific meaning.
The earlier compiled-catalog protocol and its retained failures stay unchanged.
"""
from copy import deepcopy
import re
from typing import Literal

from pydantic import Field

from . import compiled_catalog as previous, table_ownership
from .contract import StrictModel, canonical, digest
from .evidence import source_catalog
from .field_candidates import active_span_ranges, text_candidates
from .sources import sha

POLICY = 'materials-source-atom-catalog/1'
CONTEXT = 'materials-source-atom-context/1'


class TextChoice(StrictModel):
    candidate_id: str
    end_candidate_id: str | None


class Basis(previous.Basis):
    support: TextChoice | None


class IsotopeChoice(previous.IsotopeChoice):
    isotope_label: TextChoice
    applicability: TextChoice


class VariableChoice(previous.VariableChoice):
    symbol: TextChoice
    site: TextChoice | None
    basis: Basis
    applicability: TextChoice


class ConditionChoice(previous.ConditionChoice):
    basis: TextChoice | None
    orientation: TextChoice | None
    applicability: TextChoice


class StateChoice(previous.StateChoice):
    label: TextChoice | None
    preparation: TextChoice | None
    sample_support: TextChoice
    conditions: list[ConditionChoice] = Field(max_length=32)
    # Operational ownership proposals; not new canonical scientific fields.
    table_cell_ids: list[str] = Field(max_length=128)


class FormulaChoice(previous.FormulaChoice):
    formula: TextChoice
    basis: Basis
    context: TextChoice | None


class SampleChoice(previous.SampleChoice):
    label: TextChoice | None
    formula: TextChoice | None
    basis: Basis
    scope_support: TextChoice
    form: TextChoice | None
    substrate: TextChoice | None
    isotopes: list[IsotopeChoice] = Field(max_length=16)
    variables: list[VariableChoice] = Field(max_length=16)
    alternative_formulas: list[FormulaChoice] = Field(max_length=16)
    states: list[StateChoice] = Field(max_length=64)


class ParameterChoice(previous.ParameterChoice):
    name: TextChoice
    support: TextChoice


class ProcedureChoice(previous.ProcedureChoice):
    method: TextChoice | None
    observable: TextChoice | None
    details: TextChoice | None
    applicability: TextChoice
    parameters: list[ParameterChoice] = Field(max_length=32)


class Unrepresented(previous.Unrepresented):
    source: TextChoice


class CatalogChoices(previous.CatalogChoices):
    schema_version: Literal[POLICY]
    samples: list[SampleChoice] = Field(max_length=96)
    protocols: list[ProcedureChoice] = Field(max_length=64)
    unrepresented: list[Unrepresented] = Field(max_length=128)


def context(bundle, parent, ledger, *, marker_convention):
    """Embed the actual immutable table inputs, not a path to mutable inputs."""
    from .item_worker import verify_parent
    inventory = verify_parent(parent, bundle, workflow='source_item_stages_v4')
    occurrences = parent.get('required_occurrences', [])
    compiled = table_ownership.compile_ownership(bundle, ledger, marker_convention=marker_convention)
    if {c['id'] for c in compiled['cells']} != {o['id'] for o in occurrences}:
        raise ValueError('staged_atom_table_occurrences_not_closed')
    cells = {c['id']: c for c in compiled['cells']}
    for occurrence in occurrences:
        check_cell_occurrence(cells[occurrence['id']], occurrence)
    return dict(schema=CONTEXT, bundle_sha256=digest(bundle.model_dump()), parent_run_id=parent['run_id'],
        inventory_sha256=digest(inventory.model_dump()), ledger=deepcopy(ledger),
        marker_convention=marker_convention, ownership_sha256=digest(compiled),
        required_occurrences=deepcopy(occurrences))


def check_cell_occurrence(cell, occurrence):
    source = cell['source_cell']
    # A frozen result occurrence excludes a trailing explicit note marker.
    # Keep both original locations; never make the marker part of a quantity.
    value = re.sub(r'(?:\\footnotemark\[[1-9][0-9]*\])+$', '', source['quote']).rstrip()
    expected = dict(id=cell['id'], block_id=source['block_id'], start_char=source['start_char'],
        end_char=source['start_char']+len(value), quote=value, quote_sha256=sha(value.encode()))
    if expected != occurrence:
        raise ValueError('staged_atom_table_occurrence_changed')


def verify_context(value, bundle, inventory, parent=None):
    from .frozen_inventory import occurrence_accounting
    keys = {'schema', 'bundle_sha256', 'parent_run_id', 'inventory_sha256', 'ledger',
            'marker_convention', 'ownership_sha256', 'required_occurrences'}
    if (set(value) != keys or value['schema'] != CONTEXT
            or value['bundle_sha256'] != digest(bundle.model_dump())
            or value['inventory_sha256'] != digest(inventory.model_dump())):
        raise ValueError('staged_atom_context_binding_mismatch')
    if parent is not None and value != context(bundle, parent, value['ledger'], marker_convention=value['marker_convention']):
        raise ValueError('staged_atom_context_parent_mismatch')
    compiled = table_ownership.compile_ownership(bundle, value['ledger'], marker_convention=value['marker_convention'])
    if digest(compiled) != value['ownership_sha256']:
        raise ValueError('staged_atom_table_source_changed')
    cells = {c['id']: c for c in compiled['cells']}
    if set(cells) != {o['id'] for o in value['required_occurrences']}:
        raise ValueError('staged_atom_table_occurrences_not_closed')
    for occurrence in value['required_occurrences']:
        check_cell_occurrence(cells[occurrence['id']], occurrence)
    accounting = occurrence_accounting(bundle, inventory, value['required_occurrences'])
    return compiled, {r['inventory_item_id']: r['occurrence_id'] for r in accounting['rows']}


def candidates(bundle, ownership):
    result = previous.candidates(bundle)
    result['policy'] = POLICY
    blocks = {b.id: b for b in bundle.blocks}
    clauses = deepcopy(result['texts'])
    for key, row in result['texts'].items():
        row['clause_id'] = key
    count = 0
    for key, clause in clauses.items():
        block = blocks[clause['block_id']]
        pieces = [(clause['start_char']+m.start(), clause['start_char']+m.end(), 'token')
                  for m in re.finditer(r'\S+', clause['quote'])]
        pieces += [(v['start_char'], v['end_char'], 'math') for v in text_candidates(
            block.text, clause['start_char'], clause['end_char'], dollar_escape_parity=True) if v['kind'] == 'math']
        # Separate isotope labels inside arrows without interpreting the arrow.
        pieces += [(clause['start_char']+m.start(), clause['start_char']+m.end(), 'isotope_literal')
                   for m in re.finditer(r'\$\^\{[0-9]+\}\$[A-Z][a-z]?', clause['quote'])]
        seen = set()
        for start, end, kind in pieces:
            if (start, end) in seen:
                continue
            seen.add((start, end)); count += 1
            quote = block.text[start:end]
            result['texts']['A'+str(count)] = dict(clause_id=key, kind=kind,
                block_id=block.id, span_id=clause['span_id'], start_char=start, end_char=end,
                quote=quote, quote_sha256=sha(quote.encode()))
    # Table cells and attached note definitions also have exact selectable IDs.
    source = source_catalog(bundle)
    for cell in ownership['cells']:
        entries = {name: cell[name] for name in ('source_cell', 'row_label', 'source_header', 'source_row')}
        entries.update({'note_'+n['label']: n['definition_source'] for n in cell['footnotes']})
        for name, row in entries.items():
            carriers = [sid for sid, span in source['spans'].items() if span['block_id'] == row['block_id']
                        and span['start_char'] <= row['start_char'] and row['end_char'] <= span['end_char']]
            if not carriers:
                raise ValueError('staged_atom_table_carrier_missing')
            result['texts'][cell['id']+'/'+name] = dict(row, span_id=carriers[0],
                clause_id=None, kind='table_'+name, table_cell_id=cell['id'])
    return result


def select(catalog, choice, bundle):
    if choice.candidate_id not in catalog['texts']:
        raise ValueError('staged_atom_text_candidate_unknown')
    first = deepcopy(catalog['texts'][choice.candidate_id])
    if choice.end_candidate_id is not None:
        last = catalog['texts'].get(choice.end_candidate_id)
        if (last is None or first['clause_id'] is None or last['clause_id'] != first['clause_id']
                or first['block_id'] != last['block_id'] or last['start_char'] < first['start_char']
                or last['end_char'] < first['end_char']):
            raise ValueError('staged_atom_endpoint_scope_mismatch')
        block = next(b for b in bundle.blocks if b.id == first['block_id'])
        start, end = first['start_char'], last['end_char']
        if len(active_span_ranges(block.text, start, end)) != 1:
            raise ValueError('staged_atom_endpoint_comment_crossing')
        first.update(end_char=end, quote=block.text[start:end], quote_sha256=sha(block.text[start:end].encode()))
    return first


def _within(value, scope):
    return (value['block_id'] == scope['block_id'] and scope['start_char'] <= value['start_char']
            and value['end_char'] <= scope['end_char'])


def _overlaps(value, scope):
    return value['block_id'] == scope['block_id'] and max(value['start_char'], scope['start_char']) < min(value['end_char'], scope['end_char'])


def project(model, bundle, ownership, *, candidate_catalog=None, dimensionless_variable_amounts=False,
            positioned_evidence=False):
    catalog = deepcopy(candidate_catalog) if candidate_catalog is not None else candidates(bundle, ownership)
    selected = []; converted = deepcopy(model.model_dump())

    def walk(value, path=''):
        if isinstance(value, dict):
            if set(value) == {'candidate_id', 'end_candidate_id'}:
                original = select(catalog, TextChoice.model_validate(value), bundle)
                key = 'selected:'+str(len(selected)+1)
                catalog['texts'][key] = original
                selected.append(dict(selection_path=path, selection=deepcopy(value), source=original))
                return dict(candidate_id=key, literal=None)
            return {k: walk(v, path+'/'+k) for k, v in value.items() if k != 'table_cell_ids'}
        if isinstance(value, list):
            return [walk(v, path+'/'+str(i)) for i, v in enumerate(value)]
        return value

    converted = walk(converted); converted['schema_version'] = previous.POLICY
    projection = previous.project(previous.CatalogChoices.model_validate(converted), bundle, candidate_catalog=catalog,
        dimensionless_variable_amounts=dimensionless_variable_amounts, positioned_evidence=positioned_evidence)
    cells = {c['id']: c for c in ownership['cells']}; assignments = {}; owner_checks = []
    for i, sample in enumerate(model.samples):
        sample_cells = [key for state in sample.states for key in state.table_cell_ids]
        if any(key not in cells for key in sample_cells):
            raise ValueError('staged_atom_table_cell_unknown')
        # Source-scoped series with different x rows need separate samples in
        # this opt-in policy; physical specimen continuity is never inferred.
        row_positions = {(cells[key]['row_label']['block_id'], cells[key]['row_label']['start_char']) for key in sample_cells}
        if len(row_positions) > 1:
            raise ValueError('staged_atom_sample_table_rows_mixed')
        for j, state in enumerate(sample.states):
            if len(set(state.table_cell_ids)) != len(state.table_cell_ids):
                raise ValueError('staged_atom_duplicate_table_cell')
            for key in state.table_cell_ids:
                if key in assignments:
                    raise ValueError('staged_atom_table_cell_multiple_states')
                assignments[key] = dict(sample_id=f'sample:{i+1}', state_id=f'state:{i+1}:{j+1}')
            scopes = [cells[key] for key in state.table_cell_ids]
            if not scopes:
                continue
            fields = [v for v in selected if v['selection_path'].startswith(f'/samples/{i}/states/{j}/') or
                      (v['selection_path'].startswith(f'/samples/{i}/') and '/states/' not in v['selection_path'])]
            for field in fields:
                value = field['source']
                # A direct table alias is scoped to one actual result cell.
                if value.get('table_cell_id') is not None and value['table_cell_id'] not in state.table_cell_ids:
                    if not (value['kind'] in {'table_row_label', 'table_source_row'} and
                            any(_within(value, scope['source_row']) for scope in scopes)):
                        raise ValueError('staged_atom_table_alias_owner_mismatch')
                rows = [c['source_row'] for c in cells.values() if _overlaps(value, c['source_row'])]
                if rows and not any(_within(value, scope['source_row']) for scope in scopes):
                    raise ValueError('staged_atom_table_row_owner_mismatch')
                notes = [n['definition_source'] for c in cells.values() for n in c['footnotes'] if _overlaps(value, n['definition_source'])]
                attached = [n['definition_source'] for c in scopes for n in c['footnotes']]
                if notes and not any(_within(value, note) for note in attached):
                    raise ValueError('staged_atom_table_footnote_owner_mismatch')
            for variable in sample.variables:
                if variable.amount.candidate_id is None:
                    continue
                value = catalog['numbers'][variable.amount.candidate_id]
                if any(_overlaps(value, c['source_row']) for c in cells.values()) and not any(
                        _within(value, scope['row_label']) for scope in scopes):
                    raise ValueError('staged_atom_variable_row_mismatch')
            owner_checks.append(dict(sample_id=f'sample:{i+1}', state_id=f'state:{i+1}:{j+1}',
                table_cell_ids=state.table_cell_ids, source_structure_verified=True, scientific_ownership_verified=False))
    projection.update(schema=POLICY, selections_sha256=digest(model.model_dump()),
        atom_selections=selected, table_ownership_sha256=digest(ownership),
        table_assignments=assignments, table_owner_checks=owner_checks,
        unassigned_table_cell_ids=sorted(set(cells)-set(assignments)))
    return projection


def schema(bundle=None, ownership=None):
    from .inventory import strict_schema
    result = strict_schema(CatalogChoices)
    if bundle is not None:
        options = candidates(bundle, ownership)
        result['properties']['work_id']['enum'] = [bundle.work_id]
        text = result['$defs']['TextChoice']['properties']
        # Listing thousands of IDs twice in a JSON Schema wastes context.
        # Membership and endpoint scope are still checked by select(), before
        # any result extraction. Syntax does not prove a valid source choice.
        pattern = r'^(?:[TA][1-9][0-9]*|T[1-9][0-9]*:R[1-9][0-9]*:C[1-9][0-9]*/(?:source_cell|source_row|source_header|row_label|note_[a-z0-9]+))$'
        text['candidate_id']['pattern'] = pattern
        for variant in text['end_candidate_id']['anyOf']:
            if variant.get('type') == 'string':
                variant['pattern'] = r'^[TA][1-9][0-9]*$'
        for variant in result['$defs']['NumberChoice']['properties']['candidate_id']['anyOf']:
            if variant.get('type') == 'string':
                variant['enum'] = list(options['numbers'])
        for key in ('processed_block_ids', 'unread_block_ids'):
            result['properties'][key]['items']['enum'] = list(source_catalog(bundle)['blocks'])
        if ownership['cells']:
            result['$defs']['StateChoice']['properties']['table_cell_ids']['items']['enum'] = [c['id'] for c in ownership['cells']]
        else:
            result['$defs']['StateChoice']['properties']['table_cell_ids']['maxItems'] = 0
    return result


RULES = '''Select exact source positions, never retype a phrase. T IDs copy a whole
clause. A IDs select a whitespace token, math token or isotope literal. For a
contiguous phrase, select its first candidate_id and last end_candidate_id in
the SAME T clause; null end_candidate_id copies one candidate exactly. Original
whitespace, TeX notation and punctuation are retained. Table aliases select
their explicit cell, row, header or attached footnote. They cannot be extended.
N IDs select numeric occurrences with their printed units and uncertainties.
Unsupported numeric syntax or missing printed units stays unresolved.

Assign table_cell_ids to states only when the source supports those owners.
Each numeric table cell can have one state; a sample cannot combine distinct
table rows. Keep isotope alternatives and back-exchange branches separate.
Sample variables referring to a table row must select that row's x occurrence.
An attached footnote belongs only to its marked cells; the nearest row is not
its owner. A footnote containing both isotope labels describes an exchange,
not by itself a simultaneous isotope mixture or a quantitative abundance.
Leave unrepresented assertions and unsupported bindings explicit. An empty
table_cell_ids list means no table ownership proposal, not inferred coverage.
The compiler checks source structure only; all scientific meaning needs review.
'''


def render_candidates(catalog, ownership):
    lines = []
    for key, row in catalog['texts'].items():
        if not key.startswith('T') or ':' in key:
            continue
        values = [(aid, atom) for aid, atom in catalog['texts'].items() if aid.startswith('A') and atom['clause_id'] == key]
        tokens = [f"{aid}:{atom['quote']}" for aid, atom in values if atom['kind'] == 'token']
        sub = [f"{aid}:{canonical(atom['quote'])}" for aid, atom in values if atom['kind'] != 'token']
        lines.append(key+'['+row['span_id']+'] '+' '.join(tokens))
        if sub:
            lines.append('Subtokens '+ ' '.join(sub))
    table = [c['id']+' row='+canonical(c['row_label']['quote'])+' header='+canonical(c['source_header']['quote'])+
        ' value='+canonical(c['source_cell']['quote'])+' notes='+canonical({n['label']: n['definition_source']['quote'] for n in c['footnotes']})
        for c in ownership['cells']]
    numbers = [key+'['+v['span_id']+'] '+canonical(v['quote'])+' unit='+canonical(v['source_unit'])+
        (' issues='+canonical(v['issues']) if v['issues'] else '') for key, v in catalog['numbers'].items()]
    return '\n'.join(['SOURCE POSITION CANDIDATES:', *lines,
        'TABLE OWNERSHIP (aliases: cell_id/source_cell, /source_row, /row_label, /source_header; /note_LABEL only for listed notes):',
        *table, 'NUMERIC OCCURRENCES:', *numbers])
