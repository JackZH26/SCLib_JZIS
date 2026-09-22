# RPS public recomputation and catalogue delivery — DR02

Local implementation for [#74](https://github.com/JackZH26/SCLib_JZIS/issues/74).
No real campaign, consent, source disclosure or production enablement is created
by this change. Test and measurement releases are explicitly synthetic.

## Three different judgments

1. **Integrity and computation:** the actual verifier checks canonical hashes,
   transitive artifact references, cutoff/review bindings, action prerequisites,
   resource declarations and every recomputed score projection.
2. **Declared review and disclosure:** a package records complete-release
   disclosure and consented public review identifiers or public attestations.
   These declarations are not authenticated human reviews, signatures, or proof
   that a source licence permits disclosure. Closed field checks cannot detect
   private information deliberately placed inside an allowed rationale.
3. **Current serving authorization:** the server requires opt-in plus separately
   configured release and public-package digest approvals. Offline verification
   cannot prove that either approval remains current.

None of these establishes superconductivity, calibrated scientific utility,
execution permission, or an ML training label. RPS retains its action/campaign/
budget-specific interpretation and numerical `RPS-v1.2` policy. Scores from
different campaigns are not made empirically comparable by packaging them.

## Complete public package

`rps-public-bundle/1.0.0` contains:

| Field | Meaning |
| --- | --- |
| `release` | Complete unchanged `rps-release/1.2`, including campaign objective/budget/profile assignments/dimension rules, cutoff, reviewed actions, all artifacts and original manifest |
| `policy` | Complete implemented scoring policy, not just a version label |
| `rows` | Every computed projection, eligibility/reasons, effective weights, P/G/A bounds, raw/display/upper score, ranking and contributions |
| `verifier` | Version and actual installed verifier/scorer/contract source inventory hash |
| `disclosure` | Exact full-release digest, explicit complete-release/free-text disclosure declaration and one consent/public-attestation binding for each review artifact |
| `bundle_sha256` | Canonical SHA-256 of the other fields; distinct from the unchanged release manifest |

Material, review and profile-assignment contents are explicitly closed before
download, as are the existing typed state, action, rubric, source metadata,
template and template-review artifacts. Arbitrary nested full-text/private
containers fail admission. All review/template-review identifiers must use the
declared public pseudonym or public-attestation namespace and have exact
artifact-bound disclosure entries. Source metadata includes only allowed
bibliographic/locator/licence fields, never an added full-text container.

Public packages are bounded to 16 MiB, 1,000 assessments, 5,000 artifacts, a
32-level structure and a bounded node/string inventory. Canonical UTF-8 bytes
are required; duplicate keys, nonfinite numbers, unsupported fields, missing
dependencies, changed policies/inputs/rows and incorrect hashes fail closed.
The stricter public envelope does not silently migrate the older release
schema. Unsafe existing releases are rejected, not redacted behind their old
manifest or review. A safe newly reviewed release has its own new identities.

`build_public_bundle(release, disclosure=...)` is pure preparation: it neither
writes files nor grants approval. It accepts an already complete public-safe
release and explicit declarations; it does not fabricate them from old fields.

## Offline reproduction

Use the declared verifier source version and matching locked API environment.
The implementation is packaged in `services`, so it does not require a private
database, cloud account, installed repository test fixtures or the repository's
unpackaged `scripts` directory. The repository launcher is a convenience:

```bash
api/.venv/bin/python scripts/validate_public_priority_bundle.py \
  --bundle /absolute/path/release-id.public.json \
  --sha256 <independently-retained-bundle-sha256> \
  --release-sha256 <independently-retained-release-manifest>
```

The equivalent installed entry point is
`python -m services.priority_public_bundle_cli` with the same arguments.
The package alone plus its declared verifier/runtime supplies all scoring
inputs. No private local release file is needed for offline verification.
Retain the expected hashes independently of the downloaded object; a hash
copied from untrusted bytes proves only internal consistency. Verification
reports integrity, exact recomputation and closed-field conformance separately
from unauthenticated review/disclosure and unchecked current authorization.
It does not print source contents, private identities, raw exceptions or paths.

The source inventory comprises `priority_public_bundle.py`,
`priority_public_bundle_cli.py`, `priority_release_cache.py`,
`priority_releases.py` and `research_priority.py`. The verifier source digest
is a content inventory, not a code signature, Git
attestation or claim of identical runtime dependencies. Use the API lockfile and
declared runtime alongside that source version. A later verifier source change
does not retroactively update a pinned public package.

## Serving and identity

Existing release files remain `<release-id>.json`. The separately admitted
package is `<release-id>.public.json` in the configured release directory.
All defaults remain disabled/empty:

```text
DISCOVERY_RPS_PUBLIC_ENABLED=false
DISCOVERY_RPS_APPROVED_RELEASES={}
DISCOVERY_RPS_APPROVED_PUBLIC_BUNDLES={}
```

Both maps are bounded to 128 entries at the serving boundary. Identifiers are
bounded ASCII tokens without path separators; exact `.`/`..` are rejected as
unroutable URL dot segments. A bundle's `public: true`, declaration or self-hash
never adds it to these trusted administrative maps.

`GET /v1/discovery/rps/releases` returns `rps-catalog/1.3`:

- `items`: only verified approved releases, each with existing metadata and a
  `public_bundle` status of `available`, `not_published` or `unavailable`.
  Only `available` carries a bundle digest and verifier version.
- `unavailable`: bounded ID/status/reason entries for failed approved releases;
  no internal exception, path, partial row or replacement score is exposed.
- `status`: `published`, `not_published`, `degraded`, or `unavailable`. A bad
  package can degrade delivery without removing its healthy release rows.
  An all-failed approved inventory is not described as an empty publication.
- `approval_sha256`: digest of enablement plus both approved digest maps; no
  private directory is exposed.
- `catalog_revision`: canonical digest of the preceding catalogue content,
  schema and approval identity, not the static scoring policy hash.

Release membership, digest approval and observed availability affect this
revision. A configured-directory change triggers a fresh request-level check;
an identical verified public representation may still have the same ETag.
The catalogue is assembled privately with at most four workers, then file
identities and the complete approval snapshot are checked again. A changed
snapshot retries the whole catalogue once; continued change returns sanitized
503. No partially refreshed catalogue is published.

Download uses both selected catalogue pins:

```text
GET /v1/discovery/rps/releases/{id}/bundle
    ?manifest_sha256=<release-manifest>&bundle_sha256=<public-package-digest>
```

The route checks the original approved release and complete public package,
then rechecks file witnesses and both current approvals before returning an
attachment. Unapproved access is 404, a stale requested pin is 409, and failed
verification is 503. Page/detail/download retain the same original manifest as
`X-Data-Version`; the download also carries `X-RPS-Bundle-SHA256`. It returns
canonical admitted bytes, not a redacted reconstruction.

Successful responses require revalidation (`max-age=0, must-revalidate`);
conditional 304 is considered only after current checks. Publication dates
are not used as `Last-Modified` validators: different manifests may share a
date. Errors, including validation failures, use `no-store`. These checks are
read-point snapshots, not permanent approval, source-currentness or revocation
history guarantees. Existing file-backed evidence is not silently linked to
the research database's source-lifecycle ledger by this batch.

## Resource and failure controls

The shared process-local cache keys namespace, expected digest(s), path and
device/inode/size/mtime/ctime. Leaf symlinks and nonregular files are refused;
configured parent directory symlinks are not an ownership/authentication
boundary. Files are bounded to 50 MB at the common reader and read against
before/after identity witnesses. Public decoding applies its tighter limit.

At most 32 entries and 128 MiB of accounted reachable Python objects are
retained. Dataclass slots and nested model/row containers are included. This is
an accounting limit, not total process RSS; request projections, interpreter
overhead and transient decoding also consume memory. Oversized entries are
verified but not cached. Two distinct keys can verify concurrently; same-key
readers share the completed verification. Waiting is bounded to 32 callers and
30 seconds; parsed failures have a one-second negative cache without retained
exception tracebacks. Missing files fail their inexpensive metadata check.

The router separately caps submitted worker jobs at eight. Client cancellation
does not release a permit while its worker continues running. Capacity errors
are explicit and retryable, not partially accepted input. Cache counters expose
verification/hit/failure/negative-hit counts, entries, accounted bytes and live
work to local diagnostics; no public cache-management endpoint is added.
Catalogue reads use detached lightweight metadata. Full release consumers get
detached model copies so mutable nested objects cannot poison cached evidence.

Measure with `scripts/benchmark_rps_delivery.py` in the locked development
runtime. It uses only temporary synthetic fixtures and records actual cold/warm
reader latency, verification counts, Python allocation and separately labelled
process high-water RSS. It is a local service rehearsal, not an HTTP/production
p95 or agreed service budget. A representative workload and operator-reviewed
budget remain required before performance acceptance.

## Frontend and remaining gates

The English-default Discovery board checks the exact 1.3 inventory, status,
IDs, bounds and hash-shaped bindings before showing scores or downloads. Old
1.2 catalogues require coordinated frontend/backend upgrade and fail closed;
page/detail schemas remain 1.2. Refresh clears old rows, downloads and request
authority immediately. Download links use only the configured public API and
the selected pins. The browser does not claim to have recomputed the package.

Real public review/consent, DR01 scientific template acceptance, ML07 source/
release integration, representative performance budget, implementation PR/CI
and a separately authorized rollout remain acceptance work. Local synthetic
success is not permission to publish or close those scientific gates.
