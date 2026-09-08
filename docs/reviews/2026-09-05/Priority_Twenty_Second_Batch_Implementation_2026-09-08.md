# Twenty-second implementation batch — scientific query routing

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `ebf8381` (twenty-first batch).
Priority: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75),
building on the bounded 0060/0061/0062 retrieval foundations.
Operational and consumer specification:
[scientific query routing](../../SCIENTIFIC_QUERY_ROUTING.md).

## Outcome and explicit limits

Search/Ask now distinguish qualified numerical/evidence-record lookup from
ordinary topic retrieval and original-passage explanation. Structured results
retain their original quantity relations, same-record conditions and exact
extraction/generation bindings; they are not presented as scientific approval,
an original quotation, independent replication or ML-ready labels.

This is RG04a, a **local implementation increment**, not full RG04 acceptance.
The 1,000-member/16 MiB generation pilot remains bounded. No real gold set,
corpus-scale recall, provider cost, Linux release-image acceptance or production
rollout is claimed. No database schema, frozen release, actual source record,
production service or paid provider was modified. No push, PR or issue closure
was performed. Website-owned copy remains English.

## Implemented

1. **Closed versioned interpretation.** Bounded English/Chinese grammar with
   raw text/spans, formula notation, Tc/pressure constraints, evidence categories,
   numerical/mechanism/comparison/general intent and explicit clarification.
   Unsupported phase/isotope/doping/criterion/time/logical qualifiers are kept,
   not silently dropped. Ordinary topic keywords remain usable. Whitespace-only
   requests return 422; excessive query scope returns clarification.
2. **Safe formula candidates.** Unicode/LaTeX numeric subscript equivalence,
   without isotope, D/H, phase/interface, charge or variable-formula collapse.
   Source scanning has its own complete-text bound and does not apply short
   query DTO limits to valid retained documents.
3. **Original same-record selection.** Full uncertainty/interval extents,
   strict bounds, raw/cached conflicts, explicit ambient pressure, independent
   origin/source role, negative outcome and local anomaly rules. Missing/zero
   pressure is not ambient; minimum detection temperature is not a Tc label.
   Search UI predicates use the same selector, including ordinary-formula and
   opaque-keyword requests, with remaining fulltext conditions preserved.
4. **Exact parent association.** Verify full input-record hash against the
   retained derived-Fact parent plus paper/source/evidence/manifest bindings.
   Paper-wide material lists on original chunks cannot authorize numerical
   rows. A neighboring record cannot borrow another parent. Duplicate parent
   renderings are collapsed only after their own visibility admission.
5. **Live governance and event checks.** Current source/Work/material/permission
   eligibility, bounded linked payloads, fresh selected-input recheck and final
   activation-event check. Changed/unknown evidence withholds prepared values.
   Actual replacement and source-compatible rollback preserve exact old
   extraction identities; source-changing rollback remains refused by 0062.
6. **Provider-free numerical output.** Static qualified Ask text, separate
   structured rows, zero provider tokens, no generated scientific numerical
   assertion. Mechanism/comparison synthesis only admits original passages.
   Mixed/evidence-conditioned explanations explicitly remain unperformed.
7. **Wire and frontend safeguards.** Count/status/UUID/hash/parent/generation
   consistency, actual boolean false authority flags, finite quantities and
   relation shapes. English query/extraction notices withhold malformed or
   mixed-generation data. Search does not confuse empty paper hits with empty
   extraction results. Query-key remounts and abort/request guards prevent stale
   Search/Ask responses, errors and interpretation under a different query.
8. **Honest history.** Static interaction records and metrics remain present
   for early clarification/lookup branches. Existing history stores no fabricated
   citations or unbound numerical rows; it explicitly discloses that bindings
   and rows are not retained. Reproducible historical answers remain unfinished.

## Independent review findings resolved

- Generic search terms were initially over-refused by the grammar. Added
  opaque-topic compatibility without relaxing explicit scientific vetoes.
- Applying legacy UI filters after safe selection allowed cached Tc=39 to
  bypass raw 39±5 K. Both natural-language and UI scientific entry points now
  use the same original-extent selector.
- Evidence-only predicates could fall through generic retrieval and disappear.
  They now trigger structured same-record lookup. Remaining opaque keywords
  are independently retained as generation-scoped fulltext conditions.
- Valid long/mention-dense source chunks exceeded query parsing caps. Separate
  source iteration preserves complete tokens/text and bounded memory.
- Explanatory comparisons were classified separately from mechanisms and could
  bypass the original-passage gate. Both nonstructured routes now apply it.
- Premature parent deduplication could suppress a valid alternative after an
  unavailable first rendering. Admission now precedes deduplication.
- Strict `Literal[False]` still accepted numeric zero under Pydantic equality.
  Explicit before-validators now require the actual boolean false; wire
  corruption tests cover both integer and floating-point zero.
- Existing currentness tests searched the entire response for a phrase that is
  now faithfully echoed as the user's query. They still require no old answer,
  citation or scientific result; only the input interpretation is excluded
  from that source-leak assertion.
- New rollback fixtures initially changed the scientific source snapshot while
  expecting old-source activation. Fixed the fixture to restore the exact
  source before rollback, and used unchanged-source rendering replacement for
  ABA. No frozen source-hash guard was weakened. Test-local session lifetimes
  and complete input token receipts were also corrected.
- The first full API run exposed one remaining legacy family-filter assertion
  requiring the documented consumer migration, and a 50 ms test deadline that
  sometimes expired during connection setup rather than the intended post-yield
  body. The latter now arms its test deadline at that body; production's 10 s
  deadline is unchanged. A separate outer test bound prevents a hanging fixture.

## Verification

Final verification after fixes, using a fresh guarded native PostgreSQL/Redis
database for the complete API run:

| Check | Result |
| --- | --- |
| Complete API suite | 3,173 passed; 20 existing deprecation warnings |
| Complete ingestion suite, inert connection targets | 1,275 passed |
| Script suite | 287 passed plus 36 subtests |
| Frontend source / component-unit suites | 35 + 346 passed |
| TypeScript | Passed |
| Complete migration rehearsal | Passed through 0062, including empty round trips, populated-history refusals and retained generation/CAS/rollback guards |
| API and ingestion dependency locks | Both checks passed |
| Changed/new Python Ruff I/F and final whitespace checks | Passed |

Total: **5,116 ordinary tests plus 36 script subtests**. Focused runs, migration,
type, lint and lock checks are not added to that ordinary-test total. The final
API run passed in 285.50 seconds with no skipped tests reported. These counts
describe regression coverage, not a scientific gold set or accuracy estimate.

One default-worker frontend run timed out an existing Discovery registry test
under concurrent verification. The complete unit suite passed with
`pnpm exec vitest run --maxWorkers=2`, without changing its timeout or assertions.
Final source-language checks and TypeScript also passed. Native macOS runs are
not Linux/release-image or live-browser deployment acceptance.

## Compatibility and remaining acceptance

Scientific Search clients must read `scientific_results` and its own count and
status, not `results[].matching_results`. No-active scientific requests now
explicitly return unavailable. Ordinary keyword/year-only browsing still
supports legacy lexical-only mode. See the specification for exact wire fields
and the current history limitation.

Issue #75 was rechecked read-only and is **OPEN**. Its dependencies retain
their separate acceptance gates. This increment does not satisfy mixed
numerical-plus-explanation, complementary multi-chunk support, original-root
adjudication or the real scientific gold evaluation requirements.

Next dependency-ready local increment: **RG04b bounded complementary evidence
selection**. Replace universal one-source-per-paper exclusion with a versioned
selection/packing contract that can retain complementary method/results/table
passages while keeping source/root independence counts separate. Preserve each
passage's locator and immutable member binding, a hard context-token budget,
Work/root caps, deterministic selection and post-generation currentness checks.
The existing RAG code limits output tokens, source count and selected-input
bytes, but has no complete input-token budget; add that accounting explicitly
rather than renaming a character/byte count as Gemini tokens. Start same-source
packing with exact `paper_id + source_snapshot_sha256`, retain one citation and
selection pin per unchanged chunk, and keep section/table roles as retrieval
hints. Accepted Work mappings do not prove sample/result identity; current
unresolved roots must not become resolved merely by grouping passages.
Do not count derived facts as independent roots or fabricate missing Work/root
adjudication. Keep true mixed synthesis and reviewed held-out measurement gated
until the required evidence/permission/Result contracts are available.

The persistent overall upgrade goal remains active. Production canary,
corpus-wide backfill, paid measurements, source release and external acceptance
require their own authority; implementation success is not permission to do them.
