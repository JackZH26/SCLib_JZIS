# Twenty-fifth implementation batch — connected mixed scientific retrieval

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `9e04e08` (twenty-fourth batch).
Priority: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
Specification: [mixed scientific retrieval](../../MIXED_SCIENTIFIC_RETRIEVAL.md).

## Outcome and scope

Ask now actually connects exact-parent numerical lookup and original-passage
retrieval for resolved mixed questions and typed numerical/evidence comparisons.
The website displays the two inventories separately, with a complete unresolved
record–passage association matrix and one final combined currentness check.
It does not send a missing scientific association to Gemini to invent an answer.

This is a real route and frontend consumer, not an unused new schema. It is
also **qualified dual retrieval, not established numerical/causal synthesis**.
Current Paper/Work/catalogue proximity and reported sample strings cannot prove
that an explanation applies to a particular numerical Result. Every selected
pair remains `not_established`; scientific acceptance stays false and independent
support count stays null. Real reviewed Result/claim/sample/original bridges,
gold acquisition, measured held-out evaluation and release acceptance remain
unfinished. Issue #75 and the overall upgrade goal remain open.

No migration or frozen 0052–0062 evidence/index contract was changed. No push,
PR, deployment, production mutation/backfill, original source release, real
expert judgment or paid provider evaluation was performed. Website copy remains
English; user questions and quoted scientific wording retain their language.

## Implemented

1. **Preparation consumed by an actual mixed coordinator.** Extracted
   `prepare_scientific_lookup()` from the existing lookup. Preparation does not
   commit/rollback/fresh-check and leaves exception cleanup to its caller. The
   single-consumption handle exposes immutable private raw-parent/member bytes,
   detached public DTO copies and one-to-one numerical selection pins. Full
   generation/result/raw-record/paper/catalogue identities are cross-checked,
   with a 16 MiB preparation bound and no copied vector bytes.
2. **Existing numerical/search compatibility.** The public lookup wrapper
   composes preparation, consumption, rollback, fresh selected checks and active
   generation recheck. Original quantity, uncertainty, pressure, classification,
   source-role, non-detection and eligibility logic remains the shared selector.
   Numerical pins now also capture current Work-mapping state; a changed map
   withdraws stale prepared inputs without declaring scientific authority.
3. **Actual dual routing.** Mixed Ask prepares numerical records, closes that
   read transaction, then enters the existing same-generation ANN/lexical/formula
   fusion, original hydration, complementary expansion and evidence packing.
   Derived Facts are never original explanation candidates. Clarification and
   pure mechanism paths remain separate; numerical conditions are not dropped.
4. **Comparisons retain named numerical properties.** A real HTTP regression
   found that appending "explain why" to "Compare A and B Tc" cleared the Tc
   request under the explanatory grammar rule. The parser now preserves those
   fields and its primary comparison intent. Typed comparisons also use the
   dual route; a pure mechanism comparison without typed quantities/evidence
   retains original-only explanation. This also intentionally gives original
   candidates to a numerical comparison without claiming the user asked why.
5. **One shared budget.** At most `max_sources` selected numerical parents and
   original passages combined, capped at 20. Numerical lookup reserves at most
   half (at least one); unused numerical capacity goes to originals. A one-input
   request can return the numerical row alone with an explicit context-limit
   notice. At most 100 association pairs; numerical `has_more` is retained.
   Complete local UTF-8 context accounting is reused, without treating bytes as
   model tokens or inventing a zero-byte request when no pack was performed.
6. **No unsupported generated mixed answer.** Static qualified text and source
   cards only. Gemini CountTokens and generation are not invoked; generation
   usage is zero, input budget is `not_requested`, assessment is `none` and
   answer mode is `abstention`. Semantic embedding/vector retrieval may still
   run, so zero generation tokens does not assert zero provider cost.
7. **Full private original presentation seals.** Before later awaits, the
   complete source DTO—including snippet, attribution, evidence descriptor and
   packing metadata—is frozen with its selected pin. Later projection uses new
   copies from those bytes, not a mutable DTO passed around beside an old pin.
   A seal is internal consistency, not public authentication or source rights.
8. **One combined final fresh check.** Numerical and original inputs must have
   unique, typed pins in the same generation, including grouping witnesses.
   The complete set is checked in one fresh read-only repeatable-read snapshot.
   A changed source, material/permission hold, Work map or activation event
   withdraws both inventories and all association dispositions. Empty sets
   still check the generation. No eligible subset of an old combined answer is
   silently retained after a failed check.
9. **Closed, complete association wire.** Each numerical parent × original
   source pair appears exactly once, bound to the parent's catalogue snapshot,
   original citation index/vector/evidence revision/record/full-content hashes.
   Same-catalogue proximity is explicitly not a scientific experiment link.
   Unknown fields, duplicate pairs, mismatched snapshots/generations and false
   scientific acceptance are rejected.
10. **English evidence-first UI.** Separate structured-record and original-
    candidate panels, a prominent missing-explanation warning and collapsible
    full association matrix. Citation indices refer only to originals, not
    numerical-row numbers. Invalid present metadata withholds rows, snippets,
    links and old backend answer prose. Existing async cancellation/query-change
    protections remain; a captured real disposable-SQL→HTTP synthetic response
    is also validated and rendered by the frontend regression suite.
11. **Honest history and documentation.** Mixed history stores only a static
    interaction notice with empty sources; it does not reconstruct unsaved
    numerical rows, original candidates or response-level association judgments.
    Routing/specification/public API documentation distinguish qualified dual
    retrieval from generation and complete context accounting from 280-character
    display previews. The original full-content hash is not a snippet hash.

## Independent review and defects resolved

- The initial early result-lookup branch prevented mixed requests from reaching
  original retrieval. The actual router now orchestrates both existing services.
- Separate numerical and original fresh checks would permit inconsistent final
  combinations. Numerical preparation now retains private pins and all selected
  inputs participate in one final check.
- Merely carrying public source DTOs beside old pins did not bind changed
  snippets or evidence metadata. Actual HTTP fault-injection regressions exposed
  that gap; frozen presentation+pin snapshots now detect changed bytes and keep
  returned copies isolated.
- Comparison intent had priority over mixed intent, while the explanatory rule
  could erase Tc entirely. The unchanged real query—not an easier replacement—
  now keeps its numerical selector and enters the dual flow, in English and
  supported Chinese notation.
- A no-candidate path initially risked publishing an invented zero-byte context
  measurement. It now leaves packing unrequested instead of calling zero an
  observed complete payload.
- Frontend visibility checks needed to reject coercible source-status arrays
  and sticky lifecycle holds. Mixed-only guards now withhold those candidates
  without weakening legacy visibility policy.
- Test-local asynchronous fixture loop scopes were corrected in the new suites;
  no production contract or assertion was weakened to work around teardown errors.

## Verification

All database tests use the guarded disposable native PostgreSQL/Redis runner.
New fixtures write exact 0060 parent evidence, actual 0061 embedding receipts,
and 0062 staged/published generations. Original passages deliberately carry
whole-paper extraction lists containing different samples, phases, pressures
and negative outcomes. Only transport is substituted; fixtures are explicitly
synthetic and cannot establish expert accuracy or original scientific roots.

Final checks passed against the completed backend code and test inventory:

| Check | Result |
| --- | --- |
| Full API, disposable native PostgreSQL/Redis | 3,759 passed; 347.69 s; 20 existing deprecation warnings |
| Full ingestion, inert database/Redis endpoints | 1,275 passed; 8.89 s; 34 existing warnings |
| Full script suite | 363 passed plus 36 subtests; 8.68 s |
| Full frontend components | 453 passed across 27 files |
| Frontend source checks | 35 passed |
| TypeScript | `tsc --noEmit` passed |
| Migrations | Disposable rehearsal through 0062 passed, including populated-history rollback guards and retained-generation staging/CAS/replay |
| Dependency locks | API and ingestion `uv lock --check` passed |
| Changed Python import/name checks | Ruff `I,F` passed |
| Patch whitespace | `git diff --check` passed |

The ordinary test total is **5,885**, plus **36 subtests**; focused reruns are
not added again. This batch adds 100 API and 52 frontend component tests relative
to the completed preceding batch. No tests were skipped in these full suites.
Database runners reported cleanup of only their own disposable services and
temporary data; production database configuration was not used.

Additional focused evidence includes 398 preparation/legacy regressions,
129 mixed/contract/old-route regressions, 175 parser regressions, and 200
old-route/complementary/budget regressions. A captured synthetic HTTP payload,
not a handwritten look-alike alone, crosses the backend/frontend validation
boundary. The UI evidence is automated component/source verification, not a
real-browser or production canary. An initial focused command referenced one
nonexistent test filename and collected no tests; the corrected run passed.

## Remaining acceptance and next dependency decision

Issue #75 was reread from GitHub and remains OPEN. Its first routing requirement
has stronger local end-to-end evidence, but this does not satisfy real original-
root adjudication, a reviewed 100–200-question gold set, independently approved
held-out thresholds, measured comparative recall/support/unit/refusal results,
provider latency/cost, PR/release CI or production canary acceptance.

A positive mixed explanation needs a reviewed exact extraction→claim/sample→
original bridge and associated source/currentness controls. Existing source-
occurrence witnesses can verify part of a declared relation; they cannot create
the missing bridge. Do not equate catalogue adjacency or an unresolved matrix
with a supported explanation, nor use its rows as positive ML labels.

The read-only dependency review selects **P1 DR02 / #74, the RPS release
delivery chain**, next. It is a prerequisite of the Discovery scientific matrix
in #77 and already has a route and frontend consumer. Concrete local gaps are
per-release catalogue fault isolation, a content-sensitive catalogue revision,
a bounded single-flight verification cache, and a separately admitted public
recomputation package with an offline verifier. Existing unrestricted internal
artifact dictionaries must not become a download merely because a bundle has
an administrative approval hash or a `public` flag. A newly disclosed safe
package needs its own canonical identity and explicit disclosure checks.

After that dependency, ML06 / #70 should feed ML09 / #76 with an actual
task-specific dataset builder, train-only preprocessing and baseline runner.
Neither derived Facts nor successful release freezing creates accepted training
labels. Missing reviewed training rights or insufficient independent groups
must yield an explicit no-go. #77 still needs a real reviewed pilot; #78 needs
reviewed anchors and actual action/outcome/cost evidence. These scientific
requirements cannot be replaced by synthetic fixtures or UI dictionary fields.

Source release, paid evaluation, production writes and external review
coordination retain separate authority requirements; no issue is closed simply
because this batch's tests are green.
