"""Run only via the owned disposable test runner."""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from services.materials_context_sql import COMPOSITION_IDS, PROTOCOL_ID
from models.db import Base
from services.materials_family import FAMILY_SQL
from tests.test_research_freeze import db_session as db_session


@pytest.mark.asyncio
async def test_uuid_lookups_preserve_canonical_text_membership(db_session):
    canonical='aaaaaaaa-1111-4222-8333-000000000000'
    for value in [canonical,canonical.upper(),'not-a-uuid',None,canonical.replace('-','')]:
        context=json.dumps(dict(materials_context=dict(protocol_id=value,composition_ids=[value])))
        row=(await db_session.execute(text(f"""WITH ev AS (SELECT CAST(:context AS jsonb) AS context),
            rp AS (SELECT CAST(:id AS uuid) AS id)
            SELECT rp.id::text=ev.context->'materials_context'->>'protocol_id' AS old_protocol,
                rp.id=({PROTOCOL_ID}) AS new_protocol,
                rp.id::text=ANY(ARRAY(SELECT jsonb_array_elements_text(ev.context->'materials_context'->'composition_ids'))) AS old_composition,
                rp.id=ANY({COMPOSITION_IDS}) AS new_composition FROM ev,rp"""),
            dict(context=context,id=canonical))).mappings().one()
        assert bool(row['old_protocol'])==bool(row['new_protocol'])
        assert bool(row['old_composition'])==bool(row['new_composition'])


@pytest.mark.asyncio
async def test_family_backfill_preserves_sources_and_roundtrips(db_session,monkeypatch):
    path=Path(__file__).parents[1]/'alembic/versions/0105_materials_family.py'
    spec=importlib.util.spec_from_file_location('family_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    for id,formula in [('source:family-test','FeSe'),('mat:family-test','CeRu2')]:
        await db_session.execute(Base.metadata.tables['materials'].insert().values(id=id,formula=formula,formula_normalized=formula,family=None,material_semantics={'preserve':True}))
    connection=await db_session.connection()
    def upgrade(sync):
        with Operations.context(MigrationContext.configure(sync)):migration.upgrade()
    await connection.run_sync(upgrade)
    rows=(await db_session.execute(text(f"SELECT m.id,m.formula,m.material_semantics,({FAMILY_SQL}) AS family FROM materials m WHERE id IN ('source:family-test','mat:family-test') ORDER BY id"))).mappings().all()
    assert rows[0]['family']=='unclassified'
    assert rows[1]['family']=='iron_based'
    assert rows[1]['formula']=='FeSe'
    assert rows[1]['material_semantics']['preserve'] is True
    await db_session.execute(text("UPDATE materials SET formula='NbN' WHERE id='source:family-test'"))
    assert (await db_session.execute(text(f"SELECT ({FAMILY_SQL}) FROM materials m WHERE id='source:family-test'"))).scalar_one()=='unclassified'
    def downgrade(sync):
        with Operations.context(MigrationContext.configure(sync)):migration.downgrade()
    await connection.run_sync(downgrade)
    row=(await db_session.execute(text("SELECT family,material_semantics FROM materials WHERE id='source:family-test'"))).one()
    assert row.family is None and row.material_semantics=={'preserve':True}
    await db_session.rollback()
