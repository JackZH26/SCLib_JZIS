# Exact scientific Discovery projections

Issue: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77).
Schema: `0069_discovery_projection`, following `0068_answer_evidence`.
Companion: `discovery-scientific-projection/1.0.0`.
Selection: `discovery-scientific-selection/1.0.0`.
Governance: `discovery-projection-governance/1.0.0`.

## Purpose and limits

This separately versioned companion connects an unchanged, independently pinned
RPS release to actual source-linked database observations. It does not change the
RPS scorer, release manifest, public-bundle bytes or offline verifier. It does not
replace the existing synthetic layout preview with invented reviewed data.

The companion selects one explicit assessment/state/action per actual material,
retains every alternative assessment, and projects supported scientific values
from the exact selected material/state/structure context. A source being inside
the same frozen capsule is not sufficient evidence that it applies to this
candidate. Different pressures, structures, components or research actions are
not silently averaged, substituted or merged.

The exact public disclaimer is:

> Policy-based research priority; empirical calibration pending

RPS remains a policy-based research priority, not the probability of
superconductivity, measured superconductivity or an empirically calibrated
cross-family success rate. Comparisons are scoped to the **same frozen campaign,
budget, policy and release**. The original family/profile, action, constraint reasons,
evidence and score explanation remain attached. A negative-control role is not
an experimentally measured negative result. Policy evaluation remains separate
under [AL01 / #78](https://github.com/JackZH26/SCLib_JZIS/issues/78).

Backend compilation, governance and HTTP interfaces are implemented. Batch 48
adds the read-only [public scientific material matrix](DISCOVERY_SCIENTIFIC_MATRIX.md)
with explicit package selection, native observations and frozen alternatives.
Batch 49 adds [read-only curator selection preparation](DISCOVERY_SELECTION_PREPARATION.md):
verified original-bundle upload, complete explicit choices, real compiled payload
and exact commands for the unchanged registration API. The representative-selection
operator editor remains unfinished. The existing
synthetic matrix is accessible only via an explicit development-only layout
preview. A real reviewed pilot, real rights decisions, remote
delivery and issue closure are not established by synthetic integration tests.

## Actual supported fields, not a universal completed dictionary

| Native property key | Retained unit | Group | Exact positive scientific-review support |
| --- | --- | --- | --- |
| `formation_energy_per_atom` | `eV/atom` | stability | Not implemented |
| `energy_above_hull` | `eV/atom` | stability | Not implemented |
| `band_gap` | `eV` | electronic | Not implemented |
| `dos_at_fermi` | `states/eV/formula_unit` | electronic | Not implemented |
| `electron_phonon_lambda` | `1` | pairing | Not implemented |
| `omega_log` | `K` | pairing | Not implemented |
| `phonon_min_frequency` | `THz` | stability | Exact relation only; sampled-phonon-minimum profile |
| `superfluid_stiffness` | `K` | coherence | Not implemented |

All eight have native storage and quantity projection support. That is different
from being populated or scientifically accepted. Geometry and competing-order
groups remain planned; other draft dictionary fields are not new database
properties. The four RPS keys are explicitly separate policy-assessment fields.
Capability counts in a compiled projection count its actual retained
observations, not the production database. The private capability endpoint does
not query population and says `population_scope: not_queried`.

Do not adapt the old demonstration's `dos_ef`/`states/eV` or stiffness in `meV`
into these native fields without a separately justified conversion. A registry
unit alone does not establish computational normalization, a standard-cell
convention or physical comparability. Each observation therefore declares that
normalization is not asserted by this registry unit. The narrow phonon review
does not certify full-Brillouin-zone stability, DFPT convergence or the rest of
the material's physics.

## Explicit representative selection

The curator supplies a closed, canonical selection document, not arbitrary
database row JSON. Its top-level fields are `version`,
`release_manifest_sha256`, `public_bundle_sha256` and `representatives`.

Each representative contains exactly:

- `material`: original RPS material descriptor ID and hash.
- `assessment`: original assessment ID, positive integer revision and hash.
- `structure`: null or an exact `structure_records` table/row/hash reference.
- `rationale`: an explicit nonempty explanation, at most 2,000 characters.
- `alternatives`: every other assessment reference for that material, ordered by
  ID, including lower-scoring, unranked and control alternatives.
- `cells`: all eight native keys in sorted order. Each cell has `property_key`,
  `availability`, `reason_code`, `result_refs` and `evidence_refs`.

The server verifies the unchanged public bundle, complete material membership
and every original assessment reference. It never chooses the highest score or
the most recent action. Two different RPS material descriptors resolving to the
same actual database Material are rejected rather than producing duplicate
material rows with incomplete alternatives. Curators must resolve that aliasing
in the upstream release, not ask this compiler to reinterpret it silently.

Material and state descriptors must resolve through the original distribution
binding to actual sealed SQL identities. Selected structure belongs to that
actual material. Every supported native property in the sealed inventory for
that exact material/state/structure must be included in its corresponding cell;
the caller cannot hide an inconvenient result or select only one component.
Property, event revision, state and source references remain individually pinned.
Rows not already in the sealed inventory require a new base distribution.

The selection hash uses the existing Python `research_priority.digest` canonical
JSON contract. It is not an arbitrary browser `JSON.stringify` checksum. Exact
canonical text is retained in SQL TEXT so JSONB number normalization does not
rewrite a frozen payload. The complete stored public-bundle text checksum is
distinct from its embedded bundle hash, which keeps its original hash contract.

## Quantities, missingness and evidence

Quantities retain exact, interval, upper/lower inequality and unreported
relations, including finite zero and legitimate negative quantities. No
unreported value is imputed as zero. Different components are kept separate.
An `exact` relation records the reported scalar form; it does not assert zero
measurement uncertainty or exact physical knowledge.

| Availability | Required interpretation |
| --- | --- |
| `reported` | At least one quantified registered observation; not automatically reviewed or true |
| `unknown` | No matching registered result, or retained source explicitly lacks a value; exact reason code distinguishes them |
| `not_computed` | Explicit declaration requiring independent review, with a pinned selected-context source/producer; not inferred from database absence |
| `not_applicable` | Explicit declaration requiring independent review, with a pinned selected-context source/producer; not a zero or a universal family rule |
| `conflicted` | Explicit declaration with evidence and at least two quantified observations of the same component; numerical difference alone does not prove conflict |

Not-computed, not-applicable and conflicted cells carry
`availability_basis: explicit_review_required_declaration`. A referenced run or
source must belong directly to the selected context; unrelated capsule ancestry
does not qualify. That association does not itself prove the declaration for the
property. Independent review of the complete selection and payload is still
required. These declarations never become positive scientific ground truth.

Every projected observation includes native key/registry/component, relation and
unit, event ID/hash/revision/type/knowledge origin, exact material/state and
optional sample/structure/run, typed source links and bounded source locators.
Selected-event sources, forward dependencies, snapshot membership and claim
source occurrences keep different relation labels. The API does not expose raw
source bytes, unrestricted conditions/metadata prose, paths or arbitrary source
URLs as cell evidence.

The actual 0067 subject is captured independently and bridged to the sealed 0054
row closure. Those contracts have different canonical hash representations;
equal-looking IDs do not replace the bridge. The full current review status and
revision hash are frozen with each property. Event-level approval, extraction
fidelity alone, an unreviewed negative gate, a hash match or an old publication
permission cannot mark a scientific result accepted.

The current pending-import contract also retains `extraction` events carrying
`Computed` origin. That combination does not manufacture a new calculation run
or become a DFT/DFPT result merely because the frontend shows a number.

## Independent new-scope governance

Three append-only tables retain packages, reviews and publish/withdraw actions.
All actor/grant references restrict deletion and are included in the account
audit-retention boundary. Populated migration downgrade refuses without deleting
history; an empty downgrade removes only the new tables/functions.

1. An explicit current curator previews and registers the companion, including
   base package/record/inventory pins, original public bundle, full selection,
   compiled payload, complete dependency IDs and exact scientific-status pins.
2. A different current reviewer approves the exact representative selection and
   complete disclosure under `discovery_scientific_projection`. The rights list
   must cover every original sealed dependency with its exact row hash and an
   explicit license/basis code. Old RPS scope approval is not this new approval.
3. A third current publisher publishes the exact package/review/payload/selection.
   At least one currently accepted exact scientific-result cell is required;
   that does not approve the other seven properties or the entire material.

Rejected review or withdrawal holds that companion. Protection does not require
continued positive scientific eligibility. Publication and current public reads
also require the old base distribution to remain published with its own exact
rights, source and independent-account checks. Changing a source/review status
or losing a required grant is rechecked on subsequent public requests at their
two admission snapshots. Already delivered bytes cannot be revoked, and a write
after the final read point is not instant global invalidation.
The application fully rebuilds the typed payload from actual SQL rows during
admission; hashes of a manually inserted JSON payload are not semantic proof.

Service savepoints are not durable receipts. Preview defaults to rollback, and
registration commit requires the preview's exact `expected_payload_sha256`.
The request hash excludes this optional preview-only pin, so preview and commit
refer to the same operation. Exact actor/key POST replay preserves original IDs
without writes, including governance epochs. POST replay requires the original
exact grant; a changed request, pin or grant rejects. A replacement active grant
for the same original actor can recover the historical receipt through GET,
without authorizing the old POST or restoring present publication eligibility.
The enclosing HTTP transaction alone reports durable completion after commit;
it serializes and bounds the report before committing.

## Private HTTP workflow

Prefix: `/v1/ml/discovery-projections`. Existing ML foundation feature flag,
verified session/JWT, browser CSRF and explicit research roles apply. Legacy
administrator status is not a research grant. All responses/errors are private,
no-store and nosniff. Write admission is checked before reading the body and
again under the ordered serializable transaction after upload.

| Method/path | Required role | Purpose |
| --- | --- | --- |
| `GET /capabilities` | Research operator | Static registry/bounds, not population or approval |
| `POST /register` | Curator | Preview or exact-payload-pinned registration |
| `GET /{package_id}` | Research operator | Rebuilt private typed payload and complete rights targets |
| `POST /{package_id}/reviews` | Reviewer | Exact new-scope selection/disclosure approval or rejection |
| `POST /{package_id}/actions` | Publisher | Exact publication or protective withdrawal |
| `GET /outcome` | Original actor with current operation role | Historical actor/key/request-hash recovery |

Outcome takes exactly `operation`, `request_key` and
`expected_request_sha256`. Allowed operations are `register`, `review`, `publish`
and `withdraw`. A missing receipt is not proof of rollback. Preserve the original
account/key/request hash after a lost acknowledgement; inspect that operation
before considering an explicit identical retry. Historical recovery does not
restore present publication authority.

Closed request models reject client actor/grant IDs, arbitrary approval fields,
source-fetch URLs, file paths, duplicate keys, nonfinite JSON and type coercion.
The body is limited to 20 MiB and 65,536 stream chunks, raw query to 1,024 bytes,
reports to 8 KiB and private inspections to 8 MiB. Compilation caps are 25
materials, 200 assessments, 100 distinct properties, eight results per cell,
20 declaration evidence references per cell, 2 MiB selection and 4 MiB payload.
Existing full-inventory limits remain; these maxima are not all simultaneously
achievable. Existing two-slot nonwaiting private admission and bounded SQL/upload
deadlines apply. Size limits do not establish corpus-scale production throughput.

## Public delivery and browser handoff

The public API is separately opt-in. Enablement is not supplied by a client:

- `DISCOVERY_SCIENTIFIC_PUBLIC_ENABLED`, default false.
- `DISCOVERY_SCIENTIFIC_APPROVED_PROJECTIONS`, an explicit map of companion UUID
  to exact payload hash, maximum 25 entries.
- The existing RPS publication flag and exact release/public-bundle approval maps
  must still agree with the companion's base release.

`GET /v1/discovery/scientific` provides an explicit version catalogue;
`GET /v1/discovery/scientific/{projection_id}` reads exactly that companion.
There is no latest, best-score or demo-data fallback. Only configured approved
IDs are considered; private pending/held package identities are not enumerated.
Public data is read-only, no-store and nosniff, with no ETag/304 shortcut.
Current admission is checked in two fresh, dedicated bounded SQL snapshots,
including full payload rebuild, with configuration/pin checks before response.
A changed result rejects rather than serving a cached positive decision.

The browser integration should choose an explicit catalogue entry, render one
material per row with expandable exact observations/alternatives, and preserve
the isolated development-only demo preview. It must label unsupported/planned fields, recorded versus
accepted observations, declared missingness, comparison scope and calibration
limits. No browser-calculated superconductivity probability or silent numeric
aggregation should be added.

The current sealed RPS rows retain constraint/reason codes, but do not separately
declare a primary `main_barrier` field. The browser must not choose a lowest
dimension or first reason and call it the main physical barrier. Display the
exact constraints and that a main barrier was not separately declared until an
explicit versioned, reviewed field is available.

No setting is enabled by this migration or by these tests. Do not run a live
backfill, publish a real projection, change production settings or close DR04
solely because this backend increment passes its synthetic tests.
