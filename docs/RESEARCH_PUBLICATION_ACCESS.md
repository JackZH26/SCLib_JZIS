# Research access and bounded metadata publication

Issue: ML07 / #68. Schema: `0055_research_publication`.
Public policy: `research-public-metadata/1.0.0`.

This batch closes anonymous access to raw research records and adds a distinct,
reviewed metadata-publication path. It does not release scientific values,
training examples, source files or unrestricted manifests. It does not close
ML07's structured-data/export, real-rights or operational acceptance gates.

## Access boundary

The existing claims, material-claims, work, source-snapshot, dataset-snapshot and
dataset-manifest routes are internal research reads. They require a valid
JWT/browser session, active verified account and an explicit unrevoked research
role grant. Ordinary members, API-key-only credentials and legacy `is_admin` or
`is_reviewer` flags are insufficient. Existing scientific filters and pagination
remain available to authorized operators. There were no frontend consumers of
these raw routes in the reviewed local checkout.

`ML_FOUNDATION_PUBLIC_ENABLED=false` continues to disable both raw research and
public metadata reads. Enabling it never creates roles, permissions, reviews or
publications. No deployment or production flag change was performed.

## Explicit accounts and append-only decisions

Seven additive tables separate technical concurrency state from authority:

| Table | Purpose |
| --- | --- |
| `research_publication_epoch` | Shared SERIALIZABLE writer fence, not evidence |
| `research_role_grants` | Administrator-issued curator/reviewer/publisher grants |
| `research_role_revocations` | Append-only revocation of a particular grant |
| `research_publication_permissions` | Exact capsule/pin-bound metadata permission decisions and explicit successor chains |
| `research_publication_proposals` | Immutable capsule-bound public metadata body and hash |
| `research_publication_reviews` | Disclosure approval/rejection of the exact proposal hash |
| `research_publication_actions` | Exact approved-review-bound publication or withdrawal |

Administrators manage grants but do not implicitly receive research read,
review or publication authority. A curator proposes, a different reviewer
assesses disclosure, and a third distinct account publishes. Dual role grants
cannot waive these account-identity checks. This is **account separation**, not
proof that three accounts represent three independent natural persons or that
a scientific finding has been independently replicated.

All six history tables reject UPDATE, DELETE and TRUNCATE. New governance
writes require SERIALIZABLE isolation and a shared nonblocking advisory lock /
epoch update; stale transactions fail rather than selecting a permission head
from an old snapshot. Database guards independently validate roles, exact
capsule/pin/review bindings, complete permission coverage, closed public field
shapes and opaque-reference hashes. They do not authenticate an HTTP identity
from SQL arguments or prove licensing rights from a checksum.

The internal service entry points are `grant_role`, `revoke_role`,
`decide_permission`, `propose_publication`, `review_publication` and
`publication_action` in `services/research_publication.py`. They require a
trusted caller to supply its already-authenticated actor identity. There is
no public or internal HTTP write endpoint, upload endpoint, automatic role
provisioning or curator UI in this batch. The authenticated browser workflow
and independently reviewed human identity/rights process remain UX02 and
operational work, not functionality supplied by constructing a Python dict.

Every write defaults to a rollbackable dry run and owns only a savepoint.
Successful live calls never commit the caller's outer transaction. Busy or
serialization failures require a full outer rollback and fresh attempt.
Duplicate grants, permission successors and publish/withdraw actions fail
closed instead of silently appending a second active decision. This is not a
generic idempotent job scheduler or delete-based recovery mechanism.

## Permission and projection contract

Every pin in the ML04 capsule requires its own current `metadata_only` permission
decision, including rows whose raw payload is excluded. Decisions bind the
capsule hash, exact table/key and full-row hash, scope, license code, basis/reason
codes, actor and actor-grant identity. A new decision explicitly supersedes the
current predecessor; timestamps do not pick an ambiguous winner. No permission
is inferred from arXiv/APS/NIMS source names, publication tier or repository
license. Missing, denied, stale or unknown permissions block the affected body.

Supported license identifiers are CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0 and
`permission-on-file`. These record reviewed assertions; they are not automated
legal determinations, external permission-document verification, attribution
compliance certificates or authorization to export paper text. A real operator
must independently establish and retain the applicable rights evidence before
issuing a decision.

Proposal creation independently verifies the retained ML04 capsule and actual
supplied artifact bytes, then constructs an exact typed public body. Callers do
not supply arbitrary public JSON for publication. The body contains:

- Fixed version, metadata-only scope, capsule hash and opaque dataset reference.
- Sorted table/object references and exact permission IDs/hashes/license codes.
- Exact counts for the fixed 28-table inventory and a fixed exclusion manifest.
- `scientific_acceptance=false` and `ml_training_approved=false`.

There are no material/formula/raw source identifiers, source locators, URIs,
reviewer/account identifiers, scientific values, training features, raw records,
coordinates, external artifact bytes, run settings or flexible JSON fields.
Internal nested JSON is excluded wholesale, not scanned with a blacklist or
exported merely because its checksum matches. Unknown nested public fields
remain invalid even after a caller recomputes every checksum.

Opaque references bind the version, capsule hash, table, internal key and row
hash. They support equality/integrity checks, not guaranteed anonymization or
public resolution of restricted source identities. More useful public scientific
records and source links require a new versioned typed projection, appropriate
attribution and separate scientific/rights review; this batch does not silently
claim that unresolved ML labels are ready for publication.

The legacy `export_ml_foundation_snapshot.py` remains a **restricted internal
source-capture tool**, with `distribution_status=not_cleared_for_public_release`.
Its nested raw records have not been retroactively cleared for public egress.
Old export/capsule bytes and frozen specifications were not rewritten.

## Public reads and current withdrawal behavior

With the feature switch enabled:

- `GET /v1/ml/releases` lists only currently admitted publications and counts
  that same filtered set. Private drafts do not consume the public scan budget.
- `GET /v1/ml/releases/{publication_id}`, `/manifest` and `/download` return the
  same canonical JSON bytes with `X-Public-Manifest-SHA256`.
- No alias redirects to an internal artifact URI or implements weaker download
  authorization. Raw dataset/capsule IDs are not publication IDs.

Every request uses a dedicated REPEATABLE READ, read-only transaction and
rechecks immutable payload/review bindings, current permission heads, current
actor grants/accounts, source/material governance and ML04 notices. Source file
bytes were checked during proposal creation; they are not re-fetched or claimed
to be reverified on each metadata read. Admission reflects the request's coherent
database snapshot, not a guarantee against a change after the response is sent.

Any negative disclosure review permanently holds that proposal, including after
publication. A later positive review cannot erase it; a newly reviewed proposal
is needed. Publication withdrawal or any ML04 correction/withdrawal/supersession
notice also removes availability. Permission changes, role revocations,
unverified/inactive actor accounts and current source/material holds prevent
access without rewriting historical body bytes. Withdrawal stays available
after a source or permission hold. A new proposal, not republishing the same
withdrawn ID, is the recovery path.

These endpoints and raw research endpoints return `private, no-store`, including
errors. There is no research-publication cross-request cache, ETag shortcut or
304 path. Conditional request headers cannot bypass governance checks. A held,
draft, nonexistent or malformed publication returns generic 404; an unavailable
registry or exhausted public inventory/request budget returns generic 503.
The current RPS filesystem publication contract is a different subsystem and
is not retroactively governed by these tables; its later integration belongs
to DR02/SC08.

## Resource and retention limits

The capsule retains its 100-example / 1,000-row / 200-artifact limits. Public
metadata has at most 1,000 receipts, a database expanded-JSON cap of 1 MiB and
a portable verifier cap of 8 MiB. Current user checks fetch only identity and
authorization flags, not profiles/passwords. Permission grant checks are batched.

Live material/ancestor capture is checked before full-row transfer: at most
1,000 rows, 4 MiB combined expanded JSON, 5,000 records and bounded ancestry.
The shared scientific visibility adapter still evaluates current parent/source
holds. Size checks bound client work, not PostgreSQL TOAST serialization CPU.
Public reads have a 10-second asynchronous request budget, 5-second SQL statement
budget and at most 100 candidate published/nonwithdrawn proposals; overflow
fails without returning misleading partial counts. These are defensive bounds,
not measured production performance claims or hard CPU deadlines.

Actor foreign keys preserve audit references and can prevent physical deletion
of an account that participated in this history. Account deletion needs a clear
409 response and separately reviewed deidentification/retention handling, not
automatic history deletion or an unhandled foreign-key error. This is a stated
operating limitation, not a blanket legal retention policy. Real-data rollout
must resolve the account/privacy workflow; ordinary unrelated accounts keep
their existing deletion behavior.

## Offline verification and release gates

Save the exact canonical public response as `public-manifest.json` and retain
its expected SHA-256 independently:

```bash
api/.venv/bin/python scripts/verify_public_research_release.py \
  --manifest /absolute/local/public-manifest.json \
  --expected-public-sha256 '<independently-pinned-sha256>'
```

The tool is database/network-free and rejects unsafe paths, symlinks, hardlinks,
nonregular files, capture drift, oversized inputs, duplicate JSON keys,
nonfinite values, extra nested fields and inconsistent identities/counts. It
does not authenticate a reviewer, recheck the internal capsule/source bytes,
or establish current public availability. A new self-consistent hash does not
create permission or scientific authority.

Before any real publication: validate the intended deployment/schema/image,
database/runtime privileges, real actor identities, source metadata rights,
role provisioning, review process, privacy/retention handling and reproducible
staging withdrawal/rollback. Keep scientific-value and ML training export off
until ML05/ML06 and the human ML08 pilot gates are satisfied. No production
migration, role grant, source redistribution or website release occurred here.
