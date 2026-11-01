"""Paper chronology, source quantities and the public NER endpoint, without service reuse."""
from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from services.materials_timeline import display_sample, report_date, valid_quantity


@pytest.mark.parametrize('paper,expected', [
    ('arxiv:1909.10482', '2019-09'), ('arxiv:cond-mat/9501001', '1995-01'),
    ('arxiv:cond-mat/9912493', '1999-12'), ('arxiv:0704.0352', '2007-04'),
])
def test_month_precision_is_explicit_and_does_not_invent_a_measurement_day(paper, expected):
    assert report_date(None, paper) == (expected, 'arxiv_identifier_month', 'month')
    assert report_date(date(2019, 9, 23), paper) == ('2019-09-23', 'paper_submission', 'day')


@pytest.mark.parametrize('paper', ['arxiv:1913.10482', 'arxiv:1900.10482', 'doi:10.1/2019', 'arxiv:9999.test', 'arxiv:8912.12345', 'arxiv:9912.12345v1'])
def test_unusable_identifiers_do_not_turn_into_guessed_dates(paper):
    assert report_date(None, paper) is None


def row(i, family='cuprate', value=None, relation='exact', lower=None, upper=None):
    return dict(id=f'{i:04d}', family=family, date=f'20{10+i%15:02d}-{1+i%12:02d}-15',
                value_kelvin=i if value is None else value, value_relation=relation,
                value_lower_kelvin=lower, value_upper_kelvin=upper)


def test_interval_and_bound_are_not_imputed_to_scalar_values():
    interval=row(1,value=None,relation='interval',lower=6,upper=12)
    assert valid_quantity(interval)
    assert valid_quantity(row(2,relation='lt',upper=1.7))
    assert valid_quantity(row(3,value=0))
    assert not valid_quantity(row(4,relation='interval',lower=12,upper=6))
    assert not valid_quantity(row(5,value=float('nan')))
    assert not valid_quantity(row(6,relation='gt'))


def test_sample_is_bounded_reproducible_and_preserves_rare_families_and_extrema():
    rows=[row(i,value=i%9) for i in range(100)]+[row(200,'hydride',250),row(201,'organic',1.3)]
    sample=display_sample(rows,30)
    assert len(sample)==30
    assert display_sample(list(reversed(rows)),30)==sample
    assert {'0200','0201'} <= {r['id'] for r in sample}
    assert {r['value_kelvin'] for r in sample if r['family']=='cuprate'} >= {0,8}
    assert all(r in rows for r in sample)


@pytest.mark.asyncio
async def test_endpoint_feature_gate_budget_and_no_store(monkeypatch):
    from routers import materials_vnext as router
    from services import materials_timeline as service
    from models import get_db
    app=FastAPI();app.include_router(router.router,prefix='/v1')
    async def db():
        yield object()
    app.dependency_overrides[get_db]=db
    enabled=SimpleNamespace(materials_vnext_enabled=False)
    monkeypatch.setattr(router,'get_settings',lambda:enabled)
    calls=[]
    async def read(db, *, max_points):
        calls.append(int(max_points))
        return dict(points=[],total_results=0,total_materials=0,total_papers=0,plotted_results=0,
            omitted_without_date=0,omitted_invalid_quantity=0,sampled=False,families={},date_min=None,date_max=None)
    monkeypatch.setattr(service,'materials_timeline',read)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/v1/materials/timeline')).status_code==404
        assert not calls
        enabled.materials_vnext_enabled=True
        for budget in (2000,5000,20000):
            response=await client.get('/v1/materials/timeline',params={'max_points':budget})
            assert response.status_code==200
            assert response.headers['cache-control']=='private, no-store'
            assert response.json()['dataset']=='materials-production90/1'
        assert calls==[2000,5000,20000]
        assert (await client.get('/v1/materials/timeline?max_points=9999999')).status_code==422
