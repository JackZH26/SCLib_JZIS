"""Append-only native publication outbox and fenced, expiring work claims."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

TABLE_ORDER=('retrieval_publication_jobs_v2','retrieval_publication_job_fences_v2',
    'retrieval_publication_claims_v2','retrieval_publication_results_v2')
FUNCTIONS=('sclib_publication_queue_hash_v2','sclib_publication_queue_insert_v2','sclib_publication_queue_created_v2',
    'sclib_publication_queue_fence_v2','sclib_publication_queue_immutable_v2')
SQL="LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC'"
PRODUCER='sclib_retrieval_producer'
WORKER='sclib_retrieval_queue_worker'


def statements():
    jobs,fences,claims,results=TABLE_ORDER
    return ["""
      CREATE FUNCTION public.sclib_publication_queue_hash_v2(body jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp SET TimeZone='UTC' AS $$
        SELECT public.sclib_retrieval_record_hash_v2(CASE WHEN body ? 'started_at' THEN body||jsonb_build_object(
          'started_at',to_char((body->>'started_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
          'lease_until',to_char((body->>'lease_until')::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
          ELSE body END)
      $$
    """,f"""
      CREATE FUNCTION public.sclib_publication_queue_immutable_v2() RETURNS trigger {SQL} AS $$
      BEGIN RAISE EXCEPTION 'publication_queue_history_is_append_only' USING ERRCODE='55000'; END $$
    """,f"""
      CREATE FUNCTION public.sclib_publication_queue_fence_v2() RETURNS trigger {SQL} AS $$
      BEGIN
        IF TG_OP='INSERT' THEN
          IF NEW.epoch<>0 THEN RAISE EXCEPTION 'publication_queue_fence_starts_at_zero'; END IF;
        ELSIF TG_OP='UPDATE' THEN
          IF NOT coalesce((SELECT pg_has_role(current_user,oid,'MEMBER') FROM pg_roles WHERE rolname='{WORKER}'),false)
            OR NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.epoch<>OLD.epoch+1 THEN
            RAISE EXCEPTION 'publication_queue_worker_monotonic_fence_required' USING ERRCODE='42501'; END IF;
        ELSE RAISE EXCEPTION 'publication_queue_fence_history_required' USING ERRCODE='55000'; END IF;
        RETURN NEW;
      END $$
    """,f"""
      CREATE FUNCTION public.sclib_publication_queue_created_v2() RETURNS trigger {SQL} AS $$
      BEGIN INSERT INTO public.{fences}(job_id,epoch) VALUES(NEW.id,0);RETURN NEW;END $$
    """,f"""
      CREATE FUNCTION public.sclib_publication_queue_insert_v2() RETURNS trigger {SQL} AS $$
      DECLARE job public.{jobs}%ROWTYPE; previous public.{claims}%ROWTYPE;
        claim public.{claims}%ROWTYPE; successor public.{jobs}%ROWTYPE;
        publication public.retrieval_publications_v2%ROWTYPE;
        seal public.retrieval_publication_seals_v2%ROWTYPE;
        event public.retrieval_activation_events_v2%ROWTYPE;
        current_hash text; total integer; now_at timestamptz;
      BEGIN
        IF TG_TABLE_NAME='{jobs}' THEN
          IF NOT coalesce((SELECT pg_has_role(current_user,oid,'MEMBER') FROM pg_roles WHERE rolname='{PRODUCER}'),false) THEN
            RAISE EXCEPTION 'publication_queue_producer_role_required' USING ERRCODE='42501'; END IF;
          PERFORM public.sclib_index_lock_v1();
          NEW.sequence_number:=nextval(pg_get_serial_sequence('public.retrieval_publication_jobs_v2','sequence_number')::regclass);
          SELECT * INTO publication FROM public.retrieval_publications_v2 WHERE id=NEW.publication_id;
          SELECT * INTO seal FROM public.retrieval_publication_seals_v2 WHERE publication_id=NEW.publication_id;
          SELECT public.sclib_source_lifecycle_snapshot_hash_v1('paper',to_jsonb(p)) INTO current_hash
            FROM public.papers p WHERE id=publication.paper_id;
          SELECT count(*) INTO total FROM public.chunks WHERE paper_id=publication.paper_id;
          IF publication.id IS NULL OR seal.publication_id IS NULL
            OR publication.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(publication))
            OR seal.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(seal))
            OR total<>seal.member_count OR NOT EXISTS(SELECT 1 FROM public.index_generations
              WHERE logical_index=NEW.logical_index)
            OR EXISTS(SELECT 1 FROM public.retrieval_publication_members_v2 m
              JOIN public.retrieval_native_revisions_v2 n ON n.id=m.native_revision_id
              LEFT JOIN public.chunks c ON c.id=n.chunk_key AND c.paper_id=publication.paper_id
              LEFT JOIN public.chunk_evidence_current link ON link.chunk_id=n.chunk_key
              WHERE m.publication_id=publication.id AND (c.id IS NULL
                OR n.source_snapshot_sha256<>current_hash OR n.snapshot_json IS DISTINCT FROM to_jsonb(c)
                OR link.evidence_revision_id IS DISTINCT FROM n.evidence_revision_id
                OR n.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(n))
                OR n.content_sha256<>encode(public.digest(convert_to(c.text,'UTF8'),'sha256'),'hex'))) THEN
            RAISE EXCEPTION 'publication_queue_complete_current_sealed_publication_required' USING ERRCODE='23514'; END IF;
          NEW.paper_id:=publication.paper_id;NEW.publication_seal_record_sha256:=seal.record_sha256;
          NEW.publication_manifest_sha256:=seal.manifest_sha256;NEW.member_count:=seal.member_count;
        ELSE
          IF NOT coalesce((SELECT pg_has_role(current_user,oid,'MEMBER') FROM pg_roles WHERE rolname='{WORKER}'),false) THEN
            RAISE EXCEPTION 'publication_queue_worker_role_required' USING ERRCODE='42501'; END IF;
          IF TG_TABLE_NAME='{claims}' THEN
            SELECT * INTO job FROM public.{jobs} WHERE id=NEW.job_id;
          ELSE
            SELECT * INTO claim FROM public.{claims} WHERE id=NEW.claim_id;
            SELECT * INTO job FROM public.{jobs} WHERE id=claim.job_id;
          END IF;
          IF job.id IS NULL OR job.record_sha256<>public.sclib_publication_queue_hash_v2(to_jsonb(job)) THEN
            RAISE EXCEPTION 'publication_queue_actual_intact_job_required'; END IF;
          -- Updating a row, rather than merely locking it, also fences stale
          -- repeatable-read transactions against a concurrently committed lease.
          UPDATE public.{fences} SET epoch=epoch+1 WHERE job_id=job.id;
          IF NOT FOUND THEN RAISE EXCEPTION 'publication_queue_fence_missing'; END IF;
          SELECT * INTO previous FROM public.{claims} WHERE job_id=job.id ORDER BY attempt_number DESC LIMIT 1;
          IF EXISTS(SELECT 1 FROM public.{results} WHERE job_id=job.id AND outcome IN ('published','superseded')) THEN
            RAISE EXCEPTION 'publication_queue_job_already_terminal' USING ERRCODE='55000'; END IF;
          IF previous.id IS NOT NULL AND previous.record_sha256<>public.sclib_publication_queue_hash_v2(to_jsonb(previous)) THEN
            RAISE EXCEPTION 'publication_queue_previous_claim_integrity'; END IF;
          now_at:=clock_timestamp();
          IF TG_TABLE_NAME='{claims}' THEN
            IF previous.id IS NOT NULL AND previous.lease_until>now_at
              AND NOT EXISTS(SELECT 1 FROM public.{results} WHERE claim_id=previous.id AND outcome='retry') THEN
              RAISE EXCEPTION 'publication_queue_unexpired_claim' USING ERRCODE='55000'; END IF;
            NEW.attempt_number:=coalesce(previous.attempt_number,0)+1;
            IF NEW.attempt_number>100 THEN RAISE EXCEPTION 'publication_queue_attempt_limit'; END IF;
            NEW.started_at:=now_at;NEW.lease_until:=now_at+make_interval(secs=>NEW.lease_seconds);
          ELSE
            IF claim.id IS NULL OR claim.id IS DISTINCT FROM previous.id OR claim.lease_until<=now_at
              OR claim.record_sha256<>public.sclib_publication_queue_hash_v2(to_jsonb(claim)) THEN
              RAISE EXCEPTION 'publication_queue_current_unexpired_claim_required' USING ERRCODE='55000'; END IF;
            NEW.job_id:=job.id;
            IF NEW.outcome='superseded' THEN
              SELECT * INTO successor FROM public.{jobs} WHERE id=NEW.successor_job_id;
              IF successor.id IS NULL OR successor.paper_id<>job.paper_id OR successor.logical_index<>job.logical_index
                OR successor.sequence_number<=job.sequence_number
                OR successor.record_sha256<>public.sclib_publication_queue_hash_v2(to_jsonb(successor)) THEN
                RAISE EXCEPTION 'publication_queue_later_same_paper_successor_required' USING ERRCODE='23514'; END IF;
            ELSIF NEW.outcome='published' THEN
              SELECT e.* INTO event FROM public.retrieval_activation_events_v2 e
                JOIN public.retrieval_active_pointer_v2 p ON p.logical_index=e.logical_index AND p.activation_event_id=e.id
                WHERE e.id=NEW.activation_event_id AND e.logical_index=job.logical_index;
              SELECT * INTO seal FROM public.retrieval_publication_seals_v2 WHERE publication_id=job.publication_id;
              IF event.id IS NULL OR event.record_sha256<>public.sclib_retrieval_record_hash_v2(to_jsonb(event))
                OR seal.record_sha256<>job.publication_seal_record_sha256
                OR (SELECT count(*) FROM public.retrieval_content_members_v2 WHERE content_id=event.content_id
                  AND paper_id=job.paper_id)<>job.member_count
                OR EXISTS(SELECT 1 FROM public.retrieval_publication_members_v2 m
                  WHERE m.publication_id=job.publication_id AND NOT EXISTS(
                    SELECT 1 FROM public.retrieval_content_members_v2 c WHERE c.content_id=event.content_id
                      AND c.paper_id=job.paper_id AND c.origin_kind='native_v2' AND c.native_revision_id=m.native_revision_id)) THEN
                RAISE EXCEPTION 'publication_queue_actual_active_complete_publication_required' USING ERRCODE='23514'; END IF;
            END IF;
          END IF;
        END IF;
        NEW.created_at:=clock_timestamp();NEW.record_sha256:=public.sclib_publication_queue_hash_v2(to_jsonb(NEW));
        RETURN NEW;
      END $$
    """,f"CREATE TRIGGER publication_queue_created AFTER INSERT ON public.{jobs} FOR EACH ROW EXECUTE FUNCTION public.sclib_publication_queue_created_v2()",
        *[sql for table in (jobs,claims,results) for sql in (
            f"CREATE TRIGGER publication_queue_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_publication_queue_insert_v2()",
            f"CREATE TRIGGER publication_queue_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.sclib_publication_queue_immutable_v2()",
            f"CREATE TRIGGER publication_queue_truncate BEFORE TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_publication_queue_immutable_v2()")],
        f"CREATE TRIGGER publication_queue_fence BEFORE INSERT OR UPDATE OR DELETE ON public.{fences} FOR EACH ROW EXECUTE FUNCTION public.sclib_publication_queue_fence_v2()",
        f"CREATE TRIGGER publication_queue_truncate BEFORE TRUNCATE ON public.{fences} FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_publication_queue_immutable_v2()",*grants()]


def grants():
    jobs,fences,claims,results=TABLE_ORDER
    # Only new relations. Existing writer/build/source permissions remain an
    # explicit operator concern and are not changed by this schema migration.
    return [f"""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{PRODUCER}') THEN
        GRANT SELECT,INSERT ON public.{jobs} TO {PRODUCER};
        GRANT INSERT ON public.{fences} TO {PRODUCER};
        GRANT USAGE ON SEQUENCE public.retrieval_publication_jobs_v2_sequence_number_seq TO {PRODUCER};
      END IF;
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{WORKER}') THEN
        GRANT SELECT ON public.{jobs},public.{fences},public.{claims},public.{results} TO {WORKER};
        GRANT INSERT ON public.{claims},public.{results} TO {WORKER};
        GRANT UPDATE(epoch) ON public.{fences} TO {WORKER};
      END IF;
    END $$"""]


def cleanup():
    return [f'DROP TRIGGER IF EXISTS {trigger} ON public.{table}' for table in TABLE_ORDER for trigger in
        ('publication_queue_created','publication_queue_insert','publication_queue_immutable','publication_queue_truncate','publication_queue_fence')]+[
        f'DROP FUNCTION IF EXISTS public.{function}({"jsonb" if function.endswith("hash_v2") else ""})' for function in FUNCTIONS]


def register(metadata):
    def col(name,kind,*,nullable=False,default=None):return sa.Column(name,kind,nullable=nullable,server_default=default)
    def uid(name,target=None,*,nullable=False):
        return sa.Column(name,UUID(as_uuid=True),*([sa.ForeignKey(target,ondelete='RESTRICT',onupdate='RESTRICT')] if target else []),nullable=nullable)
    def history(name,*fields,constraints=()):
        return sa.Table(name,metadata,*fields,col('created_at',sa.DateTime(timezone=True),default=sa.func.clock_timestamp()),
            col('record_sha256',sa.String(64),default='0'*64),*constraints,
            sa.CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'",name='ck_'+name+'_hash'))
    jobs,fences,claims,results=TABLE_ORDER
    history(jobs,uid('id'),sa.Column('sequence_number',sa.BigInteger,sa.Identity(always=True),nullable=False),
        col('logical_index',sa.String(160)),uid('publication_id','retrieval_publications_v2.id'),
        sa.Column('paper_id',sa.String(100),sa.ForeignKey('papers.id',ondelete='RESTRICT'),nullable=False,server_default='pending'),
        col('publication_seal_record_sha256',sa.String(64),default='0'*64),col('publication_manifest_sha256',sa.String(64),default='0'*64),
        col('member_count',sa.Integer,default='0'),constraints=(sa.PrimaryKeyConstraint('id'),sa.UniqueConstraint('logical_index','publication_id'),
            sa.CheckConstraint("logical_index ~ '^[A-Za-z0-9._-]{1,160}$' AND member_count BETWEEN 1 AND 1000 AND sequence_number>0",name='ck_publication_job_shape'),sa.UniqueConstraint('sequence_number'),sa.Index('idx_publication_queue_pending_v2','logical_index','sequence_number')))
    sa.Table(fences,metadata,uid('job_id',jobs+'.id'),col('epoch',sa.BigInteger,default='0'),sa.PrimaryKeyConstraint('job_id'),
        sa.CheckConstraint('epoch>=0',name='ck_publication_queue_epoch'))
    history(claims,uid('id'),uid('job_id',jobs+'.id'),col('worker_id',sa.String(80)),col('lease_seconds',sa.Integer),
        col('attempt_number',sa.Integer,default='0'),col('started_at',sa.DateTime(timezone=True),default=sa.func.clock_timestamp()),
        col('lease_until',sa.DateTime(timezone=True),default=sa.func.clock_timestamp()),constraints=(sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('job_id','attempt_number'),sa.CheckConstraint("worker_id ~ '^[A-Za-z0-9._:-]{1,80}$' AND "
                'lease_seconds BETWEEN 30 AND 14400 AND attempt_number BETWEEN 1 AND 100 AND lease_until>started_at',name='ck_publication_claim_shape')))
    history(results,uid('claim_id',claims+'.id'),uid('job_id',jobs+'.id'),col('outcome',sa.String(16)),
        uid('activation_event_id','retrieval_activation_events_v2.id',nullable=True),uid('successor_job_id',jobs+'.id',nullable=True),
        col('error_code',sa.String(32),nullable=True),constraints=(sa.PrimaryKeyConstraint('claim_id'),sa.Index('idx_publication_queue_outcome_v2','job_id','outcome'),
            sa.CheckConstraint("(outcome='published' AND activation_event_id IS NOT NULL AND successor_job_id IS NULL AND error_code IS NULL) OR "
                "(outcome='superseded' AND activation_event_id IS NULL AND successor_job_id IS NOT NULL AND error_code IS NULL) OR "
                "(outcome='retry' AND activation_event_id IS NULL AND successor_job_id IS NULL AND error_code IS NOT NULL AND error_code IN "
                "('transient_io','build_failed','validation_failed','source_changed','operator_retry'))",name='ck_publication_result_shape')))
    for sql in statements():sa.event.listen(metadata,'after_create',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    for sql in cleanup():sa.event.listen(metadata,'before_drop',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
