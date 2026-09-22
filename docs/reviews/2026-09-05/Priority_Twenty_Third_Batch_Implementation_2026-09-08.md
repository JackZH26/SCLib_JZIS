# Twenty-third implementation batch — complementary context and real input budgets

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `80ddc52` (twenty-second batch).
Priority: [RG04 / #75](https://github.com/JackZH26/SCLib_JZIS/issues/75).
Operational specification:
[complementary evidence packing](../../COMPLEMENTARY_EVIDENCE_PACKING.md).

## Outcome and explicit limits

Ask now supports bounded complementary methods/results/table context from
retained catalogue-source snapshots, preserving every original chunk's citation,
hash and selection pin. It applies accepted Work diversity caps and complete
UTF-8 payload accounting, then requires the real provider's full-input token
preflight before generation. Failed/unknown counts, exceeded limits and expired
deadlines prevent generation; fresh source/group/event changes withdraw old
answers and citations.

This is a **local RG04b implementation increment**, not full RG04 acceptance.
It adds no database migration, changes no frozen 0052–0062 contract, and makes
no scientific gold-set, original-root, million-chunk recall, provider cost or
production-release claim. No push, PR, deployment, source release, production
backfill, paid model call or remote issue closure was performed. Website-owned
copy remains English. The overall upgrade goal remains active.

## Implemented

1. **Actual bounded complementary candidate expansion.** From at most 100
   hybrid seeds, inspect up to 20 exact paper/catalogue-snapshot groups and
   append methods/results/table alternatives under metadata and total inventory
   bounds. Every new candidate passes immutable generation/evidence hydration
   and the same live source/material/permission admission gates. No fabricated
   ANN scores or new merged excerpts.
2. **Closed deterministic packing plan.** Diversity first, new source coverage
   second, new original-passage roles third. At most 20 citations, 3 per source
   group, 3 across an accepted Work, and one per unresolved legacy paper. Exact
   repeated text is deduped as a context heuristic, not evidence equivalence.
3. **Scientific boundaries.** The current source snapshot hashes a Paper
   catalogue row, not a PDF. Section/table roles are heuristic; headers/units,
   original document identity and shared samples are not authenticated. Work
   mappings are only operational diversity/negative-governance inputs. Public
   independent support stays null and scientific acceptance stays false.
4. **Private Work witnesses and fresh recheck.** Bind all current map fields,
   including absence and pending/rejected states. Re-resolve selected mappings
   in the same new read-only repeatable-read snapshot as evidence/material/source
   and activation checks. Changed inputs withdraw the entire previous context.
   Empty and base-byte-rejected plans also check the active generation.
5. **Complete input preflight.** Canonical full question, source JSON, final
   citation metadata, system/language, model/profile and generation configuration
   determine exact trial bytes and a frozen request digest. Defaults: 256 KiB
   resource budget and 16,384 provider-counted input tokens. No truncation or
   character-to-token substitution. Count/generation bodies are equal under
   actual offline SDK serialization in Enterprise and Vertex modes.
6. **Deadline and usage honesty.** One outer count/generation attempt and one
   SDK attempt per RPC. Stop signal prevents a late count from starting a new
   generation. Already in-flight requests cannot be forcibly cancelled. Unknown
   token usage or start state remains null; preflight input count is separate
   from actual total usage.
7. **Seal, fallback and circuit integrity.** Packing and budget metadata enter
   the result fingerprint before first sealing. Valid legacy fallbacks can be
   cloned/resealed with caller context without reassessing fallback prose as a
   generated draft. Genuine provider failures cross the circuit boundary in a
   typed carrier retaining the safe sealed result/report; local no-call refusals
   are neutral and successful counts over the local token limit are not faults.
8. **Public wire and UI.** Exact positions, unique chunks, source-group hashes,
   paper/snapshot consistency, original complementary roles, group/count/cap and
   byte accounting checks. Separate English context-selection and provider
   preflight notices, one `[n]` per passage, no independent-evidence badges.
   Prior query/remount/cancellation protections remain unchanged.
9. **Honest historical display.** Saved per-source metadata is labeled as saved
   metadata, not current support. No response-level input/packing history is
   reconstructed from old token totals or per-citation labels.

## Independent review findings resolved

- Universal paper deduplication was replaced only after immutable admission;
  merely increasing a chunk limit would not recover missing method/table siblings.
- Catalogue snapshot semantics were traced to the actual ingestion hash function.
  Prompt/UI/specification explicitly avoid calling it raw document authentication.
- Complete source metadata changes trial payload size; both trial and final
  construction use identical ordered packing descriptions and source positions.
- An initial return of safe provider-error fallbacks bypassed failure accounting
  and reset the circuit. A typed safe-result carrier now preserves reports while
  recording true failures, without retrying the paid operation. Local refusal and
  successful over-budget count cases have separate health semantics.
- Late CountTokens completion after an outer timeout could otherwise start an
  unnecessary generation. Cooperative cancellation and the remaining deadline
  are checked before/after counting and before generation; unknown usage stays
  unknown rather than becoming zero.
- New grouping fields had to enter the first result fingerprint, not be appended
  to an already sealed fallback that would then be reassessed as a new draft.
- Current accepted Work assignment can change without a lifecycle visibility
  change. A separate complete mapping witness now catches that change and
  removes old source labels/counts. Mapping bytewise A→B→A is explicitly not a
  durable audit event; generation event ABA detection is unchanged.
- The initial lexical read lacked the timeout/error boundary already present for
  formula/hydration reads. It now shares a bounded, sanitized retrieval step.
- Closed input-budget DTO and frontend guards require true booleans, complete
  counted state and no fictitious observation fields in `not_requested`.
- Test-local cross-event-loop teardown errors were corrected by using the
  existing function-loop session fixture pattern. No production boundary was
  weakened. Multi-paper fixtures use actual writers, 0060/0061/0062 staging,
  publication/activation, HTTP admission and currentness; only provider/ANN
  transport is substituted, and every passage is explicitly synthetic.

## Verification

Final verification used a fresh guarded native PostgreSQL/Redis database for
the complete API suite and migration rehearsal. No production database or paid
provider was used.

| Check | Result |
| --- | --- |
| Complete API suite | 3,406 passed; 20 existing deprecation warnings; 303.60 seconds |
| Complete ingestion suite, inert connection targets | 1,275 passed |
| Script suite | 287 passed plus 36 subtests |
| Frontend source / component-unit suites | 35 + 401 passed |
| TypeScript | Passed |
| Complete migration rehearsal | Passed through 0062, including retained histories and independent populated-history rollback refusals |
| API and ingestion dependency locks | Both checks passed |
| Changed/new Python Ruff I/F and whitespace checks | Passed |

Total: **5,404 ordinary tests plus 36 script subtests**. Focused reruns,
migrations, type/lint and lock checks are not added to that ordinary-test total.
The final full suites report no skipped tests. These synthetic regressions do
not constitute independent scientific review or a benchmark accuracy estimate.
Native macOS and offline SDK verification are not Linux release-image or live
browser/production acceptance. No threshold or test assertion was weakened to
obtain a pass.

## Remaining acceptance and next dependency-ready work

Issue #75 was re-read and remains **OPEN**. RG04a + RG04b do not satisfy true
mixed numerical/explanatory association, reviewed original roots/table links,
expert-adjudicated scientific gold objects, held-out comparative recall/support/
condition/unit/refusal measurements, actual provider latency/cost or production
acceptance. The bounded 1,000-member/16 MiB retained-generation pilot remains.

Next local increment: establish the **versioned scientific adjudication and
evaluation object contract**, including exact source/generation/result/prompt
bindings, reviewer judgments/disagreement handling, development versus held-out
work/root grouping and fail-closed release gates. Prepare schema, validator,
protocol and synthetic development fixtures without fabricating real reviewers,
real gold labels, independent roots or external acceptance. True mixed synthesis
must remain explicitly gated until source/Result association is supportable.

Production canary, real source redistribution, corpus backfill and paid evaluation
still require their separate authorization; local implementation is not such
authorization. No issue should be closed merely because regression tests pass.
