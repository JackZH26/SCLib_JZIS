"""Source-bound migration regression, only on owned disposable PostgreSQL."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from services.materials_family import FAMILY_SQL
from services.materials_source_notation import sha256
from tests.test_research_freeze import db_session as db_session, seed, add


@pytest.mark.asyncio
async def test_source_display_migration_guards_pins_preserves_assertions_and_roundtrips(db_session,monkeypatch):
    path=Path(__file__).parents[1]/'alembic/versions/0106_materials_source_notation.py'
    spec=importlib.util.spec_from_file_location('display_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    f=await seed(db_session,with_children=False)
    raw=r'\pccox{1.85}{0.15}\xspace'
    await db_session.execute(text("UPDATE materials SET formula=:raw,material_semantics=:m WHERE id=:id"),
        dict(raw=raw,m=json.dumps({'preserve':True}),id=f['material']))
    original=(await db_session.execute(text("SELECT to_jsonb(c) FROM material_claims c WHERE id=:id"),dict(id=f['claim']))).scalar_one()
    annotation=copy.deepcopy(next(a for a in migration.annotations() if a['paper_id']=='arxiv:0704.0453'))
    annotation.update(id=f['material'],paper_id=f['paper'],claims=[str(f['claim'])])
    monkeypatch.setattr(migration,'annotations',lambda:[annotation])
    connection=await db_session.connection()
    def up(sync):
        with Operations.context(MigrationContext.configure(sync)):migration.upgrade()
    def down(sync):
        with Operations.context(MigrationContext.configure(sync)):migration.downgrade()
    await connection.run_sync(up)
    assert (await db_session.execute(text("SELECT material_semantics FROM materials WHERE id=:id"),dict(id=f['material']))).scalar_one()=={'preserve':True}
    await add(db_session,'event_evidence',event_id=f['event'],link_type='source',
              artifact_id=f['source'],locator={'representation_input':{'sha256':annotation['source_sha256']}})
    await connection.run_sync(up)
    row=(await db_session.execute(text(f"SELECT formula,material_semantics,({FAMILY_SQL}) AS family FROM materials m WHERE id=:id"),dict(id=f['material']))).mappings().one()
    assert row['formula']==raw and row['family']=='cuprate'
    assert row['material_semantics']['source_notation']['text']=='Pr1.85Ce0.15CuO4'
    assert row['material_semantics']['preserve'] is True
    assert (await db_session.execute(text("SELECT to_jsonb(c) FROM material_claims c WHERE id=:id"),dict(id=f['claim']))).scalar_one()==original
    before=copy.deepcopy(row['material_semantics'])
    await connection.run_sync(up)
    assert (await db_session.execute(text("SELECT material_semantics FROM materials WHERE id=:id"),dict(id=f['material']))).scalar_one()==before
    await connection.run_sync(down)
    assert (await db_session.execute(text("SELECT material_semantics FROM materials WHERE id=:id"),dict(id=f['material']))).scalar_one()=={'preserve':True}
    await db_session.execute(text("UPDATE materials SET formula='Pr1.83Ce0.17CuO4' WHERE id=:id"),dict(id=f['material']))
    await connection.run_sync(up)
    assert (await db_session.execute(text("SELECT material_semantics FROM materials WHERE id=:id"),dict(id=f['material']))).scalar_one()=={'preserve':True}
    await db_session.rollback()
