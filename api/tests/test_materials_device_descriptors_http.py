"""Separate invocation: committed synthetic data lasts until owned teardown."""
from tests.test_research_freeze import db_session as db_session, state as snapshot
from tests.test_materials_device_descriptors import fixture, displacement
from tests.test_materials_conditions import claim
from tests.test_research_publication import actors
from tests.test_scientific_review_operators import auth, private


async def test_http_descriptor_read_is_authorized_and_does_not_promote(client,db_session):
    f,x,s,e=await fixture(db_session,[displacement()]);c=await claim(db_session,f,e)
    people=await actors(db_session);await db_session.commit()
    before=await snapshot(db_session);await db_session.rollback()
    url='/v1/ml/scientific-review/targets/claim/'+str(c['id'])
    response=await client.get(url,headers=auth(people['reviewer']));private(response)
    assert response.status_code==200
    body=response.json();d=body['state']['conditions']['items'][0]
    assert body['version']=='materials-result-review-context/1.8.0'
    assert d['kind']=='reported_displacement_field' and d['normalized_quantity'] is None
    assert d['quantity']['unit']=='V/nm' and d['quantity']['value']==.61
    assert not any(body['authority'].values()) and not body['review_write_available']
    assert await snapshot(db_session)==before;await db_session.rollback()
    assert (await client.get(url)).status_code==401
    assert (await client.get(url,headers=auth(people['member']))).status_code==403
