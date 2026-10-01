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
record positions. Its **40-chunk budget is shared across papers**, with at most
120,000 combined source characters. It counts each selected paper's indexed and
bounded-length chunks before fetching text, allocates slots in paper round-robin
order, and ranks formula/table matches within each paper. Whole chunks of 1–20,000
characters are admitted; text is never cut to fit the character budget. A later
whole chunk may still fit after an earlier one is omitted. Matching measured
lengths at the text-read stage prevents a concurrent change from enlarging the
budget. This is fair bounded allocation, not a guarantee that every paper
provides usable evidence after permission, currentness and derived-source checks.

`inspection_scope` and per-paper `source_coverage` expose raw/current record
totals, indexed/bounded chunk counts, considered/inspected/supplied chunks,
excluded and omitted reasons, and record/paper/chunk/character limits. An
unsampled paper has unknown indexed/omitted counts and an explicit paper-limit
reason. Missing fields in a truncated record sample carry an incomplete-inventory
reason. Neither this request nor a zero candidate count establishes complete
full-text or supplement coverage. Original records remain unchanged.

The coverage label **Not extracted** leaves source inspection unresolved: this
status can mean an unimplemented extractor, an unavailable capture, or a checked
statement whose subject or scope still needs review. It does not mean the source
was unexamined or that the property was absent. Missing provenance, method or
state metadata displays **Not supplied in this record**, limiting the
gap to that record. Explicit supplied `Unknown` values remain unchanged;
**No candidate in checked chunks** remains a bounded extraction result, not a
claim about the complete paper or supplement.

When more than eight source papers are linked, a metadata-only `EXISTS` probe
identifies papers containing indexed nonempty bounded chunks. The reader selects
indexed papers across the complete ordering before evenly filling remaining
slots. This avoids permanently omitting an indexed ninth paper. The probe does
not establish source permissions, originality or currentness; final chunk
admission still applies the same source, visibility and derived-text guards.

Pairing, unconventional-state, gap and order statements now use the independent
bounded classifier described below. Its incomplete grammar and rejected-scope
findings have separate coverage from the established numeric/literal extractor.
Unimplemented paper-field extraction remains `not_extracted`; an external
recovery route is not an actual lookup hit. Selected-source DOI and arXiv metadata
yield allowlisted primary-publication links, without asserting a verified source
version or releasing restricted/stale source facts.

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

## Second iteration: source-statement classification

`api/services/material_classification_candidates.py` emits the independent
`material-classification-candidates/1.0.0` contract using
`materials-source-statement-extractor/1.0.1`. The numeric/literal candidate
namespace remains separate; its sample-form correction uses numeric extractor
`materials-literal-extractor/1.0.1` as described below. The enrichment report adds separate
`classification_candidates`, `classification_review_findings`,
`classification_counts` and extractor-version fields; live public windows are
bounded independently to 100 candidates and 100 findings.

Admitted local statements retain their field, raw/normalized label, author-report
role and stance (`reported`, `fitted`, `proposed` or `not_detected`). Supported
fields are `pairing_symmetry`, `is_unconventional`, `gap_structure`,
`reported_order` and explicit `competing_order`. A gap described as nodeless is
not converted to s-wave or conventional superconductivity; odd parity is not
converted to p-wave. A reported order generates a competition candidate only
when that relation is explicit. Scoped non-detection remains a source statement,
with method/window limitations, rather than a material-level false value.

The grammar requires a locally identified fixed composition or a uniquely
resolved local variable composition. A narrowly coded, same-paper sample alias
can use an independently pinned definition proposal; both definition and claim
captures remain traceable, and association is unreviewed. Reused aliases with
conflicting or unresolved doping definitions, arbitrary contextual parentheses,
single-element substrates, comparisons, cited/background assertions, uncertain
or rejected hypotheses, unbound negation, contradictory detection clauses and
multiple state-condition mentions require review. The extractor prioritizes
precision and does not claim complete recall. Candidate and finding bounds are
reported rather than silently discarded.

Coverage counts source-statement candidates separately from retained values.
Rejected subject/assertion scopes leave an explicit review count and
`not_extracted` status when neither a retained value nor a usable candidate exists. A bounded implemented
search with no local candidate may say `not_found_in_checked_sources`, with its
incomplete-recall and full-text/supplement limitations. Public output omits source
excerpts and free-form private context; nested locators, alias-source metadata,
methods, condition quantities and claim labels are constrained and validated.
All candidates remain pending, with scientific acceptance, ML approval, public
release authority and database mutation flags false.

### October 2 same-input benchmark

The benchmark reused 19 materials, 15 families and 2,257 retained records. The
frozen adapter excluded 41 generated/Facts chunks from the 362-chunk export,
leaving **321 normalized historical source captures**. Comparing the old module
at commit `4ef49494e634412b49b7d82208bb87a713ca312e` with the second iteration on
these exact inputs produced **65 legacy numeric/literal candidates and 71
retained-record references in both runs**. Every candidate ID, value, metadata
object and legacy count was equal; the canonical candidate-list SHA-256 was
`5dcf69800e72c71aa3f7a96b258c08b685f3e8e14e807e63d805f4826c3ded78`.

The independent classifier admitted **zero classification candidates from those
321 historical captures**, and produced **122 deduplicated review findings**
from 192 source-record finding matches. Most findings concern missing local
material subjects, nonmatching subjects, unresolved retained composition or
local doping. This is a useful review queue, not evidence that the papers lack
classification reports. The earlier October 1 **323-source/66-candidate** pilot
below used a different source inventory; comparing its total directly with 65
would not measure a parser regression or an extraction improvement.

The frozen extractor 1.0.0 benchmark used four purposefully selected original
arXiv captures and produced three
admitted statements and 72 deduplicated review findings. Sn/In/Te variable
composition, nominal/refined Ba/Fe/Pt composition and parenthetic Sr/Fe/Ni
composition still require subject review. This small ambiguity benchmark is not
a population estimate, a precision/recall score or complete supplement coverage.
Local receipts are `benchmark_receipt.json`, `numeric_compatibility_receipt.json`
and `classification_seed_identity_receipt.json` under
`/tmp/sclib_classification_benchmark_20261002`; source text and production exports
remain private.

### Independent primary classification metadata seed

`api/services/resources/material_classification_seed.json` uses
`material-classification-seed/1.0.0` and is separate from the numeric seed, whose
original 41 candidates are preserved historically. The numeric literal extractor
1.0.1 now retains 39 after correcting two bulk-property/sample-form mismatches;
the classification resource is unchanged. The current classification 1.0.1 resource has two candidates for `Cs(V0.93Nb0.07)3Sb5` in
[arXiv:2411.18744v1](https://arxiv.org/html/2411.18744v1): one CDW
`reported_order` source spans and one `single-nodeless` `gap_structure` span.
They use the explicit same-paper `Nb0.07-CVS` alias-definition proposal. These
statements do not constitute independent experiments, reviewed
pairing symmetry, conventionality, competition with superconductivity or a
canonical material classification.

The seed contains only constrained candidate metadata, source pins and hashes.
Its file SHA-256 is
`d7bf29439311fb7c210fa34f339c47a4e3720775c735e7cfd6218648bcdb5b34`;
its independently sealed `seed_sha256` is
`6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787`.
Each candidate references the same two verified current raw original records.
The identity receipt compares complete public records after removing only
documented API-derived decorations, and checks raw key/value equality, canonical
fingerprints and public assessment result IDs. Current paper status was active
in that receipt; captured statement status remains `unknown`, and
`publication_revision_verified` remains false.

The bounded loader validates seed and candidate identities, rejects authority
changes or nested private metadata, and fails closed if unavailable. Serving
requires the exact material ID/formula, exact source paper, and **every** retained
result ID/fingerprint to remain in `material.current_records()`. A changed,
removed or source-ineligible occurrence suppresses the affected seed statement.
Catalogue/source epoch checks run again before the API response. Seed merging is
idempotent, reseals the report and updates pending coverage without changing
numeric candidates, selected properties or raw records. It performs no new
scientific calculation and does not grant rights to source text.

The 1.0.1 correction recognizes TeX number/unit spacing (`40~K`, `40\\,K`),
whole signed exponent and decimal tokens, and whole interval/uncertainty tokens before
applying state guards. Multiple local temperature, pressure or magnetic-field
mentions require review. In the actual primary abstract, `40~K` and `58 K`
refer to different transitions; the earlier CDW abstract candidate therefore
moves into the review queue. The source was recaptured neither as new text nor
as a new experiment: the resource was rebuilt from the same original capture.
The other two statements remain pending. A same-input replay still returns
exactly 65 legacy numerical candidates, zero historical classification
candidates and 122 historical review findings. The immutable 1.0.0 receipts
retain their original three-candidate result; current correction receipts are
separate under `/tmp/sclib-classification-conditions-r5-20261002`. Conditions
are read before formula-oriented Unicode normalization, preserving original
minus signs and interval tokens. Parenthetical uncertainty forms that the
quantity parser cannot resolve remain whole raw tokens with an invalid parse
status; they are not promoted to a scalar.

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

Validation includes pure extraction/CLI and DB-free reader boundary tests for
units, uncertainty, exact source pins, formula/sample distinctions,
comparison tables, unknown lineage, derived Facts exclusion, paper/chunk/character
limits, restricted/stale evidence, metadata-only public egress and local replay.
Reader tests additionally verify record sampling through deep positions, work
outside the event-loop thread, fair per-paper chunk quotas, whole-chunk character
admission, concurrent length changes, honest per-paper omissions and
cancellation-safe CPU concurrency limits. Classifier/seed regressions cover local
and coded-alias identity, ambiguous definitions, stance and negation scope,
single-element comparators, non-detection windows, nested private-metadata
rejection, version-bound corrected seed identities, stale/current raw guards and
idempotent independent seed merging. Test counts should be read from the final
release receipt rather than from an intermediate source-edit run.
The API integration tests exercise the actual endpoint and held-material routes
through the repository's disposable-service runner.

## External reference services

Eligible material detail pages also offer separate Materials Project, COD,
NOMAD and versioned MDR SuperCon references. These panels never select retained catalogue properties or
promote a matched composition to an established sample/phase identity. External
provider requests begin when their folded panels are expanded.

The MP, COD and NOMAD routes reuse the source-aware fixed-composition guard before
cache lookup; isotope, variable occupancy, unresolved dopant or interface notation is
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
  Bounded DFT metadata preserves returned XC functional names/type and explicit
  spin-polarization settings. Missing metadata remains missing, and underlying
  DFT metadata is not presented as a complete method or convergence proof. Spin
  settings describe the calculation, not measured material magnetism. Archive
  temperature and pressure were not inspected; they are not inferred.
  MP/OQMD/AFLOW overlap is visible and task counts do not count
  independent experiments.

`no_match`, `not_applicable` and `unavailable` remain distinct. Provider failures
cannot become claims that the provider lacks data. References retain snapshot
hashes and retrieval times; source IDs/hashes sit in expandable provenance.
See [COD schema](https://wiki.crystallography.net/cod_mysql_schema/),
[COD API](https://wiki.crystallography.net/RESTful_API/), and
[NOMAD API](https://docs.nomad-lab.eu/1.4.3/howto/manage/program/api.html)
for provider field semantics. Scientific state matching, coordinate validation
and canonical review remain required before any future promotion.

### Field availability after an explicit lookup

The detail page shares an optional `MaterialProviderAvailabilityProvider` across
source recovery and the four external panels. Opening one panel triggers only
that provider's lazy request. Validated returned data updates the coverage
table's **Queried external references** column for each actually supplied field;
merely listing a provider as a recovery route creates no field hit.

The column distinguishes unrequested, loading, returned references, a successful
lookup with **no returned value for this field**, composition `no_match`,
`not_applicable` identity review and service `unavailable`. Counts are
provider-specific distinct returned record/task/source-row IDs, bounded by the
returned window, rather than total search matches or independent experiments.
Raw unresolved values carry interpretation counts and readable source scope.
Navigation drops the preceding material's fields/errors, and a cancelled
in-flight lookup cannot publish a late hit. Panels also work without the shared
context. A successful folded lookup keeps its inspected references available;
no background provider fetch is introduced.

MP structure and functional metadata remain computed references with unassociated
sample/phase/conditions; its unresolved functional placeholder is not a method
hit. COD cell/diffraction temperature, pressure and method describe the structure
measurement, not the selected Tc condition; a coordinate flag is not atomic-site
data. NOMAD XC and spin settings remain calculation metadata, not pairing or
observed magnetic order. MDR `tc` and explicit `t1/t2/t3/tcsus` source columns
remain separate; generic recommended Tc alone supplies no criterion. `tcn` and
transition width supply no Tc, `pmax` supplies no Tc pressure, and London
penetration length supplies no electron–phonon coupling λ. Raw MDR lattice,
space-group, sample and method fields continue to need interpretation and
sample/state review. Field availability performs no unit-backed canonical
conversion or property promotion.

### Corrected physical sample forms and public output allocation

The numeric literal extractor 1.0.1 requires explicit physical bulk sample,
specimen or material wording; bulk superconductivity does not establish a sample
form. Rebuilding from unchanged original HTML removes only two false bulk forms
from the original seed, retaining 39 pending candidates and all 14 quantities.
The four genuine single-crystal hits and surviving facts' complete reference sets
remain. Candidate identities are version-bound; old 41-row resources remain
historical, rather than current packaging proof.

Multi-formula contexts require a direct target/form noun-phrase association,
such as `NbN thin film` or `thin films of NbN`. This preserves the explicitly
named subject's own form in a comparison while withholding another compound's
form. Direct negation remains excluded. A same-input 321-source replay now
returns 63 candidate facts and 69 retained-reference associations: only two
bulk-property forms are removed from the historical 65/71 inventory. The two
explicit NbN thin-film descriptions withheld by the intermediate R6 guard are
restored. The other 61 complete candidate payloads and reference sets remain
exactly equal to R6; classification still returns zero candidates and 122
unchanged scope findings. This inventory is separate from the 39-row primary
seed, and direct wording remains a pending association rather than sample review.

Input fairness alone was insufficient: an actual native CI case showed a sparse
second paper could disappear in a 100-row hash-prefix output. Public candidate
overflow now round-robins papers, captures and fields; both seed mergers preserve
that selection policy. Numeric, classification and finding windows remain
independently bounded to100, with returned/omitted counts. Offline full reports
are unchanged. Findings use content-digest ordering without inventing IDs. See
the [source-field and window correction](operations/MATERIALS_RECOVERY_SAMPLE_FORM_AND_WINDOW_CORRECTION_2026-10-02.md)
for original candidate identities, source limitations and actual verification.

### Next measurable curation

Review the two current primary candidates and the held multi-temperature
statement before considering property promotion. A frozen extractor 1.0.0 /
commit `4f548a5` AI-assisted source-scope audit has already sampled 40 of the 122
historical findings across eight reason groups, nine materials and ten papers.
It identifies 25 justified holds, 12 source-association opportunities and three
missing-context cases; all remain unresolved. The opportunities include duplicate
evidence and cannot be counted as accepted properties or independent experiments.
The private audit lives under `/tmp/sclib-classification-review-20261002`.

The next deliverable is a domain-reviewed, measurable curation batch using the
current candidates and these association leads. Annotate true subject, source
role, stance, method and tested condition window, retaining rejected cases.
Measure field-specific extraction precision and recall against that independently
annotated benchmark, plus alias/state errors and reviewer disagreement; the
existing AI-assisted audit does not establish those scores or formal scientific
review. Only then expand the grammar or source inventory. Record full-text and
supplement coverage separately. For external references, audit a bounded sample
of actual returned field hits and unresolved units/codes before requesting
reviewed associations. New calculations require a separately scoped scientific
question and verified inputs.

## Versioned MDR SuperCon references

`GET /materials/{id}/external_supercon` is an additional, read-only reference
projection of NIMS MDR SuperCon Datasheet **Ver.240322**, DOI
[10.48505/nims.4487](https://doi.org/10.48505/nims.4487). The version metadata
explicitly licenses the dataset under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); attribution names the
National Institute for Materials Science and identifies this SCLib projection as
an adaptation. This permission is specific to the dataset and does not grant
rights to underlying publication full text.

The bounded official capture contains 33,458 Oxide & Metallic rows, 191 unique
columns and two actual header rows. Its bytes are pinned by SHA-256
`f599ef0040c18521e386f758ee826fe269f67ef369c1a007656035d03ccdfdf6`.
The accompanying Organic table has 569 rows and 49 columns; it was audited but is
outside this initial lookup because its identity and condition schema differs.
The digitized-figure `data.zip` is not the main property table. The existing
legacy NIMS CSV importer is not used for this projection: it can discard richer
fields, collapse intervals to midpoints and aggregate absent pressure as ambient.

Lookup uses the shared current-source fixed-composition guard. A composition
match is a reference opportunity, not an established sample or phase relation.
Versioned row identifiers, physical source-line ranges, complete raw row hashes, bibliography,
source units and unresolved codes remain distinct. Results show at most 20
references in source data-number order, with total matches and omitted counts.
A no-match result is limited to this fixed O&M version. The route retains the
same eligibility, source-partition, revision and private/no-store fences as
other material reference routes. No provider key or runtime network fetch is
required for this packaged version.

Keep recommended, zero-resistance, midpoint, R=100% and susceptibility Tc
separate. `tcn` records a lowest measurement temperature for a non-detection
report, including zero-valued source entries; it is never promoted to Tc=0.
Missing units are not filled from common practice. Undocumented measurement or
sample codes remain raw and unresolved. `pmax` is maximum applied pressure,
not pressure associated with any selected Tc. Preserve source derivation methods, critical-field
orientation and temperature context, and isotope information without assigning
it to an ordinary-isotope material. Publication/retraction status of underlying
papers has not been individually checked by this dataset adapter.

A source-aware pilot matched four of 14 eligible queries (from 19 materials)
to 37 O&M rows: La0.4Sm0.6O0.5F0.5BiS2 (2), Nb (19), NbN (15), PbCe (1).
The exploratory 232-material list audit produced 52 composition matches to 111
rows, but did not apply every retained-source spelling guard; it is an
upper-bound opportunity count. Neither count measures reviewed canonical
additions or independent experiments. All 33,458 rows and their 66 selected fields were independently compared with
the original source bytes, and the packaged resource was reproduced
deterministically. Cold resource loading took 2.01 seconds in the local test,
with 207 MB peak process RSS; this is a local observation, not a production SLA.
The adapter preserves existing records
and does not change ingestion pause state, quarantine, reviewed relations or
scientific acceptance.

The foundation snapshot exporter no longer assigns a blanket license or version
DOI from a generic legacy `nims` source label. Its previous hard-coded citation
misidentified DOI 10.48505/nims.3735 (Supercon 2 Dataset) as an MDR SuperCon
version. Original source receipts are required to establish legacy dataset
identity and terms; the new, independently verified Ver.240322 license does not
retroactively apply to those records. Existing historical exports remain intact.
