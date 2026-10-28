"""Portable provenance and read-only export command checks."""
import hashlib
import json

import pytest

import materials_ner_tc_export as exporter


def captured_source(tmp_path):
    source=tmp_path/'original.json'
    raw=b'{"blocks": [{"id": "source:1", "text": "Tc = 4 K"}]}'
    source.write_bytes(raw)
    pin=dict(path=str(source),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    bundle=tmp_path/'evidence';bundle.mkdir()
    return source,pin,bundle,raw


def test_portable_source_survives_removal_of_original_capture(tmp_path):
    source,pin,bundle,raw=captured_source(tmp_path)
    expected=exporter.read_source_representation(pin)
    (bundle/(pin['sha256']+'.json')).write_bytes(raw)
    source.unlink()
    assert exporter.read_source_representation(pin,bundle)==expected


def test_missing_copy_does_not_fall_back_to_readable_original(tmp_path):
    source,pin,bundle,_=captured_source(tmp_path)
    assert source.exists()
    with pytest.raises(FileNotFoundError):exporter.read_source_representation(pin,bundle)


def test_modified_copy_fails_even_when_original_is_valid(tmp_path):
    _,pin,bundle,raw=captured_source(tmp_path)
    (bundle/(pin['sha256']+'.json')).write_bytes(raw.replace(b'4 K',b'9 K'))
    with pytest.raises(ValueError,match='production90_input_changed'):
        exporter.read_source_representation(pin,bundle)


def test_bundle_cannot_link_back_to_the_original_host_path(tmp_path):
    source,pin,bundle,_=captured_source(tmp_path)
    (bundle/(pin['sha256']+'.json')).symlink_to(source)
    with pytest.raises(ValueError,match='export_evidence_path_outside_bundle'):
        exporter.read_source_representation(pin,bundle)


def test_export_only_command_does_not_reconcile_ledger(monkeypatch,tmp_path,capsys):
    calls=[]
    async def exported(url,output,*,evidence_root=None):
        calls.append((url,output,evidence_root))
        return {'rows':1,'evidence_read_mode':'portable_hash_bundle'},[{'id':'row'}]
    def forbidden(*args):raise AssertionError('Read-only export touched the corpus ledger')
    monkeypatch.setattr(exporter,'export',exported)
    monkeypatch.setattr(exporter,'inventory',forbidden)
    exporter.main(['--database-url','test-database','--output',str(tmp_path/'out'),
                   '--evidence-root',str(tmp_path/'evidence'),'--export-only'])
    assert calls==[('test-database',str(tmp_path/'out'),tmp_path/'evidence')]
    assert json.loads(capsys.readouterr().out)['rows']==1


def test_reconciliation_command_requires_ledger_paths_before_database_access(monkeypatch,tmp_path):
    async def forbidden(*args,**kwargs):raise AssertionError('Invalid CLI reached the database')
    monkeypatch.setattr(exporter,'export',forbidden)
    with pytest.raises(SystemExit) as exc:
        exporter.main(['--database-url','test-database','--output',str(tmp_path/'out')])
    assert exc.value.code==2


def test_existing_command_still_reconciles_when_explicitly_given_ledger_paths(monkeypatch,tmp_path,capsys):
    calls=[]
    async def exported(*args,**kwargs):return {'rows':1},[{'id':'row'}]
    def reconciled(campaign,root,rows,report):
        calls.append((campaign,root,rows,report))
        return {'canonical_records':1}
    monkeypatch.setattr(exporter,'export',exported)
    monkeypatch.setattr(exporter,'inventory',reconciled)
    exporter.main(['--database-url','test-database','--output',str(tmp_path/'out'),
                   '--campaign','campaign','--queue-root','queue'])
    assert calls==[('campaign','queue',[{'id':'row'}],{'rows':1})]
    assert json.loads(capsys.readouterr().out)['canonical_records']==1
