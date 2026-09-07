# Complete-input chunking and embedding response receipts

Status: local RG03 implementation increment, not active-index migration.
Related: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69),
[typed evidence](RAG_EVIDENCE_LINEAGE.md). Additive schema:
`0061_embedding_receipts`; contract: `sclib-embedding-completeness/1.0.0`.

## Scientific and operational boundary

An embedding must represent the exact complete input its metadata describes.
Silently removing a pressure, temperature bound, sample qualifier or negative
outcome can change a scientific statement. A successful embedding request is
nevertheless neither a scientific review nor proof of useful retrieval.

This increment enforces complete inputs, validates provider response reports,
and retains text-free completion observations. It does **not** establish that
vectors reached the index, that SQL and vectors are one active generation, that
source use is permitted, or that a result is accepted for ML training.

## Complete chunks and source coordinates

`sclib-section-chunker/2.0.0` applies the configured token limit to the entire
final string, including title/section prefix, body and overlap. The default is
512 tokens with up to 64 tokens of overlap. Configuration requires an integer
size of at least 64 and integer overlap below size; booleans and fractional
values are rejected. Counts use `cl100k_base`, not Google's tokenizer.

Original passages and abstracts are split into exact contiguous character
slices. Leading/trailing whitespace is preserved, Unicode is not reconstructed
by decoding incomplete tokens, and every new window advances into new source
characters. Overlap can shrink to preserve forward progress. Long sentences,
OCR text, CJK, formulas and tables follow the same full-string budget check.
This does not make an arbitrary table fragment independently interpretable.

The prefix uses at most `min(128, size / 2)` local tokens. Shortened metadata is
explicitly marked `[truncated]`; the original title and section metadata are
not overwritten. Locators retain the parsed section path and zero-based,
end-exclusive Python character coordinates. They are not verified PDF pages,
source-capture locations or permission grants. Existing SQL field limits can
still reject exceptionally long section labels; these are not silently
rewritten to a different source identity.

`sclib-fact-renderer/2.1.0` uses the same bounded prefix and exact full-text
count. A derived scientific fact remains one atomic statement. If it cannot
fit, the entire Facts construction fails with
`atomic_fact_exceeds_complete_text_limit`, rather than dropping qualifiers,
splitting the claim or returning a partial Facts list. Existing raw extraction
storage and the existing maximum of 40 rendered Facts are separate contracts;
this is not a promise that all extracted records become chunks.

## Provider admission and completion

Google documents per-input and per-request limits, response truncation
statistics, and rejection when automatic truncation is disabled. SCLib uses
those reported completion fields explicitly. See the [official input-limit
documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings)
and [text-embedding API reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/text-embeddings-api).

| Contract | Current SCLib policy |
| --- | --- |
| Reviewed model/profile | `google-vertex-ai`, `text-embedding-005`, 768 dimensions |
| Task | `RETRIEVAL_DOCUMENT` for indexing; `RETRIEVAL_QUERY` for queries |
| Provider limits | 2,048 tokens/input, 20,000 tokens/request, 250 inputs/request |
| Document local admission | Exact cl100k recount, at most 1,536/input and 14,000/request; normal chunks also obey the configured 512 limit |
| API query local admission | UTF-8 byte count, at most 8,192 bytes; not a provider-token estimate or guarantee |
| Truncation | Explicit `auto_truncate=False`; every response must report `truncated=False` |
| Completion | Exact response count, valid positive provider token count, provider bounds, finite nonzero vector of the expected dimension |

The model/profile is a deliberately narrow application allowlist, not Google's
complete model or dimension support. Local counts cannot certify provider
limits; the provider can reject locally admitted input. Unknown/malformed
statistics fail closed. SDK request-conversion tests verify `autoTruncate=false`
on the actual SDK transport shape. Raw provider exception bodies are not
returned to callers.

The complete document inventory is checked before the first provider call.
Responses are staged in memory and assigned to chunks only after every batch
validates. If a later batch fails, no chunk receives a new vector or completion
report; previous fields remain unchanged. Publication rechecks their current
text and vector hashes, so stale pre-existing fields cannot pass as new output.
Publication also validates the whole inventory before obtaining an index
client. This is input admission, not atomic cloud publication.

Vectors are canonicalized to the actual protobuf float32 representation.
Overflow, nonfinite values and an all-zero result after rounding/underflow are
rejected. The vector hash covers big-endian IEEE 754 binary32 bytes, with
negative zero normalized to positive zero. Text hashes cover exact UTF-8 input
bytes. No similarity or physics meaning is inferred from either hash.

## Closed metadata and additive SQL history

The completion report has exactly 17 fields:

```text
version, provider, model, task_type, output_dimensionality,
content_sha256, vector_sha256,
local_count_method, local_count, local_input_limit, local_request_limit,
provider_token_count, provider_input_token_limit, provider_request_token_limit,
provider_truncated, auto_truncate, completeness_status
```

`completeness_status=provider_reported_complete` means a trusted writer checked
a provider response, not a signed provider attestation. Supplied metadata alone
cannot authenticate an actual provider call. The ingestion writer independently
recounts actual text; the internal API append service does the same for cl100k
and verifies actual byte counts for the UTF-8 policy. Tokenizer initialization
must succeed before acquiring the shared SQL integrity fence. API and ingestion
lockfiles use matching tokenizer packages; tokenization assets must be available
in the operator runtime. An unavailable tokenizer is a failure, not an estimate.

`embedding_completion_receipts` binds each observation to the exact current
0060 evidence revision, evidence record hash, SQL chunk binding, full text hash
and vector hash. It retains a historical chunk key without a foreign key to
the replaceable Chunk row. SQL also verifies the current Paper/source snapshot.
The receipt stores no original text or vector array, and its only scope is
`embedding_response_only`.

Both arXiv and APS writers append receipts within the same SQL transaction as
the paper, chunks and evidence. An invalid completed input rolls back that
transaction. SQL-only legacy chunks may exist without fabricated completion
records; if either a vector or report is supplied, its valid counterpart is
required. The internal service defaults to dry-run and never commits the
caller-owned outer transaction. Exact replay rolls back fence-only changes as
well, preserving the complete database state.

Updates, deletes and truncation of receipt history are prohibited. Populated
downgrade refuses to erase history. SQL enforces closed metadata types and exact
source/evidence bindings; actual vector validation and tokenizer recount belong
to the trusted writers. A direct SQL writer cannot turn a fabricated report
into an independently authenticated provider receipt.

## Attempt observations and HTTP failure behavior

The arXiv and APS result dictionaries expose a text-free
`sclib-input-observation/1.0.0` summary scoped to `input_preparation_only`.
It records chunk/embedding stage status, static reason codes and elapsed
milliseconds; full-string cl100k totals/maxima; and validated returned
completion counts and their provider-token subtotal. Missing mocked reports
remain unavailable. A failed all-or-nothing embed call cannot attribute
pre-existing valid reports to the failed attempt. Unknown/partial provider
usage is not reported as zero. Cost remains explicitly unknown, with no
invented amount or currency. Summaries contain no text, vectors or raw receipts.
These are per-attempt observations, not a corpus dashboard or billing ledger.

`GET /similar/{id}` now returns a sanitized 503 for incomplete embeddings,
provider/ANN failures or timeout. A genuine successful empty lookup remains
200. Its provider work has one bounded attempt; after timeout a stop flag
prevents further calls when the in-flight blocking SDK call returns. The SDK
call already in progress cannot be forcibly cancelled. Existing paper-level
aggregation and scores are unchanged, not scientifically calibrated.

arXiv `skip_vector_search=True` currently skips upload, not embedding.
APS uses that flag to skip both embedding and upload. Neither flag authorizes
source acquisition, NER usage or other cloud operations. The tests use explicit
inert configuration, disposable SQL services and mocked provider/index clients.

## Rollout limits and next acceptance gates

Do not run production re-chunking or re-embedding from this increment. Existing
chunk IDs are still positional; vector upload is still separate from the SQL
transaction. A five-to-three shrink can leave old vector IDs, and replacement
can pair old vectors with newer SQL text. Neither 0060 provenance nor a 0061
embedding response receipt alone fixes that cross-system generation problem.

Remaining RG03 work is explicit:

1. Immutable generation and chunk-revision identities binding source, parser,
   chunker, full content, embedding profile and response receipt.
2. Stage build and vector inventory validation before explicit atomic activation;
   query hydration accepts only the pinned active generation and exact hashes.
3. Bounded read-only reconciliation for orphan/missing/hash/profile mismatches,
   interrupted publication and tombstones, with reviewed repair plans.
4. Disposable shrink/replacement/interruption/promotion/rollback rehearsals,
   preserving both history and the last valid generation.
5. Authorized canary measurement of corpus coverage, rejection/truncation,
   actual costs and build/query latency. No fabricated production baselines,
   recall gains or scientific accuracy claims from synthetic tests.
6. Current-SHA Linux/release-image CI, source-use review, reviewed deployment
   sequence and explicit production approval.

Apply the additive migration through the migration job before compatible
writers. Do not change frozen 0052–0060 schemas or ML04 v1 capsules. The new
renderer version also makes old renderer bindings non-current; plan the API
transition with generation migration and explicit user-facing availability,
not a silent bulk replacement. Roll back application behavior while retaining
immutable history; never delete receipts to force a downgrade.
