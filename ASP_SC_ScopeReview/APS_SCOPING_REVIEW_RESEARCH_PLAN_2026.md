# APS Superconductivity Scoping Review Plan

Date: 2026-06-29

## Working Title

`A Peer-Reviewed APS Scaffold for Superconductivity Research: LLM-Extracted Material-Tc Records, 1986--2026`

Final file names should follow the standing authorship rule, for example:

- `Zhou_A_Peer_Reviewed_APS_Scaffold_For_Superconductivity_Research_1986_2026_2026.tex`
- `Zhou_A_Peer_Reviewed_APS_Scaffold_For_Superconductivity_Research_1986_2026_2026.pdf`

## Author Block

Use Jian Zhou as sole author in the eventual manuscript, with the
institution, title, email, and ORCID required by the standing
authorship instructions.

## Scientific Positioning

The arXiv paper established a reproducible preprint-corpus scaffold.
The APS paper should answer a different question:

> Which superconductivity bibliometric structures survive when the corpus
> changes from arXiv preprints to APS peer-reviewed journal articles, and
> which structures are filtered, delayed, damped, or sharpened by the
> publication process?

This framing lets the APS paper become the planned peer-reviewed-corpus
replication promised in the arXiv manuscript.

## Central Comparison Axes

1. Corpus status: peer-reviewed APS articles vs arXiv preprints.
2. Temporal window: APS 1986--2026 vs arXiv 1993--2026.
3. Venue structure: PRB/PRL/PRX/PRResearch/PRMaterials/RMP etc.
4. Evidence balance: experimental vs theoretical records, especially
   high-pressure hydrides.
5. Publication lag: APS publication year vs arXiv submission year where
   DOI overlap exists.
6. Selection filtering: which arXiv high-Tc or controversial claims do
   not appear as active APS records.
7. Geography: APS country/region affiliation patterns vs arXiv
   country-affiliation participation patterns, including how different
   countries and regions concentrate on different superconducting
   material families over time.

## Research Questions

RQ1. What is the annual APS superconductivity article volume from
1986--2026, and how does the 1986 cuprate shock appear in APS compared
with later shifts?

RQ2. Do the arXiv 100 K watershed and 50--80 K density valley reproduce
in the APS peer-reviewed corpus?

RQ3. Is the 2008 iron-based transition sharper, weaker, or delayed in
APS relative to arXiv?

RQ4. Does the post-2020 multi-polar diversification remain visible in
APS when recent papers are filtered through journal publication?

RQ5. Is the high-pressure hydride stratum less theory-heavy in APS than
in arXiv, or do APS peer-reviewed hydride records still mostly encode
DFT screening?

RQ6. Which material families are disproportionately APS-published versus
arXiv-preprinted?

RQ7. How do PRL, PRB, PRX/PRResearch/PRMaterials, RMP, and PRApplied
partition discovery claims, follow-up characterization, methods, and
reviews?

RQ8. For DOI-linked arXiv/APS work pairs, how often do material--Tc
records differ between preprint and published versions?

RQ9. Do USA/China/Japan/Germany participation patterns seen in arXiv
persist in APS, and how sensitive are they to non-mutually-exclusive vs
fractional counting?

RQ10. Does peer review reduce the high-risk above-100 K residual queue
seen in arXiv, especially ambiguous unclassified or speculative records?

RQ11. What are the country/region-specific research timelines in APS:
for example, USA/Japan/Europe in cuprates and heavy fermions,
China/Japan/USA in iron-based superconductors, China/USA/Europe in
hydrides, and China/USA/Japan/Korea in kagome/nickelate-era work?

RQ12. Which countries or regions specialize in which material families
or evidence types, and do those specializations change after key field
events such as 1986 cuprates, 2001 MgB2, 2008 iron-based, 2015 hydrides,
2020 kagome, and 2023 nickelates?

## Hypotheses

H1. The 100 K watershed will reproduce in APS, probably with an equal or
larger below-100 K share after peer-reviewed filtering.

H2. The 50--80 K density valley will reproduce, but its depth may differ
because APS begins at the 1986 cuprate discovery and includes the intense
late-1980s/early-1990s cuprate literature that arXiv misses.

H3. APS will show the cuprate revolution directly from 1986 onward,
whereas arXiv sees cuprates mostly as a mature background literature.

H4. APS hydrides will remain theory-heavy but should contain a larger
fraction of canonical experimental records than arXiv if the APS venue
mix filters speculative preprints.

H5. PRL will concentrate high-impact discovery reports; PRB will carry
the bulk characterization and follow-up literature; PRX/PRResearch and
PRMaterials will be more recent and more methods/theory intensive.

H6. DOI-linked arXiv/APS pairs will usually preserve numerical Tc on
shared formulas, but differences will concentrate in formula selection,
evidence type, pressure tier, and whether a cited claim is promoted or
removed in the published version.

H7. Country/region timelines will not be a single USA-vs-China story:
older APS families should show strong USA/Japan/Europe participation,
the 2008 iron-based era should show a sharp China/Japan/USA mixture, and
post-2015 hydride/kagome/nickelate records should show more China-led or
China-near-parity participation, with strong dependence on family and
evidence type.

## Corpus Definition

Primary corpus:

- APS DOI prefix `10.1103`
- journal articles in authorized Harvest scope
- publication date 1986-01-01 through freeze date, with 2026 labelled
  partial unless the freeze is after 2026-12-31
- superconductivity candidate manifest derived from Crossref terms plus
  local keyword/tag filtering
- successfully ingested APS rows with TDM deletion audit

Primary manuscript denominator:

```sql
p.source = 'aps'
AND p.status != 'retracted'
AND p.credibility_tier = 'T1'
AND p.year BETWEEN 1986 AND 2026
```

Strict Tc denominator:

```sql
v.tc_kelvin > 0
AND v.tc_kelvin <= 300
```

Secondary denominators:

- harvest-ready DOI universe
- all candidate DOI universe
- APS papers with any material extraction
- APS papers with at least one strict Tc record
- DOI-linked APS/arXiv pairs
- journal-specific subsets
- strict experimental subset

## Methods Adapted From The arXiv Paper

Reuse:

- Gemini production material--Tc extraction schema
- material family enumeration
- strict filter `0 < Tc <= 300 K`
- pressure tiering with null pressure kept separate
- evidence-type separation
- Golden multi-model agreement logic
- interpretation classes:
  - value-conditional distribution structures
  - extraction-selection-sensitive material counts
  - coverage-conditioned geography

Change:

- corpus source is APS, not arXiv
- year means APS publication year, not arXiv submission year
- APS full text is transient and cannot be archived
- vector chunks are abstract/facts only, never full-text sections
- manuscript must include TDM compliance and deletion audit as a first-class
  methods element
- journal venue is a core variable

## Planned Tables And Figures

Figure 1. PRISMA-style corpus flow:
Crossref candidate DOI universe -> authorized date-window candidate
universe -> harvest-ready DOI universe -> successfully ingested APS
papers -> material-bearing papers -> strict Tc records.

Figure 2. Annual APS article volume and strict-Tc paper volume,
1986--2026, with markers for 1986 cuprates, 2001 MgB2, 2008 iron-based,
2015 hydrides, 2020 kagome, 2023 nickelates.

Figure 3. Annual material-family stack for APS strict Tc records.

Figure 4. Tc-vs-year APS timeline scatter, colored by family, styled by
pressure and evidence type.

Figure 5. APS Tc histogram with 50--80 K valley and 100 K watershed.

Figure 6. APS vs arXiv side-by-side:
watershed share, valley depth ratio, family concentration HHI, hydride
theory share.

Figure 7. Journal venue matrix:
family/evidence/pressure distributions by PRB, PRL, PRX/PRResearch,
PRMaterials, RMP, PRApplied.

Figure 8. DOI-linked arXiv-to-APS lag and extraction-difference plot.

Figure 9. Country-affiliation participation trends, with
non-mutually-exclusive and fractional sensitivity.

Figure 10. Country/region x material-family heatmap by period, showing
how research focus shifts across USA, China, Japan, Germany, UK/EU,
South Korea, Taiwan, India, and multi-country collaborations.

Figure 11. Country/region timelines for selected families: cuprate,
iron-based, hydride, kagome, nickelate, heavy fermion, MgB2, and
conventional/elemental superconductors.

Core tables:

- corpus denominators and coverage
- annual and period counts
- top families by period
- 100 K watershed filters
- above-100 K by family, pressure, evidence type
- 50--80 K valley metric and robustness
- hydride evidence-type/pressure table
- top formula strings by distinct APS paper count
- arXiv/APS paired-work comparison
- country/region x family x period matrix
- country/region x evidence-type and pressure-tier matrix
- country/region research-focus summary, using both integer participation
  and fractional counting
- Golden APS validation design and headline agreement

## Analysis Modules

Module A: Corpus Coverage

- candidate, harvest-ready, ingested, material-bearing, strict-Tc
  denominators
- journal and year coverage
- invalid DOI and unsupported full-text audit

Module B: Temporal Dynamics

- annual paper volume
- annual strict-Tc paper volume
- family succession by period
- 1986 cuprate onset and 2008 iron shock
- family concentration HHI and effective number of families

Module C: Tc Distribution

- 100 K watershed under multiple filters
- 50--80 K density valley with bootstrap/KDE sensitivity
- five-regime Tc spectrum
- high-pressure and ultra-high-pressure subsets
- experimental vs theoretical ceiling

Module D: Journal Venue Analysis

- PRB vs PRL vs PRX/PRResearch/PRMaterials
- discovery vs follow-up venue signatures
- journal-specific material families
- evidence-type and pressure composition by journal

Module E: APS vs arXiv Replication

- compare only derived frozen statistics, not live services
- align years where possible
- separate effects of corpus window, publication status, and source
  culture
- paired DOI subset for direct preprint-to-publication comparison

Module F: Geography

- APS paper_geo coverage
- country/region participation, non-mutually-exclusive counts
- fractional country-count sensitivity
- USA--China joint papers
- family-by-country participation
- country/region x family x year and period timelines
- country/region x journal venue patterns
- country/region x evidence-type patterns, especially experimental vs
  theoretical hydride records
- regional aggregates with explicit definitions:
  - North America: USA, Canada, Mexico
  - Europe: EU member states plus UK, Switzerland, Norway, etc.
  - East Asia: China, Japan, South Korea, Taiwan, Hong Kong, Singapore
  - South Asia: India and neighboring South Asian countries
- missing-geography audit and sensitivity analysis

Module G: Validation

- APS Golden-400 agreement diagnostic, matching the arXiv Golden-400
  sample size and interpretation boundary
- optional arXiv/APS paired validation
- human adjudication queue for:
  - above-100 K
  - hydrides
  - pressure >1 GPa
  - evidence-type disagreements
  - formula disagreement
  - journal/DOI metadata anomalies

## Interpretation Guardrails

- APS peer review is not replication or confirmation.
- Candidate DOI coverage is not successful ingest coverage.
- Crossref keyword search is not an exhaustive APS subject taxonomy.
- Null pressure is pressure-not-stated, not ambient.
- `primary` is ambiguous and must not be silently collapsed into
  `primary_experimental`.
- Country counts are participation counts unless explicitly fractional.
- Journal venue counts measure publication venue, not discovery credit.
- LLM agreement is not expert ground truth.
- APS full text cannot be redistributed or included in validation packets.

## Manuscript Structure

1. Introduction
   - why peer-reviewed replication matters after the arXiv study
   - 1986 as natural APS start point
   - contribution statement

2. Data And Methods
   - APS corpus construction
   - TDM compliance and deletion audit
   - material/Tc extraction
   - geography extraction
   - strict filters and analysis conventions
   - validation design

3. Corpus Coverage And Venue Structure
   - DOI universe, harvest-ready frame, ingested frame
   - journal distribution and annual volume

4. Temporal Material-Family Dynamics
   - cuprate onset, MgB2, iron-based, hydride, recent multi-polar era

5. Tc Distribution Structure
   - 100 K watershed, 50--80 K valley, pressure/evidence decomposition

6. APS vs arXiv Replication
   - stable conclusions
   - source-sensitive differences
   - paired DOI subset

7. Geography
   - country/region participation and collaborations
   - country/region research-focus timelines by material family
   - regional specialization and venue/evidence-type differences

8. Discussion
   - what APS confirms
   - what APS filters
   - methodological implications for LLM bibliometrics

9. Limitations
   - keyword manifest limitations
   - APS corpus limits
   - TDM restrictions
   - LLM validation limits
   - geography and formula canonicalization limits

10. Data Availability And Reproducibility
    - freeze DOI when available
    - checksum and schema provenance
    - no APS licensed full-text redistribution

11. Declarations
    - use required declarations and AI/LLM usage statement

## Work Plan

Phase 0: Freeze Preparation

- verify APS ingest state on VPS2
- generate harvest-ready manifest
- archive invalid DOI list
- run compliance SQL
- stop timers and export data
- compute checksums and row counts

Phase 1: Descriptive Corpus Analysis

- annual/journal/candidate coverage
- PRISMA-style flow
- journal-year heatmaps

Phase 2: Tc And Family Analysis

- replicate arXiv scripts for APS-only exports
- compute watershed, valley, HHI, family succession, Pareto
- produce first figures

Phase 3: APS-vs-arXiv Comparison

- use arXiv 2026-06-15 frozen outputs
- align comparable metrics
- build paired DOI analysis if related links exist
- compare country/region timelines and family specialization patterns
  between APS and arXiv

Phase 4: Validation

- freeze APS Golden-400 frame
- run multi-model or human adjudication only through transient TDM path
- summarize as agreement diagnostic

Phase 5: Manuscript Draft

- write LaTeX with required Jian Zhou author block
- include declarations before references
- compile and visually check figures/tables

Phase 6: Deposit

- package derived data, prompts, schema, scripts, checksums
- exclude APS licensed full text
- upload dataset when ready

## Initial Go/No-Go Decision

Go for manuscript analysis only after:

- production APS paper count is known
- APS strict Tc record count is known
- compliance gate passes
- APS-only exports are frozen and checksummed

If APS ingest is only at calibration scale, the correct next product is a
registered analysis protocol or pilot report, not the full 1986--2026
scoping review.
