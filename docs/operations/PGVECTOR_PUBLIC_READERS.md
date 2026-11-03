# Public retrieval integration

This is unreleased implementation work. Production remains on the Google
backend. Setting an environment flag is not authorization to switch production.

`RETRIEVAL_BACKEND=google` is the default and preserves the existing route and
startup behavior. `pgvector` selects one process-owned `ContentRetriever` for
Search, Ask and Similar. Request input cannot select a database, relation,
content ID, build ID or backend. There is no implicit Google fallback in this
mode, including during startup, provider failure or authority change.

Startup checks the exact application schema before creating background writers,
loads the SQL-authoritative activation pin and explicitly prepares the matching
physical projection. One dedicated ANN engine has four connections and no
overflow; embedding/provider work holds no caller-owned SQL session. Shutdown
awaits reader cleanup and disposes this engine without disposing the shared
metadata engine. The deployment must provision pgvector, pg_prewarm, roles,
grants, a sealed validated build and genuine accepted activation evidence before
admission. The API never installs extensions or grants itself privileges.

`/readyz` and dependency health check the current authority, server boot and
prepared physical projection in a bounded probe. They do not warm relations on
a request. A changed activation or restarted database requires explicit
preparation before this process can serve that build. Liveness remains separate.

Search retains lexical, formula, scientific filters, redaction and presentation
through the shared presenter. Ask retains the existing source admission,
packing, generation budget, extractive fallback and final currentness checks.
Numeric requests use exact immutable extraction parents without model calls;
mixed requests keep extraction results and original passages separate. Native
and legacy originals cannot create extraction parents or reviewed scientific
links. Saved v2 answers use the separate content-bound receipt path; v1 history
bytes and replay remain supported.

Similar uses at most 20 stored source vectors, with one shared three-second ANN
budget and four SQL slots. It hydrates candidates in bounded batches, retains
the prior mean-distance scoring, excludes every source-paper member and checks
all source and contributing winning members in a new common snapshot before
publishing. Failure never publishes partial candidates.

## Verification and remaining release gates

Runtime tests run only in freshly owned services via
`scripts/run_disposable_tests.py --pgvector --suite api`. The dedicated Linux
pgvector CI job explicitly includes the four public-reader test modules; ordinary
non-vector shards may skip them. Real ASGI tests exercise all three routes,
owner history, unavailable readiness and pool/lifespan ownership. Native/legacy
mixed original fixtures are synthetic engineering checks, not scientific gold.

Production cutover still requires complete stable-head CI/schema rehearsal,
real-corpus filtered and full-service load trials, human relevance and expert
review, native new/revised-paper publication and queue replay, coordinated signed
images/schema/roles/standby, and verified recovery. Large future native scientific
collections must also resolve the explicitly bounded complete-inventory strategy.
Keep ingestion paused until its publication path is migrated and verified.

Retain APS archives until the user's explicit deletion instruction. Keep the
current Google deployment until the approved seven full stable days after
cutover with fallback disabled. Permanent index/endpoint deletion is outside
this implementation's authorization.
