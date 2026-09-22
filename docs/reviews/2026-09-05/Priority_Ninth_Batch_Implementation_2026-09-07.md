# Ninth implementation batch — priority follow-through

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.

This is a local implementation and verification record, not production rollout,
scientific acceptance or issue closure. The preceding batches five through eight
were checkpointed in local commit `52930eb`; batches one through four were already
in `c6f05f1`. Neither checkpoint implies publication on the remote branch.

## Priorities and actual delivery

| Priority | Issue | Delivered in this batch | Remaining acceptance gate |
| --- | --- | --- | --- |
| 1 | [EN04 #52](https://github.com/JackZH26/SCLib_JZIS/issues/52) | Release-image versus locked test-runtime inventory capture/comparison in all three Python CI jobs; strict v2 provenance and isolated capture | Actual Linux/Docker CI artifacts and release revision/digest review |
| 2 | [SC11 #63](https://github.com/JackZH26/SCLib_JZIS/issues/63) | Pending-only local structure proposals, removal of whole-paper phase broadcast, API/UI integration, disclosure and identity-stability guards | Authoritative revision-aware association review and real pilot evidence; no accepted coordinates/relations yet |
| 3 | [ML08 #54](https://github.com/JackZH26/SCLib_JZIS/issues/54) | Proposed protocol, empty templates, schema and offline review-accounting validator | Approved source scope, strata, 60 actual events and independent human reviews |

All three remain open for their outstanding gates. Local test counts are not a
percentage of the 37 execution issues completed. GitHub remains authoritative
for live issue status; this batch does not close issues or bypass the previously
reported GitHub write-access restriction.

## EN04: make runtime drift detectable in CI

API, migration and ingestion retain their separate locked test environments and
now each compare against an image built from the corresponding release Dockerfile.
The six CI jobs, frontend frozen installs and disposable-service safeguards remain.
Inventory v2 binds the project/lock/collector bytes, revision, platform, interpreter
and actual installed versions. Only documented dev-only packages can be extra.

Image inspection uses an immutable image ID, an overridden isolated Python
entrypoint, no network, read-only rootfs, non-root UID and no mounts or app startup.
It neither starts the API nor invokes ingestion/migrations. Builds themselves need
normal dependency-download access in CI. Existing release workflow gating already
requires successful tests; its configuration was inspected, not remotely changed.

No Docker/uv installation or real image build occurred locally. Package comparison
does not prove Python patch/OS-library/ABI equality or that a later rebuilt and
published image has the same bytes. See [EN04 follow-up](EN04_Runtime_Parity_Followup.md)
and [safe testing](../../TESTING_SAFELY.md).

## SC11: distinguish structure proposals from material properties

### Extraction and scientific meaning

- Whole-document phase regex matches no longer fill every extracted material's
  phase. Unassigned mentions retain bounded local context and character locators.
- Typed `structure_claims` preserve a field/value, exact local quotation and
  explicitly supplied locator. Literal material/label co-occurrence and simple
  pressure/doping/sample checks can describe a proposal, never approve a relation.
- Separate or conflicting materials, samples/states, cited/tentative contexts,
  missing/repeated quotations and historical normalized-only labels stay pending.
- The input hash identifies the bounded assembled NER text, not an authenticated
  publication revision. No formula/phase label becomes a CIF, coordinate artifact
  or coordinate-derived feature. Scientific acceptance remains false.

### API and website interaction

`structure-evidence/1.0.0` is rebuilt from original records on read. A cached or
source-provided accepted envelope cannot supply a reviewed property. The public
aliases `structure_phase`, `crystal_structure` and `space_group` remain null.
The aggregation writer likewise withholds these rebuildable summary aliases;
original records and stored override decisions remain intact.

Material detail offers expandable pending proposals and unassigned mentions,
with source identifiers, hashes, locator diagnostics and declared subject/state.
List, variant and bookmark views consistently show Pending source review or Unknown.
Phase proposals do not inflate linked-field coverage. Other atomic measurements,
including Tc and separately selected lattice parameters, retain their contracts.

The phase filter is explicitly unavailable: nonempty API requests return 422.
Saved website URLs receive an explanation and a deployment-prefix-aware removal
link that preserves the other filters, resets pagination and requests a fresh
document. The UI does not silently drop the condition
or misrepresent an unavailable search as no matching materials. Website-owned
copy remains English.

### Disclosure and identity safeguards

Source lifecycle status is not excerpt redistribution permission. Recomputed
public proposals withhold quotation text and retain only bounded hashes/locators
and permission-unresolved notices. Newly introduced extraction-only quotation
containers are recursively removed from raw material, source, search and paper
DTOs and alternate nested payloads. Original database records are unchanged.
This narrow guard is not a general license or free-text PII sanitizer; ML07's
broader recursive permission and release-admission work remains necessary.

Derived `structure_evidence` is excluded from existing claim, property, filter,
material-semantics, anomaly and Timeline identity calculations. Annotation-only
changes therefore do not create a new original Tc occurrence. Actual source
assertions, including original `structure_claims`, remain identity-bearing.
Identity and scientific decisions use originals before public disclosure guards;
a redacted public DTO is not a complete raw-hash reconstruction export.

Details and limits: [structure evidence contract](../../STRUCTURE_EVIDENCE_CONTRACT.md).

## ML08: preparation, not invented pilot results

The [pilot protocol](../../pilot/ML08_Pilot_Protocol.md), JSON schema and templates
currently contain **0 selected events and 0 human reviews**. The offline CLI checks
selection freezing against a separately retained hash, append-only review
revisions, second-review comparisons and disagreement dispositions. Events,
atomic results and declared work/sample/state/structure identities stay separate.

Inaccessible or failed events cannot be silently removed from the fixed candidate
denominator. Missingness, error types, recorded active time and timing coverage
are reported separately; missing time is not treated as measured zero. Negative
observations are not manufactured from absent Tc. Final readiness is only
readiness for human signoff, never automatic scientific or ML acceptance.

Before the actual pilot, humans must approve source/storage permissions, family
and condition strata, selection allocation, the real event manifest, reviewer
roles and independent second-review subset. A software agent is not the second
independent human. No accuracy, recoverability, curation-time result or reviewed
canary dataset is claimed from the synthetic tests.

## Verification

| Check | Result |
| --- | --- |
| Full API suite, owned disposable PostgreSQL/Redis | 1,320 passed |
| Full ingestion unit suite, unreachable placeholder service URLs | 674 passed |
| Full scripts suite | 102 passed; 36 subtests additionally reported |
| Frontend source regressions | 35 passed |
| Frontend component regressions | 245 passed |
| Total tests, excluding subtests and duplicate targeted reruns | **2,376 passed** |
| TypeScript | Passed |
| Production build, API destinations restricted to loopback | Passed; 28 static-generation entries |
| Controlled `/sclib` build and synthetic desktop/mobile browser smoke | Passed; real recovery click and list render |
| Disposable migration head and supported round trips | Passed at `0051_material_semantics` |
| Changed Python files, Ruff I/F; whitespace checks | Passed |
| Shared scientific module byte parity | Passed in regressions |

The API suite retains one pre-existing FastAPI `regex` deprecation warning.
These are local/synthetic software checks, not corpus accuracy, production health
or real Docker execution evidence.

### Browser verification

The final controlled `/sclib` build used an owned loopback fixture API and browser
network guards; no live material/source data was requested. The explicit recovery
click produced exactly one full-document request, preserved family/Tc filters,
removed phase/page and rendered a Pending structure row. Expanded source hashes,
locators, declared state and separate unassigned mentions were inspected. Deliberate
synthetic secret excerpts/private context were absent from returned HTML/RSC;
stale phase values did not inflate linked coverage.

At a 390px viewport both material detail and list retained a 390px document width;
the structure panel was 358px wide. Desktop and mobile screenshots were visually
inspected. There were zero JavaScript page errors and zero non-loopback request
attempts. Expected CSP denials of the deliberately unavailable loopback client-auth
endpoint are not authentication-flow validation. All owned Next/browser/mock
processes were closed.

Earlier local RSC soft navigation was intermittently delayed; that observation
is not a diagnosed production incident. The final recovery check depended on
actual full-document navigation, without a test-only navigation fallback.

## Next acceptance and development order

1. Review and run EN04 in the authorized Linux CI workflow; do not call mocked
   Docker tests its final acceptance evidence.
2. Confirm the ML08 human/source/selection decisions and freeze the real pilot
   before reviews; retain all unsuccessful cases. Use its outcomes to refine
   SC11 association review, not to retroactively change the selected denominator.
3. Continue [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57): exact source
   revisions and result-level availability, preserving Unknown rather than
   backdating later results to a work's earliest publication date. This unlocks
   revision-aware shadow loading and the later research dataset work.

No production connection, data backfill, full-corpus extraction, paid model call,
deployment, remote CI dispatch or source redistribution was performed. No new
database migration is required by this batch's pending-only SC11 contract.
