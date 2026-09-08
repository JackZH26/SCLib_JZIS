# RPS structured-distribution governance

Version: `research-distribution/1.0.0`; additive schema revision
`0063_research_distribution`. Scope: `rps_structured_bundle` only.

## Outcome and limits

Discovery's released RPS data now requires an actual database-backed disclosure
decision in addition to the two existing deployment configuration pins. A JSON
`public` flag, source URL, declared license, matching checksum or high RPS score
does not grant publication authority. Static `/discovery/rps/policy` remains
public because it contains the scoring policy, not a released research dataset.

This is a disclosure-governance boundary, not a superconductivity classifier or
scientific acceptance process. The unchanged RPS score ranks research attention,
not superconductivity probability. A valid provenance binding does not establish
that a cited result applies to a candidate's phase, pressure, composition or
experimental state. Contextual, opposing and general execution evidence can
legitimately refer to other states; adjudicating relevance remains a separate
scientific review. None of these controls makes cross-family score calibration
empirically established.
Distribution admission also does not establish the truth of each declared RPS
artifact availability date or certify a historical known-by cutoff. Temporal
backtests and task-specific ML compilation require their own exact source-time
checks; a distribution receipt must not be reused as evidence of leakage-free
historical availability.

`scientific_acceptance` and `ml_training_approved` remain false. Rights review
records are attributable assertions by authenticated accounts, not an automated
legal determination. Three distinct accounts do not prove three distinct people
or absence of organizational conflicts. The private ML task datasets introduced
in the preceding batch are not public RPS bundles and are not released here.

The frozen 0054 capsule and 0055 `metadata_only` publication contracts are
unchanged. Existing permissions in that metadata-only scope cannot authorize
these structured RPS bundles or subsequent model training.

## Exact artifact and source bindings

Registration independently pins the RPS release, its complete existing public
bundle, and a new `research-distribution-bindings/1.0.0` document. The complete
original release must exactly equal the release carried in the verified public
bundle. Its existing typed public contract rejects private reviewer fields,
unknown nested fields and unrestricted source-payload fields. Allowed prose still
requires genuine disclosure/consent review: it is not automatically secret-scanned,
and a portable consent declaration does not authenticate the consenting person.

Every RPS artifact is bound, including material/state descriptors, profile
assignments, rubrics, execution templates, actions, template reviews and other
reviews—not only the evidence attached to a displayed row. A binding has the
original artifact ID, kind and hash, an explicit identity where applicable, and
one of these roots:

| Root | Database authority and actual-byte verification | Deliberate restriction |
| --- | --- | --- |
| `source_capture` | Actual 0052 pinned source revision and capture, exact hashes and bytes, accepted Paper-to-Work mapping, matching provider version | Literature evidence only; title, URL and locator prose do not prove entailment |
| `frozen_result` | Actual 0054 release with exact claim/property row, verified complete capsule and artifact bytes | Every row in the complete capsule enters the permission inventory; curation and calculation must match the actual event origin |
| `internal_artifact` | Actual verified EvidenceArtifact holding the canonical complete original RPS artifact, including its own hash | Non-evidence descriptors only; cannot turn a free-form evidence declaration into a verified source |

Material and state bindings also require exact current database row IDs and
row hashes. Formula/family, material-to-state association, pressure status/value
and temperature role/value are checked. Finite numeric `0` and `0.0` represent
the same physical value; booleans and missingness do not. IDs are never inferred
from a matching formula. Multiple phases/states can share a formula.

The trusted service reads the dependency rows itself. Caller-supplied row JSON
is not accepted as a database observation. It follows the validated live roots,
their outgoing dependencies and the Paper-to-Work mapping; frozen roots include
their entire independently verified capsule. A conflicting projection of the
same `(table, row_id)` rejects registration. Targets are deduplicated by exact
identity and hash, not by title or formula.

The private inventory contains every full pinned projection and a per-artifact
list of dependency IDs. This inventory is not returned by public Discovery
routes. Its portable authority flags remain false; current database admission
is a separate live service observation, not a self-authenticating JSON claim.

## Persistent records

Six additive tables implement the new scope:

| Table | Purpose |
| --- | --- |
| `research_distribution_epoch` | Ordered transaction fencing with the existing integrity, publication and source-lifecycle guards |
| `research_distribution_packages` | Exact release/bundle/binding/inventory pins and accountable curator proposal |
| `research_distribution_dependencies` | Complete normalized targets with actual foreign keys to all supported source/result identities and referenced capsules |
| `research_distribution_permissions` | Append-only purpose-specific allow/revoke chain for each dependency |
| `research_distribution_reviews` | Independent disclosure review of the exact inventory and exact complete permission manifest |
| `research_distribution_actions` | Third-account publish/withdraw history |

Packages and dependency rows are assembled in one transaction. A deferred SQL
constraint rejects incomplete or extra inventories. After that transaction the
package is sealed. Actual source foreign keys prevent deleting retained targets
out from under the audit trail; updating a source cannot silently update the
frozen projection. New proposals can be created after withdrawal, but an old
package cannot acquire a second publish action. Multiple active matches to the
same public pins fail closed instead of selecting the newest or highest score.

Every permission must target one exact normalized dependency. A single broad
permission for a multi-source capsule is insufficient. An actual verified
`review` EvidenceArtifact with schema `rps-distribution-rights/1.0.0` must contain
the canonical bytes of this closed intent:

```json
{
  "version": "rps-distribution-rights/1.0.0",
  "scope": "rps_structured_bundle",
  "package_id": "<actual-package-UUID>",
  "inventory_sha256": "<exact-inventory-SHA256>",
  "dependency_id": "<exact-dependency-SHA256>",
  "dependency_row_sha256": "<exact-row-SHA256>",
  "public_bundle_sha256": "<exact-public-bundle-SHA256>",
  "license_code": "permission-on-file",
  "basis_code": "documented_disclosure_review",
  "distribution_permitted": true,
  "scientific_acceptance": false,
  "ml_training_approved": false
}
```

Its metadata must be exactly `{"distribution_rights": <document>}`; its record
and actual-byte hashes must match the canonical document. The reviewer chooses
one of `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0` or `permission-on-file` based on
actual evidence, not the provider name. These codes do not themselves resolve
attribution, contractual limitations or legal uncertainty. Unknown or unresolved
rights are not silently converted into an allow decision.

Each positive review freezes the sorted complete permission IDs and their
record hashes. Renewing a permission invalidates that review even if the
replacement permission also says allow. A new review is needed. Any negative
review holds that package. Revocation, negative review and withdrawal remain
possible after prior source/rights/actor eligibility fails; a protective action
must not require the positive condition that just ceased to hold.

## Operator workflow

Private endpoints are disabled with the existing ML foundation feature flag and
always require the application's authenticated session plus an explicit active,
verified research-role grant. Legacy admin flags are not substitutes. An actor
UUID in request JSON is forbidden; the actor is obtained from authentication,
then the role, account and session version are checked again in the dedicated
transaction. Existing browser-cookie CSRF protection is retained.

Upload admission checks the required live role before reading or decoding the
body. A small nonblocking per-process capacity gate also bounds simultaneous
large operations, including inventory inspection; saturation is a retryable
503, not an unbounded waiting queue. This does not replace the final transaction's
fresh role check. It is a per-process bound, not a fleet-wide memory guarantee.

| Method and route, under `/v1/ml/distributions` | Required role | Action |
| --- | --- | --- |
| `POST /register` | curator | Verify exact release/bundle, actual sources/bytes and register sealed private inventory |
| `GET /{package_id}` | any explicit research role | Inspect the private bindings/inventory, without asserting current publication approval |
| `POST /{package_id}/permissions` | reviewer | Record an exact dependency allow/revoke decision |
| `POST /{package_id}/reviews` | reviewer, account distinct from curator | Review the complete current permission manifest |
| `POST /{package_id}/actions` | publisher, account distinct from curator and reviewer | Publish or withdraw the exact reviewed package |

All mutations require a bounded `request_key` and default to `dry_run: true`.
Use a new key for a new intent; retry an uncertain operation with the same key
and exact intent. Matching replays return the same record with `replayed: true`
and do not advance guard epochs. Reusing a key for a different intent rejects.

Registration fields mirror `register_distribution`: `release`, `bindings`,
`public_bundle`, the three independently expected SHA-256 values, and actual
artifact byte maps. On the HTTP wire these maps are named
`artifact_bytes_base64` and `capsule_artifact_bytes_base64`. Permission requests
use `rights_bytes_base64`, the actual rights artifact ID and expected row hash.
For revocation, `supersedes_id` is required and the old rights reference can be
inherited without retrieving obsolete source bytes. Allow still requires the
complete actual rights inputs.

The API does not fetch caller URLs, read caller filesystem paths, grant itself
roles, invent rights reviews, or create missing upstream evidence. Source
captures, internal descriptor artifacts and rights documents must first exist
in the governed ingestion/curation store. A dedicated curator interface for
their preparation is a subsequent usability task, not fabricated by a test.

The internal service owns a savepoint and reports `committed: false`; callers
own the outer transaction. The HTTP operation envelope reports durable success
only after its outer commit succeeds, or after an exact existing durable record
is identified as a replay. Previews roll back the complete transaction. Errors
and cancellations do not emit invented success receipts; responses and errors
are private/no-store and do not echo input text, source bodies or driver details.
Direct service inspection/admission also requires a clean repeatable-read or
serializable session and normalizes database projections to UTC. An unchanged
timestamp must not acquire a different row hash from the caller's time zone.

## Public admission and withdrawal

All release-specific Discovery RPS routes use the same admission service:

1. Capture both configuration pin sets. Page-only approval is insufficient.
2. In a fresh, bounded read-only repeatable-read transaction, find the exact
   published package and validate its complete inventory and normalized rows.
3. Recheck the current projections, material/ancestor/source lifecycle, capsule
   pins/notices, all purpose permissions and rights documents, the permission
   manifest, and active curator/reviewer/publisher accounts and grants.
4. Read or reuse the independently verified file contents. File computation may
   be cached; authorization cannot be cached across requests.
5. Reobserve the database in a new snapshot before output, then check the final
   configuration and file identities without another intervening await before
   constructing the response or its conditional 304.

Unpublished, pending, rejected, withdrawn or currently ineligible IDs are omitted
from the public catalogue, not exposed as named unavailable entries. The
catalogue's effective approval fingerprint excludes those IDs. A direct lookup
returns 404. A mid-request admission change retries the catalogue or returns a
controlled 409 for direct delivery. A registry failure returns sanitized 503;
it never falls back to old authorization or a stale 304. Failures of an already
admitted content file retain the existing bounded catalogue degradation policy.

These are current-read checks, not a claim of distributed instantaneous
revocation after the final observation, deletion of already downloaded data, or
measured propagation SLA. The immutable historical file is not rewritten on
withdrawal. A separately downloaded offline bundle verifies historical integrity
only; it cannot promise current permission or scientific validity.

## Bounds, migration and rollout

Private verification limits include 5,000 artifact bindings, 20,000 normalized
dependencies, eight frozen capsules, 8 MiB per artifact and 64 MiB combined
verification material. JSON depth/node bounds and canonical finite-value checks
are enforced. HTTP uploads are streamed with a separate 96 MiB wire cap for
base64 overhead and 64 MiB decoded-byte budget. Over-limit inputs fail closed;
the limits are ceilings, not a claim that all maxima can be combined or meet a
production latency budget. Requests use database statement limits and bounded
snapshot work; deployment-sized benchmarks remain required.

Migration 0063 creates no real proposals, grants, rights decisions, published
packages, enabled flags or configuration pins. Old pin-only releases become
unavailable until an actual reviewed distribution is registered. Treat that
change as an intentional compatibility gate, not a missing fallback to restore.

Run the explicit guarded migration job and read-only schema admission; do not
let API startup migrate production. Downgrade refuses to delete retained
distribution history. Account-deletion retention recognizes all four new actor
references. Test fixtures are disposable and synthetic; native local migration
and regression evidence does not replace Linux CI, a backed-up staging rehearsal,
real rights/consent review, authorized production rollout or scientific testing.

The release gate remains [ML07 / #68](https://github.com/JackZH26/SCLib_JZIS/issues/68).
The remaining work includes real operator-reviewed source/rights inventories,
purpose-specific non-RPS ML exports, a usable artifact-preparation workflow,
staging and corpus-sized performance evidence, and approved production release.
