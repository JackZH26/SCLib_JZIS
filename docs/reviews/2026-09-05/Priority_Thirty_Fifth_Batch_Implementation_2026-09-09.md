# Thirty-fifth batch: independently pinned review-aware ML datasets

Started: 2026-09-08. Completion audit: 2026-09-09.
Base commit: `8b3dcaed774519ebb29f8c589ab6550f9b276265` on `codex/sclib-research-v2`.
Primary continuation: [UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73),
exact-result review consumption by scientific ML workflows.

## Outcome and boundary

This batch implements a private review companion, read-only explicitly admitted
SQL capture/recheck, independent lossless offline verification, a v3 task and
dataset compiler, and a safe offline build/verify command. Negative review and
source effects apply before feature admission and preprocessing. An acceptance
does not override missing calculation, state, protocol, source-time or leakage
evidence. Independently eligible composition rows survive optional feature holds.

The operative guide is [ML_REVIEW_COMPANIONS.md](../../ML_REVIEW_COMPANIONS.md).
The original [implementation design](ML_Review_Companion_Implementation_Design_2026-09-08.md)
is retained as the preceding proposal, not an alternative API specification.

There is no new database migration, public endpoint, training job, provider call,
real scientific review, source redistribution, production backfill, deployment,
remote branch/PR publication or issue-state change in this batch. It advances
local software acceptance; it does not close the full upgrade goal or establish
a scientifically qualified real training corpus.

## Implementation layers

| New component | Responsibility |
| --- | --- |
| `api/services/ml_feature_review_companion.py` | Closed independently pinned companion, full frozen input/property inventory, complete private audit closure and negative captured-status replay. |
| `api/services/ml_review_projection.py` | Strict lossless Decimal JSON, raw SQL text hashes, 0067/0055 record parity and explicit frozen-to-current scientific projections. |
| `api/services/ml_review_source_observation.py` | Independent current source closures, compound FK/type validation, original 0056 snapshot/ledger replay and critical source-identity holds. |
| `api/services/ml_review_capture.py` | Read-only complete capture under explicit active verified admin + exact curator grant + full-audit export scope; bounded historical-versus-current recheck. |
| `api/models/ml_task_v3.py` | Closed `negative_only/1.0.0` policy on the unchanged v2 scientific task requirements. |
| `api/services/ml_dataset_builder_v3.py` | Exact direct/ancestor negative gates, raw cohort rebuilding, train-only fitting, complete source-pinned recompute verification. |
| `scripts/ml_reviewed_dataset.py` | No-network offline CLI, independently pinned inputs, stable no-alias reads and exclusive owner-only output. |

The artifact versions are `ml-feature-review-companion/1.0.0`,
`ml-task/3.0.0` and `ml-task-dataset/3.0.0`. Capture does not change the original
`research-release/1.0.0` or `ml-feature-companion/1.0.0` formats. All **17** sources
returned by the old v2 implementation provenance inventory were individually
hashed against the base commit and found byte-identical. The new compiler pins
its new transitive verifier/projection/contract sources in addition to those
unchanged dependencies. The live capture service is not misrepresented as an
offline compiler dependency.

### Complete audit without false scientific dependencies

Every frozen input remains explicit, including inputs without a 0064 source
binding and unsupported claim/Tc/RPS inputs. The relevant property inventory is
derived through existing explicit result and retained run-manifest dependencies.
Each property has two exact head observations, including null heads.

The verifier retains and checks complete canonical private requests and all
sibling decisions, subjects and predecessor/fidelity dependencies required to
replay their original identity. An unrelated property included only in the same
request does not become a feature ancestor, group or independent evidence.
Original decision bases are retained separately from current subject snapshots.
Role observations have minimal user flags and exact grant/revocation closure,
including grantors and revokers, without exporting account secrets or emails.

The independently observed current source closure and current subject must agree
on their shared scientific fields. Each source row has strict scalar domains and
complete compound foreign-key bindings. Replacing a field while retaining an
old `record_sha256` cannot hide a changed binding. Critical Paper/Work identity
changes withhold the affected input rather than relying on a still-active status.

The shared sixteen-MiB/ten-second capture budget, 200 reviewed-target limit,
200-request limit, 4,000-row audit/source bounds and version-owned parser limits
fail closed without a partial result. Twenty-one real reviewed targets are
tested independently of the twenty-item interactive request cap. A separate
20,000 held-reference output budget bounds repeated dependency audit expansion.

### Scientific and temporal boundaries

Direct input-source holds and property-scoped review holds are distinct. A direct
input B is not rejected merely because direct input A for the same property has
a source hold. An explicit strict ancestor without a source-choice edge requires
all its declared source bindings conservatively. Unrelated properties that share
a state, event or run are not automatically rejected.

Eligible composition rows and base partition decisions remain intact. `P`, `S`
and `PS` cohorts and all paired views are rebuilt from raw admitted features;
imputation/scaling are fitted only on each resulting training partition. A new
task pin legitimately changes assignment receipt hashes, not the meaning of
preserving base partition decisions.

Actual retained producer input documents with a Tc ancestor still trigger the
target-leakage gate after a scoped phonon acceptance. Actual native 0065 imports
with both 0067 scopes accepted remain excluded from the physical feature views.
The native test preserves the real extraction run/event, pending original fact
states and unknown conditions. In addition to the missing independent source
witness, the unchanged scalar validator explicitly reports missing calculation,
completed compatible producer, pressure and temperature facts. This is not a
claim that the native fixture has an independently established same-state,
source-qualified physical feature that merely needs an acceptance flag.

### Historical reproducibility is not live permission

Old companions remain reproducible after reviewer revocation, source withdrawal
or current scientific metadata change. A newly admitted recheck in a fresh
transaction detects the changed observation and refuses an old pin. The tests
also exercise independent concurrent database transactions: one stable snapshot
remains coherent, while a later transaction sees the changed source state.

Recheck does not refresh a caller's already-open snapshot or authorize training,
source export or publication. All authority flags remain strictly false. Offline
checksums establish internal consistency, not human/database authentication or
proof that no newer or omitted external record exists.

## Verification evidence

Final combined API compatibility execution: **937 passed**, **687.59 seconds**
(11 minutes 27 seconds), **exit 0**, across the exact 28 modules listed below.
The only warning was the existing FastAPI `regex` deprecation in
`routers/admin.py:83`. The guarded runner confirmed removal of only its own
disposable services and temporary test data. This run includes all final source,
projection, audit-scalar, cross-observation and negative-only policy fixes.

The entire script suite separately passed **989 tests + 36 subtests** in
**12.61 seconds**, exit 0. Scoped Ruff import/undefined-name checks and final
Git whitespace checks passed. No inherited/development/production test endpoints
were used. This is targeted integrated API acceptance, not the complete all-API
suite, Linux release-image validation or a deployment result.

Already completed independent checkpoints:

- Projection bridge: **34 passed**, 7.51 seconds, one existing FastAPI deprecation
  warning; actual PostgreSQL canonical/hash/timestamp parity, no fixture bypass.
- V3/CLI owner checkpoint: **110 passed**, 126.11 seconds, one existing warning,
  exit 0 and disposable cleanup confirmed. This includes 52 pure v3 cases,
  14 actual SQL/compiler/CLI cases and 44 CLI file-safety cases.
- Root contract/integrity checkpoint: **26 passed**, 29.94 seconds, one existing
  warning; final combined run also includes subsequent added scalar mutations.
- Source capture/observation checkpoint: **31 passed**, 103.48 seconds, one
  existing warning; real twenty-one-target capture, concurrent source updates,
  historical replay/recheck, identity changes and strict source closure cases.
- Entire script suite: **989 passed + 36 subtests**, 12.61 seconds, exit 0.
- Old compiler source preservation: **17/17 exact source hashes unchanged**.

One earlier owner run reached 110 passing test bodies but failed the teardown
safety guard with `sentinel-identity-or-lifetime-invalid` across an environment
date/time change. It is not counted as a successful run. Its runner confirmed
owned disposable services/temp cleanup, and a new guarded environment produced
the complete 110-pass exit-0 result above. No safety guard was weakened.

Early test development also exposed real existing safeguards and integration
assumptions: the capsule has no embedded release ID; PostgreSQL limits
`jsonb_build_object` to 100 arguments; declared SQL timestamps differ in notation
from normalized frozen timestamps; frozen events refuse new owned properties;
and event/property/component identities are unique. New code and synthetic
fixture assembly were corrected without editing old protocols, bypassing SQL
guards or redefining failed runs as successful.

An intermediate source checkpoint had 29 passing cases and two failures after a
temporary positive-status whitelist treated valid unknown publication status as
a hold. The whitelist was removed; the original negative-only source policy
was preserved, and unchanged tests passed in the final 31-case checkpoint.

No frontend or migration source changed in this batch. This report does not
reuse prior frontend/migration runs as if they were rerun here, and does not
claim a complete all-API or deployed-environment test result.

The final combined API selection is exactly the following 28 modules. Run from
the repository root with the guarded runner; do not use inherited application
PostgreSQL/Redis endpoints:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- \
  tests/test_ml_foundation_exporter.py tests/test_ml_feature_provenance_v2.py \
  tests/test_ml_dataset_adversarial.py tests/test_ml_coordinate_features.py \
  tests/test_ml_task_dataset_sql.py tests/test_ml_foundation.py \
  tests/test_ml_physical_feature_sql.py tests/test_ml_dataset_v3.py \
  tests/test_ml_review_projection.py tests/test_ml_reviewed_dataset_sql.py \
  tests/test_ml_frozen_provenance.py tests/test_ml_claim_visibility.py \
  tests/test_ml_foundation_schema.py tests/test_ml_feature_companion.py \
  tests/test_ml_review_companion_integrity_sql.py tests/test_ml_preprocessing.py \
  tests/test_ml_review_capture.py tests/test_ml_review_companion_contract.py \
  tests/test_ml_review_source_observation.py tests/test_ml_feature_contract_v2.py \
  tests/test_ml_composition.py tests/test_scientific_adjudication_contract.py \
  tests/test_scientific_adjudication_schema.py tests/test_scientific_result_subject.py \
  tests/test_scientific_result_effects.py tests/test_scientific_adjudication.py \
  tests/test_scientific_adjudication_operators.py tests/test_scientific_result_public_gates.py \
  -q --tb=short --show-capture=no

api/.venv/bin/python -m pytest scripts/tests -q --tb=short --show-capture=no
```

## Acceptance map and remaining delivery

| Design requirement | Local evidence |
| --- | --- |
| Exact replay and preservation | Real SQL freeze/source/review capture, full bundle recompute, 17 old source pins, full SQL state comparison. |
| Exact bindings and complete bytes | Resealed malformed inventories/heads/requests/types/contradictory sources fail; audit-only sibling's complete request remains retained. |
| No twenty-target truncation | Actual twenty-plus-one reviewed-target capture, with final rejection retained; count/byte/deadline refusal tests. |
| Exact negative propagation | Direct and full-ancestor policies, independent source choices, unrelated same-context sibling, physical/structural source holds. |
| Historical versus current | Actual role/source/scientific changes, old replay and newly captured recheck, separate concurrent sessions. |
| Scoped acceptance and native no-go | Fidelity dependency policy, real both-scope native acceptance without physical promotion, unchanged scalar exclusions. |
| Fair baseline/cohort/preprocessing | Real five-group baseline, nested paired views, training-row removal and newly fitted raw subsets. |
| Leakage/time/grouping | Original grouped/time gates preserved; real retained Tc producer dependency remains excluded; audit actor/batch never enters grouping. |
| Operational safety | Explicit private export admission, no SQL/epoch mutation, full offline subprocess build/verify with connection-blocking audit hook, safe file tests. |

Remote delivery and issue closure remain separate from these local checks. The
software slice does not authorize a push, PR, issue closure, deployment, training,
data backfill or real source redistribution. It does not broaden 0067 to all
material properties or material families, or replace the separate scientific
requirements for training/evaluating a real superconductivity dataset.

A fresh read-only backlog audit on 2026-09-09 still found **38 open issues,
including the tracker**. This is not evidence that no local work was completed;
local software acceptance, remote delivery and scientific/data release gates
are deliberately separate. The next safe local implementation priorities are:

1. **SC08 / #66:** the private source-change task enqueue/preview/execute/receipt
   interaction, scoped only to the already implemented Timeline invalidation
   action. Do not label incomplete cross-system propagation as complete.
2. **EN06 / #71:** a complete scientific-release restore drill in two guarded
   disposable databases, including retained artifacts, provenance, permissions
   and selected-generation rebuild checks, not merely core-table counts.
3. **RG03 / #69:** immutable response-level evidence/generation pins for newly
   saved answers, with honest legacy-history handling and separate current
   source holds. No fabricated reconstruction of old unpinned answers.

These are concrete remaining software slices. The real reviewed pilot (#54),
real audited baseline evaluation (#76), policy replay (#78), actual Linux image
acceptance and approved production operations remain distinct requirements;
synthetic tests cannot substitute for them.
