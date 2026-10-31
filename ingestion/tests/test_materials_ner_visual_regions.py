"""Synthetic integrity controls; optical confidence is never scientific acceptance."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import page_images, paper_coverage as coverage, reviewed_proposals as projection, visual_regions as visual
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.proposals import ProposalDatabase, review_rows, verify_packet
from ingestion.materials_ner.sources import sha
from test_materials_ner_page_images import png
from test_materials_ner_reviewed_proposals import prepared, graph, reframe, at, packet, AUTHOR, NOW


@pytest.fixture
def region_case(prepared, tmp_path):
    original = packet(prepared); b = prepared[3].model_copy(deep=True)
    b.documents[0].source_kind = 'original_pdf'; b.blocks[0].locator = 'pdf_page:1'
    m = deepcopy(prepared[4]); source = m['source']; structure = json.loads(source['structure_json'])
    structure.update(container='pdf', pages=[dict(page=1)])
    source['structure_json'] = canonical(structure); source['structure_ref'].update(
        bytes=len(source['structure_json'].encode()), sha256=sha(source['structure_json'].encode()))
    image_file = tmp_path / 'synthetic.png'; image_file.write_bytes(png())
    from ingestion.materials_ner.reviewed_reader import reference
    tool = tmp_path / 'synthetic-tool'; tool.write_text('Synthetic tool pin. Never executed.')
    tool_pin = reference(tool)
    c = page_images.freeze(b, [dict(pdf_sha256=source['original']['sha256'], pdf_page=1,
        rendering=dict(tool='pdftoppm', executable=tool_pin, source=source['original'], page=1, dpi=200), raw=png())])
    observed = dict(schema='materials-vision-text/1', recognizer='Apple Vision VNRecognizeTextRequest', revision=3,
        recognition_level='accurate', language_correction=False, recognition_languages=['en-US'],
        coordinate_system='normalized_top_left_xyxy', coordinate_precision='approximate_word_boxes',
        scientific_acceptance=False, image_sha256=sha(png()), image_bytes=len(png()), width=2, height=2,
        observations=[dict(id='line:0', text='Tc = 5 K', confidence=1, box=[.1,.1,.8,.3], words=[
            dict(text='Tc', start_char=0, end_char=2, box=[.1,.1,.2,.3]),
            dict(text='=', start_char=3, end_char=4, box=[.3,.1,.4,.3]),
            dict(text='5', start_char=5, end_char=6, box=[.5,.1,.6,.3]),
            dict(text='K', start_char=7, end_char=8, box=[.7,.1,.8,.3])])])
    body = dict(schema=visual.ASSET_VERSION, capture=c, ocr_json=canonical(observed),
        ocr_sha256=sha(canonical(observed).encode()), ocr_executable=tool_pin, ocr_source=tool_pin)
    asset = dict(body, asset_id=digest(body))
    assertion = dict(id='figure-label', kind='figure_label', anchor=at(b.blocks[0], b.blocks[0].text),
        visual=dict(unit_id='page:1', image=reference(image_file), region=[.1,.05,.85,.35], label='Tc = 5 K'),
        note='Synthetic printed-label obligation.')
    m = reframe(m, b, source=source, assertions=[assertion],
        visuals=[dict(id='page:1',status='pending',note='Remaining page content unreviewed.',evidence=[])])
    g = graph(b); g['results'][0]['evidence'] = [e for e in g['results'][0]['evidence'] if e['field'] != '/quantity']
    scope = json.loads(prepared[2].read_text())
    binding = dict(result_id='r', field='/quantity', asset_id=asset['asset_id'], assertion_id='figure-label',
        selector=dict(line_id='line:0',start_char=5,end_char=8), transcription='5 K', interpretation_note='Synthetic explicit binding.')
    return dict(bundle=b, manifest=m, scope=scope, extraction=parse_extraction(g), assets=[asset],
        bindings=[binding], author=AUTHOR, created_at=NOW), original


def make_packet(case, original, *, version=visual.VERSION):
    """Fully authored test provenance, never a claim of a real provider run."""
    support = visual.build(**case, version=version); b = case['bundle']; provenance = deepcopy(original['receipt']['reader_provenance'])
    provenance['config']['input_pins'].append(dict(path='/synthetic/bundle.json', bytes=len(canonical(b.model_dump()).encode()),
        sha256=digest(b.model_dump())))
    config_hash = digest(provenance['config']); provenance['attempt']['config_sha256'] = config_hash
    returned = json.loads(provenance['provider_return_json']); returned['config_sha256'] = config_hash
    provenance['provider_return_json'] = canonical(returned)
    provenance['attempt']['provider_return'].update(sha256=sha(canonical(returned).encode()), bytes=len(canonical(returned).encode()))
    provenance['attempt_pin'].update(sha256=digest(provenance['attempt']), bytes=len(canonical(provenance['attempt']).encode()))
    receipt = projection.make_receipt(bundle=b, graph=case['extraction'].model_dump(), manifest=case['manifest'],
        provenance=provenance, raw_output=original['raw_output'], author=AUTHOR, created_at=NOW,
        scope_review_complete=False, note='Synthetic visual projection.', visual_support=support)
    p = dict(schema='materials-ner-proposals/2', run_id=digest(receipt), job_id=receipt['job_id'], work_id=b.work_id,
        bundle_hash=digest(b.model_dump()), bundle=b.model_dump(), receipt=receipt, raw_output=original['raw_output'],
        rows=review_rows(case['extraction'],receipt['validation']), evidence=receipt['validation']['resolved_evidence'],
        scientific_acceptance=False, ml_training_eligible=False)
    p['packet_hash'] = digest(p); verify_packet(p)
    return p


def test_visual_numeric_binding_is_not_a_fabricated_original_text_span(region_case):
    case, original = region_case; before = deepcopy(case['bundle'].model_dump()); p = make_packet(case, original)
    assert p['receipt']['validation']['valid'], p['receipt']['validation']['issues']
    v = [e for e in p['evidence'] if e.get('kind') == 'visual_region']; assert len(v) == 1
    assert v[0]['transcription'] == '5 K' and v[0]['caption']['quote']
    assert not {'start_char','end_char','quote','quote_sha256'} & set(v[0])
    assert case['bundle'].model_dump() == before
    assert p['receipt']['schema'] == projection.VISUAL_FORMAT and p['receipt']['extraction']['schema_version'] == 'materials-ner/13'
    assert not p['scientific_acceptance'] and not p['receipt']['structured_graph_authored_by_reader']


def test_caption_alone_cannot_supply_a_visual_quantity(region_case):
    case, _ = region_case
    _, v = projection.validate_graph(case['extraction'].model_dump(),case['bundle'],case['scope'],case['manifest'])
    assert not v['valid'] and {'field_evidence_missing','quantity_raw_not_in_field_evidence',
        'result_without_target_original_evidence'} <= {x['code'] for x in v['issues']}


@pytest.mark.parametrize('change', ['wrong_transcription','substring_digit','wrong_line','wrong_image','wrong_region',
    'context_page','partial_target','bibliography','wrong_caption','duplicate_binding','duplicate_assertion',
    'unknown_result','wrong_field','text_quantity_also_present','self_approval','wrong_publication'])
def test_region_binding_rejects_scope_source_and_identity_changes(region_case, change):
    case, _ = region_case; binding = case['bindings'][0]; m=case['manifest']; b=case['bundle']
    if change == 'wrong_transcription': binding['transcription']='7 K'
    elif change == 'substring_digit': binding['selector']['start_char']=6; binding['transcription']=' K'
    elif change == 'wrong_line': binding['selector']['line_id']='line:missing'
    elif change == 'wrong_image': m['assertions'][0]['visual']['image']['sha256']='0'*64
    elif change == 'wrong_region': m['assertions'][0]['visual']['region']=[.01,.01,.1,.1]
    elif change == 'context_page': case['scope']['passages'][0]['role']='context'
    elif change == 'partial_target': case['scope']['passages'][0]['start_char']=1
    elif change == 'bibliography': m['roles'][0]['role']='bibliography'
    elif change == 'wrong_caption': m['assertions'][0]['anchor']['quote']='Invented caption'
    elif change == 'duplicate_binding': case['bindings'].append(deepcopy(binding))
    elif change == 'duplicate_assertion':
        r=case['extraction'].results[0].model_copy(deep=True);r.id='r2';case['extraction'].results.append(r)
        other=deepcopy(binding);other['result_id']='r2';case['bindings'].append(other)
    elif change == 'unknown_result': binding['result_id']='missing'
    elif change == 'wrong_field': binding['field']='/definition/criterion'
    elif change == 'text_quantity_also_present': case['extraction']=parse_extraction(graph(b))
    elif change == 'self_approval': case['author']=dict(AUTHOR,kind='human')
    elif change == 'wrong_publication': m['source']['original']['sha256']='0'*64
    with pytest.raises(ValueError):
        case['manifest']=reframe(m,b)
        visual.build(**case)


@pytest.mark.parametrize('change',['pixels','ocr_image','ocr_word_offset','ocr_language_correction','ocr_selector_position','ocr_hash','image_page'])
def test_asset_checks_reject_optical_capture_mismatch(region_case,change):
    case,_=region_case; asset=case['assets'][0];o=json.loads(asset['ocr_json'])
    if change=='pixels': asset['capture']['pages'][0]['png_base64']='AA=='
    elif change=='ocr_image':o['image_sha256']='0'*64
    elif change=='ocr_word_offset':o['observations'][0]['words'][2]['start_char']=4
    elif change=='ocr_language_correction':o['language_correction']=True
    elif change=='ocr_selector_position':o['observations'][0]['words'][2]['box']=[.8,.8,.9,.9]
    elif change=='image_page':asset['capture']['pages'][0]['pdf_page']=2
    asset['ocr_json']=canonical(o);asset['ocr_sha256']=sha(asset['ocr_json'].encode())
    if change=='ocr_hash':asset['ocr_sha256']='0'*64
    asset['asset_id']=digest({k:v for k,v in asset.items() if k!='asset_id'})
    case['bindings'][0]['asset_id']=asset['asset_id']
    with pytest.raises(ValueError):visual.build(**case)


def test_scalar_mismatch_still_reaches_existing_quantity_validator(region_case):
    case,_=region_case;case['extraction'].results[0].quantity.value=7.0
    support=visual.build(**case)
    _,v=projection.validate_graph(case['extraction'].model_dump(),case['bundle'],case['scope'],case['manifest'],support)
    assert not v['valid'] and any(i['path']=='/results/0/quantity' for i in v['issues'])


def test_visual_storage_and_portable_replay_require_no_source_files(region_case,tmp_path,monkeypatch):
    case,original=region_case;p=make_packet(case,original);db=ProposalDatabase(tmp_path/'proposal')
    assert db.ingest(p)['inserted'] and not db.ingest(p)['inserted']
    with db.connect() as c:restored=json.loads(c.execute('SELECT payload FROM runs').fetchone()[0])
    assert restored==p
    def forbidden(*args,**kw):raise AssertionError('portable replay read a source path')
    monkeypatch.setattr(Path,'read_bytes',forbidden);monkeypatch.setattr(Path,'read_text',forbidden)
    verify_packet(restored)
    status=projection.paper_status(case['manifest'],case['bundle'],[restored])
    assert status['unresolved_assertion_ids']==[] and 'visual_units_unreviewed' in status['holds']
    assert not status['paper_ready_for_independent_review']


def test_local_ingestion_rerenders_original_instead_of_trusting_declared_hash(region_case,monkeypatch):
    case,_=region_case;support=visual.build(**case)
    monkeypatch.setattr(visual,'configured_renderer',lambda:case['assets'][0]['ocr_executable']['path'])
    monkeypatch.setattr(visual,'render_pdf',lambda *args:png(pixel=1))
    with pytest.raises(ValueError,match='local_render_mismatch'):visual.verify_local_assets(support,case['bundle'])


def test_received_asset_cannot_select_an_executable(region_case,monkeypatch,tmp_path):
    case,_=region_case;support=visual.build(**case);configured=tmp_path/'configured-renderer';configured.write_text('Different trusted renderer.')
    monkeypatch.setattr(visual,'configured_renderer',lambda:configured)
    def forbidden(*args):raise AssertionError('An unconfigured executable reached rendering')
    monkeypatch.setattr(visual,'render_pdf',forbidden)
    with pytest.raises(ValueError,match='renderer_not_configured'):visual.verify_local_assets(support,case['bundle'])


def test_two_assertion_ids_cannot_count_one_printed_label_twice(region_case):
    case,_=region_case;m=case['manifest'];a=deepcopy(m['assertions'][0]);a['id']='second-label';m['assertions'].append(a)
    case['manifest']=reframe(m,case['bundle'])
    r=case['extraction'].results[0].model_copy(deep=True);r.id='second-result';case['extraction'].results.append(r)
    other=deepcopy(case['bindings'][0]);other.update(result_id=r.id,assertion_id=a['id']);case['bindings'].append(other)
    with pytest.raises(ValueError,match='printed_label_reused'):visual.build(**case)


def test_rehashed_packet_cannot_change_visual_scalar_or_reader_source(region_case):
    case,original=region_case;p=make_packet(case,original)
    p['receipt']['extraction']['results'][0]['quantity']['value']=7
    p['run_id']=digest(p['receipt']);p['packet_hash']=digest({k:v for k,v in p.items() if k!='packet_hash'})
    with pytest.raises(ValueError):verify_packet(p)


def test_append_only_amendment_cannot_silently_drop_visual_numeric_checks(region_case):
    from ingestion.materials_ner import review_amendments as amendments
    case,original=region_case;p=make_packet(case,original)
    change=dict(path='/results/0/quantity/value',before=5.0,after=7.0,reason='Synthetic wrong scalar control.',
        anchors=[at(case['bundle'].blocks[0],case['bundle'].blocks[0].text)])
    reviews=[dict(result_id='r',fields={f:dict(disposition='not_reviewed',note='Synthetic control.',anchors=[])
        for f in amendments.FIELDS},holds=[])]
    a=amendments.build(p,bundle=case['bundle'].model_dump(),changes=[change],reviews=reviews,author=AUTHOR,created_at=NOW)
    assert not a['validation']['valid'];amendments.verify(a,p)
