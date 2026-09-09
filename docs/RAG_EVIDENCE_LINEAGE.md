# RAG evidence lineage and conservative Facts rendering

Contract: `rag-evidence/1.0.0`. Additive schema: `0060_rag_evidence`.
Related work: [RG02 / #65](https://github.com/JackZH26/SCLib_JZIS/issues/65),
[claim-support contract](RAG_SUPPORT_CONTRACT.md), [API](API.md).

## What the implementation establishes

The new registry records which actual indexed bytes came from which retained
machine-extraction snapshot, under which producer version and current source
snapshot. It distinguishes an original-passage producer, abstract producer and
derived Facts producer. Unregistered legacy text remains `legacy_unknown`.
Kind is obtained from database lineage, never promoted from a section name.

This is **not** scientific acceptance, confirmation of the original source,
an independently replicated result, permission to quote/index/train on text,
or a canonical material/state/result identity. All descriptors have
`root_status=unresolved`, `support_eligible=false`, `independent_evidence=false`
and `scientific_acceptance=false`. Permission is `unresolved` or `restricted`;
there is no positive grant path in this version.

As a deliberate consequence, current live descriptors cannot establish
positive scientific support. The existing narrow checker remains available for
synthetic/internal compatibility tests, but live delivery is limited to clearly
labeled, unverified extracts or abstention until reviewed root and permission
admission is implemented. Missing data is not a negative physical result.

## Additive storage and transaction contract

| Table | Retained role | What it does not establish |
| --- | --- | --- |
| `rag_extraction_revisions` | Immutable exact input-record hash, extractor/projection versions, source snapshot and closed text-free scientific projection | A reviewed canonical Result or a fully reconstructable historical material/state record |
| `rag_evidence_revisions` | Immutable chunk key, full content/binding hashes, kind, exact parent, renderer version, optional capture link, source locator and unresolved/restricted state | Original-root approval, permission, independent confirmation |
| `chunk_evidence_current` | Replaceable pointer bound by SQL to the exact live chunk and source snapshot | Durable historical text or permanent currentness |

Immutable revisions do not reference mutable `chunks` through a foreign key.
Deleting/replacing indexed chunks preserves their historical revisions; only
the current pointer can cascade. A plain, indexed historical chunk key permits
bounded lookup after invalidation. Any retained restricted declaration remains
restrictive even if a later automatic rebuild submits `unresolved`: this
version has no authority to clear it. Changing chunk content invalidates the
pointer and produces a stale descriptor, not a downgrade to legacy text.

Both arXiv and APS SQL writers append lineage inside the same paper/chunk
transaction. A derived candidate must match the actual persisted Chunk record
and Paper extraction; actual database hashes are computed by the writer.
The internal registration service requires an actual current Chunk parent,
provides a default dry run, and never commits a caller's transaction. Exact
internal registration replay preserves rows and the research-integrity epoch.
Re-ingestion may append a new source-bound revision. IDs and hashes supplied
by callers are not accepted as authority. SQL guards enforce immutable history,
exact source/parent association, exact pointer binding, bounded closed
projection/locator shapes and nonempty downgrade refusal.

No original prose, quotes, source contexts or arbitrary NER strings are copied
into the immutable projection. It preserves normalized quantity relations,
units, bounds/uncertainties, origin, source role and a positive-interpretation
veto. Its full-record hash also binds omitted input fields. It does not retain
the full original formula/sample/state text for historical replay. SQL shape
validation is not a physical plausibility or complete cross-field scientific
validator. Canonical Result revisions, exact reviewed state identity and
source-artifact access remain separate work.

The 0054 shared integrity fence coordinates writes. Original text-use review
and 0055 metadata-publication permissions are different contracts: metadata
publication grants cannot authorize excerpts, RAG model input or training.
ML04 v1 capsules remain unchanged and do not claim to include this new graph.

## Scientific rendering and normalization

Facts renderer: `sclib-fact-renderer/2.1.0`.
NER normalizer: `sclib-material-ner/2.1.0`.

Renderer 2.1.0 adds a full-input token bound and disclosed shortened metadata
prefix. An oversized atomic fact is rejected without splitting its scientific
qualifications. Historical 2.0.0 revisions remain retained, not rewritten or
automatically current. See [complete-input and embedding contracts](EMBEDDING_COMPLETENESS.md)
for the rollout boundary and additive 0061 completion observations.

- Preserve Observed, Computed, Inferred, AI-Proposed and Unknown origins,
  primary/cited roles and classification conflicts. Paper genre or extraction
  confidence cannot manufacture an experimental or primary origin.
- Reparse preserved raw quantities. Never convert `Tc < 100 K` into `Tc = 100 K`,
  replace an interval by a midpoint, discard uncertainty or accept booleans and
  nonfinite values as measurements. Contradictory raw/typed proposals remain
  unresolved rather than selecting a favorable cached scalar.
- Preserve negative, malformed and contradictory outcome markers. A negative
  report cannot become a positive Tc. Minimum test temperature is separate;
  a Tc value is never reused as a missing detection limit. Conflicting outcomes
  suppress the positive numeric interpretation.
- Keep explicit pressure separate from unknown pressure. Include reported
  criterion, sample, substrate, regime and magnetic field when unambiguous.
  A bulk label or absent pressure is not ambient evidence.
- Preserve malformed-field flags so normalization cannot erase a negative
  veto or origin conflict. Raw extraction remains unchanged. New producer
  versions are generated by the normalizer, not accepted from model output.
- Do not append free-form comments or original source quotes to Facts.
  The legacy `build_authorized_chunks` function name is not a rights grant.

This changes future ingestion, not all previously indexed Facts. No production
backfill, corpus-wide rerender or vector rebuild is included.

## Retrieval, model input and UI

`SearchMatch` and `AskSource` expose a closed `evidence_provenance` object.
The resolver admits at most 300 requested chunks, checks each actual SQL row
against a 1 MiB text/material limit and enforces an 8 MiB combined limit.
Missing, oversized or changed rows are stale/unavailable, not inferred valid
legacy text. Initial Ask and Search provenance work have a 10-second application
deadline; Search returns sanitized 503 on lookup failure or malformed inventory.

Known restricted/stale evidence is excluded from Ask selection and Search
excerpts. Prompt/fallback helpers independently reject malformed descriptors,
content-hash mismatch and restricted/stale text; they also suppress extracted
material data for a withheld excerpt. Only an exact empty dictionary retains
the old internal text-policy compatibility. It grants no new rights.

Before generation, Ask pins the selected actual bytes, source/material review
states and descriptor, then releases its read transaction. After the provider
returns, a fresh 10-second read-only `REPEATABLE READ` check recomputes Paper,
accepted Work, explicit Material and lineage states. A change, SQL failure,
timeout or budget failure discards the draft and old sources/assessments and
returns an explicit abstention. No database lock spans the model call. This
check records only snapshot consistency; a later change is still possible.
Internal result sealing includes the provenance descriptor, preventing changed
metadata from reusing a previously checked answer as a fresh result.

English UI distinguishes derived Facts from original quotations, current
catalogue binding from acceptance, and saved lineage from live checks. Source
cards and claim inspection show conservative provenance. Unattributable,
restricted, stale or malformed claim excerpts are withheld. A reported
`supported` badge cannot override unresolved typed evidence. Saved answers
remain untouched historical snapshots, explicitly not revalidated.

## Remaining acceptance and rollout gates

1. Reviewed original evidence roots with exact source-version and locator
   validation; explicit permission-purpose events for reproduction, model input,
   indexing and ML/export. No inferred permission from public accessibility.
2. Canonical reviewed Result/state revision bindings, complete retained replay
   artifacts where permitted, semantic-version migration policy and scientific
   review workflow. Current snapshots are machine-derived pending metadata.
3. Positive support admission and independent-root deduplication only after
   those reviews. The current solution prevents amplification by admitting no
   positive independent support; it does not claim a complete root graph.
4. [Final-output history receipts](ANSWER_HISTORY_RECEIPTS.md) now preserve
   new answers' selected generation references, with separate current Paper/Work
   warnings. Old histories are not backfilled. Complete provider-input archives,
   scientific revalidation and permission-approved research replay remain distinct.
5. ML04 v2 dependency closure, RG03 index generation/reconciliation and explicit
   corpus migration/rebuild plans. Large-corpus latency/contention measurement,
   current-SHA Linux/release-image CI and staging rollout are still required.
6. Human-adjudicated, work/root-separated scientific evaluation before claiming
   precision, recall, calibrated confidence or ML label suitability.

Deploy the additive migration through the existing migration job before a new
API/ingestion binary. Drain older incompatible writers before rollout. Use a
separately reviewed small canary and rights audit; do not infer production
approval from native synthetic tests. Downgrade is allowed only while the new
ledger is empty; populated immutable history must not be deleted to roll back.
