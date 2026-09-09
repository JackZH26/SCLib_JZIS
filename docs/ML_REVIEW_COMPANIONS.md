# Private review-aware ML datasets

This workflow adds an independently pinned review observation to the existing
frozen scientific dataset workflow. It does not modify a research release,
source companion, producer manifest, scientific result or adjudication record.
It does not train a model or authorize training, source disclosure or publication.

## Versioned artifacts

| Artifact | Version | Purpose |
| --- | --- | --- |
| Original frozen capsule | `research-release/1.0.0` | Original rows and retained artifact bytes. |
| Original source companion | `ml-feature-companion/1.0.0` | Independent feature-source identities and historical availability declarations. |
| New private review companion | `ml-feature-review-companion/1.0.0` | Exact property review heads, complete private audit requests, role observations and current source-governance observations at capture. |
| New task | `ml-task/3.0.0` | The unchanged v2 scientific policies plus `exact_result_review_policy="negative_only/1.0.0"`. |
| New dataset | `ml-task-dataset/3.0.0` | Rebuilt feature admissions, paired cohorts, partitions and train-only transforms. |

All externally supplied SHA-256 pins identify the **complete canonical file**.
The review companion also has an internal `companion_sha256` that excludes its
own field, and an `observation_sha256` for its observation body. These are not
interchangeable. The release ID comes from the independently verified original
source companion and database release receipt; no release-ID field is added to
the frozen capsule manifest.

## Scientific interpretation

The first review policy is negative-only. A rejected, clarification-required,
stale, source-held, reviewer-unavailable or fidelity-dependency-held exact result
is withheld from applicable feature views. An accepted scoped observation never
waives the existing calculation, protocol, state, coordinate, source-time,
target-leakage or label checks. Unreviewed means unreviewed, not accepted.

Holds operate before feature admission, cohort construction and fitting:

1. Independently verify all input pins, frozen rows and actual artifact bytes.
2. Reconstruct explicit result and retained producer-manifest dependencies.
3. Apply exact-property review holds and exact input-source holds.
4. Run the unchanged scientific and temporal eligibility checks.
5. Preserve independently eligible composition rows and their base partition
   decisions; rebuild affected physical (`P`), structural (`S`) and joint (`PS`)
   cohorts from raw admitted data.
6. Fit each view's imputation and scaling on its training partition only.

A direct input uses its own source binding. A different input for the same
property is not vetoed solely by the first input's source hold. For a strict
ancestor without an edge-level source-input selector, every declared source
binding for that ancestor is required conservatively. A property-scoped review
hold applies to every use of that exact property. Sharing a material, event,
producer, reviewer or request is not itself a new causal edge.

The common review batch, actor and private receipt never become scientific
groups or independent support. Review timestamps never become publication or
feature-availability dates. Malformed mandatory evidence fails verification;
valid negative optional-feature observations are not silently converted into
negative superconductivity labels.

## Private capture and completeness

Internal service: `api/services/ml_review_capture.py`.

`capture_ml_review_companion` requires an authenticated trusted caller's actor ID,
an active verified administrator account **and** the exact active curator grant,
and explicit `export_scope="ml_review_full_audit/1.0.0"`. Reviewer, curator or
administrator status alone does not grant this export. This is a technical
private-audit export capability, not scientific or publisher authority. No new
public HTTP endpoint is provided.

The caller owns a clean UTC repeatable-read or serializable transaction with a
finite statement timeout of at most ten seconds. Capture is read-only. It derives
the full property inventory from **all** frozen ML inputs and their explicit
result/run dependencies. Inputs without a source binding remain explicit;
missing source witnesses still fail the existing optional-feature gate. Tc/RPS
targets remain inventory entries, not invented supported review profiles.

Every relevant property has an explicit two-scope current-head inventory,
including null heads. A reviewed property retains the current subject separately
from each stored historical decision basis. Every needed request retains its
entire original JSON and every request item/decision, with recursively required
predecessor, resolution, subject and extraction-fidelity dependencies. An
audit-only sibling property never enters the scientific feature inventory.

The private actor inventory contains only account IDs and active, verified and
administrator flags, plus the required grant/revocation audit records. It does
not contain email addresses, credentials, passwords or session tokens. Request
rationales and source snapshots can contain private or copyrighted material:
the companion must not be served as a public dataset or public website response.

Capture also checks that the current complete 0064 binding inventory still
matches the supplied original source companion. It observes independent
Paper/Work/source closures even when those sources are absent from the exact
review subject. Source revision/capture siblings, current identity mappings and
negative lifecycle history cannot be omitted simply because a scope is unreviewed.
Source holds are retained as negative observations, not rejected by the old
positive-only source-capture helper.

Current observations also cross-check their shared scientific projections with
the current review subjects; two independently hashed but contradictory current
rows do not form a valid package. The source verifier checks strict SQL scalar
domains and all columns of compound foreign keys. A changed critical source
identity (Paper provider/DOI/arXiv/external identifier, or Work canonical identity)
withholds the associated input even when the catalogue remains active. This
does not treat citation counts, titles or disclosure settings as physical facts.

Bounds are cumulative and fail closed, never truncate:

- At most 200 reviewed property targets, independently of the 20-item interactive
  adjudication request limit.
- At most 200 complete requests and 4,000 private audit rows.
- A separate bounded source-closure inventory and eight-MiB per-row/subject
  parser limit; the complete companion is at most sixteen MiB.
- One ten-second capture budget, including final synchronous verification.
- The v3 compiler additionally limits cumulative held-reference audit expansion
  to 20,000 references. It rejects excess instead of emitting a partial audit.

These are technical guardrails, not measured throughput or an assertion that
every combination at every upper bound fits the shared time/byte budget.

## Two hash protocols and a lossless bridge

`ml_review_projection.py` distinguishes frozen 0054 full-row hashes from 0067
recursive SQL-canonical subject/property hashes. It retains and hashes the
original SQL UTF-8 text, parses decimals without a floating-point intermediate,
checks closed subject shapes and forward foreign-key bindings, and compares
only the versioned scientific projection. Known typed date/timestamp fields are
normalized as dates/instants; arbitrary source strings are not rewritten.

Different property identities or malformed closures are package failures.
Valid current scientific differences cause a projection hold. Legacy JSONB
precision already lost when an older capsule decoded a decimal cannot be
recovered: unresolved comparison is withheld, never approximately accepted.
Two hash protocols can incidentally produce the same digest when their exact
input bytes agree; their distinct definitions still must not be conflated.

Source lifecycle snapshots preserve their separate original PostgreSQL
`jsonb::text` representation and 0056 snapshot hash. The source verifier replays
the retained snapshot, complete lifecycle chain, predecessor/revision bindings
and current source status. A later return to an active catalogue status does
not erase tracked negative history or establish source reinstatement.

## Offline build and verification

New command: `scripts/ml_reviewed_dataset.py`. All pins must come from independently
identified inputs, not be substituted with an internal companion-body digest.
Example argument layout (replace the uppercase placeholders with actual pins):

```bash
api/.venv/bin/python scripts/ml_reviewed_dataset.py build \
  --manifest /private/capsule/manifest.json --manifest-sha256 CAPSULE_FILE_SHA \
  --companion /private/source-companion.json --companion-sha256 SOURCE_FILE_SHA \
  --review-companion /private/review-companion.json --review-companion-sha256 REVIEW_FILE_SHA \
  --task /private/task-v3.json --task-sha256 TASK_FILE_SHA \
  --output /private/new-reviewed-dataset.json
```

Verification uses the same inputs with `verify`, `--bundle` and its independent
`--bundle-sha256`, instead of `--output`. Verification recomputes the complete
bundle, not just its checksum. The command rejects aliases, symlinks, concurrent
input changes and overwrite attempts. Successful builds create a new
owner-only file outside the input capsule; no-go builds do not write a bundle.
The workflow does not connect to a database or provider, execute a calculation,
invoke training, or upload source material.

## Captured history is not current authorization

An old artifact can remain exactly reproducible after a later rejection,
reviewer revocation or source withdrawal. All authority flags stay strictly
`false`, and receipt semantics are `captured_not_live`.

`recheck_ml_review_companion` verifies the old independently pinned artifact,
repeats the explicitly admitted capture in the caller's stable transaction,
and requires the observation hash to match. A changed observation requires a
new companion and rebuild; the historical artifact is never overwritten. This
read-only comparison does not authorize an external effect and does not turn
an already-open database snapshot into a fresh transaction. A future authorized
training/export operator still needs its own fresh transaction, concurrency
fence, rights checks and explicit effect-specific admission.

Offline verification proves internal consistency with the supplied independent
pins. It cannot independently authenticate the database or human identity,
prove that no omitted/newer external review exists, establish expertise, or
grant source rights. An attacker who replaces the entire package and every
trusted external pin has crossed this protocol's trust boundary.

## Native-import scientific boundary

Native file import records extraction of retained sampled data. It does not
establish upstream DFT/DFPT execution, complete Brillouin-zone stability, known
measurement/calculation conditions or an independent source-time witness.
Neither an accepted extraction-fidelity review nor the limited sampled-minimum
scientific review supplies those missing facts. The v3 task retains the existing
physical feature requirements; it does not relabel native extraction as a
calculation, rewrite producer documents or invent positive training examples.

Synthetic SQL/CLI regressions test these technical contracts. They are not
physical validation of the fixtures, a scientifically qualified real corpus,
measured ML performance, production deployment or permission to publish sources.
