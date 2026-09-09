# Public scientific Discovery matrix

Issue: [DR04 / #77](https://github.com/JackZH26/SCLib_JZIS/issues/77).
Implemented in batch 48 over the separately governed
[scientific companion](DISCOVERY_SCIENTIFIC_PROJECTIONS.md). This is a read-only
English interface in the existing Next.js / FastAPI application, not a new
hosting setup, production publication, scientific pilot or calibration result.

## Published data, not layout examples

The ordinary Discovery page now starts with `ScientificDiscoveryMatrix`.
The original RPS assessment board remains a separate action-level disclosure,
and historical candidate leads retain their separate legacy disclosure. The
synthetic matrix remains reachable only through the existing explicit
development-only `?preview=layout` path. Production components never import
synthetic fixtures or the demonstration value registry.

The public scientific catalog is loaded without cookies or authorization
headers. The visitor explicitly chooses a package; neither the first/latest
package nor the highest-scoring representative is chosen automatically.
The catalog currently exposes UUIDs and hashes, not human-readable campaign
titles. The selector consequently labels a package by UUID and shortened
payload hash; the loaded record then supplies its campaign, version and release.

Unavailable, disabled, malformed or changed publications do not produce fake
rows. A valid empty catalog says no companion is published. Configured but
unavailable companions are counted without exposing their private identities
or failure reasons. An HTTP or verification failure hides the material matrix.
The old assessment and legacy views are not substitute scientific publications.

## One actual material, one frozen representative

Row identity is the native `materials.row_id`, not the RPS material descriptor.
The row displays formula, family, frozen profile mixture, selected state and
pressure, next action, role, RPS, lower P/G/A bounds, scientific columns and
review/evidence context. The material order is the sealed descriptor order,
not a newly generated material ranking. Original assessment ranks, if present,
are explicitly identified as assessment ranks in details.

Discovery, mechanism research and reference/control roles have separate filters.
Search matches formula, family or frozen profile labels. Filtering and column
selection only change presentation; they never select a different action,
reweight a family or recalculate a score. A negative-control role is not an
experimental negative label.

Opening a material exposes its exact selection rationale, all alternative
assessment references and actions, original RPS review reference, state / sample
/ structure / run pins, policy contributions and source-scoped scientific data.
The detail heading receives focus and is scrolled into view; closing restores
the material-button focus. Tables have semantic headers/captions, labeled
horizontal-scroll regions and native keyboard-operable controls. These behaviors
have component coverage; they are not a substitute for browser/device visual QA.

## Scientific cells and scoring boundaries

The live registry contains eight native `rv2/1` scientific properties; see the
companion guide for the exact key/unit/group table. DOS is
`dos_at_fermi` in `states/eV/formula_unit`, and `superfluid_stiffness` is in `K`.
The broader planned dictionary is explicitly identified as a different contract.
Geometry and competing order have policy dimensions but no native scientific
properties in this version. Storage support, actual projected population and
implemented scientific-review profiles are shown independently.

Each cell retains its property key, registry version, quantity relation, unit,
availability and reason, exact result references and availability evidence.
Each observation retains event revision/origin, selected context, component,
source evidence edges, source occurrences, subject/review pins and normalization
status. Source edges preserve `source`, `derives_from`, `context`, `supports` and
`refutes`; typed dependencies retain both their event and property/claim ID.
An occurrence or forward dependency is not automatically direct supporting
evidence. A locator not disclosed remains explicitly undisclosed.

Exact scalars, intervals, one-sided inequalities and unreported quantities are
distinct. Zero, negative formation/phonon values, small nonzero values and signed
zero are retained. Multiple observations are not averaged or reduced to a
preferred result. Conflicted results remain declared conflicts, with every
observation available in details. Unknown, not computed and not applicable are
never imputed to zero. Intervals are not automatically confidence intervals;
an exact scalar does not mean zero uncertainty.

Only the current exact sampled-phonon-minimum profile can carry narrow scientific
acceptance. Extraction fidelity, original RPS review and the recorded run's
`Computed` / `dfpt` / `completed` labels do not establish that acceptance or
upstream execution. A sampled-phonon review does not establish full-zone
dynamical stability or superconductivity. A registry unit does not establish
normalization. Publication does not approve ML training.

The exact disclaimer remains:

> Policy-based research priority; empirical calibration pending

RPS is a policy priority in 1,000–10,000, not probability. P/G/A are policy
dimensions, not scientific measurements. Frozen signed point contributions
describe policy scoring, not measured positive/negative physical effects.
Missing support is not evidence against superconductivity. Comparisons are
restricted to the same frozen campaign, budget, policy and release, with a link
to [AL01 / #78](https://github.com/JackZH26/SCLib_JZIS/issues/78).

There is still no independently reviewed `main_barrier` field in the sealed
contract. The matrix truthfully says **Main barrier not separately declared**
and retains exact execution-constraint codes. It does not choose the lowest
dimension or the first reason as an invented barrier.

## Transport and byte verification

`frontend/lib/discovery-scientific.ts` owns a dedicated public reader. Requests
are GET-only, `credentials: omit`, `cache: no-store`, reject redirects, and use
the configured public API origin. A 60-second deadline accommodates the server's
55-second admission budget. Catalogs are bounded to 16 KiB; details to 4 MiB plus
64 KiB, with at most 4,096 stream chunks. UTF-8 decoding is fatal on invalid bytes.
Errors use static English text rather than reflecting raw server/source content.

Closed DTO validation checks versions, enum/quantity shapes, counts, canonical
identifiers, exact native units, unique material and assessment membership,
representative/alternative bindings, cell/result-reference correspondence,
selected native identities and conditions, capabilities and narrow review scope.
Global scientific/ML/publication authority flags remain false. The public
minimum of at least one narrowly accepted scientific observation is mirrored.
This is not a browser replay of database closure, rights decisions or RPS math.

A bounded JSON scanner rejects duplicate decoded keys, illegal Unicode,
nonfinite numbers, numeric underflow to false zero, excessive nesting and
trailing content. It locates complete raw `payload`, `payload.selection` and
`payload.campaign` JSON value spans. Web Crypto hashes those original UTF-8
spans directly, preserving Python spellings such as `1.0`, `-0.0` and `1e-05`.
It never substitutes `JSON.stringify` for Python's canonical float serializer.
Package, payload, selection, publication and review pins must all match the
selected catalog entry. Payload, selection and campaign byte hashes are checked.
Hashes establish byte consistency with that read point, not scientific truth
or permanent authorization.

Refresh or selection changes immediately clear the previous detail, abort its
request and advance a generation counter. Late fetch/hash completions cannot
restore old data. Page hide/visibility changes clear the matrix; a resumed page
reloads its catalog and requires an explicit selection again. There is no
local/session storage, automatic package substitution or background retry loop.
Server authorization remains a fresh read-point check, not continuous revocation
monitoring of an already displayed stationary page. Visitors can refresh to
recheck; the UI makes this limitation explicit.

## Evidence and remaining acceptance

`frontend/tests/fixtures/discovery-scientific-*.wire.json` contain JSON strings
of the exact unmodified synthetic public HTTP response texts. Decoding that
single string recovers the original bytes; an ordinary file import must not
reshape/re-serialize the response before testing its hashes. The accompanying
provenance file records the original response hashes and backend source pins.
The original fixture has RPS 7100. A separately sealed variant explicitly selects
4400 and retains the 7100 alternative. Both share one synthetic material and
scientific inventory: they are not independent research samples.

All eight synthetic scientific quantities were captured through actual guarded
PostgreSQL/Redis, dependency rights, original publication, new three-account
companion governance and unauthenticated public ASGI GETs. Only the phonon result
has actual synthetic two-scope adjudication. Production data, rights and settings
were not changed. Additional re-sealed test mutations are adversarial client
contract tests, not additional real/public approvals.

For explicit regeneration, the checked-in
`frontend/tests/fixtures/capture-discovery-scientific.py` is a portable fixture
asset, not an automatically collected test. Run it alone through the unchanged
disposable-test runner, from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/bin/redis-server --suite api -- \
  -p tests.conftest -c pyproject.toml \
  "$PWD/frontend/tests/fixtures/capture-discovery-scientific.py" \
  -q -s -p no:cacheprovider
```

The explicit `tests.conftest` plugin admits the runner's private capability before
application imports. The capture additionally permits only the owned database
and Redis loopback ports. The runner's API working directory resolves the
repository; no inherited DSN, output path or environment-forwarding override is
used. Only fixed filenames are created exclusively in an empty, owner-only
pytest temporary directory held by a no-follow descriptor. The final output
directory is printed; checked-in fixtures are never overwritten. New random
identifiers create new byte hashes, so compare contracts and provenance, not
expect byte equality between separate regenerations. The original checked-in
captures keep their original writer hash; the portable writer records its own
hash on regeneration.

DR04 is not closed by this interface: the independently reviewed real pilot,
scientifically justified explicit main-barrier contract, representative-selection
operator interaction and remote delivery remain separate work. No deployment,
empirical calibration or scientific discovery is claimed.
