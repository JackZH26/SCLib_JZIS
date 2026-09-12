# Private ML run plans and independent conditional review

Batch61; schema `0074_ml_use_runs`, protocol `ml-use-run-governance/1.0.0`.
This extends the [private submissions](ML_USE_SUBMISSIONS.md) and
[source-rights registry](ML_USE_RIGHTS.md). The API remains default-off under
`ML_USE_GOVERNANCE_ENABLED`. Membership, a request, a source permission and a
run review are different records with different meanings.

## Scientific and execution boundary

A plan identifies a proposed **private baseline evaluation**, not a new
superconductivity result, an accepted scientific dataset or a public release.
All-family training eligibility still comes from the task-specific data and
dependency gates; missing or censored Tc cannot become a convenient label,
and RPS is not an observed superconductivity target.

The approval is conditional review of an exact plan and requested budget. It
does not automatically resolve source rights, assert a successful scientific
pilot, reserve hardware, start a worker or authorize fitting. It may be recorded
while source permissions remain incomplete; the live check reports those
unmet requirements separately. No numerical success or scientific acceptance
is inferred from approval count or an audit hash.

**This batch exposes no executable run endpoint.** `run_baseline_dataset`
continues to refuse execution. All responses retain `run_authorization_granted`,
`ml_training_approved`, `public_release`, `execution_environment_attested` and
`budget_reserved` as false. A completed conditional review cannot override
these gates. The later execution consumer must establish an independent
scientific pilot decision, actual isolated runtime admission and one-shot
consumption under fresh authorization/concurrency checks.

## Owner: exact plan, not a mutable configuration

The authenticated owner needs current verified admin status, an explicit
curator grant and an explicit ML requester grant. New plans must use the same
owner and exact grants as the original retained submission; regranting a role
does not silently rebind old inputs.

1. `GET /v1/ml/use/runs/requester-access` checks current admission.
2. `POST /v1/ml/use/runs/context` accepts only submission UUID, record SHA-256
   and inventory SHA-256. It returns pinned task/config/package/prepared hashes,
   owner grants, retention expiry and fixed-path source/host observations.
   It does not return uploaded source bodies or choose a budget for the user.
3. `POST /v1/ml/use/runs/plans` supplies these pins, a new request key and
   integer budgets. `cpu_seconds` and `wall_seconds` are 1–1800, with CPU no
   greater than wall time; `memory_mib` is 128–4096. The profile is fixed to
   `private-cpu-baseline/1.0.0`, a proposed single-process CPU workflow.
4. The default `dry_run: true` performs the SQL insert inside a rolled-back
   savepoint and returns the intent hash, not a durable plan ID. Commit requires
   a separate `dry_run: false` call with `expected_intent_sha256` from preview.
   Changes in inputs, budget, role pins or observed source/host pins require
   a new preview. No client-supplied JSON runtime claim, command, path, network
   destination, GPU job, provider API or arbitrary code is accepted.

Plans are immutable. A changed budget/configuration needs a new plan and its
own approval; a review cannot transfer to another plan or submission. Input
expiry is the original seven-day retention boundary, not a sliding extension.

## Independent approver

The reviewer needs current verified admin status, an explicit curator grant
and an explicit ML `run_approver` grant, on a different account from the owner.
An admin or source-rights reviewer is not automatically a run approver.

- `GET /v1/ml/use/runs/approver-access` checks admission.
- `POST /v1/ml/use/runs/inspect` accepts an exact plan UUID and record hash.
  It returns only the plan metadata and the current review head, including
  historical source/host documents. This is not a live source/permission check.
- `POST /v1/ml/use/runs/decisions` follows preview/commit, with an original
  request key, exact plan hash and exact predecessor ID/hash (both null only
  for a first decision). Decisions are `approve`, `deny` or `revoke`.
- Approval requires a reason code, evidence-document SHA-256 and explicit
  future expiry no later than original input expiry, retained input bytes and
  the owner's still-active exact grants. The evidence hash records the human
  review's external evidence reference; it does not authenticate that evidence.
- Denial/revocation must have null expiry. Revocation must follow an exact
  approval. Neither operation requires the owner's continued membership or
  retained inputs, so disabling an owner or purging inputs cannot prevent
  protective withdrawal. The independent approver must still be admitted.

The database enforces exact parent/intent/record hashes, independent accounts,
current role grants, expiry, predecessor heads and immutable history. SQL callers
are trusted database principals: knowing a user UUID or a hash is not API
authentication, legal authorization or proof of real-world independence.

## Recovery and current readiness

`POST /v1/ml/use/runs/plans/outcome` and `/decisions/outcome` accept the original
request key and intent SHA-256 under the original actor. They return historical
receipts. Current admission is still required, but a current replacement grant
can recover old history without making that old grant current again.

A committed identical-key retry is a no-op, including after a later review or
input purge; a conflicting intent is refused. Unknown commit replies carry
`X-Operation-State: unknown`. Recover before deciding whether an explicit exact
retry is needed. A 404 recovery result means not observed in that snapshot, not
proof of rollback. No automatic retry is provided.

`POST /v1/ml/use/runs/check` is **owner-only** and accepts the exact plan ID/hash.
It retrieves the bounded retained inputs internally and launches the existing
actual reconstruction worker under the authenticated owner's identity. The
independent reviewer cannot borrow that identity or request private byte export.
After the worker completes, a fresh read-only snapshot rechecks:

1. Original owner grants, retention and byte-for-byte input equality.
2. Full source/review/label currentness and the exact dependency inventory.
3. Purpose-specific permission coverage for every row representation/artifact.
4. Exact plan/prepared-input binding, latest independent review, expiry and
   the original approver's still-current grants.
5. Equality with the plan's selected on-disk implementation and observed host
   fingerprints. Missing currentness/rights or mismatched fingerprints block
   readiness; new grants cannot revive an old approval.

The result separates `conditional_run_approval_current`, nested
`source_coverage`, `fingerprints_match` and explicit blockers. Even when those
observations match, this version reports `ready_for_execution: false` and
`decision: not_authorized` until the remaining execution gates are implemented.
The response is a snapshot, never a reusable permission lease; state can change
immediately after it returns.

The earlier declaration-only preflight and source-rights endpoints do not
consume these approvals. Their run blocker is now
`independent_run_approval_not_checked`, rather than claiming the registry is
unavailable. They remain non-authorizing; their previous receipts are historical.

The implementation fingerprint covers a listed subset of on-disk modules. The
runtime fingerprint records Python/platform properties, numerical policy and
lockfile hash. **Neither proves installed dependency versions, loaded-code
identity, a complete release image or the future execution environment.** The
fixed requested budgets are not advertised as enforced resource limits here.

## Storage and operational limits

`ml_use_run_plans` and `ml_use_run_decisions` are append-only, reject updates,
deletes and truncation, and retain user references for audit preservation.
The migration creates no roles, plans or approvals. Downgrade locks both tables
and refuses if either contains history. Empty downgrade/re-upgrade must preserve
all older rows; rehearsal must populate 0074 only after independently testing
the older history-preservation guards.

Initial ceilings are 10,000 total plans / 20 per submission and 100,000 decisions
/ 100 per plan for new non-revocation decisions. Protective revocations are
exempt from decision-count admission caps. These are bounded admission defaults,
not throughput measurements. Both stored host documents are limited to 16 KiB.

The API uses authenticated server-side sessions, private/no-store responses,
strict closed JSON requests up to 8 KiB, a five-second body deadline and bounded
stream parts. It shares the private ML request concurrency gate and a 100-second
route deadline; SQL statements have a five-second timeout. Writes use the shared
publication fence, SERIALIZABLE transactions and commit-time session checks;
reads use fresh REPEATABLE READ, READ ONLY snapshots.

Production rollout, real role provisioning, actual reviewer decisions,
evidence-document storage, owner/approver browser controls and guarded execution
remain separately gated work. Test fixtures are synthetic and confer no real
rights or scientific approval.
