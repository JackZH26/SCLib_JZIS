# Independent, purpose-specific ML rights review

Batch59; `ml-use-rights/1.0.0`, migration `0073_ml_use_rights`.
The registry records an independently authenticated reviewer's documented
permission decision for **one exact resource in one exact private request**.
It is separate from public metadata/RPS publication, scientific adjudication,
run approval and model execution. `ML_USE_GOVERNANCE_ENABLED` stays off by default.

## Scientific and authorization scope

An intake request already pins eight original files, the reconstructed dataset,
task/configuration, reviewed feature/label companions and the full recaptured
dependency inventory. See [private submissions](ML_USE_SUBMISSIONS.md).

Each inventory row is one resource, retaining **all** its distinct current and
historical representations, their encodings, container hashes and origins.
Each inventory artifact digest is another resource. A resource ID is the SHA-256
of the canonical object `{"kind":"row|artifact","entry":<exact inventory entry>}`;
the actual kind is either `row` or `artifact`, not the literal string `row|artifact`.
Row/byte resources are not interchangeable. A subject-membership hash is not a
standalone row checksum. Repeated representations and citations do not become
independent scientific support. No resource is omitted because it is an unused
feature, internal audit row, indirect dependency, inaccessible source or
historical record. This conservative scope may require substantial review.

The exact submission hash, inventory hash, resource ID and fixed
`private_baseline_evaluation` purpose bind every decision. Decisions cannot be
borrowed from a different dataset/request or from public RPS permissions. This
inventory covers the registered and recaptured dependency graph, not a proof
that unknown external dependencies do not exist.

## Reviewer and evidence requirements

A rights reviewer needs a current active, email-verified administrator account,
an explicit curator grant (the existing private-audit boundary), and an explicit
ML `rights_reviewer` membership. Site administration, a legacy reviewer role or
ML requester membership alone is insufficient. The reviewer must be a different
account from the submission owner. Account distinction is enforceable; human
identity, expertise, independence outside the system and legal competence are
not established by account IDs.

An `allow` decision must include:

- One of `documented_license`, `documented_permission` or
  `documented_institutional_policy`.
- `evidence_sha256`: the exact hash of the rights document independently held
  and inspected by the reviewer/operator.
- An explicit integer UTC expiry in Unix seconds, strictly after the database
  clock and no later than the submission's original seven-day input expiry.

This increment stores the evidence **hash**, not the document or its text, and
does not fetch, parse, authenticate or legally interpret that document. An
operator must maintain an access-controlled, resolvable evidence record outside
this ledger and must not declare an allow without the requisite permission.
Hashes are commitments, not signatures, source licences or proof that evidence
was inspected. Responses explicitly retain
`legal_evidence_independently_verified: false`; the software does not invent a
licence or automatically promote a source's public availability into ML rights.

`deny` records unresolved or withdrawn rights and can be the first decision.
`revoke` requires an exact current `allow` predecessor. Both use
`rights_unresolved` or `withdrawn`, and have no expiry. Denial/revocation can be
recorded even after input purge, owner disablement or expiry; withdrawal must
not depend on those positive eligibility conditions. A different qualified
independent reviewer may revoke another reviewer's decision.

## Authenticated endpoints

All endpoints are private/no-store, use fixed English errors, and return no raw
input bytes or source text. JWT/browser authentication and existing Origin/CSRF
rules apply; API keys do not substitute for a user session. Required role checks
precede body processing, and session/current-role checks repeat at the operation.

| Endpoint under `/v1/ml/use/rights` | Caller and behavior |
| --- | --- |
| `GET /access` | Rights reviewer: own current exact curator/rights membership IDs only |
| `POST /inspect` | Independent rights reviewer: exact submission ID/hash and inventory hash; 25 resources per page, exact historical head and current reviewer/expiry status |
| `POST /decisions` | Independent rights reviewer: rollback-only preview or exact intent-pinned commit; one resource per request |
| `POST /outcome` | Current rights reviewer: own exact original request key and intent hash; historical recovery only |
| `POST /check` | Submission owner with current admin/curator/requester admission: original submission key/hash; actual retained-input reconstruction followed by fresh source and rights checks |

The inspection body contains only `submission_id`, `submission_sha256`,
`inventory_sha256` and optional `after` (the previous page's last resource ID).
No global submission/user directory is introduced. Resource membership is
immutable and pinned across pages; permission heads can change between page
reads, so the pagination is not a reusable authorization snapshot.

For a decision, explicitly provide the following closed fields:

```text
submission_id, submission_sha256, inventory_sha256, resource_id,
purpose = private_baseline_evaluation,
reviewer_grant_id, curator_grant_id,
request_key, decision, basis_code, evidence_sha256, expires_epoch,
supersedes_id, supersedes_sha256,
dry_run, expected_intent_sha256
```

For a root, both predecessor fields are null. Otherwise both must match the
current head. Start with `dry_run: true`; the service executes the real insert
and SQL constraints inside a rollback-only savepoint. Review the returned exact
intent (including identity, purpose, evidence, expiry and predecessor) and retain
its hash independently. Commit the unchanged fields with `dry_run: false` and
`expected_intent_sha256` set to that original hash. Changing the decision or
renewing it requires a new explicit key/preview bound to the exact current head;
expiry cannot be extended by replay. There is no bulk auto-allow operation.

The authenticated actor is never a client body field. The durable record hash
covers every typed decision field, its UUID and intent hash. Creation time is
server-assigned display metadata; the hashed explicit expiry and predecessor
chain determine validity rather than timestamp sorting.

## Recovery versus live permission

`POST /outcome` takes only `request_key` and `expected_intent_sha256`. Outer
`committed: true` denotes a durable decision or exact recovery. Nested service
`committed` remains false because services do not commit their caller's outer
transaction. Preview returns no durable decision ID.

If a commit reply is lost, 503 may carry `X-Operation-State: unknown`. Do not
assume rollback or replace the key. Recover the original intent or repeat the
identical request. Old allow receipts remain recoverable after revocation,
expiry or regrant if the caller still has current review access. Replay is a
database no-op and cannot restore eligibility. A missing outcome is only
not-observed in that snapshot. Another reviewer cannot recover the original
actor's request by copying its key/hash.

`POST /check` accepts the **owner's submission** key and intent hash, not a
rights decision key. It retrieves unexpired retained bytes internally, runs the
actual bounded reconstruction worker, then in one fresh read-only snapshot:

1. Rechecks owner/session and exact submission grants, retention and byte identity.
2. Rechecks the full original source/review/label observations and compares the
   current inventory to the stored exact inventory. A retraction/change cannot
   be waived by a rights decision.
3. Checks every resource's exact current decision head, expiry and issuing
   reviewer's current account and exact curator/rights grants.
4. Emits separate counts for unreviewed, denied, revoked, expired,
   reviewer-unavailable and recorded-allow resources, a deterministic coverage
   hash, and at most 25 blocked-resource headers.

`recorded_permissions_complete` means every scoped resource has a current
recorded allow. `source_permission_granted` is true **only for this exact purpose
and inventory** when that coverage and the fresh source/scientific negative gates
both pass. It is a point-in-time observation of documented decisions, not a
legal conclusion, public release, scientific acceptance or authorization lease.
`run_authorization_granted`, `ml_training_approved` and `public_release` remain
false, and `training_execution` remains disabled. Unknown external dependency
completeness is not promoted to true. A later run approver/consumer must repeat
these checks under its own concurrency boundary; it cannot trust this HTTP
response as a durable execution credential.

The older declaration/currentness endpoints still do not consume this registry.
Their blocker is now `purpose_specific_permissions_not_checked`; they must not
claim a registry is unavailable or grant rights from reconstruction alone.

## Private browser review workbench (batch60)

The English-only dashboard entry **ML source rights** opens
`/dashboard/research/ml-rights` (under the configured site base path). It uses
the same default-off API and does not provision users, grant memberships or
change production flags. Site admin status alone does not enable the controls.

1. Refresh reviewer access. Obtain the exact submission UUID, submission record
   SHA-256 and inventory SHA-256 from the approved private handoff, then inspect
   the inventory. No global request directory is introduced.
2. Review one resource at a time. Pages contain 25 resources and pin the same
   inventory, count and input expiry. Every row representation, encoding,
   temporal scope, container hash and origin remains visible in expandable
   metadata. Artifact digests remain separate resources. No raw source bodies,
   clickable untrusted source URLs or automatic downloads are rendered.
3. Explicitly choose allow, deny or revoke. Allow requires a documented basis,
   evidence-document hash, reviewer declaration and a future UTC Unix-second
   expiry within original retention. No expiry, evidence or permission is
   guessed. Denial/revocation do not require an unexpired input; revocation
   targets an exact previous allow. The server rechecks the current head.
4. Preview performs the actual rollback-only SQL operation. The browser checks
   the exact original intent hash, account, grants, resource, purpose, evidence,
   expiry and predecessor before enabling a separate commit action. Changing
   any decision field invalidates the preview and reviewer declaration.
5. A lost or unverifiable commit reply locks new decisions. Recovery uses the
   original account/key/hash in a private POST read, not a URL query string.
   A missing outcome is not rollback. An explicit retry can reuse the identical
   original write; no automatic write retry, background polling or bulk allow
   is implemented. Committed/recovered receipts are labeled **historical**.

After reload, manually enter the original rights decision key and intent hash
under the original reviewer account to recover the record. Retain these in the
approved private operation log before leaving. Drafts and evidence references
are not saved to browser storage. Session notifications erase displayed private
data and pending write bodies, and ignore stale asynchronous responses; only an
opaque in-memory original-account recovery locator is retained until resolved.
An unrelated account cannot view or act on it. Server session/role checks remain
authoritative even when a browser does not receive a session notification.

The client verifies the backend's exact integer-only canonical HTTP encoding,
closed response fields, negative authority flags, resource digests and both
decision/intent hashes. It rejects duplicate keys, unsupported encodings, extra
fields, fractional numeric aliases, unsafe integers, mismatched pages and stale
previews rather than rounding or repairing them. Inspection is bounded to
1,100 KiB, all requests to 8 KiB, and transport to 30 seconds/4,096 stream parts.
Requests use the configured fixed API origin, cookies, no-store and redirect
refusal. Error bodies are not displayed. These checks are integrity defenses,
not legal verification or a substitute for server authentication.

This reviewer page deliberately does not call the owner's `/check` as the
reviewer, authorize execution, fit a model or promote a historical allow into
current source validity. The owner-side live-check UI, durable evidence-document
resolution and independent run-approval/consumption integration remain separate
work. See the [batch60 verification report](reviews/2026-09-05/Priority_Sixtieth_Batch_Implementation_2026-09-13.md).

## Storage, limits and rollout

`ml_use_rights_decisions` is append-only. One root per submission/resource, one
successor per decision and one request key per actor prevent forks/replay drift.
SQL independently enforces exact submission/inventory membership, purpose,
declared reviewer separation/current roles, grant/expiry/input eligibility for
allow, exact predecessor and record/intent hashes. The shared nonblocking writer
fence and SERIALIZABLE transaction boundary serialize competing decisions.
SQL checks do not authenticate arbitrary SQL callers; runtime credential
restrictions and application authentication remain required.

Updates, deletes and truncation are refused. Actor foreign keys participate in
the account-erasure hold. Any history, including a denial or revoked/expired
allow, blocks a 0073 downgrade. An empty downgrade removes only this ledger and
its function and preserves all older records. The migration provisions no users,
roles or decisions. Startup must use the exact new head even when the feature
flag is disabled; no production migration is performed here.

Limits: 8 KiB closed request bodies, five-second body and SQL statement bounds,
4,096 stream parts, two shared nonblocking private-inspection slots per process,
100-second outer deadline (including the bounded reconstruction worker), and
1,100 KiB response ceiling. At most 8,000 resources are covered. New non-revocation
decisions stop at 32,000 history rows per submission or 100,000 globally;
revocations are still permitted at these caps. These are initial admission
ceilings, not a production capacity measurement or a distributed rate limit.

The core private review UI is delivered in batch60 above. Rights-document
storage/resolution, owner-side live-check UI, independent run approval and a
genuinely human-reviewed ML08 pilot remain required integrations.
This batch does not enable the flag, change real memberships, sign any actual
rights decision, train a model, publish predictions or deploy the service.
