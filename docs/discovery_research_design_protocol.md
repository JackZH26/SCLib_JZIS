# Private Discovery research designs

This protocol retains researcher proposals. It does not certify a stable host,
create a physical material/sample/state association, predict Tc, execute an action,
change RPS, grant ML rights, or publish scientific results.

## Contract and admission

- Data: `discovery-design/1.0.0`; request: `discovery-design-operation/1.0.0`.
- Independent Alembic head: `0087_discovery_designs`, after unchanged 0086.
- Independent flag `DISCOVERY_DESIGNS_ENABLED=false` by default. The flag does
  not depend on source-property intake flags and does not grant a research role.
- Every read/write requires an authenticated active session and an explicit,
  unrevoked curator grant. Ordinary admin/reviewer flags are insufficient.
- Every response is private, no-store and non-authoritative. Reads recheck the
  live session/grant and the source/publication fence before response egress.

Routes under `/v1/research/discovery-designs`:

| Method | Route | Behavior |
|---|---|---|
| GET | `/capabilities` | Exact actor/session/grant and limits |
| GET | `/context` | Exact baseline capture and bounded safe reference |
| POST | `/operations/preview` | No retained write; pins exact operation |
| POST | `/operations/commit` | Expected preview SHA; append one revision |
| GET | `/operations/outcome` | Recover original request key and SHA |
| GET | `/designs?offset=…&limit=8` | Owner-only current heads, bounded page |
| GET | `/designs/{id}` | Latest eight immutable revisions with explicit total |

## Proposal content

Baseline kinds are unanchored, retained_result and native_property. An anchored
baseline requires exact material/record or property identity and the current
context SHA. A legacy bibliographic ID is not a reviewed paper-work foreign key.
Native references use the actual property/event/state/structure/run subject and
source lifecycle closure. Formula equality cannot substitute for this identity.

A design contains a host label, proposed state label, 1–8 explicit modifications,
requested pressure/temperature, pairing hypothesis and a decision-changing action.
Modification kinds are doping, substitution, vacancy, strain, interface, layer,
twist and pressure. Parameters remain researcher text; these are not a resolved
atomic site/occupancy/charge model or a candidate-generation specification.

The action records source_review, calculation or experiment, its question,
prerequisites and 2–8 distinguishable anticipated outcomes. At least two different
continue/stop/redirect decisions are required. Five resource bounds (CPU, GPU,
memory, storage, human time) are individually unknown or estimated. Unknown is
null, never zero; estimated raw decimal tokens preserve explicit zero.

## Immutable history and recovery

Operations are propose, revise and withdraw. Revise/withdraw pin the exact prior
revision and its record SHA. A linked proposal pins the parent owner/design/
revision/SHA and describes a proposed modification of another research design.
It does not establish a scientific derives_from edge or inherit any property.

The SQL ledger rejects UPDATE, DELETE and TRUNCATE; it prevents duplicate keys,
revision forks, self-links, cycles and cross-owner/withdrawn-parent links. Parent
traversal is bounded at 32. Withdrawn chains cannot be revived by revision.
Nonempty migration downgrade fails before removing retained history.

Preview cannot create a saved row. Commit checks exact canonical request,
preview, actor/session/grant and live context within one guarded transaction.
Unknown save responses retain only minimal recovery pins. GET outcome uses the
original key and request SHA; the browser never retries the POST automatically.

## Source currentness and proof disclosure

Source hold/withdrawal/retraction, negative native event validity and baseline
context drift hide current reference values while retaining immutable proposal
history. Source rechecks do not edit original record or receipt hashes.

Record proofs expose a context SHA and a safe projection SHA. They exclude raw
subject/context JSON and raw scientific source values. The bounded safe
projection has exact canonical JSON bytes (maximum 8192 bytes), verified before
rendering. Held projections and their canonical text are both withheld; their
original digest remains a historical pin. SQL validates the safe projection
against the captured source context before retaining it.

Scientific decimal JSON tokens are verified as received and compared with the
finite decoded value. The browser does not rewrite them with integer-only
canonicalization. Async validators detach data and actor/recovery pins before
awaiting hashes. Leaving the page or changing identity invalidates pending work
and clears private values; uncertain operation recovery retains only its pins.

## Interface and verification scope

The public Discovery workspace links to an authorized private history. The
private form uses the existing sage research styling, consistent controls,
folded source pins and resource estimates, and explicit requested conditions.
Its current baseline and its proposed modified state are displayed separately.

Synthetic native SQL/HTTP receipts exercise preview, commit, recovery, history,
roles, source drift/holds, direct-SQL forgery rejection and migration guards.
The checked-in native fixture is synthetic; it is not a discovered material or
an executed calculation. Browser playback checks rendering against these
receipts; native API tests separately verify actual persistence.

This is D1/D2 proposal preparation and version history plus D6 action design.
Stable-host certification, structured site models, bounded candidate generation,
comparable pressure scans, actual executions/result intake and calibrated models
remain separate engineering and scientific milestones in the comprehensive plan.
