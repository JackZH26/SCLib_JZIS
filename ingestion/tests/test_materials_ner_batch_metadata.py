"""Batch metadata preserves identity, version, advisory and byte binding."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from ingestion.materials_ner import reviewed_reader as live_reader
from ingestion.materials_ner.source_metadata import metadata_url, parse_metadata
from materials_ner_tc_sources import OfficialReader
import materials_ner_tc_sources as source_stage
from test_materials_ner_reviewed_reader import scope_fixture


def atom(entries):
    body = ''.join(f'<entry><id>http://arxiv.org/abs/{aid}{version}</id>'
        f'<title>Synthetic test</title><summary>{summary}</summary></entry>'
        for aid, version, summary in entries)
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + body + '</feed>').encode()


def response(ids):
    url = metadata_url(ids)
    return dict(status=200, requested_url=url, final_url=url)


@pytest.fixture
def reader():
    candidate = os.environ.get('MATERIALS_READER_CANDIDATE')
    if not candidate:
        return live_reader
    spec = importlib.util.spec_from_file_location('ingestion.materials_ner.metadata_candidate_reader', candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROTOCOL = live_reader.PROTOCOL
    return module


def batch_preflight(tmp_path, entries=None):
    scope = scope_fixture(tmp_path)
    original = json.loads(scope.read_text())['preflight']
    p = json.loads(Path(original['path']).read_text())
    raw = tmp_path / 'batch.atom'
    raw.write_bytes(atom(entries if entries is not None else [('2401.00001', 'v1', 'Measured Tc.')]))
    receipt = tmp_path / 'batch.receipt.json'
    meta = dict(response(['2401.00001']), artifact=live_reader.reference(raw))
    receipt.write_text(json.dumps(meta))
    p.update(official_metadata_format='arxiv_atom_batch', official_metadata_receipt=live_reader.reference(receipt))
    path = tmp_path / 'batch-preflight.json'
    path.write_text(json.dumps(p))
    return original, live_reader.reference(path), raw


def test_batch_and_legacy_metadata_preserve_the_identical_source(reader, tmp_path):
    old, new, _ = batch_preflight(tmp_path)
    p0, b0, _ = reader.source_input(old)
    p1, b1, pins = reader.source_input(new)
    assert b0.model_dump() == b1.model_dump()
    assert p0['exact_version_binding'] == p1['exact_version_binding']
    assert p1['latest_version_observed'] == 'v1'
    assert any(Path(pin['path']).name == 'batch.atom' for pin in pins)


@pytest.mark.parametrize('entries', [[], [('2401.00001', 'v2', 'Measured Tc.')],
    [('2401.00001', 'v1', 'This paper has been withdrawn by the authors.')]])
def test_missing_different_version_or_withdrawn_source_is_not_accepted(reader, tmp_path, entries):
    _, pin, _ = batch_preflight(tmp_path, entries)
    with pytest.raises(ValueError):
        reader.source_input(pin)


def test_changed_metadata_bytes_fail_hash_verification(reader, tmp_path):
    _, pin, raw = batch_preflight(tmp_path)
    raw.write_bytes(atom([('2401.00001', 'v2', 'Changed')]))
    with pytest.raises(ValueError, match='reader_input_pin_changed'):
        reader.source_input(pin)


def test_mixed_legacy_and_modern_ids_and_per_article_advisory():
    ids = ['cond-mat/9907183', '2401.00001']
    parsed = parse_metadata(response(ids), atom([
        (ids[0], 'v2', 'This paper has been withdrawn by the authors.'),
        (ids[1], 'v1', 'Primary experimental report.')]))
    assert parsed[ids[0]] == dict(version='v2', withdrawn=True)
    assert parsed[ids[1]] == dict(version='v1', withdrawn=False)


@pytest.mark.parametrize('change', ['host', 'redirect', 'status', 'filtered_query', 'duplicate_parameter'])
def test_request_must_be_an_unfiltered_official_id_lookup(change):
    receipt = response(['2401.00001'])
    if change == 'host':
        receipt['requested_url'] = receipt['final_url'] = receipt['requested_url'].replace('export.arxiv.org', 'other.example')
    elif change == 'redirect':
        receipt['final_url'] = 'https://other.example/feed'
    elif change == 'status':
        receipt['status'] = 503
    elif change == 'filtered_query':
        receipt['requested_url'] += '&search_query=all:superconductivity'
        receipt['final_url'] = receipt['requested_url']
    else:
        receipt['requested_url'] += '&id_list=2401.00001'
        receipt['final_url'] = receipt['requested_url']
    with pytest.raises(ValueError):
        parse_metadata(receipt, atom([('2401.00001', 'v1', '')]))


@pytest.mark.parametrize('entries', [
    [('2401.00002', 'v1', '')],
    [('2401.00001', 'v1', ''), ('2401.00001', 'v1', '')],
    [('2401.00001', '', '')],
])
def test_extra_duplicate_or_unversioned_entry_is_rejected(entries):
    with pytest.raises(ValueError):
        parse_metadata(response(['2401.00001']), atom(entries))


@pytest.mark.parametrize('body', [b'not xml', b'<feed/>', b'x' * (4 * 1024**2 + 1)])
def test_malformed_or_excessive_metadata_is_rejected(body):
    with pytest.raises(ValueError):
        parse_metadata(response(['2401.00001']), body)


@pytest.mark.parametrize('ids', [[], ['2401.00001'] * 2, ['2401.00001v1'], ['../private']])
def test_lookup_cannot_change_ids_or_request_a_specific_old_version(ids):
    with pytest.raises(ValueError):
        metadata_url(ids)


@pytest.mark.parametrize('status', [200, 503])
def test_missing_entries_or_http_failure_keep_html_fallback(tmp_path, monkeypatch, status):
    ids = ['2401.00001', '2401.00002']
    raw = tmp_path / 'metadata.atom'
    raw.write_bytes(atom([(ids[0], 'v1', '')]))
    captured = dict(response(ids), status=status, artifact=live_reader.reference(raw))
    receipt = tmp_path / 'metadata.receipt.json'
    receipt.write_text(json.dumps(captured))
    official = OfficialReader()
    monkeypatch.setattr(official, 'fetch', lambda *_: (captured, live_reader.reference(receipt)))
    try:
        official.prepare_metadata([dict(id='arxiv:' + aid) for aid in ids], tmp_path)
    finally:
        official.client.close()
    report = json.loads((tmp_path / 'BATCH_METADATA.json').read_text())
    assert report['fallback_ids'] == ([ids[1]] if status == 200 else ids)
    assert set(official.batch_metadata) == ({ids[0]} if status == 200 else set())


def test_completed_preflight_resumes_without_refetch_or_new_metadata(reader, tmp_path, monkeypatch):
    old, _, _ = batch_preflight(tmp_path)
    captured = json.loads(Path(old['path']).read_text())
    captured['route'] = 'official_arxiv_version'
    path = tmp_path / 'PREFLIGHT.json'
    path.write_text(json.dumps(captured))
    original_bytes = path.read_bytes()
    monkeypatch.setattr(source_stage, 'rr', reader)
    class NoNetwork:
        def fetch(self, *_):
            raise AssertionError('Already-bound original must not be fetched again')
    result = source_stage.preflight(dict(id='arxiv:2401.00001'), tmp_path,
        tmp_path / 'cache', 'unused-plan-hash', NoNetwork())
    assert result['state'] == 'source_ready' and result['version'] == 'v1'
    assert path.read_bytes() == original_bytes
