# Materials source recovery

The Materials recovery endpoint and offline CLI expose source candidates in a
separate namespace. They never overwrite retained records, select catalogue
properties, approve science, admit ML training examples, or grant source rights.

## Implemented workflow

`api/services/material_enrichment.py` is the pure implementation. It accepts
explicit retained material records and exact source captures, checks source
membership, text hashes, revision identifiers and locators, and produces:

- Pending literal Tc, pressure, method, sample-form and text-structure candidates.
- Column-bound lattice, measurement-temperature and atomic-site table candidates.
- Explicit nominal/refined composition proposals, with the linking source
  capture retained on downstream candidates. These do not establish equivalence.
- Source-scoped matches for retained Tc in sentences using a sample identifier
  rather than a chemical formula. These explicitly lack local subject binding.
- Per-field recovery routes and missing reasons. An unsuccessful bounded search
  is never labelled `not_reported`.

Pressure units, bounds and intervals use the existing scientific-value parser.
Parenthetical crystallographic uncertainties preserve the raw representation and
are normalized to uncertainty in the final displayed digits; their statistical
interpretation stays unspecified. Tc onset and zero-resistance values are
separate. A narrow `respectively` grammar aligns two formulas with two Tc values.
Measurement temperatures, transition widths and ambiguous multi-material Tc
statements are excluded from direct Tc extraction.

`source_captures_from_chunks` adapts exact SQL exports. Generated Facts and derived
facts are excluded. Unknown historical prose remains `legacy_unknown`; a paper
row capture hash is never called a publication version.

The live reader inspects at most 32 retained records, stratified across at most
eight eligible source papers and evenly spaced through each paper's retained
record positions. It retrieves at most 40 chunks and 120,000 combined source
characters. `inspection_scope` reports current eligible and raw retained totals,
the number actually inspected, and record/paper truncation. Missing fields in a
truncated record sample carry an explicit incomplete-inventory reason. The
original records remain unchanged.

When more than eight source papers are linked, a metadata-only `EXISTS` probe
identifies papers containing indexed nonempty bounded chunks. The reader selects
indexed papers across the complete ordering before evenly filling remaining
slots. This avoids permanently omitting an indexed ninth paper. The probe does
not establish source permissions, originality or currentness; final chunk
admission still applies the same source, visibility and derived-text guards.

Pairing symmetry and competing-order classifications currently require a
specialist extraction step. Their coverage says `specialist_extraction_needed`,
not that an implemented extractor searched and found nothing. Numeric extractors
and classification extractors have separate coverage. Selected-source DOI and
arXiv metadata yield allowlisted primary-publication links, without asserting a
verified source version or releasing restricted/stale source facts.

Synchronous parsing and hashing run with `asyncio.to_thread`, behind a two-worker
semaphore. Cancelling a request does not release its CPU slot until the underlying
worker terminates. The existing `claim_support.is_derived_source_hint` is shared
by live retrieval, offline SQL adaptation and direct-capture validation, covering
generated/derived/Facts/summary section variants, generated paper identifiers,
and embedded legacy `Section: Facts` or `Section: Derived` headers.

One fact in one source span may reference several retained records. The output
deduplicates that fact and exposes `retained_result_refs` containing each
`result_id` and `record_sha256`. Its representative singular fields are preserved
for existing callers. The reference count does not count independent studies.
Composition proposals referenced by other facts use the final deduplicated ID.

## Offline CLI

Use a Python 3.11+ environment containing the API dependencies. None of these
commands connects to PostgreSQL, calls an LLM, or runs a scientific calculation.
Keep source exports and captured publisher text in a private directory.

Create a snapshot from explicit JSONL exports:

```bash
python scripts/materials_enrichment.py snapshot \
  --materials /private/materials.jsonl \
  --sources /private/sources.jsonl \
  --coverage /private/source_coverage.json \
  --output-dir /private/snapshot
```

The command prints the independent manifest SHA-256. Save it outside the bundle
and supply it when planning:

```bash
python scripts/materials_enrichment.py plan \
  --manifest /private/snapshot/manifest.json \
  --expected-manifest-sha256 SAVED_MANIFEST_SHA256 \
  --output-dir /private/recovery
```

The default report omits excerpts. `--private-excerpts` additionally retains the
short private contexts and candidate JSONL for source review. Neither mode grants
redistribution permission. Snapshot hashes prove input integrity, not scientific
validity or publication time.

Optional local candidate import is replay-safe and checks candidate identities:

```bash
python scripts/materials_enrichment.py import-candidates \
  --report /private/recovery/report.json \
  --ledger /private/candidate_ledger.jsonl
```

This is a private local candidate ledger, **not a canonical database importer**.
`pending_tc_records.jsonl` is an additive review handoff compatible with the
existing typed-claim mapper; it is not an authorized INSERT package. The existing
scientific-correction endpoint refuses originally unreported quantities and must
not be used to bypass a new-result import/review workflow.

For a specified arXiv or APS HTML source:

```bash
python scripts/materials_enrichment.py capture-html \
  --paper-id arxiv:0912.2752 \
  --url https://arxiv.org/html/0912.2752v2 \
  --source-revision arxiv:0912.2752v2 \
  --output-dir /private/primary_capture
```

The adapter freezes the actual HTML bytes, creates paragraph/table captures with
text checksums and locators, and preserves comparison-table column boundaries.
Explicit HTTPS hosts and redirects are allowlisted. A captured URL/revision does
not establish material-state association, source rights or scientific validity.

## Genuine October 1, 2026 pilot

The read-only production export covered 19 materials across 15 families, 2,257
retained records and 23 source papers. From 362 current chunks, all 39 generated
Facts chunks were excluded. The remaining 323 had unknown historical lineage.
The final extraction produced 66 distinct source candidates referencing 74
retained-record matches, including 22 Tc, 4 pressure and 2 space-group candidates.
No candidate was promoted. These are bounded pilot counts, not whole-library
coverage estimates.

Two primary-source captures were additionally checked:

- [YScH10 source](https://journals.aps.org/prb/abstract/10.1103/PhysRevB.109.054512):
  `respectively` alignment recovers 116 K at 140 GPa for YScH10 and distinguishes
  110 K for YScH8. Direct Cmmm–YScH10 text associations stay pending and do not
  assert validated coordinates. The five deduplicated candidates include the
  separately reported 140–250 GPa stability-range candidate.
- [Pt-doped BaFe2As2 source](https://arxiv.org/html/0912.2752v2): 36 source
  candidates include 23 K onset, 21.5 K zero resistance, I4/mmm, lattice
  `a=3.9772(9)` and `c=12.988(6)`, structure temperature 250 K, atomic-site
  positions, As `z=0.35422(9)`, and the refined Fe:Pt same-site ratio
  `0.953(4):0.047(4)`. Linking the nominal table composition to the refined
  catalogue composition is an explicit pending proposal. Parent BaFe2As2 table
  values do not fill the doped material's fields. No full coordinate model is
  created from these text facts.

`api/services/resources/material_enrichment_seed.json` contains only factual metadata, candidate
values and source pins from these primary examples. Full source text stays in a
private capture store. Before serving an additive seed, validate its digest and
each candidate identity, require every referenced retained record fingerprint to
be current, require the exact paper to remain eligible, and keep the seed outside
canonical property projections. Candidate public identities are unchanged by
omitting private `evidence_text` because its separate SHA-256 remains pinned.

The real offline snapshot/plan/import was executed: 66 candidates were first
inserted into a private local ledger; replay inserted zero and reused all 66.

## Next data run

1. Export a bounded, current source-scoped sample using read-only queries. Pin
   material records, exact paper rows and actual source chunk bytes. Do not call
   unknown or derived chunks original passages.
2. Run deterministic recovery first. Prioritize retained values missing locators,
   existing text structures and missing pressure/Tc criteria. Measure precision
   by source and field, and review false or unresolved identity matches.
3. Fetch full text and supplements only where access permits. Capture table
   headers, columns, footnotes and source versions. Record scope completeness;
   this extractor has incomplete recall even for a complete captured source.
4. Review nominal/refined composition and sample/pressure/state relations before
   turning a source candidate into a property record. Reviewed source text and
   reviewed coordinate files have separate gates.
5. Use the existing additive ingestion, reviewer and immutable passage-link
   workflows for genuinely reviewed records. Retain original values and record
   superseding interpretations instead of editing them in place. External MP,
   COD or NOMAD entries require their own structure/state matching and stay
   external references until that matching is established.
6. Create explicit computation tasks only for remaining scientifically useful
   gaps, with input structure, composition, pressure, method and convergence
   requirements. The recovery CLI itself does not calculate Tc or stability.

Validation: 35 pure extraction/CLI tests and 25 DB-free reader boundary tests
cover units, uncertainty, exact source pins, formula/sample distinctions,
comparison tables, unknown lineage, derived Facts exclusion, paper/chunk/character
limits, restricted/stale evidence, metadata-only public egress and local replay.
Reader tests additionally verify record sampling through deep positions, work
outside the event-loop thread, and cancellation-safe CPU concurrency limits.
The API integration tests exercise the actual endpoint and held-material routes
through the repository's disposable-service runner.

## External reference services

Eligible material detail pages also offer separate Materials Project, COD and
NOMAD references. These panels never select retained catalogue properties or
promote a matched composition to an established sample/phase identity. External
provider requests begin when their folded panels are expanded.

All three routes reuse the source-aware fixed-composition guard before cache
lookup; isotope, variable occupancy, unresolved dopant or interface notation is
not replaced with a parent formula. Each API route checks current catalogue
eligibility and source partition, then rechecks the source epoch after retrieval.
Responses are private and `no-store`. Successful provider projections may use a
24-hour internal Redis cache. Provider requests have a 512 KiB identity-encoding
body limit, an overall 12-second deadline and per-provider shared request budgets.
Unexpected compression is rejected in these bounded paths. Existing unbounded
Materials Project client callers retain their prior transport compatibility.

- `GET /materials/{id}/external_references`: up to 20 MP computed composition
  references with task IDs and the provider's reference-condition limitations.
- `GET /materials/{id}/external_structures`: up to 20 COD structures. Preserve
  declared and calculated cell-content formulas separately, diffraction method,
  lattice values and uncertainties, temperature/pressure and revision links.
  COD pressure fields use kPa, not GPa. Missing pressure does not imply ambient.
  A provider coordinate flag or external CIF link is not a validated local
  coordinate model. Measurement origin stays unresolved unless explicit method
  metadata supports diffraction. Held, erroneous, retracted or explicitly
  theoretical records are not admitted by this experimental-reference adapter.
- `GET /materials/{id}/external_calculations`: query public NOMAD metadata,
  inspect at most 21 entries and display at most 20. Preserve individual task,
  structure, parser, method/program and allowlisted repository/citation links.
  Archive temperature, pressure and functional were not inspected; they are not
  inferred. MP/OQMD/AFLOW overlap is visible and task counts do not count
  independent experiments.

`no_match`, `not_applicable` and `unavailable` remain distinct. Provider failures
cannot become claims that the provider lacks data. References retain snapshot
hashes and retrieval times; source IDs/hashes sit in expandable provenance.
See [COD schema](https://wiki.crystallography.net/cod_mysql_schema/),
[COD API](https://wiki.crystallography.net/RESTful_API/), and
[NOMAD API](https://docs.nomad-lab.eu/1.4.3/howto/manage/program/api.html)
for provider field semantics. Scientific state matching, coordinate validation
and canonical review remain required before any future promotion.
