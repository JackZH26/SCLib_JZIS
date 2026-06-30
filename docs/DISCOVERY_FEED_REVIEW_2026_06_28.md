# Discovery Feed Review - 2026-06-28

Source page: https://jzis.org/sclib/discovery  
Source API: https://api.jzis.org/sclib/v1/discovery  
Feed timestamp: `2026-06-28T06:18:43.814108Z`  
Reviewed candidate count: `127`

## Executive Summary

The current discovery feed is scientifically useful, but it should be presented
as a reviewed SC SuperLoop lead/control queue rather than as a clean list of
`100+ predicted superconductors`.

The feed mixes several record types:

- literature-confirmed references
- mechanism anchors
- benchmark controls
- DFT-screened exploratory leads
- parent/comparator compounds
- conditional candidates
- negative controls

The main issue is not missing formulas or broken source data. It is that the
current public categories can make parent compounds, known superconductors,
controls, and pending DFT-screened leads look like equivalent superconductivity
predictions.

## Current Feed Composition

By `record_role`:

| Role | Count |
|---|---:|
| exploratory_candidate | 92 |
| reference_anchor | 16 |
| mechanism_anchor | 9 |
| benchmark_control | 5 |
| negative_control | 3 |
| conditional_candidate | 2 |

By `evidence_level`:

| Evidence | Count |
|---|---:|
| DFT-screened | 98 |
| literature-confirmed | 28 |
| reference | 1 |

By `checker_status`:

| Checker Status | Count |
|---|---:|
| pending | 93 |
| verified | 30 |
| revise | 4 |

## Key Findings

### 1. Category Semantics Are Mixed

Many records under `exploratory_candidate` are not direct superconducting
candidates in the usual materials-science sense. Several are better described
as parent compounds, comparators, or mechanism probes.

Examples:

- `La2CuO4`, `CaCuO2`, `SrCuO2`, `Nd2CuO4`: cuprate parent/comparator systems.
- `BaFe2As2`, `CaFe2As2`, `SrFe2As2`, `LaFeAsO`: iron-based parent or nearby
  comparator systems.
- `HfNCl`, `ZrNCl`: layered nitride-halide parent comparators requiring
  intercalation or electron doping context.
- `Bi2Se3`, `Bi2Te3`: topological parent systems where superconductivity
  usually depends on intercalation or doping.

These should not be displayed as ordinary discovery candidates without a
front-visible condition such as `parent only`, `doping required`, or
`comparator`.

### 2. Some Known Superconductors Are Marked As Exploratory

Several records currently marked as `exploratory_candidate` are known
superconductors or established superconducting families.

Examples:

- `LuNi2B2C` and `YNi2B2C` are known borocarbide superconductors.
- `Ta` and `V` are elemental superconductors.
- `TiN` appears under `benchmark_control`, but its `public_confidence` is
  `Exploratory Review Passed`.

These should be moved to reference or benchmark categories, or explicitly
tagged as known baseline materials.

### 3. Public Confidence Label Is Too Strong

The label `Exploratory Review Passed` appears on `98` records, but most of
those records are still `checker_status = pending`, and a few are
`checker_status = revise`.

This creates a semantic conflict:

- `public_confidence = Exploratory Review Passed`
- `checker_status = pending` or `revise`

Recommended replacement labels:

- `DFT-screened lead`
- `Pending review`
- `Needs revision`
- `Negative control`
- `Known reference`

The word `Passed` should be reserved for records whose checker status has
actually passed or been verified.

### 4. Duplicate Candidate IDs

The feed contains duplicate `candidate_id` values. Formula values are unique,
so this appears to be an ID generation issue rather than duplicate material
records.

Observed duplicates:

| candidate_id | Formula A | Formula B |
|---|---|---|
| `track-b-e0-2026-06-28-0099` | `BC3N3` | `WC` |
| `track-b-e0-2026-06-28-0244` | `BaFe2As2` | `CaFe2As2` |
| `track-b-e0-2026-06-28-0153` | `BaFe2P2` | `Ti3CN` |
| `track-b-e0-2026-06-28-0297` | `BeB2` | `Bi2S3` |
| `track-b-e0-2026-06-28-0242` | `La0.8Sr0.2NiO2` | `VB2` |
| `track-b-e0-2026-06-28-0285` | `PbTe` | `SbH3` |

Risks:

- unstable React keys
- ambiguous review tracking
- ambiguous external references
- future bookmark/citation collisions

Recommended fix: generate stable IDs from at least
`record_role + normalized_formula + branch`, or use a content hash.

### 5. High Discovery Scores Need Calibration

The highest scoring records include known materials, parent systems, and
condition-dependent systems.

Top examples:

| Score | Formula | Current Role | Concern |
|---:|---|---|---|
| 78.8 | `LiBC` | exploratory_candidate | Needs hole doping context; bare LiBC is not a simple direct candidate. |
| 78.5 | `LuNi2B2C` | exploratory_candidate | Known borocarbide superconductor. |
| 78.5 | `YNi2B2C` | exploratory_candidate | Known borocarbide superconductor. |
| 75.8 | `HfNCl` | exploratory_candidate | Parent/intercalation-dependent layered nitride halide. |
| 75.8 | `ZrNCl` | exploratory_candidate | Parent/intercalation-dependent layered nitride halide. |
| 75.2 | `Ta` | exploratory_candidate | Known elemental superconductor. |
| 75.2 | `V` | exploratory_candidate | Known elemental superconductor. |

If `discovery_score` is intended to prioritize new superconductivity leads, it
should penalize known references, parent comparators, and condition-missing
records.

### 6. Condition Dependence Needs Front-Visible Labels

Many entries are scientifically meaningful only with explicit conditions:

- Hydrides: high pressure, structure, and dynamic stability.
- MXenes: surface termination and stoichiometry.
- Cuprates: carrier doping, oxygen stoichiometry, and structural phase.
- Iron pnictides/chalcogenides: doping, pressure, magnetism, and nematic
  competition.
- Nickelates: thin-film context, substrate effects, reduction chemistry, and
  rare-earth choice.
- `LaAlO3/SrTiO3`: interface/2DEG system, not an ordinary bulk formula.
- Fullerides: stoichiometry, molecular phase, and intercalation state.

These conditions should be visible in the collapsed card, not only buried in
review text.

## Recommended Data Model Changes

Add or derive a public-facing `display_class` separate from `record_role`.

Suggested classes:

- `known_reference`
- `mechanism_anchor`
- `benchmark`
- `parent_comparator`
- `conditional_candidate`
- `negative_control`
- `dft_screened_lead`

Add a `condition_badges` or normalize existing `risk_tags` into a public
surface:

- `doping required`
- `high pressure`
- `interface required`
- `surface termination sensitive`
- `parent only`
- `known superconductor`
- `negative control`
- `requires experimental validation`

## Recommended UI Changes

1. Rename the page framing from “Discovery” alone to something like
   “Reviewed Leads and Controls”.
2. In collapsed cards, show:
   - formula
   - display class
   - evidence
   - checker status
   - top condition badges
3. Visually distinguish:
   - confirmed references
   - pending DFT-screened leads
   - parent/comparator records
   - negative controls
4. Avoid showing `Exploratory Review Passed` for records that are pending or
   revise.
5. Add a small explanatory note: DFT-screened entries are not Tc claims.

## Recommended Priority Fixes

### P0

- Fix duplicate `candidate_id` generation.
- Rename or re-map `Exploratory Review Passed` for pending/revise records.
- Move known superconductors out of ordinary exploratory candidate display.

### P1

- Add `display_class`.
- Promote condition badges into collapsed cards.
- Reclassify parent compounds and comparators.

### P2

- Recalibrate `discovery_score` so known references and parent comparators do
  not dominate the lead ranking.
- Add an audit report that flags category conflicts automatically.

## Bottom Line

The feed is valuable, but the current public representation overstates the
meaning of some entries. It is best interpreted as a reviewed discovery
workflow snapshot, not as a list of confirmed or direct superconductivity
predictions.

The highest-impact cleanup is to separate known references, controls,
parent/comparator records, conditional candidates, and DFT-screened leads into
distinct public classes.
