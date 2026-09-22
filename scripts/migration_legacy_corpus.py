"""0079/0080 owned migration round trips and independent history guards."""

from test_safety import validate_test_environment, verify_postgres_identity

TABLES = (
    "legacy_index_papers",
    "legacy_index_sources",
    "legacy_index_windows",
    "index_corpora",
    "index_corpus_partitions",
    "index_corpus_member_routes",
    "index_corpus_formula_terms",
    "index_corpus_seals",
    "index_corpus_observations",
)


def snapshot(connection, old_only=False):
    from sqlalchemy import inspect, text

    return {
        name: connection.execute(
            text(
                f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
            )
        )
        .scalars()
        .all()
        for name in inspect(connection).get_table_names(schema="public")
        if name != "alembic_version" and (not old_only or name not in TABLES)
    }


def objects(connection):
    from sqlalchemy import text

    return connection.execute(
        text("""SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND (p.proname LIKE 'sclib_corpus_%' OR p.proname LIKE 'sclib_legacy_%'
        OR p.proname='sclib_index_insert_v1') ORDER BY p.proname""")
    ).all()


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from sqlalchemy import inspect, text
    from services.schema_lifecycle import check_connection_schema

    validate_test_environment()
    with engine.connect() as c:
        assert check_connection_schema(c)["status"] == "compatible"
        verify_postgres_identity(c, capability)
        assert all(
            c.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() == 0
            for name in TABLES
        )
        before, definitions = snapshot(c, True), objects(c)
    command.downgrade(config, "0078_scientific_result_passage")
    with engine.connect() as c:
        verify_postgres_identity(c, capability)
        assert not set(TABLES) & set(inspect(c).get_table_names(schema="public"))
        assert snapshot(c, True) == before
        assert (
            c.execute(
                text("SELECT to_regclass('public.idx_ic80_fulltext')")
            ).scalar_one()
            is None
        )
    command.upgrade(config, "head")
    with engine.connect() as c:
        assert check_connection_schema(c)["status"] == "compatible"
        verify_postgres_identity(c, capability)
        assert snapshot(c, True) == before and objects(c) == definitions
        assert (
            c.execute(
                text("SELECT to_regclass('public.idx_ic80_fulltext')")
            ).scalar_one()
            is not None
        )


def retained_history(capability, engine, config):
    import json
    from uuid import uuid4
    from alembic import command
    from sqlalchemy import text
    from services.schema_lifecycle import check_connection_schema
    from models.index_generations_v1 import PROFILE

    validate_test_environment()
    with engine.begin() as c:
        verify_postgres_identity(c, capability)
        c.execute(
            text(
                "INSERT INTO papers(id,source,title,authors,abstract,status) VALUES ('synthetic:corpus-migration','arxiv','Synthetic retained migration','{}','','published')"
            )
        )
        c.execute(
            text("""INSERT INTO legacy_index_papers(paper_sha256,paper_id,source_snapshot_sha256,body_raw)
            SELECT public.sclib_answer_evidence_text_hash_v1(body),id,source_hash,body FROM (
            SELECT p.id,public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text AS body,
            public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) AS source_hash
            FROM papers p WHERE p.id='synthetic:corpus-migration') x""")
        )
    with engine.connect() as c:
        before = snapshot(c)
    try:
        command.downgrade(config, "0078_scientific_result_passage")
    except RuntimeError as e:
        assert "Refusing destructive retained legacy" in str(e)
    else:
        raise AssertionError("Retained source history downgrade was allowed")
    with engine.connect() as c:
        assert check_connection_schema(c)["status"] == "compatible"
        verify_postgres_identity(c, capability)
        assert snapshot(c) == before
    resource = {
        "backend": "disposable",
        "project": "synthetic",
        "location": "local",
        "index_resource": "synthetic-index",
        "endpoint_resource": "synthetic-endpoint",
        "deployed_index_id": "synthetic",
        "distance_measure": "COSINE_DISTANCE",
        "feature_norm": "NONE",
    }
    identifier = uuid4()
    with engine.begin() as c:
        verify_postgres_identity(c, capability)
        c.execute(
            text("""INSERT INTO index_generations(id,logical_index,profile,resource,expected_member_count,manifest_sha256)
            VALUES(:id,'synthetic-corpus',CAST(:profile AS jsonb),CAST(:resource AS jsonb),1,:hash)"""),
            {
                "id": identifier,
                "profile": json.dumps(PROFILE),
                "resource": json.dumps(resource),
                "hash": "a" * 64,
            },
        )
        c.execute(
            text("""INSERT INTO index_corpora(generation_id,pack_sha256,expected_partitions,expected_sources,input_manifest_sha256)
            VALUES(:id,:hash,1,1,:hash)"""),
            {"id": identifier, "hash": "a" * 64},
        )
    with engine.connect() as c:
        before = snapshot(c)
    try:
        command.downgrade(config, "0079_retained_legacy")
    except RuntimeError as e:
        assert "Refusing destructive corpus history" in str(e)
    else:
        raise AssertionError("Corpus history downgrade was allowed")
    with engine.connect() as c:
        assert check_connection_schema(c)["status"] == "compatible"
        verify_postgres_identity(c, capability)
        assert snapshot(c) == before
    print(
        "Retained corpus empty migration round trip and both independent populated-history downgrade guards passed."
    )
