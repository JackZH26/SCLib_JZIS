"""0081 backfill/roundtrip on owned migrated data, including sealed members."""

from test_safety import validate_test_environment, verify_postgres_identity


def populated_roundtrip(capability, engine, config):
    from alembic import command
    from sqlalchemy import inspect, text
    from services.schema_lifecycle import check_connection_schema

    def retained(connection):
        return {name: connection.execute(text(
            f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
        )).scalars().all() for name in inspect(connection).get_table_names(schema="public")
            if name not in {"alembic_version", "index_generation_search"}}

    def projected(connection):
        rows = connection.execute(text("""SELECT to_jsonb(s) FROM index_generation_search s
          ORDER BY generation_id,vector_id""")).scalars().all()
        assert rows, "A populated member backfill must actually be exercised"
        assert connection.execute(text("""SELECT NOT EXISTS(
          SELECT 1 FROM index_generation_members m LEFT JOIN index_generation_search s
            USING(generation_id,vector_id)
          WHERE s.vector_id IS NULL OR s.paper_id IS DISTINCT FROM m.paper_id
            OR s.year IS DISTINCT FROM (m.snapshot_json->>'year')::integer
            OR s.document IS DISTINCT FROM to_tsvector('english'::regconfig,
              coalesce(m.snapshot_json->>'title','')||' '||(m.snapshot_json->>'text'))
            OR m.record_sha256<>public.sclib_index_record_hash_v1(to_jsonb(m)))""")).scalar_one()
        return rows

    validate_test_environment()
    with engine.connect() as c:
        verify_postgres_identity(c, capability)
        before, documents = retained(c), projected(c)
    command.downgrade(config, "0080_index_corpus")
    with engine.connect() as c:
        verify_postgres_identity(c, capability)
        assert retained(c) == before
        assert c.execute(text("SELECT to_regclass('public.index_generation_search')")).scalar_one() is None
    command.upgrade(config, "head")
    with engine.connect() as c:
        assert check_connection_schema(c)["status"] == "compatible"
        verify_postgres_identity(c, capability)
        assert retained(c) == before and projected(c) == documents
    print("Populated full-text backfill/roundtrip preserved all original records, hashes and active pins.")
