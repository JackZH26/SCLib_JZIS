"""Purpose-specific source ANN budget, preserving every prior policy identity."""
import hashlib
import json

import sqlalchemy as sa

from migration_history.retrieval_backend_v2 import guard_statements
from migration_history.retrieval_policy_v3 import SUPPORTED_POLICIES as PRIOR_POLICIES

POLICY = {**PRIOR_POLICIES[-1][0],
    'version': 'sclib-pgvector-query-policy/4.0.0',
    'source_ef_search': 256, 'source_candidate_pool': 257,
    'source_budget_selector': 'complete-stored-source-batch/1.0.0',
    'filter_predicate': 'present-bounds-and-nonempty-exclusions/1.0.0'}
POLICY_SHA256 = hashlib.sha256((json.dumps(POLICY, sort_keys=True, indent=2)+'\n').encode()).hexdigest()
assert POLICY_SHA256 == '51b1c348b6f22039ac76cfd7a7cc3230fe12d6445740cfb3c7bec66748504832'
SUPPORTED_POLICIES = (*PRIOR_POLICIES, (POLICY, POLICY_SHA256))
FUNCTION = 'sclib_retrieval_policy_build_v4'
TABLE = 'retrieval_backend_builds_v2'
TRIGGER = 'retrieval_backend_v2_insert'


def statements():
    source = next(sql for sql in guard_statements()
                  if 'CREATE FUNCTION public.sclib_retrieval_backend_insert_v2()' in sql)
    old_policy, old_sha = PRIOR_POLICIES[0]
    original = (f"OR NEW.policy IS DISTINCT FROM '{json.dumps(old_policy)}'::jsonb\n"
                f"            OR NEW.policy_artifact_sha256<>'{old_sha}'")
    alternatives = ' OR '.join(
        f"(NEW.policy='{json.dumps(policy)}'::jsonb AND NEW.policy_artifact_sha256='{digest}')"
        for policy, digest in SUPPORTED_POLICIES)
    assert source.count(original) == 1
    source = source.replace(original, 'OR NOT ('+alternatives+')').replace(
        'FUNCTION public.sclib_retrieval_backend_insert_v2()', f'FUNCTION public.{FUNCTION}()', 1)
    return [source, f'DROP TRIGGER {TRIGGER} ON public.{TABLE}',
            f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()']


def register(metadata):
    for sql in statements():
        sa.event.listen(metadata, 'after_create', sa.DDL(sql.replace('%','%%')).execute_if(dialect='postgresql'))
    sa.event.listen(metadata, 'before_drop', sa.DDL(f'''DO $$ BEGIN
      IF to_regclass('public.{TABLE}') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS {TRIGGER} ON public.{TABLE};
      END IF;
      DROP FUNCTION IF EXISTS public.{FUNCTION}();
    END $$''').execute_if(dialect='postgresql'))
