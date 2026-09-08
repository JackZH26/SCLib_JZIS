# Complementary retrieval and complete input budgets

Status: local RG04b increment, 2026-09-08. This is not scientific gold-set
acceptance, a production release, or a claim about million-chunk recall.
See [scientific query routing](SCIENTIFIC_QUERY_ROUTING.md) for the preceding
numerical/explanatory routing contract and the explicitly unfinished mixed path.

## Scientific meaning

Ask can retain several **unchanged, separately cited chunks** when methods,
results and a table provide complementary context. No new merged source, result
tuple, experiment identity or independent replication is created by packing.
Every chunk still has its own content/evidence revision and fresh selection pin.
Existing capture identifiers and source locators are retained; absent page/table
locations are not invented. A bibliographic citation is not a complete locator.
The existing original-passage gate for explanatory mechanism/comparison requests
remains. Structured numerical requests remain provider-free and do not use this
packer or acquire generated explanations implicitly.

The operational source group is exact `paper_id + source_snapshot_sha256`.
Importantly, the current producer computes this hash from a **source-lifecycle
Paper catalogue snapshot**. It is not a raw PDF hash or authentication of one
original document, sample, experiment or scientific root. Current evidence roots
remain unresolved; `independent_support_count` is always null, and
`scientific_acceptance` is always the actual boolean false. A source group is
not an independently replicated result.

Accepted current `PaperWorkMap` rows may group sources for diversity limits.
Pending/rejected maps do not establish that grouping. Accepted here means the
mapping state, not acceptance of a scientific claim. Raw Work UUIDs remain
private; public `src:` and `div:` identifiers are domain-separated opaque
digests. Work/root scientific adjudication remains a separate prerequisite.

Section names and `has_table` are **retrieval role hints only**. A table flag
does not establish complete headers, units, row labels, captions or footnotes.
Methods/results from one group must not be combined into an invented numerical
tuple, nor may an unrelated sample/material borrow a condition from its neighbor.
Mixed methods/results section labels deliberately remain `other` unless the
separate table flag applies.

## Bounded deterministic selection

1. Retain the existing generation-pinned ANN/fulltext/formula fusion and rerank
   at most 100 seed candidates. No active generation means lexical-only legacy
   retrieval, not an unversioned ANN fallback.
2. For up to 20 ranked seed catalogue-source groups, inspect only same-generation,
   same-paper, same-snapshot original-passage metadata. Preflight at most 1,000
   metadata rows / 2 MiB before hydration. Append up to three alternatives for
   each methods/results/table role: at most 180 additions, 280 total candidates.
   Appended candidates have a `source_complement` retrieval label and no invented
   ANN distance or relevance score. No sibling expansion is attempted for legacy
   text without a retained catalogue snapshot.
3. Rehydrate the complete bounded candidate set through immutable-member
   verification, respecting the existing 8 MiB hydration bound. Apply typed
   evidence integrity, permission/currentness, source/Work holds and bounded
   material projection. Exclusion from a packed set never makes a candidate
   scientifically invalid; it can simply mean insufficient context budget.
4. Construct the private `evidence-packing/1.0.0` plan: rank-stable diversity
   first, new source coverage second, complementary roles last. Respect the
   requested maximum (1–20 chunks), at most 3 per catalogue-source group and
   3 across each accepted Work group. Legacy sources retain one chunk per paper.
5. Complementary additions require `original_passage` and a previously unused
   methods/results/table hint. Identical full-text hashes are globally deduped
   as a conservative context-redundancy heuristic. This can omit the same text
   under different attribution/metadata; it does not prove scientific equivalence
   and is not a substitute for root adjudication.
6. Trial costs serialize the **complete proposed final ordered input**, including
   final citation positions and packing metadata, the full question, source JSON,
   system/language instructions, model/profile and generation settings. They are
   not sums of excerpt lengths. Over-budget chunks are excluded intact, never
   silently cut or summarized. A malformed/nonmonotone cost fails closed.

The public summary counts **admitted packing candidates**, not the full corpus,
all retrieval hits, or all potentially relevant evidence. It includes exclusion
reason counts but no withheld candidate identities. Empty/base-over-budget plans
have no selected sources and make no generation call.

## Real provider input preflight

The `sclib-gemini-text-rag/1.0.0` profile is text-only. It freezes model, user
contents, system instruction and fixed generation settings (temperature 0.2,
maximum output 1,024, thinking budget 0) in one canonical payload. Tools, media,
caches, external content URIs and automatic routing are not admitted implicitly.

| Setting | Default | Hard bound / meaning |
| --- | --- | --- |
| `GEMINI_INPUT_BYTE_LIMIT` | 262,144 bytes (256 KiB) | 1 MiB; complete canonical application-payload resource bound |
| `GEMINI_MAX_INPUT_TOKENS` | 16,384 | 131,072; provider-observed input-token application limit |
| `GEMINI_COUNT_TIMEOUT_SECONDS` | 5 seconds | At most the remaining generation pipeline deadline |
| `GEMINI_TIMEOUT_SECONDS` | 30 seconds | Count plus generation, at most 120 seconds |

Packing trial measurement can inspect up to 64 MiB of complete canonical JSON
to reject an oversized candidate. That is **not** the send limit. Byte limits
are not model context-window specifications, transport-wire size measurements,
token counts or billing receipts.

Before generation, the actual SDK CountTokens call receives the same full
`contents`, `systemInstruction` and `generationConfig` as generation. The model
and client are the same, and the payload is reconstructed from frozen bytes
after counting to prevent mutation by a caller/SDK adapter. Unknown, noninteger,
nonpositive or excessive counts, an unsupported profile, errors, cancellation
and expired deadlines prevent generation. The SDK performs one attempt per RPC;
the outer count/generation operation is not retried.

Genuine provider failures cross the circuit boundary as typed exceptions carrying
the already sealed safe fallback/report. Thus a user-visible fallback does not
misreport provider health as success. Local preparation refusals are neutral;
a valid count above the application token limit is a successful count followed
by a local rejection, not a provider fault. Pre/post-dispatch cancellation is
distinguished privately without inventing a public token-count observation.

The implementation was checked against installed `google-genai` 2.11.0 using
its actual offline transport serializers, for both Enterprise and Vertex modes.
The REST API documents count inputs including system instructions and generation
configuration. CountTokens is a preflight observation, distinct from final usage
and cost. See [Google CountTokens REST reference](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.publishers.models/countTokens)
and [Google token-count guidance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/get-token-count).
No live provider accuracy/cost measurement was performed for this increment.

`input_budget.input_tokens` is the count observation; `tokens_used` remains
provider-reported total usage when actually available. Neither is fabricated
from the other. Unknown usage remains null. On an outer timeout, whether
generation started can be unknown (`generation_started: null`). The cancellation
event prevents a late CountTokens return from starting generation; it cannot
forcibly cancel an SDK request already in flight. A late result is withheld.

## Currentness, integrity and delivery

Each private selection pin now optionally binds the whole current Work mapping,
including no-map/pending/rejected cases, in addition to its existing complete
chunk, evidence, material/visibility and generation/event inputs. After the
provider call, a new bounded read-only repeatable-read transaction checks every
selected source and mapping again. No catalogue transaction is held across the
model call. A source/material hold, mapping mutation or activation change
withdraws the **whole old answer/citation set**; it does not relabel surviving
citations in an old draft. Empty plans also recheck the active generation.

The Work witness detects differences in the current row, not an audit of every
intermediate map edit. A mapping A→B→A with exactly restored row bytes has no
new durable event in this schema and is not claimed detectable. Generation
activation A→B→A has its separate immutable event check and remains detectable.

Packing metadata and input-budget reports enter the in-process answer integrity
fingerprint before the first seal. A caller attaching validated context to an
already valid old extractive fallback clones and reseals it without treating
that fallback as a new scientific draft. A seal only detects in-memory changes;
it never replaces the fresh database check or constitutes scientific review.

On withdrawal, public sources, group counts, selected payload accounting and
excluded identities are removed. An operational input-count/request-digest
observation may remain, explicitly describing the earlier prepared request,
not the withdrawn evidence inventory or current scientific support.

## Consumers and history

`AskSource.packing_info` is a closed `evidence-pack-item/1.0.0` object with its
ordered position, immutable chunk ID, opaque source/diversity groups, retained
catalogue snapshot hash, basis/role/reason and false scientific acceptance.
`AskResponse.evidence_packing` is a closed summary; `input_budget` is a separate
closed operational report. Counts, indices, unique identities, same-group
paper/snapshot consistency, role eligibility, limits and complete-payload bytes
are validated independently of citation syntax and scientific support checks.

The English frontend retains separate `[n]` links even for the same paper,
shows source-role hints without an independence badge, and separates byte
accounting, provider token preflight and unknown generation state. Existing
stale-request and query-remount guards remain in place.

Existing history can save per-citation metadata in its sources JSON, but it
does not retain a response-level packing plan/input report/generation snapshot
for reproducible replay. History labels this limitation and does not invent
such a plan from `tokens_used`, resurrect old source eligibility, or report
unavailable historical checks as current support.

## Unfinished scientific acceptance

Issue #75 remains open. True mixed numerical/explanatory association, verified
original roots, complete scientific table linkage, reviewer-adjudicated 100–200
question gold objects, frozen work/root-disjoint held-out evaluation, comparative
recall/support/error/refusal/latency/cost results and agreed release thresholds
remain separate work. Synthetic tests below are development regressions, never
an adjudicated benchmark or ML-ready training labels. Current pilot limits,
source permission policies and release-authority gates are unchanged.
