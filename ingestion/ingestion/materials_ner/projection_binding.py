"""Mechanical address/text binding for unaudited model graphs.

Changes only evidence metadata. Uses supplied original ranges, never reference
answers, numeric proximity, semantic substitutions or nearest-quote guesses.
"""
from copy import deepcopy
import re
from . import paper_coverage as coverage, reader_scope
from .contract import canonical, digest
from .validation import pointer_exists, resolve_quote
from .quantities_v2 import UNITS

VERSION = 'materials-projection-binding/5'
GROUPS = ('samples','states','protocols','results','sample_relations','condition_supports')
UNIT_ATOMS = {name for unit in UNITS.values() for name in unit[1]
    if re.fullmatch(r'[A-Za-zμµΩÅ%]+',name)}


def native_graph(graph):
    """Remove only known provider locator metadata; keep it in the raw artifact."""
    output = deepcopy(graph)
    if not isinstance(output,dict):return output
    for group in GROUPS:
        entities=output.get(group, [])
        if not isinstance(entities,list):continue
        for entity in entities:
            if not isinstance(entity,dict) or not isinstance(entity.get('evidence',[]),list):continue
            # Source-ID selections have no native locator until compiled. The
            # raw provider artifact retains them; this view checks science only.
            entity['evidence'] = [e for e in entity['evidence']
                if not isinstance(e,dict) or 'witness_ids' not in e]
            for evidence in entity.get('evidence', []):
                if isinstance(evidence,dict):evidence.pop('context_quote', None)
    return output


def isolated_selector(text, start, end, field):
    """A contextual selector cannot clip a word, signed number or unit token."""
    before = text[start-1] if start else ''
    after = text[end] if end < len(text) else ''
    first,last = text[start],text[end-1]
    if first.isalnum() and (before.isalnum() or before=='_'):return False
    if last.isalnum() and (after.isalnum() or after=='_'):return False
    if first.isdigit() and before in ('-','+','−','.'):return False
    if first.isdigit() and text[:start].rstrip().endswith(('-','+','−')):return False
    if last.isdigit() and after=='.' and end+1<len(text) and text[end+1].isdigit():return False
    if field.endswith('/unit') and (before in ('/','^','*','·') or after in ('/','^','*','·')):return False
    if field.endswith('/unit'):
        left,right=text[:start].rstrip(),text[end:].lstrip()
        if right.startswith(('/','^','*','·')):return False
        if left.endswith(('/','*','·')):
            atom=re.search(r'([A-Za-zμµΩÅ%]+)$',left[:-1].rstrip())
            if atom and atom[1] in UNIT_ATOMS:return False
    return True


def contextual_positions(text, quote, start, end, field):
    """Count eligible full-token occurrences before deciding uniqueness.

    A 'K' inside 'T/K' or 'mK' is not an alternative standalone-K unit witness.
    Context and selected text are still original bytes. Multiple eligible
    occurrences remain ambiguous; no numerical proximity or property inference.
    """
    pieces=quote.split()
    if not pieces:return set()
    pattern=r'(?=(' + r'\s+'.join(re.escape(piece) for piece in pieces) + r'))'
    positions=set()
    for match in re.finditer(pattern,text[start:end]):
        a,z=start+match.start(1),start+match.end(1)
        if isolated_selector(text,a,z,field):positions.add((a,z))
    return positions


def scientific_payload(graph):
    copy = deepcopy(graph)
    for group in GROUPS:
        for entity in copy[group]:
            entity.pop('evidence', None)
    return copy


def compile_catalog_bindings(graph, bundle, scope, manifest, catalog):
    """Compile explicit source IDs without asking a model to copy evidence.

    Only literal raw/unit pointers are narrowed, using the unchanged scientific
    field as selector. Repeated occurrences stay held; no closest-number or
    semantic association is inferred. Other pointers keep their selected spans.
    """
    from . import scoped_evidence
    if catalog != scoped_evidence.build(bundle, scope, version=catalog.get('schema')):
        raise ValueError('scoped_catalog_drift')
    coverage.verify(manifest, bundle)
    blocks = {b.id: b for b in bundle.blocks}
    output = deepcopy(graph); selections = []; holds = []
    for group in GROUPS:
        for i, entity in enumerate(output[group]):
            original = entity['evidence']; entity['evidence'] = []
            # A unit can use only an already established literal raw occurrence,
            # independent of the order in which the provider listed evidence.
            ordered=sorted(enumerate(original),key=lambda pair:
                isinstance(pair[1],dict) and isinstance(pair[1].get('field'),str) and pair[1]['field'].endswith('/unit'))
            for n, item in ordered:
                path = f'/{group}/{i}/evidence/{n}'
                try:
                    if set(item) != {'field', 'witness_ids'}:
                        raise ValueError('catalog_selection_shape')
                    field = item['field']
                    if not isinstance(field, str) or not field.startswith('/') or not pointer_exists(entity, field):
                        raise ValueError('evidence_field_address_unresolved')
                    ids = item['witness_ids']
                    if not isinstance(ids, list) or any(not isinstance(x,str) for x in ids):
                        raise ValueError('catalog_selection_shape')
                    anchors = scoped_evidence.selected(catalog, ids, bundle, scope, manifest)
                    resolution='provided_source_spans'
                    if field.endswith(('/raw', '/unit', '_raw')):
                        value = entity
                        for key in field.lstrip('/').split('/'):
                            key = key.replace('~1','/').replace('~0','~')
                            value = value[int(key)] if isinstance(value,list) else value[key]
                        if not isinstance(value,str) or not value.strip():
                            raise ValueError('catalog_literal_selector_shape')
                        resolution='candidate_literal_in_selected_source'
                        if field.endswith('/unit'):
                            from .field_quantity import expression,strict_unit
                            raw_field=field[:-len('/unit')]+'/raw'
                            siblings={(e['block_id'],e['start_char'],e['end_char']):e for e in entity['evidence'] if e['field']==raw_field}
                            if len(siblings)==1:
                                sibling=next(iter(siblings.values()));parsed=expression(sibling['quote'])
                                if parsed and parsed['inline_unit']:
                                    if strict_unit(parsed['inline_unit'])!=strict_unit(value):
                                        raise ValueError('catalog_inline_unit_disagrees_with_raw')
                                    if not coverage.inside(sibling,anchors):
                                        raise ValueError('catalog_inline_unit_outside_selection')
                                    # For result numeric raw, retain the existing
                                    # TARGET obligation before it can locate a unit.
                                    if group=='results' and raw_field=='/quantity/raw' and not coverage.inside(sibling,[s for s in scope['passages'] if s['role']=='target']):
                                        raise ValueError('catalog_inline_raw_outside_target')
                                    anchors=[sibling]
                                    resolution='inline_unit_in_bound_raw_occurrence'
                        positions = set()
                        for a in anchors:
                            text = blocks[a['block_id']].text
                            positions.update((a['block_id'],start,end) for start,end in
                                contextual_positions(text,value,a['start_char'],a['end_char'],field))
                        if len(positions) != 1:
                            raise ValueError('catalog_literal_ambiguous' if positions else 'catalog_literal_not_in_selected_source')
                        block_id,start,end = next(iter(positions))
                        anchors = [dict(block_id=block_id,start_char=start,end_char=end,
                            quote=blocks[block_id].text[start:end])]
                    compiled = [dict(field=field, **{k:a[k] for k in ('block_id','start_char','end_char','quote')}) for a in anchors]
                    entity['evidence'].extend(compiled)
                    selections.append(dict(path=path, before=deepcopy(item), after=deepcopy(compiled),resolution=resolution))
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    holds.append(dict(path=path,code=str(exc)))
    result = compile_bindings(output, bundle, scope, manifest)
    result.update(input_graph_sha256=digest(graph), source_catalog_sha256=digest(catalog),
        evidence_transport='source_catalog', selections=selections,
        holds=holds+result['holds'], scientific_payload_unchanged=scientific_payload(result['graph'])==scientific_payload(graph))
    assert result['scientific_payload_unchanged']
    return result


def compile_bindings(graph, bundle, scope, manifest):
    reader_scope.shape(scope)
    coverage.verify(manifest, bundle)
    if graph['work_id'] != bundle.work_id or scope['preflight'] != manifest['source']['preflight']:
        raise ValueError('projection_binding_source_identity')
    blocks = {b.id:b for b in bundle.blocks}
    for p in scope['passages']:
        b = blocks.get(p['block_id'])
        if (b is None or type(p['start_char']) is not int or type(p['end_char']) is not int
                or not 0 <= p['start_char'] < p['end_char'] <= len(b.text)
                or p['role'] not in {'target','context'}):
            raise ValueError('projection_binding_scope_bounds')
    output = deepcopy(graph)
    edits = []
    holds = []
    for group in GROUPS:
        for i, entity in enumerate(output[group]):
            for n, evidence in enumerate(entity['evidence']):
                path = f'/{group}/{i}/evidence/{n}'
                before = deepcopy(evidence)
                context = evidence.pop('context_quote', None)
                def record_edit():
                    if evidence!=before:
                        edits.append(dict(path=path,before=before,after=deepcopy(evidence)))
                field = evidence['field']
                escaped = entity['id'].replace('~','~0').replace('/','~1')
                prefix = f'/{group}/{escaped}/'
                if field.startswith(prefix):
                    field = field[len(prefix)-1:]
                # No ID-to-array-index guessing; null or root fields do not
                # identify the claimed scientific property.
                if not field.startswith('/') or not pointer_exists(entity, field):
                    holds.append(dict(path=path,code='evidence_field_address_unresolved'))
                    record_edit()
                    continue
                block = blocks.get(evidence['block_id'])
                spans = [p for p in scope['passages'] if p['block_id']==evidence['block_id']
                    and (group!='results' or field not in {'/quantity','/quantity/raw','/quantity/value','/quantity/lower','/quantity/upper'} or p['role']=='target')]
                if block is None:
                    holds.append(dict(path=path,code='evidence_source_block_missing'))
                    record_edit()
                    continue
                evidence['field'] = field
                positions = set()
                ambiguous = False
                if context is not None:
                    if not isinstance(context,str) or not context.strip() or 'start_char' in evidence or 'end_char' in evidence:
                        holds.append(dict(path=path,code='contextual_selector_shape_invalid'))
                    else:
                        for span in spans:
                            a,z=span['start_char'],span['end_char']
                            try:
                                left,right=resolve_quote(block.text[a:z],context)
                                left,right=a+left,a+right
                                selected=contextual_positions(block.text,evidence['quote'],left,right,field)
                                if selected:positions.update(selected)
                                elif evidence['quote'] in block.text[left:right]:
                                    holds.append(dict(path=path,code='contextual_selector_clips_token'))
                            except ValueError as exc:
                                if str(exc)=='ambiguous_quote_locator':ambiguous=True
                elif 'start_char' in evidence or 'end_char' in evidence:
                    a,z=evidence.get('start_char'),evidence.get('end_char')
                    if (type(a) is int and type(z) is int and 0<=a<z<=len(block.text)
                            and block.text[a:z]==evidence['quote']
                            and coverage.inside(dict(block_id=block.id,start_char=a,end_char=z),spans)):
                        positions.add((a,z))
                    else:
                        holds.append(dict(path=path,code='explicit_evidence_selector_invalid'))
                else:
                    for span in spans:
                        a,z=span['start_char'],span['end_char']
                        try:
                            left,right=resolve_quote(block.text[a:z],evidence['quote'])
                            positions.add((a+left,a+right))
                        except ValueError as exc:
                            if str(exc)=='ambiguous_quote_locator':ambiguous=True
                if ambiguous or len(positions)!=1:
                    holds.append(dict(path=path,code='evidence_occurrence_ambiguous' if ambiguous or len(positions)>1 else 'evidence_quote_unresolved_in_scope'))
                else:
                    a,z=next(iter(positions))
                    witness=dict(block_id=block.id,start_char=a,end_char=z,quote=block.text[a:z])
                    if not coverage.published(witness,manifest,bundle):
                        holds.append(dict(path=path,code='evidence_source_not_published'))
                    else:
                        evidence.update(witness)
                record_edit()
    assert scientific_payload(output)==scientific_payload(graph)
    return dict(schema=VERSION, input_graph_sha256=digest(graph), output_graph_sha256=digest(output),
        graph=output, edits=edits, holds=holds, scientific_payload_unchanged=True,
        source_bundle_sha256=digest(bundle.model_dump()), scope_sha256=digest(scope),
        reference_answers_used=False, scientific_acceptance=False, native_graph_validated=False)
