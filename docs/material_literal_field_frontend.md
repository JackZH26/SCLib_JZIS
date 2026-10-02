# Private literal material field workspace

The English workspace at `/dashboard/research/material-literal-fields` connects the fourteen original-text fields to usable private source imports and pending field cases. It preserves the existing sage palette, Inter typography and Tailwind 3 controls. This is a scientific curation surface: compact controls, visible raw printed values and field roles, and collapsed source text, hashes and policy explanation.

The route accepts bounded `material`, `field` and `candidate` query selectors. A selector never loads private source text or performs a write automatically. Authentication is owned by the existing dashboard/session boundary. The private backend flag and actual grants remain authoritative; the frontend does not enable either.

## Explicit forward flow

1. Refresh matching private prepare/source capabilities for the authenticated actor and session.
2. Choose an exact catalogue material ID and retained-record index. Load its private canonical context and the bounded public enrichment response. Show the exact result ID, paper ID and retained scalar summary before choosing a candidate.
3. Select one of the fourteen fields. Candidates must name the same exact result ID and raw-record SHA256 as the private context. Formula aliases do not pass this path.
4. Select **Prepare original source**. This read-only POST sends only the closed selector/pin keys. It never sends exported enrichment JSON as source text. The backend rereads the actual retained original chunk and returns a pending package, exact context and target skeleton.
5. Independently compile the returned package from canonical UTF-8 bytes. Check full source SHA256, codepoint positions, amount/unit/cue/uncertainty span hashes, shared source window, fixed field role, qualifiers, package hash and projection hash. Preserve the original printed value; quantities remain null and normalization remains `none`.
6. Explicitly preview and save the source import. Load its actual current source head using bounded raw-profile reads, then inspect its UUID detail and import receipt.
7. Explicitly preview and save the exact target operation from the prepared context. Load the saved target with its original receipt SHA256 and canonical proof before continuing.
8. Explicitly preview and save the matching source proposal. Target field and expression field must agree; a prepared flow also requires its exact retained-context hash. A paper link is a visible, optional proposal. Sample, phase, Work and selected-result identity remain unestablished.

Every source import, target and association is a real private append operation. Preview does not retain a write. The three operations each have their own exact request and preview pins. Saving does not confer interpretation, scientific acceptance, canonical promotion, public release or ML approval.

## Version and scope boundaries

| Boundary | Explicit raw profile | Existing default |
|---|---|---|
| Read query | `profile=material-literal-field/1.0.0` | No profile query |
| Source package/intake | `2.1.0` | `2.0.0` |
| Field-case request/receipt | `1.1.0`, fourteen raw fields | `1.0.0`, existing twenty-four fields |
| Retained context | Existing `1.0.0` selector contract | Same |

The raw capability advertises the combined 38-field registry and exact per-field request versions. The raw workspace exposes only its fourteen fields. The existing twenty-four fields retain their old request versions, mappings and validators. Raw read hold codes are an explicit separate capability property; they do not expand attempt-write reasons.

Maximum applied pressure uses `study_extent`. Minimum measured temperature uses `measurement_limit`. Ordering temperatures use `reported_order_transition`. These roles never become selected Tc conditions. Printed units and uncertainty strings remain original text, including TeX and line breaks. Numerical interpretation remains a later review task.

Source read DTOs retain selected text and immutable proof pins, not full source fragment bytes. Their selected spans, hashes, overlaps, projection identity and import receipt are checked independently. Optional model/sample/origin text outside the value window is checked against its own retained spans. Only preparation verifies the full returned fragment bytes. Publication revision, rights and scientific material identity remain unverified.

## Bounded reads and late holds

Source lists and field-case adapters preserve returned offsets and limits. The case workbench supports all fourteen fields, including an 8 + 6 continuation; no first-window completeness is inferred. Omitted historical entries remain explicit counts.

Source capture supersession and capture/import/association authority holds are shown as withheld pending source history. Historical row and canonical pins remain readable; held expressions are absent. The frontend refuses a late noncurrent source head before presenting a new association preview. Currentness is rechecked independently by the backend on preview/save and subsequent reads.

## Unknown write outcomes

Each operation has a 25-second UI timeout, even if the transport ignores cancellation. Before attempting a save POST, the workspace must successfully write and read back a closed, versioned recovery identity in actor-scoped browser-tab `sessionStorage`. The stored entry is bounded to 4 KiB and contains only actor, original request/preview/receipt hashes and IDs, plus source package/capture/manifest pins or field-case operation/context/field/chain pins. It contains no source text, values, package, canonical request or draft. Unavailable, corrupt or mismatched storage blocks pending writes; it is never treated as an empty ledger.

A timeout, network error, unverifiable response or server error locks the workflow. The frontend does not infer failure or rollback and never retries the POST. **Check original request** performs only the corresponding original GET outcome query. Independent canonical receipt proofs must match the exact original receipt SHA256, request/preview and source or case pins. A missing or unavailable outcome remains unknown. Recovery requires a replayed saved receipt and returns only confirmation pins; it does not restore a prepared package, private fragment or field case. Reload current sources or cases explicitly before continuing.

Session notifications, actor changes and unmounting clear private fragments and fence late responses while preserving the minimal tab-scoped identity. Actor B cannot see or recover actor A's pins; returning to A or remounting the route restores only A's original GET recovery control. The same actor can check an old immutable receipt under a new read-only session. Only a verified commit or GET outcome permits clearing that exact actor identity. If clearing fails, recovery remains held and writes stay blocked. This browser-tab scope does not promise recovery after the tab's session storage is destroyed.

## Validation and limits

The focused test suite includes all fourteen field/role cases, exact 1.0/1.1 and 2.0/2.1 separation, non-BMP codepoint spans, original unit/uncertainty/newline preservation, rehashed unit/role/window mutants, exact prepare pins, three distinct preview/save steps, source/target GET-only recovery across remounts and A → B → A changes, new read-only sessions, ignored-cancellation timeouts, stale navigation/auth/commit/outcome responses, corrupt or unavailable storage, failed writes/read-back/clears, late capture holds and all fourteen cases across two bounded pages.

Final focused validation passed 110 tests in the three new raw-field suites plus 33 existing numeric-source and field-case contract tests, for 143 tests in five files. TypeScript no-emit validation also passed.

Fourteen frozen synthetic packages and projection hashes were compiled independently by the Python contract and compared directly with the TypeScript compiler. Oracle source receipt SHA256: `7209271621a86a16fd8204c273814bf93c49da572ff2b1a0199fc006e1096038`.

The fixture stores each public deterministic expression identity digest separately as `expression_identity_digest`, then maps that unchanged digest into the exported projection's `expression_key`. This is an explicit data representation, not credential encoding or a scanner exception. All fourteen digests were independently recomputed from the frozen identity fields; the reconstructed oracle is semantically identical to the original Python JSON. The existing parity tests continue to compare the full projection and its independently frozen SHA256, including the reconstructed identity field. Production contracts and secret-scanning rules are unchanged.

These fixtures demonstrate protocol behavior. They are not real scientific sources, a production import, reviewer approval, an end-to-end native browser acceptance or evidence of extraction precision/recall. Root integration owns final registration, full frontend/build checks, owned native backend checks and actual UI acceptance. No browser, native service, production account, flag, grant or production scientific data was mutated by this frontend task.
