"""Frozen additive 0059 operational background-cycle coordination ledger.

The trusted scheduler owns the dedicated connection and session advisory lock.
PostgreSQL's lock inventory proves current-backend key ownership, not whether
the caller chose session versus transaction scope. This is an operational
retry/history table, not scientific provenance or an approval mechanism.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_NAME = "background_job_cycles"
JOB_LOCK_KEYS = {
    "stats_refresh": 589017031,
    "timeline_projection": 589017032,
    "formula_audit": 589017033,
    "nightly_audit": 589017034,
    "ask_history_prune": 589017035,
}
FUNCTION_SIGNATURES = (
    ("sclib_background_job_has_lock_v1", "text"),
    ("sclib_background_job_guard_v1", ""),
    ("sclib_background_job_retention_v1", ""),
)
_SQL = "LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp SET TimeZone = 'UTC'"


def guard_statements() -> list[str]:
    lock_cases = " ".join(f"WHEN '{job}' THEN {key}" for job, key in JOB_LOCK_KEYS.items())
    return [f"""
      CREATE OR REPLACE FUNCTION public.sclib_background_job_has_lock_v1(job text)
      RETURNS boolean LANGUAGE sql SET search_path = pg_catalog, public, pg_temp AS $$
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks l
          WHERE l.locktype='advisory' AND l.pid=pg_backend_pid() AND l.granted
          AND l.mode='ExclusiveLock' AND l.classid=0
          AND l.objid=(CASE job {lock_cases} END)::oid AND l.objsubid=1
          AND l.database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database()))
      $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_background_job_guard_v1() RETURNS trigger {_SQL} AS $$
      BEGIN
        IF NOT public.sclib_background_job_has_lock_v1(NEW.job_name) THEN
          RAISE EXCEPTION 'background_job_current_backend_lock_required' USING ERRCODE='42501'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.status<>'running' OR NEW.attempts<>1 OR NEW.backend_pid<>pg_backend_pid() THEN
            RAISE EXCEPTION 'background_job_initial_running_claim_required' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.job_name IS DISTINCT FROM OLD.job_name
          OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for OR NEW.schedule_sha256 IS DISTINCT FROM OLD.schedule_sha256 THEN
          RAISE EXCEPTION 'background_job_cycle_identity_immutable' USING ERRCODE='23514'; END IF;
        IF OLD.status='succeeded' THEN
          IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'background_job_success_immutable' USING ERRCODE='55000'; END IF;
          RETURN NEW;
        END IF;
        IF NEW.status='running' AND OLD.status IN ('running','failed') THEN
          IF NEW.attempts<>OLD.attempts+1 OR NEW.backend_pid<>pg_backend_pid()
            OR NEW.started_at<OLD.started_at
            OR (OLD.status='failed' AND NEW.started_at<OLD.next_retry_at) THEN
            RAISE EXCEPTION 'background_job_exact_retry_claim_required' USING ERRCODE='23514'; END IF;
        ELSIF OLD.status='running' AND NEW.status IN ('succeeded','failed') THEN
          IF NEW.attempts<>OLD.attempts OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
            OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.backend_pid<>OLD.backend_pid
            OR NEW.backend_pid<>pg_backend_pid() THEN
            RAISE EXCEPTION 'background_job_exact_owner_completion_required' USING ERRCODE='23514'; END IF;
        ELSE
          RAISE EXCEPTION 'background_job_invalid_transition' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$
    """, f"""
      CREATE OR REPLACE FUNCTION public.sclib_background_job_retention_v1() RETURNS trigger {_SQL} AS $$
      BEGIN RAISE EXCEPTION 'background job cycle history cannot be deleted' USING ERRCODE='55000'; END $$
    """, f"CREATE TRIGGER bj59_guard BEFORE INSERT OR UPDATE ON public.{TABLE_NAME} FOR EACH ROW "
         "EXECUTE FUNCTION public.sclib_background_job_guard_v1()",
        f"CREATE TRIGGER bj59_retention_row BEFORE DELETE ON public.{TABLE_NAME} FOR EACH ROW "
        "EXECUTE FUNCTION public.sclib_background_job_retention_v1()",
        f"CREATE TRIGGER bj59_retention_truncate BEFORE TRUNCATE ON public.{TABLE_NAME} FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.sclib_background_job_retention_v1()"]


def register(metadata: sa.MetaData) -> sa.Table:
    job_names = ",".join("'" + job + "'" for job in JOB_LOCK_KEYS)
    value = sa.Table(TABLE_NAME, metadata,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_name", sa.String(40), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schedule_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
        sa.Column("backend_pid", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(40)),
        sa.Column("result_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("job_name", "scheduled_for", name="uq_bj59_cycle"),
        sa.CheckConstraint(f"job_name IN ({job_names})", name="ck_bj59_job"),
        sa.CheckConstraint("schedule_sha256 ~ '^[0-9a-f]{64}$'", name="ck_bj59_schedule_hash"),
        sa.CheckConstraint("backend_pid>0 AND attempts>0 AND (duration_ms IS NULL OR duration_ms>=0)", name="ck_bj59_counters"),
        sa.CheckConstraint("jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=16384", name="ck_bj59_result"),
        sa.CheckConstraint("error_code IS NULL OR error_code IN ('execution_failed','database_unavailable','timeout','cancelled')",
                           name="ck_bj59_error"),
        sa.CheckConstraint("isfinite(scheduled_for) AND isfinite(started_at) "
                           "AND (completed_at IS NULL OR isfinite(completed_at)) "
                           "AND (next_retry_at IS NULL OR isfinite(next_retry_at)) "
                           "AND scheduled_for<=started_at AND (completed_at IS NULL OR completed_at>=started_at) "
                           "AND (next_retry_at IS NULL OR next_retry_at>=completed_at)", name="ck_bj59_times"),
        sa.CheckConstraint("(status='running' AND completed_at IS NULL AND duration_ms IS NULL AND error_code IS NULL AND next_retry_at IS NULL) "
                           "OR (status='succeeded' AND completed_at IS NOT NULL AND duration_ms IS NOT NULL AND error_code IS NULL AND next_retry_at IS NULL) "
                           "OR (status='failed' AND completed_at IS NOT NULL AND duration_ms IS NOT NULL AND error_code IS NOT NULL AND next_retry_at IS NOT NULL)",
                           name="ck_bj59_state"),
        sa.Index("idx_bj59_job_state_schedule", "job_name", "status", "scheduled_for"))
    for statement in guard_statements():
        sa.event.listen(value, "after_create", sa.DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))
    return value
