# Curator preparation for scientific Discovery

Issues: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77) and
[UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
Preparation version: `discovery-selection-preparation/1.0.0`.

## Implemented scope

This is the **read-only backend preparation layer**, not a completed curator
page. It provides explicit choices over an actual registered distribution and
compiles the complete proposed scientific projection. It returns exact commands
for the existing registration API; it does not execute them.

The unchanged [scientific projection and governance contract](DISCOVERY_SCIENTIFIC_PROJECTIONS.md)
remains authoritative. No database migration, new governance table, score
formula, scientific review profile, publication permission or automatic choice
is introduced. The existing [public scientific matrix](DISCOVERY_SCIENTIFIC_MATRIX.md)
is unchanged.

All new endpoints require an authenticated, active, verified account with a
current explicit **curator** grant. Legacy administrator/reviewer flags are not
substitutes. Actor and grant identities come from the existing authentication
and role system, never from request JSON.

| Method and path, under `/v1/ml/discovery-projections` | Purpose |
| --- | --- |
| `GET /selection/access` | Current curator actor/grant and preparation capability |
| `POST /selection/context` | Complete bounded candidate choices over an exact distribution and original bundle |
| `POST /selection/prepare` | Recheck context pin, compile explicit choices and return exact preview/commit commands |

These reads use dedicated **read-only, repeatable-read** transactions. Role and
session are checked again after upload; source lifecycle and retained dependency
hashes are checked against current SQL. An unavailable or changed source rejects
the entire read, rather than silently returning fewer materials or results.

## Original bundle and exact text

The base distribution does not retain the complete original public bundle in
its package record. Supply the actual canonical bundle file used to register
that distribution. Its contents are data, not instructions. The server does
not open a path, follow a URL, fetch a provider or reconstruct missing original
bytes from descriptors.

The closed `source` object contains:

- `distribution_package_id`: canonical package UUID.
- `public_bundle_json`: original canonical UTF-8 JSON text, held as a string.
- `expected_public_bundle_text_sha256`: SHA-256 of those exact UTF-8 bytes.

`POST /selection/context` accepts only `{ "source": ... }`. The server verifies
the text hash, canonical encoding, full original bundle contract, embedded
bundle/release hashes and their equality to the registered package. The text
hash is **not** the embedded `bundle_sha256`; their contracts differ.

Keep the text as a string through browser transport. Do not parse and
`JSON.stringify` the bundle as an object: Python canonical float tokens such as
`1e-07` may otherwise become `1e-7`, invalidating exact pins. Noncanonical text,
duplicate keys, nonfinite values, underflow-to-zero spellings, trailing bytes,
invalid Unicode and over-budget nesting/node counts are refused. Limits apply
to the embedded JSON as well as the outer HTTP envelope.

## Selection context

The response contains `version`, `context_json`, `context_sha256` and false
authority flags. Hash the exact UTF-8 bytes of `context_json` before using it;
do not hash a browser-reserialized object.

The parsed context includes actor/current grant, base package/record/inventory/
bundle/release pins, the original campaign, and materials sorted by their RPS
descriptor ID. Each material includes:

- Its original descriptor and actual native Material identity/hash.
- Every original assessment with reference, complete read-only RPS row, actual
  state identity and original state descriptor context.
- All retained structures belonging to this material, plus an explicit null
  structure option.
- All eight-registry-property candidates across the assessment states, with
  exact property/event pins, component, native quantity/unit, state, structure
  and knowledge origin.
- Applicable declaration-evidence references, each qualified by exact state
  and nullable structure: direct event sources and their artifacts, producer
  runs and their input/output manifest artifacts.

No full inventory, raw source body, private event context, arbitrary locator
metadata, run settings or filesystem path is added to this response. Source
details in the final preview continue to use the existing narrow scientific
projection. A retained reference establishes association, not that a passage
proves a curator's interpretation.

The context labels its quantities
`frozen_inventory_not_current_scientific_acceptance`. It is not a scientific
review snapshot. Final preparation and native registration rebuild actual
current scientific status independently.

## Explicit choices, not score-driven defaults

`POST /selection/prepare` accepts only `source`, `expected_context_sha256`,
`request_key` and `choices`. The context pin includes the original actor and
current grant. A different actor or replacement grant requires a new context.

`choices` must contain exactly one entry per material, sorted by descriptor ID:

- `material_id`: original RPS descriptor ID, not an invented database ID.
- `assessment_id`: an explicitly selected original assessment.
- `structure_id`: an explicitly selected exact structure UUID or null.
- `rationale`: nonblank explanation, at most 2,000 characters.
- `cells`: all eight native keys, sorted by `property_key`.

Each cell accepts only `property_key`, `availability`, `reason_code` and
`evidence_refs`. Evidence references use the existing table/row/hash shape and
must be sorted, unique and applicable to the chosen state/structure. Client
values, scores, weights, units, result lists and scientific approval flags are
not accepted.

The server derives **every alternative** and **every matching result reference**.
There is no highest-score fallback, best-result picker, averaging, truncation or
suppression of inconvenient components. Aliased descriptors that resolve to one
native Material are rejected; resolve them in the upstream release.

The UI must distinguish an **unchosen** form field from the legitimate null
structure option. Null means **only events without a structure binding**;
it is not a wildcard and must not be selected automatically. A suitable English
label is “No structure binding (only unbound events)”.
Selecting a retained structure does not itself prove that phase exists at the
selected pressure/state; scientific observations still require that exact
event context, and the representative choice remains subject to review.

Reported/unknown states remain constrained by the complete registered result
inventory. `not_computed`, `not_applicable` and `conflicted` require explicit
declarations with exact applicable evidence; no declaration is inferred from
material family, missing data or numerical disagreement. Conflict additionally
requires at least two quantified results of the same component. Missing values
never become zeros.

## Preparation, native rehearsal and registration

The preparation response returns actor/grant, context and request pins, plus
`payload_json`, `preview_json`, `commit_json` and the SHA-256 of each exact text.
It also returns the stable `request_sha256` and `selection_sha256`. The payload
includes the real compiled native observations, all alternatives, rationale,
declarations and current scope-specific scientific review status. Unreviewed or
empty scientific observations are permitted in this **private preparation**;
that does not weaken the stricter public publication gate.

An operator client must:

1. Verify exact text hashes, closed response fields, actor/context bindings and
   stable payload/selection/request pins; show the complete scientific preview.
2. Actually POST `preview_json` unchanged to `/register`. Merely obtaining a
   prepared command does not prove native registration guards passed.
3. Check the actual rehearsal's stable pins, then require explicit confirmation
   before posting `commit_json` unchanged to `/register`.
4. Treat only the successful **outer** `committed: true` as durable. The inner
   receipt intentionally retains `committed: false`; rehearsal IDs/record hashes
   are provisional and need not match the eventual committed ID.

The request digest follows the unchanged registration algorithm. Dry-run,
request key and expected payload pin are not part of that digest; recovery still
requires the **original actor + operation + request key + request hash**.
Never derive a fresh key or automatically retry a write after an ambiguous
response. Use the existing `/outcome` read. A 404 means “not currently observed”,
not proof of rollback. Historical recovery remains possible after source drift
or a replacement same-role grant; it is not current publication eligibility.

Complete intended exact-result scientific adjudication before freezing the
projection. If scientific decisions change after preparation, the prepared
payload hash becomes stale and a new registration rejects it. Re-prepare and inspect
the new payload; never update an old approved package in place. Even when only
scientific decisions change and the inventory context hash stays identical, the
new scientific payload hash must be checked.

All preparation authority flags are false: `scientific_acceptance`,
`ml_training_approved`, `current_authorization_checked`,
`public_release_authorized` and `registration_performed`. Registration remains
separate from selection/disclosure review, three-account publication and the
explicit public allowlist. The RPS calibration-pending disclaimer is unchanged.

## Bounds and remaining work

The pilot interface admits at most 25 materials and 200 assessments. Candidate
inventory limits are separate from final-selection limits: up to 5,000 native
candidate properties and 5,000 state/structure-qualified declaration evidence
references; no clipping. The final compiler still permits at most 100 selected
properties, eight results per cell and 20 evidence references per cell.

The original bundle is limited to 16 MiB, a choice document to 2 MiB, context
text to 8 MiB and scientific payload to 4 MiB. Preparation upload envelopes are
limited to 40 MiB; original registration remains 20 MiB. Exact prepared command
texts each remain within that original limit, and the complete prepared response
has a 64 MiB ceiling. The context envelope allows for escaped text overhead.
Shared authentication, browser-origin protection, no-store/nosniff headers,
bounded concurrent admission, upload chunk limits and timeouts remain active.
These are rejection ceilings, not measured production latency guarantees.

Next is the English curator editor consuming these exact contracts, with no
default representative/structure, explicit declarations, genuine native
rehearsal and original-request recovery. Independent reviewer/publisher history
and protective actions after source holds also need an operator interface.
An independently declared main-barrier field, real reviewed pilot and rights,
empirical calibration and authorized remote delivery remain separate gates.
Synthetic API tests do not close either issue or authorize deployment.
