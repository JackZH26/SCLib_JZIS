# Batch64 — replayed private ML08 human-review report

Base: `605663f` on `codex/sclib-research-v2`, initially a clean worktree.
The preceding goal turn made progress by committing the completed workbench
verification and private canary CLI at the user's request. The full upgrade
goal remains active; this increment does not redefine completion around one
report feature.

## Priority and actual remaining dependency

Fresh read-only GitHub inspection found 38 open issues. ML08 #54 and ML09 #76
were read in full. ML08 is P1 and a prerequisite of real ML09 evaluation. Its
accepted deliverable must communicate event/atomic-result denominators,
missingness, state-association errors, independent-review dispositions and
curation effort without manufacturing science or hiding failure cases.

The previous batch supplied executable canary reconstruction and exact
conclusion binding. The human reviewing that package still had to inspect large
JSON documents. This batch adds a deterministic private report derived from a
fully replayed package, rather than a second scientific acceptance policy or
an automatically approved sample. It improves the human inspection/delivery
surface while the actual selection and independent reviewer remain unassigned.

The user has separately been asked whether pushing this development branch and
creating an evaluation/CI-only PR is authorized. No answer was assumed; no
remote write, merge, deployment or issue closure was performed.

## Implementation

- `scripts/ml_pilot_report.py`: `build` and read-only `verify`, reusing the
  existing canary replay, original schema/accounting and bounded file readers.
- `scripts/tests/test_ml_pilot_report.py`: 41 new synthetic tests of actual
  local files and CLI subprocesses, rendering and adversarial boundaries.
- `frontend/tests/e2e/ml-pilot-report.visual.cjs`: standalone isolated Chromium
  checks against an owned synthetic report; no website/API/mock-user execution.
- [Operator guide](../../ML_PILOT_REPORT.md), root README and canary-guide links.

The self-contained English HTML has fixed internal navigation and native
expand/collapse controls; no JavaScript, remote assets, forms or source links.
User-supplied markup, references and prose are escaped as text. CSP,
no-referrer/no-index metadata and a no-network browser check supplement that
boundary. They do not grant distribution rights or turn the document public.

It retains all original candidate events in selection order, effective result
associations, and every primary/secondary/arbitration revision. Failure events,
pending/rejected rows, conflicting alternatives and superseded effort remain.
Reported work/state/structure identities do not become independent material or
replication counts. Reported field coverage includes pending/rejected results
and is explicitly not extraction correctness.

All eleven priority fields and seven availability states are displayed with
their actual candidate/atomic denominators. Family/source-class/stratum groups
come from the frozen cohort. Additional per-group/per-field timing uses all
recorded revisions, including explicit zero and missing timing coverage; it
does not estimate unrecorded effort. No success threshold or optimal family
allocation is inferred.

The result table preserves normalized quantity inequalities, intervals,
approximation and uncertainty, unknown pressure, separate result origins,
criterion and method. Not-detected Tc displays **Not applicable (not detected)**
with the tested temperature window, not a point zero or ordinary missing Tc.
Original typed review records and source references remain available in the
disclosures; source context/protocol bytes themselves are not embedded.

The supplied go/narrow/stop and keep/narrow/defer recommendations are shown
verbatim as declarations, never generated or signed by the renderer. Every
authority flag remains false and model execution remains disabled.

## Exact replay, privacy and output behavior

All original input pins and local context files are required. Canary/conclusion
replay runs before and after rendering; the captured canary/conclusion identities
and renderer source are also rechecked. The report records the canonical canary
hash, raw conclusion pin and source/selection/log bindings. Its own file pin is
returned separately to avoid a circular hash. Verification rebuilds the entire
report; resealed changed counts or deleted history fail.

A boundary audit confirmed that the reused canary codec already refuses
noncanonical JSON. A new regression preserves that rule. The resealed-count
test uses valid canonical forged bytes and a correspondingly repinned conclusion,
so it exercises content reconstruction rather than failing only on whitespace
or a mismatched outer anchor.

This is **not redacted output**: private review prose, pseudonyms, locators,
permission references and small-group counts remain in the HTML. Text pasted
into review fields remains included. Native collapsed sections are not redaction.
Only authorized private storage/readers may use real input. Tests contain
conspicuous synthetic declarations and no actual humans or scientific events.

HTML output is bounded to 32 MiB, never silently truncated. Exclusive `0600`
creation refuses preexisting files/aliases and the closed evidence directory.
Final bytes, inode, single-link mode and parent identity are checked. This is
not atomic publication: a concurrent reader might see a partial file before
successful completion. Any post-create failure is `output_state_unknown`, not
rollback; possibly partial files remain for independent inspection. No existing
or uncertain output is automatically overwritten, deleted or retried.

## Verification history

- Initial targeted report run: 34 passed / 1 failed, 20.46s. The new arbitration
  fixture referenced the helper's default context hash instead of its actual
  retained synthetic bytes. Corrected the fixture, not the evidence gate; it now
  includes distinct secondary Tc and an unresolved state-association error.
- Combined report/canary/original pilot: 118 passed / 7 subtests, 29.60s.
- First full scripts: 2,031 passed / 36 subtests, 68.05s.
- First browser attempt failed an overspecified assertion that even a desktop
  table must scroll. Actual measured width was 1,350 / 1,350 pixels, with all
  columns fitting. Updated the test to require scrolling only when needed,
  while mobile still requires a usable scroll region.
- Desktop 1440×1000 and mobile 390×844 then passed with 60 event entries,
  11 field rows, zero external requests/page errors, inert hostile strings,
  working navigation/disclosures/focus and no document overflow.
- Visual inspection identified over-wrapped field identifiers in the mobile
  matrix. Widened columns, retained horizontal scrolling, clarified non-transition
  display and added separate-origin/zero-time/output-ceiling cases.
- Expanded combined scope: 123 passed / 7 subtests, 31.37s. Full scripts after
  the final rendering changes: 2,036 passed / 36 subtests, 91.36s.
- Full frontend: 44 files / 1,566 passed, 52.61s, followed by 38 passing source
  checks and successful nonincremental TypeScript checking. No production
  frontend/API/schema source was changed.
- Repeated desktop/mobile browser checks after final render changes passed.
  The final mobile field matrix and desktop expanded event/history screenshots
  were visually inspected. Temporary screenshots are in
  `/private/tmp/sclib-pilot-report-browser-q9Rzea`; they are diagnostics, not a
  committed or independently approved research artifact.

Final full-script regression after the canonical-byte and stronger resealed
content tests: **2,037 passed / 36 subtests**, 72.57s, including all **41 new
report tests**. Scoped Ruff, browser-harness JavaScript syntax and
`git diff --check` passed; all **124 relative Markdown links** in changed/new
documents resolve. The full frontend/browser results above retain their
unchanged rendering/application source scope. Every test process has a terminal
outcome; no running test or browser service is being left as assumed success.

## Remaining delivery and scope

The actual ML08 selection count and real human-review count remain zero; draft
templates are unchanged. Real pilot data, legal/source authority, justified
independent scientific acceptance, dataset/task applicability and actual runtime
admission still require their own evidence. A readable report cannot meet them
through its layout, hashes or passing synthetic tests.

No database test/rehearsal was rerun because no API/schema source changed.
Existing native wire fixtures and the 0074 migration report retain their original
bytes and selected-source scope; no historical artifact was resealed to claim
coverage of this new CLI. Exact-revision PR/CI delivery remains pending user
direction and actual execution. The current work remains uncommitted.

Next software dependencies remain controlled independent evidence review and
scope-bound acceptance, followed by guarded runtime/one-shot execution admission;
actual source selection and human review can proceed only with the approved
protocol, roster and permissions. No scientific, production or remote action is
silently inferred from this increment.
