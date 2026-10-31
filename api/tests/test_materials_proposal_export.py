"""Complete review exports retain scientific shape, evidence and authority."""
from copy import deepcopy
import csv
import hashlib
import io
import json
from zipfile import ZipFile

import pytest

from services import materials_proposal_export as export
from services import materials_proposal_review as review
from tests.test_materials_proposal_review import proposals, retained, PREFIX
from tests.research_access_helpers import research_operator, revoke_research_grant


def unpack(raw):
    with ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist())=={'manifest.json','graph.json','results.csv','README.txt'}
        files={name:z.read(name) for name in z.namelist()}
    manifest=json.loads(files['manifest.json']);graph=json.loads(files['graph.json'])
    for entry in manifest['files']:
        assert len(files[entry['name']])==entry['bytes']
        assert hashlib.sha256(files[entry['name']]).hexdigest()==entry['sha256']
    return files,manifest,graph


@pytest.mark.asyncio
async def test_whole_run_http_export_is_lossless_deterministic_and_source_owned(client,proposals):
    actor=await research_operator(role='reviewer');url=f"{PREFIX}/runs/{proposals['run_id']}/export"
    descriptor=await client.get(url,headers=actor['headers']);assert descriptor.status_code==200,descriptor.text
    d=descriptor.json();assert not any(d['authority'].values())
    response=await client.get(url+'/package',params={'expected_sha256':d['sha256']},headers=actor['headers'])
    assert response.status_code==200 and response.headers['content-type']=='application/zip'
    assert response.headers['cache-control']=='private, no-store'
    assert len(response.content)==d['bytes'] and hashlib.sha256(response.content).hexdigest()==d['sha256']
    files,manifest,graph=unpack(response.content)
    for group,rows in proposals['rows'].items():
        expected=[dict(deepcopy(row),source_path=f'/{group}/{i}') for i,row in enumerate(rows)]
        assert graph['entities'][group]==expected
    assert len(graph['evidence'])==len(proposals['evidence'])
    for original,item in zip(proposals['evidence'],graph['evidence']):
        assert all(item[k]==v for k,v in original.items())
        block=next(b for b in proposals['bundle']['blocks'] if b['id']==item['block_id'])
        assert item['quote']==block['text'][item['start_char']:item['end_char']]
    parsed=list(csv.DictReader(io.StringIO(files['results.csv'].decode(),newline='')))
    assert len(parsed)==len(proposals['rows']['results'])==manifest['counts']['results']
    assert all(r['formula_as_written']=='' and r['formula_status']=='ambiguous' for r in parsed)
    assert all('ambient' not in r['measurement_conditions_json'] for r in parsed)
    assert (await client.get(url,headers=actor['headers'])).json()==d
    bad=await client.get(url+'/package',params={'expected_sha256':'0'*64},headers=actor['headers'])
    assert bad.status_code==409 and proposals['bundle']['title'] not in bad.text


@pytest.mark.parametrize('suffix',['','/package?expected_sha256='+'0'*64])
@pytest.mark.asyncio
async def test_export_requires_current_read_role(client,proposals,suffix):
    url=f"{PREFIX}/runs/{proposals['run_id']}/export"+suffix
    assert (await client.get(url)).status_code==401
    actor=await research_operator(role='publisher')
    assert (await client.get(url,headers=actor['headers'])).status_code==403


@pytest.mark.asyncio
async def test_export_revocation_after_packaging_prevents_any_download(client,proposals,monkeypatch):
    actor=await research_operator();original=export.run_export
    async def revoke(*args,**kwargs):
        value=await original(*args,**kwargs)
        await revoke_research_grant(grant_id=actor['grant_id'],revoked_by=actor['grantor_id'])
        return value
    monkeypatch.setattr(export,'run_export',revoke)
    r=await client.get(f"{PREFIX}/runs/{proposals['run_id']}/export",headers=actor['headers'])
    assert r.status_code==403 and r.headers['content-type']=='application/json'


@pytest.mark.parametrize('text_value',["=1+1", " +SUM(A1:A2)", "-20 K", "@source", "'literal", '\tvalue', 'comma, "quote"\nμ₀H 🚀'])
def test_csv_keeps_source_text_reversible_and_negative_numbers_numeric(text_value):
    record={c:None for c in export.COLUMNS};record.update(result_id='R1',source_value=text_value,value=-1.25,lower=0,approximate=False)
    raw,contract=export.csv_files([record]);rows=list(csv.DictReader(io.StringIO(raw.decode(),newline='')))
    for cell in contract['escaped_cells']:
        assert cell['row']==2;rows[0][cell['column']]=rows[0][cell['column']][1:]
    assert rows[0]['source_value']==text_value and rows[0]['value']=='-1.25' and rows[0]['lower']=='0'
    assert rows[0]['upper']=='' and rows[0]['approximate']=='false'
    assert not any(c['column']=='value' for c in contract['escaped_cells'])


def test_bounds_uncertainty_and_non_detection_payload_survive_projection(retained):
    from datetime import datetime, timezone
    source=deepcopy(retained);r=source['rows']['results'][0]['payload']
    r['quantity'].update(relation='interval',value=None,lower=1.1,upper=2.2,approximate=True,
        raw='1.1–2.2 K',uncertainty={'kind':'reported_unspecified','minus':0.1,'plus':0.2,'level':None,'raw':'-0.1/+0.2 K'})
    r['qualifiers']=[{'non_detection_target':'synthetic_target','window_status':'unresolved'}]
    original=deepcopy(source)
    _,raw=export.package(source,datetime(2026,1,1,tzinfo=timezone.utc));files,_,graph=unpack(raw)
    assert source==original and graph['entities']['results'][0]['payload']==r
    row=next(x for x in csv.DictReader(io.StringIO(files['results.csv'].decode(),newline='')) if x['result_id']==r['id'])
    assert row['value']=='' and row['lower']=='1.1' and row['upper']=='2.2' and row['approximate']=='true'
    assert json.loads(row['uncertainty_json'])==r['quantity']['uncertainty']


def test_device_export_preserves_geometry_and_criterion_without_measurement_relabel(retained):
    from datetime import datetime, timezone
    from tests.test_materials_device_descriptors import angle, displacement, definition
    source=deepcopy(retained)
    # An explicitly synthetic projection control, never a portable provider receipt.
    source['receipt']['extraction']['schema_version']='materials-ner/15'
    source['run_id']=review.digest(source['receipt'])
    for state in source['rows']['states']:
        state['payload']['conditions']=[angle(),displacement()]
        state['payload']['pressure']=dict(availability='not_reported',regime='unknown',condition_id=None,basis_raw=None)
    for row in source['rows']['results']:row['payload']['definition']=definition()['definition']
    _,raw=export.package(source,datetime(2026,1,1,tzinfo=timezone.utc))
    files,manifest,graph=unpack(raw)
    assert manifest['version']==export.DEVICE_VERSION and not any(manifest['authority'].values())
    rows=list(csv.DictReader(io.StringIO(files['results.csv'].decode(),newline='')))
    for row in rows:
        assert json.loads(row['state_conditions_json'])==[angle(),displacement()]
        assert json.loads(row['measurement_conditions_json'])==[displacement()]
        assert row['criterion']=='linear_fit_intersection'
        assert row['criterion_as_written']==definition()['definition']['criterion_raw']
        assert json.loads(row['pressure_declaration_json'])['availability']=='not_reported'


@pytest.mark.asyncio
async def test_export_size_cap_refuses_whole_response_instead_of_truncating(client,proposals,monkeypatch):
    actor=await research_operator();monkeypatch.setattr(export,'MAX_UNCOMPRESSED_BYTES',100)
    r=await client.get(f"{PREFIX}/runs/{proposals['run_id']}/export",headers=actor['headers'])
    assert r.status_code==404 and 'source' not in r.text.lower()


@pytest.mark.parametrize('kind,value,unit,error',[
    ('tc_pressure_slope',-1.1,'K GPa−1',.1),('electrical_resistivity',300,'µΩ·cm',30)])
def test_adopted_properties_keep_source_scale_in_csv_and_normalization_in_graph(retained,kind,value,unit,error):
    from datetime import datetime,timezone
    source=deepcopy(retained);source['receipt']['extraction']['schema_version']='materials-ner/12'
    row=source['rows']['results'][0];r=row['payload']
    r.update(quantity_kind=kind,quantity_name_raw='dTc /dp' if kind=='tc_pressure_slope' else 'absolute resistivity')
    r['quantity'].update(value=value,unit=unit,raw=f'{value} ± {error} {unit}',approximate=True,
        uncertainty=dict(kind='reported_unspecified',minus=error,plus=error,level=None,raw=f'± {error}'))
    row['normalized']={'/results/0/quantity':dict(status='reported',normalized=dict(
        value=-1.1 if kind=='tc_pressure_slope' else 3e-6,unit='K/GPa' if kind=='tc_pressure_slope' else 'Ω m'))}
    # This is a newly authored projection fixture, never a modification of a
    # provider artifact. Its changed receipt must have its own identity.
    source['receipt']['extraction']['results'][0]=deepcopy(r)
    source['run_id']=review.digest(source['receipt'])
    _,raw=export.package(source,datetime(2026,1,1,tzinfo=timezone.utc));files,manifest,graph=unpack(raw)
    parsed=next(x for x in csv.DictReader(io.StringIO(files['results.csv'].decode(),newline='')) if x['result_id']==r['id'])
    assert parsed['quantity_kind']==kind and float(parsed['value'])==value and parsed['unit']==unit
    assert json.loads(parsed['uncertainty_json'])==r['quantity']['uncertainty']
    assert graph['entities']['results'][0]['payload']==r and graph['entities']['results'][0]['normalized']==row['normalized']
    assert graph['run']['extraction_version']=='materials-ner/12'
    assert not any(graph['authority'].values()) and manifest['counts']['results']==len(source['rows']['results'])


@pytest.mark.parametrize('schema_version', ['materials-ner/13', 'materials-ner/14'])
def test_native_pressure_declaration_survives_csv_without_numeric_imputation(retained, schema_version):
    from datetime import datetime, timezone
    source = deepcopy(retained)
    source['receipt']['extraction']['schema_version'] = schema_version
    declaration = dict(availability='reported', regime='explicit_ambient', condition_id=None, basis_raw='ambient pressure')
    for row in source['rows']['states']:
        row['payload']['pressure'] = deepcopy(declaration)
    for state in source['receipt']['extraction']['states']:
        state['pressure'] = deepcopy(declaration)
    source['run_id'] = review.digest(source['receipt'])
    descriptor, raw = export.package(source, datetime(2026, 1, 1, tzinfo=timezone.utc))
    files, manifest, graph = unpack(raw)
    rows = list(csv.DictReader(io.StringIO(files['results.csv'].decode(), newline='')))
    assert descriptor['version'] == manifest['version'] == 'materials-proposal-export/2'
    assert all(json.loads(r['pressure_declaration_json']) == declaration for r in rows)
    assert graph['entities']['states'][0]['payload']['pressure'] == declaration
    assert all('0 GPa' not in r['pressure_declaration_json'] for r in rows)
    assert not any(graph['authority'].values())


@pytest.mark.parametrize('schema_version,version,columns', [
    ('materials-ner/12', export.VERSION, export.COLUMNS),
    ('materials-ner/13', export.PRESSURE_VERSION, export.PRESSURE_COLUMNS),
    ('materials-ner/14', export.PRESSURE_VERSION, export.PRESSURE_COLUMNS),
])
def test_empty_run_csv_retains_its_versioned_columns(retained, schema_version, version, columns):
    from datetime import datetime, timezone
    source = deepcopy(retained)
    source['receipt']['extraction']['schema_version'] = schema_version
    source['rows']['results'] = []
    source['receipt']['extraction']['results'] = []
    source['run_id'] = review.digest(source['receipt'])
    descriptor, raw = export.package(source, datetime(2026, 1, 1, tzinfo=timezone.utc))
    files, manifest, _ = unpack(raw)
    assert descriptor['version'] == manifest['version'] == version
    assert list(csv.reader(io.StringIO(files['results.csv'].decode(), newline=''))) == [list(columns)]
    assert [column['name'] for column in manifest['csv']['columns']] == list(columns)


def test_native14_extrapolation_target_is_preserved_without_becoming_measurement(retained):
    from datetime import datetime, timezone
    source = deepcopy(retained)
    source['receipt']['extraction']['schema_version'] = 'materials-ner/14'
    pressure = dict(availability='not_reported', regime='unknown', condition_id=None, basis_raw=None)
    target = dict(id='evaluation-temperature', kind='temperature', role='extrapolation_target',
        basis_raw='extrapolating to T=0', quantity=dict(status='reported', value=0, unit='K', raw='T=0'))
    # A projection fixture tests transport, not scientific admission or extraction.
    for group in [source['rows']['states'], source['receipt']['extraction']['states']]:
        for row in group:
            state = row.get('payload', row)
            state['pressure'] = deepcopy(pressure)
            state.setdefault('conditions', []).append(deepcopy(target))
    source['run_id'] = review.digest(source['receipt'])
    _, raw = export.package(source, datetime(2026, 1, 1, tzinfo=timezone.utc))
    files, _, graph = unpack(raw)
    for row in csv.DictReader(io.StringIO(files['results.csv'].decode(), newline='')):
        assert json.loads(row['pressure_declaration_json']) == pressure
        assert all(c['role'] == 'measurement' for c in json.loads(row['measurement_conditions_json']))
        state_index = int(row['state_pointer'].split('/')[-1])
        assert target in graph['entities']['states'][state_index]['payload']['conditions']
    assert not any(graph['authority'].values())
