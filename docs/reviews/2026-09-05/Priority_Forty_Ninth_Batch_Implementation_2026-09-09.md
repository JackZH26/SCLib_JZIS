# Batch 49 — exact curator selection preparation

Date: 2026-09-09.
Branch: `codex/sclib-research-v2`.
Starting commit: `531975a02ed78e212b6902314ad53328dc29f83f`.
Issues: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77),
[UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
API guide: [Curator selection preparation](../../DISCOVERY_SELECTION_PREPARATION.md).

## Outcome and scope

Adds a read-only backend preparation layer for the representative-selection
editor. Authenticated curators can inspect complete actual candidate states,
actions, structures and scientific result choices from one registered
distribution; prepare explicit representatives and declarations; and obtain the
actual compiled scientific payload and byte-exact commands for the unchanged
registration interface. The source bundle is supplied as a canonical file's
text, not fabricated from metadata or fetched through a client-provided path.

No frontend page is added in this increment. The public scientific matrix,
original RPS contracts/verifiers, native review profiles, database schema and
three-account governance writer remain unchanged. Preparation does not grant
rights, accept science, register a record or publish a package.

## Implementation

`discovery_selection_preparation.py` provides current curator access, compact
exact candidate context, closed explicit choice capture, complete selection
assembly and current full-payload compilation. `discovery_projections.py` adds
three static preparation routes ahead of the existing dynamic package route.

The original verified bundle is bound to the database package, inventory and
release. Native Material/state descriptor identities are rechecked. The context
includes all original assessments and material structures, all applicable native
property candidates and direct source/producer declaration references. Private
raw metadata and entire inventory/source bodies are not included.

Context and prepared texts are separate canonical JSON strings with exact UTF-8
hashes. This avoids browser float reserialization. The context pin includes the
actor/current grant and original base pins. No highest-score assessment,
structure or missingness is selected automatically. An actual null structure
means only unbound events, not all structures.

The server derives all alternatives and every matching result reference for the
explicit material/state/structure. Values, components, units and scores cannot
be client edited or omitted. All eight cells are required. Special missingness
and conflict declarations require applicable evidence; different components
are not relabeled as conflicts. Whole-package membership alone does not make
another state's source applicable.

Preparation rebuilds actual current scientific status. A context's frozen
quantity inventory is not a scientific-acceptance snapshot. Scientific decisions
changing after preparation invalidate the old payload for a new registration;
already committed historical recovery retains the unchanged original semantics.

Prepared preview/commit commands bind stable request, selection and payload
hashes. Clients must actually submit the preview to the original native writer
before explicit commit. Preview IDs are provisional; outer HTTP durability and
original-key outcome recovery remain distinct from the inner savepoint report.

## Admission and bounds

The existing authenticated browser/bearer identity, role system, no-store/
nosniff boundary and bounded request admission are reused. Source upload follows
a cheap curator check, then a new read-only repeatable-read transaction rechecks
role/session and exact current source status. No raw error or input value is
echoed to unauthorized or malformed requests.

Embedded bundle JSON is structurally preflighted before hydration. Canonical
checks reject duplicate keys, nonfinite values, invalid Unicode, trailing bytes
and noncanonical float spellings. Once-built indexes avoid a per-event scan of
the full dependency inventory. Candidate budgets are separate from the final
100-property selection budget; excess input fails whole, never truncates.

The API guide documents exact byte, node, material, assessment, candidate,
selected-property and evidence limits. This is a bounded pilot interface, not a
claim about measured production throughput or universal material-family schema
completion.

## Verification

The new guarded native module passed **75 tests** in **89.75 seconds**. These
include real disposable SQL → private HTTP context → exact preparation → native
rehearsal → durable registration → original outcome recovery, with complete
SQL-state equality checks for all read/preview steps.

Additional cases cover role admission before body allocation, session/grant
changes during upload, actor/regrant context drift, byte/node/depth limits,
closed fields, current material/Paper/Work/scientific holds, complete alternatives
and real lower-score selection, descriptor aliases, exact null structure,
same-capsule other-state evidence, signed/tiny/zero/unreported quantities,
multiple components, explicit missingness, stale scientific payloads and
candidate-versus-final selection budgets. All data and review decisions are
synthetic; tests do not assert a real scientific result or pilot.

The final combined guarded native regression passed **376 tests in 778.05
seconds**, including the 75 new tests above (not 451 independent tests). It
covered scientific cells, explicit projections, companion governance, private
and public Discovery HTTP, original distribution operators and new preparation.
Only the pre-existing `routers/admin.py` deprecated `regex` warning remained.
Changed Python files pass targeted Ruff checks and `git diff --check`.

Reproduction from the repository root, with the verified local native binaries:

```sh
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  tests/test_discovery_scientific_cells.py \
  tests/test_discovery_scientific_projection.py \
  tests/test_discovery_projection_governance.py \
  tests/test_discovery_projection_http.py \
  tests/test_discovery_scientific_http.py \
  tests/test_research_distribution_operators.py \
  tests/test_discovery_selection_preparation.py -q
```

The existing full API CI job discovers the new module automatically; no remote
Linux CI result is claimed. No migration or frontend code changed, so no new
migration rehearsal, browser QA or frontend build is claimed here.

An additional external actual-wire capture passed **1 test in 12.37 seconds**
on independently owned disposable services. It retained 14 original request/
response assets plus provenance, with eight properties, actual SQL sample/
structure rows containing synthetic data, and zero scientific acceptance. All 36 recorded source hashes
and all 14 asset hashes were independently checked against the retained files.
This capture is preparation for the next UI batch, not a second scientific
dataset or a public release. Its temporary assets are not added to this commit.

Capture writer SHA-256:
`3d16b2fcccbb83b6467c60e7a37130448f077b756859fbb204f72f6eb1b0b3c1`.
Provenance SHA-256:
`46296e5897e6b0d5c8c49b5d52cb8f7103d449630fbb9589041e852aa42bb783`.
The runner confirmed cleanup of only its own disposable services and temporary
service data. Existing development services were not used or restarted.

## Remaining goal work

Both linked issues were freshly read as OPEN. This increment does not close
either issue or the persistent upgrade goal.

Next is the English curator editor with explicit unchosen controls, upload and
hash checks, complete native observations, genuine native rehearsal, explicit
commit and original-request recovery. Independent reviewer/publisher handoff
also needs bounded governance history that remains available for protective
actions after source holds; do not weaken current scientific payload admission
to provide that history.

The separately reviewed main-barrier field, real source/rights/scientific pilot,
calibration and authorized remote release/issue delivery remain open gates. No
push, PR, remote issue mutation, deployment, production migration/backfill,
provider fetch, actual calculation or real approval was performed.
