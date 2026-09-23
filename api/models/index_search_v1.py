"""Derived full-text documents without changing immutable member hashes.

The parent member is append-only. Populate once during migration and atomically
for every later member insert; callers cannot supply different search content.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

TABLE = "index_generation_search"
DOCUMENT = "to_tsvector('english'::regconfig,coalesce(snapshot_json->>'title','')||' '||(snapshot_json->>'text'))"


def install_statements():
    return [
        # The migration holds a parent-table lock. Existing membership and its
        # hashes are read only; no scientific or activation record is rewritten.
        f"""INSERT INTO public.{TABLE}(generation_id,vector_id,paper_id,year,document)
          SELECT generation_id,vector_id,paper_id,(snapshot_json->>'year')::integer,
            {DOCUMENT} FROM public.index_generation_members""",
        f"""CREATE FUNCTION public.sclib_index_search_derive_v1() RETURNS trigger
          LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
          BEGIN
            SELECT paper_id,(snapshot_json->>'year')::integer,{DOCUMENT}
              INTO NEW.paper_id,NEW.year,NEW.document
              FROM public.index_generation_members
              WHERE generation_id=NEW.generation_id AND vector_id=NEW.vector_id;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'search_document_member_required' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
          END $$""",
        f"""CREATE FUNCTION public.sclib_index_search_append_v1() RETURNS trigger
          LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
          BEGIN
            INSERT INTO public.{TABLE}(generation_id,vector_id)
              VALUES(NEW.generation_id,NEW.vector_id);
            RETURN NEW;
          END $$""",
        f"CREATE TRIGGER is81_derive BEFORE INSERT ON public.{TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_index_search_derive_v1()",
        f"CREATE TRIGGER is81_immutable BEFORE UPDATE OR DELETE ON public.{TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_index_immutable_v1()",
        f"CREATE TRIGGER is81_truncate BEFORE TRUNCATE ON public.{TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_index_immutable_v1()",
        "CREATE TRIGGER is81_append AFTER INSERT ON public.index_generation_members "
        "FOR EACH ROW EXECUTE FUNCTION public.sclib_index_search_append_v1()",
        f"ANALYZE public.{TABLE}",
    ]


def remove_statements():
    return [
        "DROP TRIGGER is81_append ON public.index_generation_members",
        f"DROP TRIGGER is81_derive ON public.{TABLE}",
        f"DROP TRIGGER is81_immutable ON public.{TABLE}",
        f"DROP TRIGGER is81_truncate ON public.{TABLE}",
        "DROP FUNCTION public.sclib_index_search_append_v1()",
        "DROP FUNCTION public.sclib_index_search_derive_v1()",
    ]


def register(metadata):
    table = sa.Table(
        TABLE, metadata,
        sa.Column("generation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("vector_id", sa.String(120), nullable=False),
        sa.Column("paper_id", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer),
        sa.Column("document", TSVECTOR, nullable=False),
        sa.PrimaryKeyConstraint("generation_id", "vector_id"),
        sa.ForeignKeyConstraint(
            ["generation_id", "vector_id"],
            ["index_generation_members.generation_id", "index_generation_members.vector_id"],
            ondelete="RESTRICT", onupdate="RESTRICT",
        ),
        sa.Index("idx_is81_document", "document", postgresql_using="gin"),
        sa.Index("idx_is81_year", "generation_id", "year"),
    )
    # The integrity function used by this derived table is installed by the
    # generation tables; corpus guards must also be complete before backfill.
    table.add_is_dependent_on(metadata.tables["index_corpus_observations"])
    for event, statements in (("after_create", install_statements()),
                              ("before_drop", remove_statements())):
        for statement in statements:
            sa.event.listen(table, event,
                sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return table
