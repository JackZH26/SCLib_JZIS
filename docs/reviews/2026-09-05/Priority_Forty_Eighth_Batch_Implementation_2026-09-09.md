# Batch 48 — public scientific Discovery material matrix

Date: 2026-09-09.
Branch: `codex/sclib-research-v2`.
Starting commit: `1d722e62221623adfd84a2a8965406f3642987b3`.
Primary issue: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77).
Contract guide: [Public scientific Discovery matrix](../../DISCOVERY_SCIENTIFIC_MATRIX.md).

## Outcome

The ordinary English Discovery page now displays a real public scientific
companion interface, not the demonstration layout. It requires explicit package
selection and shows one row per actual material with its frozen representative
state/action. The original action-level RPS board and historical lead feed remain
separate disclosures. No API error is replaced by synthetic rows.

The matrix supports all eight native scientific properties and their actual
registry units. It shows material/family/profile, pressure/state, next action,
role, RPS, lower P/G/A bounds, scientific cells, review context and exact execution
constraints. Search, role filters and scientific-column groups change only the
presentation. Geometry and competing-order scientific properties are labeled
planned. The broader draft dictionary explicitly distinguishes its keys/units
from the live native schema.

Material details preserve the reviewed selection rationale, all alternative
assessments, original RPS review, native material/state/structure identities,
each scientific component/result, relation/unit, event revision/origin, run and
source pins, source occurrences and scope-specific scientific reviews. Native
details disclosures keep the matrix compact. Opening details moves focus and
scrolls to their heading; closing returns focus to the row trigger.

## Scientific and integrity boundaries

The interface retains the exact calibration disclaimer and limits comparisons
to one frozen campaign, budget, policy and release. It does not recompute RPS,
infer profile weights from family, select highest-score representatives or
relabel original assessment ranks as material ranks. Controls and mechanism
research remain separate. A negative-control role is not a measured negative.

Unknown, not computed, not applicable, conflicted and unreported quantities stay
distinct. Multiple observations are never averaged or collapsed to a preferred
number. Exact, interval and inequality forms, signed values and tiny nonzero
numbers are preserved. Scientific intervals are not labeled confidence intervals,
and exact scalars are not claimed to have zero uncertainty.

Only exact sampled-phonon-minimum results can carry the current narrow scientific
acceptance. The seven other property profiles remain unreviewed scientifically.
The original RPS review, extraction fidelity and recorded execution labels are
not substituted for scientific acceptance. Registry units do not establish
normalization; sampled phonon review does not establish full-zone stability,
upstream execution/convergence or superconductivity. Global scientific and ML
authority flags remain false.

There is no independently declared `main_barrier` in the existing sealed
contract. This increment deliberately displays **Main barrier not separately
declared** together with exact constraint codes. A reviewed versioned field and
operator workflow remain needed; neither a low policy dimension nor the first
reason is fabricated into a scientific barrier.

## Dedicated public client

The new reader uses public GET-only, no-cookie, no-store requests with no redirect
following. Catalog and detail responses have explicit byte/chunk/deadline limits
and strict UTF-8 decoding. Closed DTO validation checks versions, enums, units,
quantities, canonical IDs, exact representative/alternative/cell memberships,
selected context bindings, capability counts and the narrow scientific-review
scope. It mirrors the public minimum of at least one accepted narrow result.

Original JSON spans, not reserialized JavaScript objects, are SHA-256 checked for
payload, selection and campaign. This preserves Python float spellings. Duplicate
decoded keys, malformed Unicode, nonfinite numbers, nonzero numerical underflow,
oversized/deep payloads and trailing content are rejected. All five selected
catalog pins must match the detail, including publication and review hashes for
the same package UUID.

Refresh/selection invalidates the previous matrix immediately, aborts pending
work and increments a generation checked after cryptographic completion. Page
hide clears results; restored visibility reloads the catalog and requires another
explicit selection. Errors are static and source-free. There is no browser data
storage, automatic substitution or implicit retry. Server checks remain read-point
checks, not permanent authority or continuous monitoring of a stationary page.

## Independent findings corrected

- Native provenance edges are `source/derives_from/context/supports/refutes`.
  A typed dependency contains both its event ID and property/claim ID; the client
  now mirrors this shape instead of an incorrect one-target XOR.
- Narrow accepted-result inventory, locator bounds and RPS anchor/status shapes
  are explicitly checked without porting the scoring calculation to JavaScript.
- A nonzero numerical token cannot silently underflow to zero. Representable
  subnormal values and legitimate signed zero remain accepted.
- Material detail focus/scroll and close-focus restoration fix the offscreen
  detail problem for long lists and keyboard navigation.
- Accessible scientific-column names separate the label from its native unit.

Read-only independent schema/science audits and an independently prepared
external fixture capture supported these corrections. Frontend implementation
and repository integration were performed by the main agent. The existing-site
skill informed preservation of the established framework/style and accessibility;
the incompatible new Sites hosting workflow was not applied.

## Verification

| Check | Result |
| --- | --- |
| New scientific client/component module | 88 passed |
| Full frontend component/unit regression | 1,165 passed across 35 files; 174.60 seconds |
| Full frontend source regression | 38 passed |
| TypeScript, `--noEmit --incremental false` | Passed |
| Isolated production Next.js build | Passed, all 33 static pages generated |
| Original guarded public fixture capture | 1 passed, 25.78 seconds |
| Final repository-path portable capture | Same scenario repeated successfully, 1 passed, 30.55 seconds; owned services cleaned up |
| Original backend source pins | All 30 unchanged |
| Whitespace check | `git diff --check` passed |

The 88 new tests are included in the 1,165 total, not additional independent
coverage. Earlier checkpoints overlapped these results; three initial test
failures were corrected (configured API prefix, asynchronous empty-catalog wait
and accessible label/unit separation). An independent portable-writer checkpoint
also passed the same case in 60.01 seconds. Final repository-path regeneration
followed removal of one trailing blank line from that writer. These repeated
captures exercise the same synthetic scenario, not independent scientific
datasets. Native startup emitted the existing admin-route deprecated `regex`
warning; no new API warning was introduced.

The checked-in fixture strings decode to exact actual unauthenticated public
ASGI response bytes. They were generated through capability-owned PostgreSQL and
Redis, full dependency rights, original publication, new three-account companion
publication and two-scope phonon adjudication. Public GETs left the complete SQL
state unchanged; disposable services were cleaned up. The two variants share
one synthetic material and all eight native results. The original representative
scores 7100; the second explicitly selects 4400 and retains 7100 as an alternative.
Additional re-sealed client mutations are explicitly adversarial fixture tests,
not claimed publications or source verification.

Original decoded-wire SHA-256 values are retained in
`frontend/tests/fixtures/discovery-scientific-provenance.json`. The final portable
capture asset was exercised directly from its checked-in repository path:
`0a582c1bcd9dac404438cfe3e0f62a26d7cd7e5cab1b10c1797d13326e95557b`.
Regeneration writes only fresh private pytest output and never replaces fixtures.
The unchanged guarded runner, test capability and environment policy remain
required. See the contract guide for the explicit reproduction command.

The build used `/tmp/sclib-discovery-build.K3D6bx/frontend`, an owned source copy
with copy-on-write installed dependencies, unchanged Next.js configuration,
`/sclib` base path, the existing offline font fixture and inert API origins.
The Discovery production route compiled at 34.4 kB / 141 kB first-load JS in this
local build. This is not a performance benchmark or deployed measurement. Normal
worktree `.next`, existing development services, dependencies and hosting were
not changed. Browser/device visual QA and actual Linux release-image CI were
not performed in this increment. No full API-suite rerun or migration rehearsal
is claimed: backend source and schemas did not change.

## Issue status and next work

A fresh read-only GitHub list returned **38 OPEN items, including the tracking
issue**; DR04 #77 remains OPEN. This local interface increment does not constitute
remote delivery, issue closure or a reviewed real-data pilot.

Next bounded steps:

1. Add the curator's explicit representative-selection and review/publication
   interaction on top of the already governed companion endpoints. Keep roles,
   preview/commit pins and original-key recovery separate.
2. Define a small, independently reviewed main-barrier contract with provenance
   and applicability, rather than deriving it from RPS. Any sealed-contract
   extension must be versioned and compatibility-tested.
3. Complete authorized independent real-pilot review and publication evidence;
   evaluate AL01 / ML09 only against genuinely approved, leakage-audited data.
4. Deliver and close issues only when their full acceptance criteria and remote
   delivery authority are satisfied.

No push, PR, production deployment, real rights decision, source redistribution,
database backfill, provider/DFT execution or real-model training occurred. The
overall upgrade goal remains active.
