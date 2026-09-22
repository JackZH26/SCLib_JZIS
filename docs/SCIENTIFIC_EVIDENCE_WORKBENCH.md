# Private scientific evidence workbench

Contract versions: `scientific-review-capabilities/1.0.0`,
`scientific-review-queue/1.0.0`, `scientific-result-dossier/1.0.0`,
`scientific-result-impact/1.0.0`.

The dashboard route `/dashboard/research/review` provides private inspection of
canonical non-Tc, non-RPS properties. The v1 dossier and queue documented here
remain **read-only**. A separate, versioned
[exact-result adjudication workflow](SCIENTIFIC_RESULT_ADJUDICATION.md) now adds
explicit accept, reject and clarification actions for supported sampled-phonon
profiles. These actions do not change the authority flags of the read dossier.
Full UX02 / #73 acceptance still requires the outstanding versioned ML and
consumer integrations, evidence and delivery checks; this is not issue closure.

## Scientific interpretation

The selected identity is an exact `event_properties.id`, its parent event ID
and event revision. A quantity always stays with its own state, structure and
producer run. The page does not merge formulas, choose a new preferred value,
compute RPS, infer superconductivity, or fill missing conditions.

| Display | Meaning | Not established |
|---|---|---|
| Quantity and native registry/unit | Stored exact point, interval, bound or unreported relation | Exact underlying physics, convergence or uncertainty of zero |
| Pressure and temperature | Values and explicit status/role; null remains unresolved | Ambient pressure or 0 K when absent |
| State/structure/run identities | Current canonical references captured together | Same sample/phase from formula agreement, or compatible computational method |
| `Computed` origin with an extraction run | A parsed computed observation and its import process | A newly executed or independently attested calculation |
| Parent review and validity | Existing **event-level** states | Acceptance of this selected property or its siblings |
| Artifact hash status | Stored source-byte metadata | New independent browser verification or source disclosure permission |
| Dependency relationships | Exact registered SQL references in the stated bounded scope | Scientific causality, refresh completion or global downstream completeness |

The queue's denominator is explicitly: “Canonical non-Tc, non-RPS properties;
review status belongs to each parent event. This page is not a reviewed-result
total.” Pagination is UUID keyset order, not priority or review readiness.
Only the current page is retained. No global total is calculated or implied.

## API and current authority

| Method and route | Result |
|---|---|
| `GET /v1/ml/scientific-review/capabilities` | Current research-role capabilities; no write capability |
| `GET /v1/ml/scientific-review/results?limit=25&after=UUID` | Up to 50 canonical property identities, without values/raw records |
| `GET /v1/ml/scientific-review/results/{property_id}` | Exact typed result, private dependency metadata and bounded reverse inventory |

Each request authenticates the current active/verified account, browser session
or JWT and current research grants in a new PostgreSQL **read-only repeatable-read**
transaction. Curator or reviewer grants permit evidence inspection. Publisher,
ordinary member and legacy administrator/reviewer flags alone do not. The
existing research feature flag is an additional availability gate, not authority.
This is a point-in-time check, not a promise that access cannot change after a
request starts. No raw source rights are granted by any of these roles.

Responses are `private, no-store` with `nosniff`. Query validation is sanitized
422, malformed/unsupported snapshots are sanitized 400, unavailable SQL or
deadline failures are sanitized 503, and authorization is 401/403. Disabled
feature returns 404. These three v1 routes have no POST operation; the separate
adjudication namespace has its own write contract. No raw SQL, source or arbitrary
exception details are returned. No counters, guard epochs or audit rows are
written by successful reads; native tests compare the entire database state.

Four requests may execute per process; each has a 10-second application deadline
and 5-second SQL statement timeout. These are bounded execution policies, not
a production latency SLA. Thread cancellation releases the owned request slot.
The frontend uses the existing credentialed fetch client, no-store, abort
signals and request generations; it does not persist evidence in local storage.

## Descriptor and privacy boundary

The dossier captures complete current canonical rows under its **event-local**
traversal policy, including outbound references and recursively owned children.
For example, event → claims → quality checks is included, as are sibling
properties and their dependencies. Exact snapshot-membership rows are collected
by each reached event ID, with their snapshot metadata. The dossier does not
expand a shared source snapshot into thousands of unrelated member events;
those events neither support this result nor belong to its review subject.
Changing an exact membership changes the pin, whereas merely adding an unrelated
member does not. The separate frozen 0054 traversal policy is unchanged.
The closure is capped at 1,000 rows,
200 artifacts and the existing pre-hydration byte budget. Oversized or missing
references fail the request; a partial inventory is never labeled complete.

The descriptor SHA-256 binds the contract version, selected identity/revision,
complete captured rows, reverse-impact inventory and unavailable write flag.
The separate inventory hash binds the captured rows. Private JSON changes and
new sibling/evidence/quality-check rows therefore change the hash even when
their contents are not displayed. These hashes are server capture identifiers:
the browser receives neither the full private preimage nor original files,
and cannot independently verify them or treat them as portable review evidence.
They do not prove persistent currentness between requests.

Only explicitly selected typed fields leave the reader. The API never returns
source text, quote bodies, arbitrary raw/context/metadata JSON, artifact URLs,
filenames or original byte downloads. For every artifact access label, including
restricted and unknown, well-shaped integer line/start-byte/end-byte metadata
may be displayed. Arbitrary locator objects are replaced by
`locator_not_disclosed`. Numeric offsets are not a grant to retrieve the source.
Line numbers are 1–1,000,000; byte offsets are ordered, nonnegative and at most
64 MiB. A zero-width range is allowed as stored locator metadata.

The source panel lists **all retained dependency artifacts**, not just direct
support for the selected property. Parent, sibling, state, run and ancestor
artifacts can appear. Membership itself is not proof of evidential support.
Each artifact has at most 200 evidence links/locators. The whole response is
limited to 2 MiB. Formula storage is already natively `VARCHAR(200)`.

## Bounded reverse relationships

The reverse reader uses registered typed SQL keys, not formula similarity,
arbitrary JSON traversal or source-text matching:

1. Exact target property/event pair.
2. Direct ML input-property and input-event references; owning examples and
   dataset snapshots. An event reference can concern a sibling, not this property.
3. Direct event snapshot memberships and their source snapshots.
4. **One-hop** `derives_from` input-event edges and output events.
5. Frozen row pins for reached identities and their historical releases.
6. Publication proposals for those exact releases.
7. Exact distribution dependency `(table_name, row_id)` references and the
   eight typed capsule-release reference columns, with owning packages.

The result includes the explicit scope and unsupported scope. Limits are 1,000
rows per query, 2,000 unique nodes, 4,000 distinct relations and a 1 MiB impact
envelope. Crossing a limit or deadline fails closed. Historical pin/proposal/
package membership does not assert current authorization. No global recursive
causality, external vector index/cache, historical generated answer, file-backed
release or dependency created after the snapshot is claimed.

Additive migration `0066_result_impact_indexes` supports reverse predicates
without changing scientific fields, immutable receipts or frozen capsule formats.
Index presence and native query plans are engineering checks; large-corpus
performance and deployment require their own rehearsal. The API does not apply
migrations on startup or mutate indexes while serving a request.

## Browser behavior and rollout

The dashboard navigation exposes the entry point to signed-in users, but the
page checks research capabilities before requesting evidence. It rechecks on
refresh and pagination. Selection immediately clears the old detail; failed
requests, lost access, unexpected contracts or mismatched identity/revision
clear displayed evidence and require a fresh access check. Late responses from
aborted/replaced requests cannot overwrite newer state.

Closed runtime validators check IDs, units, registry keys, finite quantity
relations, null/status consistency, exact queue/detail identity, artifact counts
and impact identity/count consistency. These are display-integrity checks, not
scientific validation. Desktop columns stack on mobile; all UI copy is English.

Deploy the schema revision, API contracts and frontend coherently through the
existing explicit rollout process. No production migration, review, release,
backfill, vector operation or remote issue closure is implied by local tests.

## Full UX02 integration status

The read dossier alone does not satisfy the issue. Migration 0067 and the
separate adjudication contract implement the property-level immutable ledger,
actor/source/head checks, explicit bounded batches and historical recovery.
Current public publication/distribution gates consume exact negative or stale
review effects. See the adjudication guide for the implemented scope and limits.
The following design and acceptance obligations remain relevant:

- A separately versioned, immutable **property-level** accept/reject/clarification
  decision ledger with exact target revision and whole-source descriptor pins;
  current reviewer authority, independent authorship rules, reason/evidence
  requirements, stale-write conflicts, retries and bounded batch behavior.
- An auditable canonical review artifact with retained actual bytes. Existing
  publication/disclosure reviews are not scientific adjudication and must not be
  reused as such. The current browser descriptor alone cannot be submitted as
  evidence that an operator inspected original source bytes.
- Explicit reviewed method/state/structure binding. Missing pressure, geometry,
  phase, calculation method, source-time or upstream-run identity remains unknown
  unless supported by actual reviewed evidence; approval cannot supply defaults.
- A property-scoped consumer contract. Updating parent `review_status` could
  accidentally approve unseen siblings; it is not a valid implementation shortcut.
  Preserve frozen rows and do not attach new owned children to frozen events.
- Preserve actual producer-output identity. Cloning a calculated property to a
  new UUID while retaining an old output manifest breaks lineage; versioned
  review-to-original-result binding and downstream provenance compilation must
  be explicit. Do not rewrite immutable producer manifests to manufacture a match.
- Wire supersession/rejection into actual public, Timeline, Facts/RAG and ML
  consumers with tests for invalidation and refresh. Merely appending a decision
  does not withdraw an old public view, authorize new publication or refresh a
  vector index. Frozen integrity, scientific review, rights and dataset admission
  remain separate gates.

Regardless of separately recorded decisions, every v1 inspection dossier
returns `scientific_accepted=false`, `ml_training_approved=false`,
`public_release=false`, `review_write_available=false` to describe authority
conferred by this inspection—not to overwrite historical statuses. Its warning
is now `dossier_read_only_no_adjudication_performed`; the historical batch32 wire
fixture retains its original unavailable-workflow warning as a recorded capture.
