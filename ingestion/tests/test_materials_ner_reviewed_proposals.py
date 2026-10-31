"""Scope, provenance and completion boundaries; synthetic inputs, no model calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import paper_coverage as coverage, reviewed_proposals as projection, reviewed_reader as reader
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.proposals import ProposalDatabase, verify_packet
from ingestion.materials_ner.source_audit import audit_source
from ingestion.materials_ner.sources import Bundle, sha
from ingestion.materials_ner.store import Store
from test_materials_ner_reviewed_reader import scope_fixture, Fake

AUTHOR = dict(kind='assistant', identity='Synthetic test author', thread_id='synthetic:test')
NOW = '2026-10-26T00:00:00+00:00'


def reframe(m, b, **changes):
    args = {k: deepcopy(m[k]) for k in ('source', 'roles', 'visuals', 'dependencies', 'supplement',
                                      'assertions', 'author', 'created_at')}
    args.update(changes); return coverage.build(bundle=b, **args)


def at(block, quote):
    start = block.text.index(quote)
    return dict(block_id=block.id, start_char=start, end_char=start+len(quote), quote=quote)


def graph(b):
    block = b.blocks[0]; q = 'The sample showed a resistive onset at 5 K.'
    def ev(fields, quote=q): return [dict(field=f, **at(block, quote)) for f in fields]
    return parse_extraction(dict(schema_version='materials-ner/13', work_id=b.work_id, outcome='results',
        empty_reason=None, processed_block_ids=[block.id], unread_block_ids=[], limitations=[],
        samples=[dict(id='s', label=None, formula_raw=None, composition_basis='unresolved',
            formula_unavailability=dict(status='not_extracted', explanation='Synthetic formula unavailable.', checked_block_ids=[block.id]),
            identity_resolution='unresolved', target_kind='unresolved', form_raw=None, substrate_raw=None,
            isotopes=[], variables=[], evidence=[])],
        states=[dict(id='st', sample_id='s', label=None, conditions=[], preparation_raw=None,
            pressure=dict(availability='not_extracted', regime='unknown', condition_id=None, basis_raw=None), evidence=ev(['/sample_id']))],
        protocols=[dict(id='p', method='resistive', method_class='resistivity', observable=None, details_raw=None,
            parameters=[], context_uses=[], evidence=ev(['/method', '/method_class']))],
        results=[dict(id='r', sample_id='s', state_id='st', protocol_id='p', quantity_kind='tc', quantity_name_raw=None,
            quantity=dict(status='reported', raw='5 K', relation='exact', value=5.0, unit='K'), origin='observed',
            source_role='primary', component_raw=None, interpretation_raw=None, cited_source_raw=None, dependencies=[],
            definition=dict(criterion='onset', criterion_raw='onset', parameters=[]), qualifiers=[],
            evidence=ev(['/quantity_kind', '/quantity', '/sample_id', '/state_id', '/protocol_id', '/origin', '/source_role',
                         '/definition/criterion', '/definition/criterion_raw']))], sample_relations=[], condition_supports=[])).model_dump()


@pytest.fixture
def prepared(tmp_path):
    scope_path = scope_fixture(tmp_path / 'inputs'); s = json.loads(scope_path.read_text())
    pp = Path(s['preflight']['path']); p = json.loads(pp.read_text()); b = Bundle.model_validate(json.loads(Path(p['bundle']['path']).read_text()))
    structure = audit_source(Path(p['original']['path']), work_id=b.work_id, bundle=b)
    Path(p['structure']['path']).write_text(canonical(structure)); p['structure'] = reader.reference(p['structure']['path'])
    pp.write_text(canonical(p)); s['preflight'] = reader.reference(pp); scope_path.write_text(canonical(s))
    m = coverage.seed(s['preflight'], author=AUTHOR, created_at=NOW)
    roles = deepcopy(m['roles']); roles[0].update(role='main', note='Synthetic complete source.', anchors=[at(b.blocks[0], b.blocks[0].text)])
    m = reframe(m, b, roles=roles)
    queue = Store(tmp_path / 'queue'); identifier = reader.enqueue(queue, scope_path)
    reader.run(queue, identifier, provider_override=Fake())
    return queue, identifier, scope_path, b, m


def packet(prepared, **changes):
    queue, identifier, _, b, m = prepared
    args = dict(graph=graph(b), manifest=m, author=AUTHOR, created_at=NOW, note='Synthetic source-backed review.')
    args.update(changes); return projection.build(queue, identifier, **args)


def test_pending_graph_reuses_existing_store_idempotently_and_retains_authorship(prepared, tmp_path):
    p = packet(prepared); assert p['receipt']['validation']['valid'], p['receipt']['validation']['issues']
    db = ProposalDatabase(tmp_path / 'proposals')
    assert db.ingest(p)['inserted']; assert not db.ingest(p)['inserted']
    with db.connect() as c:
        restored = json.loads(c.execute('SELECT payload FROM runs').fetchone()[0])
    assert restored == p; verify_packet(restored)
    assert p['receipt']['config']['model'] == 'assistant'
    assert p['receipt']['reader_provenance']['config']['model'] == 'gpt-6-luna'
    assert not p['receipt']['structured_graph_authored_by_reader']
    assert p['rows']['results'][0]['review_status'] == 'pending_review'
    status = projection.paper_status(prepared[4], prepared[3], [p])
    assert not status['paper_ready_for_independent_review']
    assert not status['scientific_acceptance'] and not status['ml_training_eligible']


@pytest.mark.parametrize('change', ['context_only_quantity', 'crossing_target_edge', 'all_context'])
def test_result_same_block_does_not_bypass_character_scope(prepared, change):
    _, _, scope_path, b, m = prepared; s = json.loads(scope_path.read_text()); block = b.blocks[0]
    cut = block.text.index('The criterion') if change != 'crossing_target_edge' else 25
    s['passages'] = [dict(block_id=block.id, start_char=0, end_char=cut, role='context'),
                     dict(block_id=block.id, start_char=cut, end_char=len(block.text), role='target')]
    if change == 'all_context': s['passages'][1]['role'] = 'context'
    parsed, v = projection.validate_graph(graph(b), b, s, m)
    assert 'result_without_target_original_evidence' in {i['code'] for i in v['issues']}


def test_target_descriptor_cannot_launder_a_numeric_context_witness(prepared):
    _, _, path, b, m = prepared; s=json.loads(path.read_text()); block=b.blocks[0]
    cut=block.text.index('The criterion')
    s['passages']=[dict(block_id=block.id,start_char=0,end_char=cut,role='context'),
                   dict(block_id=block.id,start_char=cut,end_char=len(block.text),role='target')]
    g=graph(b);r=g['results'][0]
    # An otherwise valid parent /quantity binding in TARGET must not mask the
    # separate raw witness that is available only in CONTEXT.
    r['evidence']=[e for e in r['evidence'] if e['field']!='/quantity']
    r['evidence'] += [dict(field='/quantity',**at(block,'The criterion is onset.')),
                      dict(field='/quantity/raw',**at(block,'5 K'))]
    _,v=projection.validate_graph(g,b,s,m)
    assert 'result_without_target_original_evidence' in {i['code'] for i in v['issues']}


@pytest.mark.parametrize('raw,quote,expected', [('5 K','Tc = 15 K.',False),('5 K','Tc = 5 K.',True),
                                             ('4.4','14.4',False),('4.4','4.4  K',True),
                                             ('5 K','-5 K',False),('5 K','−5 K',False),
                                             ('4.4','4.44 K',False),('4.4','Tc is 4.4.',True)])
def test_numeric_target_witness_uses_token_boundaries(raw,quote,expected):
    assert coverage.literal_value_in_quote(raw,quote)==expected


@pytest.mark.parametrize('role', ['unreviewed', 'excluded', 'bibliography'])
def test_non_published_roles_cannot_supply_result_values(prepared, role):
    _, _, path, b, m = prepared; roles = deepcopy(m['roles']); roles[0]['role'] = role
    changed = reframe(m, b, roles=roles)
    _, v = projection.validate_graph(graph(b), b, json.loads(path.read_text()), changed)
    assert not v['valid']; assert 'result_without_target_original_evidence' in {i['code'] for i in v['issues']}


@pytest.mark.parametrize('change', ['gap', 'overlap', 'omitted_block', 'no_anchor'])
def test_source_partitions_cannot_hide_unread_content(prepared, change):
    b, m = prepared[3:]; roles = deepcopy(m['roles'])
    if change == 'gap': roles[0]['start_char'] = 1
    if change == 'overlap': roles.append(deepcopy(roles[0]))
    if change == 'omitted_block': roles = []
    if change == 'no_anchor': roles[0]['anchors'] = []
    with pytest.raises(ValueError): reframe(m, b, roles=roles)


@pytest.mark.parametrize('change', ['graph_value', 'validation', 'author', 'reading', 'scope', 'self_approval'])
def test_portable_packet_replay_rejects_rehashed_tampering(prepared, change):
    p = packet(prepared); r = p['receipt']
    if change == 'graph_value': r['extraction']['results'][0]['quantity']['value'] = 7.0
    if change == 'validation': r['validation']['valid'] = False
    if change == 'author': r['projection_author']['kind'] = 'model'
    if change == 'reading': p['raw_output'] = '{"reading":"Altered."}'; r['raw_output_sha256'] = sha(p['raw_output'].encode())
    if change == 'scope': r['reader_provenance']['scope_json'] += '\n'
    if change == 'self_approval': r['scientific_acceptance'] = True
    p['run_id'] = digest(r); p['packet_hash'] = digest({k:v for k,v in p.items() if k!='packet_hash'})
    with pytest.raises(ValueError): verify_packet(p)


def test_no_source_free_paper_completion_and_context_coverage_not_counted(prepared):
    b, m = prepared[3:]; full = reframe(m, b, supplement=dict(status='reviewed_none_reported',
        note='Synthetic fixture declares the source scope only.', anchors=[at(b.blocks[0], b.blocks[0].text)]))
    p = packet(prepared, manifest=full, scope_review_complete=True)
    status = projection.paper_status(full, b, [p]); assert not status['paper_ready_for_independent_review']
    assert 'source_reconciliation_missing' in status['holds']
    assert status['reviewed_target_characters'] == len(b.blocks[0].text)
    assert not status['scientific_acceptance'] and not status['ml_training_eligible']
    assert not projection.paper_status(full, b, [])['paper_ready_for_independent_review']


def test_comment_quote_rejected_without_rewriting_original(prepared):
    b, m = prepared[3:]; b = b.model_copy(deep=True); b.documents[0].source_kind = 'original_tex'
    block = b.blocks[0]; block.text = '% ' + block.text; block.sha256 = sha(block.text.encode())
    roles = deepcopy(m['roles']); roles[0]['end_char'] = len(block.text); roles[0]['anchors'] = [at(block, block.text)]
    m = reframe(m, b, roles=roles)
    e = at(block, 'The sample showed a resistive onset at 5 K.')
    assert not coverage.published(e, m, b)
    assert block.text.startswith('% ')


def test_pixel_only_label_stays_unresolved_even_with_caption_evidence(prepared, tmp_path):
    b, m = prepared[3:]; b = b.model_copy(deep=True); b.documents[0].source_kind = 'original_pdf'; b.blocks[0].locator = 'pdf_page:1'
    source = deepcopy(m['source']); structure = json.loads(source['structure_json'])
    structure.update(container='pdf', pages=[dict(page=1)])
    source['structure_json'] = canonical(structure); raw=source['structure_json'].encode()
    source['structure_ref'].update(sha256=sha(raw), bytes=len(raw))
    image = tmp_path/'label.png'; image.write_bytes(b'synthetic-pin-not-an-image')
    a = dict(id='figure-label', kind='figure_label', anchor=at(b.blocks[0], b.blocks[0].text),
        visual=dict(unit_id='page:1', image=reader.reference(image), region=[0.1,0.2,0.4,0.6], label='14.7 K'), note='Synthetic visual obligation.')
    m = reframe(m,b,source=source,visuals=[dict(id='page:1',status='pending',note='Synthetic pending visual.',evidence=[])],assertions=[a])
    status=coverage.progress(m,b,[])
    assert status['unresolved_assertion_ids']==['figure-label']
    assert 'visual_result_evidence_adapter_required' in status['holds']


def test_unfinished_reader_cannot_trigger_provider_via_projection(prepared):
    queue, identifier, _, _, _ = prepared
    with queue.connect() as c: c.execute("UPDATE jobs SET state='queued' WHERE id=?", (identifier,))
    before=queue.summary()
    with pytest.raises(ValueError,match='requires_completed_reading'): packet(prepared)
    assert queue.summary()==before


def test_preparation_namespace_cannot_receive_reviewed_candidates(prepared, tmp_path):
    root = tmp_path/'preparation'; root.mkdir(); (root/'STAGING_PREPARATION.json').write_text('{}')
    with pytest.raises(ValueError, match='staging_preparation_only'):
        projection.ingest_local(packet(prepared), root)
    assert not (root/'proposals.sqlite3').exists()


def test_append_only_amendment_keeps_the_target_gate(prepared):
    from ingestion.materials_ner import review_amendments as amendments
    queue, _, path, b, m = prepared; s=json.loads(path.read_text()); block=b.blocks[0]
    cut=block.text.index('The criterion')
    s['passages']=[dict(block_id=block.id,start_char=0,end_char=cut,role='target'),
                   dict(block_id=block.id,start_char=cut,end_char=len(block.text),role='context')]
    new=path.with_name('narrow.json'); new.write_text(canonical(s))
    identifier=reader.enqueue(queue,new);reader.run(queue,identifier,provider_override=Fake())
    parent=packet((queue,identifier,new,b,m))
    before=parent['receipt']['extraction']['results'][0]['evidence'];after=deepcopy(before)
    context=at(block,'The criterion is onset.')
    next(e for e in after if e['field']=='/quantity').update(context)
    change=dict(path='/results/0/evidence',before=before,after=after,reason='Synthetic context boundary control.',anchors=[context])
    reviews=[dict(result_id='r',fields={f:dict(disposition='not_reviewed',note='Synthetic control.',anchors=[]) for f in amendments.FIELDS},holds=[])]
    amendment=amendments.build(parent,bundle=b.model_dump(),changes=[change],reviews=reviews,author=AUTHOR,created_at=NOW)
    assert 'result_without_target_original_evidence' in {i['code'] for i in amendment['validation']['issues']}
    assert not amendment['scientific_acceptance']; amendments.verify(amendment,parent)


def test_portable_replay_uses_embedded_receipts_without_source_files(prepared, monkeypatch):
    p=packet(prepared)
    def forbidden(*a,**k):raise AssertionError('Portable verification read a local source file')
    monkeypatch.setattr(Path,'read_bytes',forbidden);monkeypatch.setattr(Path,'read_text',forbidden)
    verify_packet(p)


def test_pdf_visual_inventory_includes_text_empty_pages(prepared):
    b=prepared[3]
    structure=dict(source_sha256=b.documents[0].source_sha256,container='pdf',pages=[dict(page=1),dict(page=2)])
    units=coverage.inventory(b,structure)['visual_units']
    assert len(units)==2 and units[1]['id']=='page:2' and units[1]['block_ids']==[]
