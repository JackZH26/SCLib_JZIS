"""Run separately: committed synthetic v2 history lasts until owned DB teardown."""
import pytest

from services import research_publication
from tests.test_research_freeze import db_session as db_session, state as snapshot
from tests.test_research_publication import actors
from tests.test_scientific_review_operators import auth, private
from tests.test_materials_conditions_adoption_v2 import fixture
from tests.test_materials_claim_outcomes import outcome, tc


async def test_v2_http_live_permissions_redaction_and_read_only_state(client,db_session):
    f,x,s,e=await fixture(db_session);c=await outcome(db_session,f,e,tc())
    people=await actors(db_session);await db_session.commit()
    url='/v1/ml/scientific-review/targets/claim/'+str(c['id'])
    before=await snapshot(db_session);await db_session.rollback()
    response=await client.get(url,headers=auth(people['reviewer']));private(response)
    assert response.status_code==200
    body=response.json();item=body['state']['conditions']['items'][0]
    assert body['version']=='materials-result-review-context/1.6.0'
    assert item['field_convention']=='unresolved' and item['normalized_quantity'] is None
    assert '$H$' not in response.text and '\\perp' not in response.text
    assert not any(body['authority'].values()) and not body['review_write_available']
    assert await snapshot(db_session)==before;await db_session.rollback()
    for role in ('member','admin','publisher'):
        denied=await client.get(url,headers=auth(people[role]));private(denied)
        assert denied.status_code==403 and 'subject_id' not in denied.text
    anonymous=await client.get(url);private(anonymous);assert anonymous.status_code==401
    await research_publication.revoke_role(db_session,actor_user_id=people['admin'],grant_id=people['grants']['reviewer'],
        reason_code='synthetic_v2_access_withdrawn',dry_run=False)
    await db_session.commit()
    revoked=await client.get(url,headers=auth(people['reviewer']));private(revoked)
    assert revoked.status_code==403 and 'subject_id' not in revoked.text
