"""Private HTTP check in its own disposable database; all rows are authored."""
from tests.test_research_freeze import db_session as db_session, state as snapshot
from tests.test_research_publication import actors
from tests.test_scientific_review_operators import auth, private
from tests.test_materials_conditions import setup
from tests.test_materials_properties_v3 import prop, CASES
from services import research_publication


async def test_new_property_http_preserves_units_redaction_and_live_access(client,db_session):
    f,x,s,e=await setup(db_session);r=await prop(db_session,e,CASES[2]);people=await actors(db_session)
    await db_session.commit();before=await snapshot(db_session);await db_session.rollback()
    url='/v1/ml/scientific-review/targets/property/'+str(r['id'])
    response=await client.get(url,headers=auth(people['reviewer']));private(response)
    assert response.status_code==200,response.text
    body=response.json();q=body['result']
    assert body['version']=='materials-result-review-context/1.7.0'
    assert q['value']==3e-6 and q['unit']=='Ω m'
    assert q['source_quantity']['value']==300 and q['source_quantity']['unit']=='µΩ·cm'
    assert q['normalized_uncertainty']['plus']==3e-7
    assert 'raw' not in q['source_quantity'] and 'raw' not in q['normalized_uncertainty']
    assert not any(body['authority'].values()) and not body['review_write_available']
    assert await snapshot(db_session)==before;await db_session.rollback()
    for role in ('member','admin','publisher'):
        denied=await client.get(url,headers=auth(people[role]));private(denied)
        assert denied.status_code==403 and 'subject_id' not in denied.text
    assert (await client.get(url)).status_code==401
    await research_publication.revoke_role(db_session,actor_user_id=people['admin'],grant_id=people['grants']['reviewer'],
        reason_code='authored_properties_access_withdrawn',dry_run=False)
    await db_session.commit();denied=await client.get(url,headers=auth(people['reviewer']));private(denied)
    assert denied.status_code==403 and 'subject_id' not in denied.text
