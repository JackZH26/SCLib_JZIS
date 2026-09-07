"""Frozen additive 0058 bounded negative cache-invalidation task ledger.

Trusted callers authenticate actor identities and re-inspect the relationship
inventory. SQL verifies declared bytes/bindings and atomically invalidates only
the Timeline readiness singleton. A receipt is not a refresh, source approval,
scientific acceptance, or proof that dependency propagation has completed.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

TABLE_ORDER = ("source_task_epoch", "source_task_requests", "source_task_attempts")
PARENT_TABLES = ("source_lifecycle_events", "users", "research_role_grants",
                 "timeline_projection_state", "timeline_projection_points")
LOCK_KEY = 580017026
LOCK_FUNCTION = "sclib_source_task_lock_v1"
ACTION_VERSION = "timeline-cache-invalidation/1.0.0"
INVENTORY_VERSION = "source-impact/1.0.0"
FUNCTION_SIGNATURES = (
    ("sclib_source_task_record_hash_v1", "jsonb"),
    (LOCK_FUNCTION, ""),
    ("sclib_source_task_projection_writer_v1", ""),
    ("sclib_source_task_writer_v1", ""),
    ("sclib_source_task_current_event_v1", "uuid, text, text"),
    ("sclib_source_task_immutable_v1", ""),
    ("sclib_source_task_request_v1", ""),
    ("sclib_source_task_attempt_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"


def guard_statements() -> list[str]:
    statements = ["""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_record_hash_v1(body jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public, pg_temp AS $$
        SELECT encode(public.digest(convert_to('{'||COALESCE(string_agg(
          to_jsonb(key)::text||':'||value::text,',' ORDER BY key COLLATE "C"),'')||'}','UTF8'),'sha256'),'hex')
        FROM jsonb_each(body-ARRAY['created_at','record_sha256','inventory_json'])
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.{LOCK_FUNCTION}() RETURNS void {_SQL} AS $$
      BEGIN
        IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
          RAISE EXCEPTION 'source_task_busy_retry_transaction' USING ERRCODE='55P03';
        END IF;
        UPDATE public.source_task_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN RAISE EXCEPTION 'source_task_epoch_missing' USING ERRCODE='55000'; END IF;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_projection_writer_v1() RETURNS trigger {_SQL} AS $$
      BEGIN PERFORM public.{LOCK_FUNCTION}(); RETURN NULL; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_writer_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF current_setting('transaction_isolation')<>'serializable' THEN
          RAISE EXCEPTION 'source_task_requires_serializable' USING ERRCODE='25000';
        END IF;
        PERFORM public.sclib_research_integrity_lock_v1();
        PERFORM public.sclib_research_publication_lock_v1();
        PERFORM public.sclib_source_lifecycle_lock_v1();
        PERFORM public.{LOCK_FUNCTION}(); RETURN NULL;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_current_event_v1(identifier uuid,event_hash text,snapshot_hash text)
      RETURNS boolean {_SQL} AS $$
      DECLARE event public.source_lifecycle_events%ROWTYPE; actual jsonb; kind text;
      BEGIN
        SELECT * INTO event FROM public.source_lifecycle_events WHERE id=identifier;
        IF event.id IS NULL OR event.record_sha256 IS DISTINCT FROM event_hash
          OR event.snapshot_sha256 IS DISTINCT FROM snapshot_hash
          OR event.record_sha256 IS DISTINCT FROM public.sclib_source_lifecycle_record_hash_v1(to_jsonb(event))
          OR EXISTS(SELECT 1 FROM public.source_lifecycle_events WHERE predecessor_id=event.id) THEN RETURN false; END IF;
        kind:=CASE WHEN event.paper_id IS NOT NULL THEN 'paper' ELSE 'work' END;
        IF kind='paper' THEN SELECT to_jsonb(p) INTO actual FROM public.papers p WHERE id=event.paper_id FOR SHARE;
        ELSE SELECT to_jsonb(w) INTO actual FROM public.works w WHERE id=event.work_id FOR SHARE; END IF;
        RETURN actual IS NOT NULL AND public.sclib_source_lifecycle_snapshot_hash_v1(kind,actual)=snapshot_hash;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_immutable_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'source task history is append-only: %',TG_TABLE_NAME USING ERRCODE='55000'; END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_request_v1() RETURNS trigger {_SQL} AS $$
      DECLARE inventory jsonb;
      BEGIN
        IF NOT public.sclib_research_publication_role_v1(NEW.requester_id,NEW.requester_grant_id,'curator') THEN
          RAISE EXCEPTION 'source_task_explicit_active_curator_required' USING ERRCODE='42501'; END IF;
        IF NOT public.sclib_source_task_current_event_v1(NEW.event_id,NEW.event_sha256,NEW.source_snapshot_sha256) THEN
          RAISE EXCEPTION 'source_task_current_event_required' USING ERRCODE='23514'; END IF;
        IF octet_length(NEW.inventory_json)>1048576 OR encode(public.digest(convert_to(NEW.inventory_json,'UTF8'),'sha256'),'hex')
          IS DISTINCT FROM NEW.inventory_sha256 THEN
          RAISE EXCEPTION 'source_task_exact_inventory_bytes_required' USING ERRCODE='23514'; END IF;
        inventory:=NEW.inventory_json::jsonb;
        IF jsonb_typeof(inventory) IS DISTINCT FROM 'object'
          OR inventory->>'version' IS DISTINCT FROM NEW.inventory_version
          OR jsonb_typeof(inventory->'event') IS DISTINCT FROM 'object'
          OR inventory->'event'->>'id' IS DISTINCT FROM NEW.event_id::text
          OR inventory->'event'->>'record_sha256' IS DISTINCT FROM NEW.event_sha256
          OR inventory->'event'->>'source_snapshot_sha256' IS DISTINCT FROM NEW.source_snapshot_sha256
          OR inventory ?| ARRAY['observation','inventory_sha256'] THEN
          RAISE EXCEPTION 'source_task_exact_inventory_envelope_required' USING ERRCODE='23514'; END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_source_task_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_source_task_attempt_v1() RETURNS trigger {_SQL} AS $$
      DECLARE request public.source_task_requests%ROWTYPE; prior public.source_task_attempts%ROWTYPE; version integer;
      BEGIN
        IF NOT public.sclib_research_publication_role_v1(NEW.executor_id,NEW.executor_grant_id,'curator') THEN
          RAISE EXCEPTION 'source_task_explicit_active_executor_required' USING ERRCODE='42501'; END IF;
        SELECT * INTO request FROM public.source_task_requests WHERE id=NEW.request_id;
        IF request.id IS NULL OR request.record_sha256 IS DISTINCT FROM public.sclib_source_task_record_hash_v1(to_jsonb(request)) THEN
          RAISE EXCEPTION 'source_task_exact_request_required' USING ERRCODE='23514'; END IF;
        SELECT * INTO prior FROM public.source_task_attempts WHERE request_id=NEW.request_id ORDER BY attempt_number DESC LIMIT 1;
        IF NEW.predecessor_id IS DISTINCT FROM prior.id OR NEW.attempt_number<>COALESCE(prior.attempt_number,0)+1
          OR (prior.id IS NOT NULL AND prior.status<>'retryable_failure') THEN
          RAISE EXCEPTION 'source_task_exact_retry_predecessor_required' USING ERRCODE='23514'; END IF;
        NEW.state_present:=false; NEW.state_changed:=false;
        IF NEW.status='succeeded' THEN
          IF NOT public.sclib_research_publication_role_v1(request.requester_id,request.requester_grant_id,'curator') THEN
            RAISE EXCEPTION 'source_task_request_authority_unavailable' USING ERRCODE='42501'; END IF;
          IF NOT public.sclib_source_task_current_event_v1(request.event_id,request.event_sha256,request.source_snapshot_sha256) THEN
            RAISE EXCEPTION 'source_task_current_event_required' USING ERRCODE='23514'; END IF;
          SELECT schema_version INTO version FROM public.timeline_projection_state WHERE id=1 FOR UPDATE;
          NEW.state_present:=FOUND;
          IF NEW.state_present AND version IS DISTINCT FROM 0 THEN
            UPDATE public.timeline_projection_state SET schema_version=0 WHERE id=1;
            NEW.state_changed:=true;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();
        NEW.record_sha256:=public.sclib_source_task_record_hash_v1(to_jsonb(NEW)); RETURN NEW;
      END $$
    """, "INSERT INTO public.source_task_epoch(id,epoch) VALUES (1,0)"]
    for name in TABLE_ORDER[1:]:
        statements.extend([
            f"CREATE TRIGGER st58_writer BEFORE INSERT ON public.{name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.sclib_source_task_writer_v1()",
            f"CREATE TRIGGER st58_immutable_row BEFORE UPDATE OR DELETE ON public.{name} FOR EACH ROW "
            "EXECUTE FUNCTION public.sclib_source_task_immutable_v1()",
            f"CREATE TRIGGER st58_immutable_truncate BEFORE TRUNCATE ON public.{name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.sclib_source_task_immutable_v1()",
        ])
    for name in ("timeline_projection_state", "timeline_projection_points"):
        statements.append(f"CREATE TRIGGER st58_projection_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE "
                          f"ON public.{name} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_source_task_projection_writer_v1()")
    statements.extend([
        "CREATE TRIGGER st58_request BEFORE INSERT ON public.source_task_requests FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_source_task_request_v1()",
        "CREATE TRIGGER st58_attempt BEFORE INSERT ON public.source_task_attempts FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_source_task_attempt_v1()",
    ])
    return statements


def remove_parent_guards() -> list[str]:
    return [f"DROP TRIGGER IF EXISTS st58_projection_writer ON public.{name}"
            for name in ("timeline_projection_state", "timeline_projection_points")]


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    tables = {}

    def uid(name, target=None, *, required=True):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def col(name, kind, *, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def ck(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_st58_{name}")

    def table(name, *items):
        checks = [ck(f"{item.name} ~ '^[0-9a-f]{{64}}$'", item.name) for item in items
                  if isinstance(item, sa.Column) and item.name.endswith("sha256")]
        tables[name] = sa.Table(name, metadata,
            sa.Column("id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            *items, col("record_sha256", sa.String(64), default="0" * 64),
            col("created_at", sa.DateTime(timezone=True), default=sa.func.clock_timestamp()),
            ck("record_sha256 ~ '^[0-9a-f]{64}$' AND isfinite(created_at)", "record_time"),
            *checks, sa.PrimaryKeyConstraint("id"))

    tables[TABLE_ORDER[0]] = sa.Table(TABLE_ORDER[0], metadata, col("id", sa.Integer), col("epoch", sa.BigInteger),
        sa.PrimaryKeyConstraint("id"), ck("id=1 AND epoch>=0", "epoch_singleton"))
    table("source_task_requests", uid("event_id", "source_lifecycle_events"),
        col("event_sha256", sa.String(64)), col("source_snapshot_sha256", sa.String(64)),
        col("inventory_version", sa.String(80)), col("inventory_sha256", sa.String(64)), col("inventory_json", sa.Text),
        col("action_version", sa.String(80)), uid("requester_id", "users"), uid("requester_grant_id", "research_role_grants"),
        col("request_key", sa.String(160)), ck(f"inventory_version='{INVENTORY_VERSION}'", "inventory_version"),
        ck(f"action_version='{ACTION_VERSION}'", "action_version"),
        ck("octet_length(inventory_json) BETWEEN 2 AND 1048576", "inventory_bytes"),
        ck("request_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$'", "request_key"),
        sa.UniqueConstraint("requester_id", "request_key", name="uq_st58_request_key"),
        sa.Index("idx_st58_request_event", "event_id"))
    table("source_task_attempts", uid("request_id", "source_task_requests"), col("attempt_number", sa.SmallInteger),
        uid("predecessor_id", "source_task_attempts", required=False), uid("executor_id", "users"),
        uid("executor_grant_id", "research_role_grants"), col("execution_key", sa.String(160)),
        col("status", sa.String(40)), col("outcome_code", sa.String(60)),
        col("state_present", sa.Boolean, default=sa.false()), col("state_changed", sa.Boolean, default=sa.false()),
        ck("attempt_number BETWEEN 1 AND 5", "attempt_number"),
        ck("predecessor_id IS NULL OR predecessor_id<>id", "attempt_not_self"),
        ck("execution_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$'", "execution_key"),
        ck("(status='succeeded' AND outcome_code='timeline_cache_invalidated') "
           "OR (status='obsolete' AND outcome_code IN ('source_changed','inventory_changed')) "
           "OR (status='blocked' AND outcome_code IN ('request_authority_unavailable','scope_limit','inventory_unavailable')) "
           "OR (status IN ('retryable_failure','exhausted') AND outcome_code IN ('database_busy','statement_timeout','serialization_failure'))",
           "status_outcome"),
        ck("(status<>'retryable_failure' OR attempt_number<5) AND (status<>'exhausted' OR attempt_number=5)", "retry_bound"),
        ck("(status='succeeded' OR (NOT state_present AND NOT state_changed)) AND (NOT state_changed OR state_present)", "state_flags"),
        sa.UniqueConstraint("request_id", "attempt_number", name="uq_st58_attempt_number"),
        sa.UniqueConstraint("predecessor_id", name="uq_st58_attempt_successor"),
        sa.UniqueConstraint("request_id", "execution_key", name="uq_st58_execution_key"),
        sa.Index("uq_st58_attempt_root", "request_id", unique=True, postgresql_where=sa.text("predecessor_id IS NULL")))
    last = tables[TABLE_ORDER[-1]]
    for name in PARENT_TABLES + TABLE_ORDER[:-1] + ("source_lifecycle_reviews",):
        last.add_is_dependent_on(metadata.tables[name])
    for statement in guard_statements():
        sa.event.listen(last, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return tables
