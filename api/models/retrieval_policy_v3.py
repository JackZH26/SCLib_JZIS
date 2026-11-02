"""Frozen bounded exact year filtering; preserve the original v2 policy."""
import hashlib
import json

import sqlalchemy as sa

from models.retrieval_backend_v2 import POLICY as POLICY_V2,POLICY_SHA256 as SHA_V2,guard_statements

POLICY={**POLICY_V2,'version':'sclib-pgvector-query-policy/3.0.0',
    'exact_cohort_limit':1000,'year_exact_cohort_limit':200000,
    'exact_filtered_order':'distance_plus_zero_then_vector_id_C/1.0.0'}
POLICY_SHA256=hashlib.sha256((json.dumps(POLICY,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
assert POLICY_SHA256=='c55de6c3f91622ce9ebbc080bf0cb53c90296d2e7aa75eb61d1ba566b86f417f'
SUPPORTED_POLICIES=((POLICY_V2,SHA_V2),(POLICY,POLICY_SHA256))
FUNCTION='sclib_retrieval_policy_build_v3'
TABLE='retrieval_backend_builds_v2'
TRIGGER='retrieval_backend_v2_insert'


def statements():
    source=next(sql for sql in guard_statements() if 'CREATE FUNCTION public.sclib_retrieval_backend_insert_v2()' in sql)
    original=(f"OR NEW.policy IS DISTINCT FROM '{json.dumps(POLICY_V2)}'::jsonb\n"
        f"            OR NEW.policy_artifact_sha256<>'{SHA_V2}'")
    replacement=(f"OR NOT ((NEW.policy='{json.dumps(POLICY_V2)}'::jsonb AND NEW.policy_artifact_sha256='{SHA_V2}') "
        f"OR (NEW.policy='{json.dumps(POLICY)}'::jsonb AND NEW.policy_artifact_sha256='{POLICY_SHA256}'))")
    assert source.count(original)==1
    source=source.replace(original,replacement).replace('FUNCTION public.sclib_retrieval_backend_insert_v2()',f'FUNCTION public.{FUNCTION}()',1)
    return [source,f'DROP TRIGGER {TRIGGER} ON public.{TABLE}',
        f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()']


def register(metadata):
    # Fresh test bootstrap only; deployed schemas use explicit Alembic jobs.
    for sql in statements():
        sa.event.listen(metadata,'after_create',sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    sa.event.listen(metadata,'before_drop',sa.DDL(f'''DO $$ BEGIN
      IF to_regclass('public.{TABLE}') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS {TRIGGER} ON public.{TABLE};
      END IF;
      DROP FUNCTION IF EXISTS public.{FUNCTION}();
    END $$''').execute_if(dialect='postgresql'))
