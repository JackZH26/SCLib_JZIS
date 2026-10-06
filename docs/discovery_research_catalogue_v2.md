# Retained research coordinate catalogue v2

This is a manually selected, versioned website catalogue of reproducible coordinate
proposals. It does not select the most promising superconductors. The first batch
contains **20 original source entries, 19 coordinate states and eight composition
groups**. All states are unrelaxed and unranked; pressure, temperature, charge,
magnetic state and all six physical evidence axes remain unknown. No host result,
unrelated calculation, research strategy or source-integrity check supplies a score.
The separately released three-proposal v1 catalogue remains unchanged.

## Original scientific inputs

The original downloaded batch bytes are retained in
`docs/data/discovery-research-catalogue/`. They contain scientific source and
coordinate data, not local paths, account data or resource budgets.

| Batch | Full SHA-256 | Original entries |
|---|---|---:|
| `sclib-site-candidates-87e0ec0aaa37.json` | `87e0ec0aaa3700419e035f804d3c750787846dd2c578e17b59583de63cfa68a6` | 3 |
| `sclib-combined-6e52be02d9dd.json` | `6e52be02d9dd41ae58847a51a5e3f0ed38d6149ebdd4624dbba8c87f7ebb838c` | 17 |

Both use the captured MgB2 COD 1526507 revision 176429 coordinates. The combined
input contains a repeated Al choice: 27 raw combinations become 18 distinct
combinations, then the unchanged zero-strain baseline is excluded, leaving 17.
The candidate catalogue does not repeat that baseline as a candidate. The two
Mg8B16 entries are changed cells at −2% and +2% uniform linear lattice scaling;
they share the MgB2 composition but are not the unmodified reference.

| Composition label | Coordinate states |
|---|---:|
| Mg7AlB16 | 3 |
| Mg7CaB16 | 1 |
| Mg7B16 | 1 |
| Mg7AlB15C | 3 |
| Mg7AlB15 | 3 |
| Mg8B15C | 3 |
| Mg8B16 | 2 |
| Mg8B15 | 3 |

## Identity and lineage

`research-proposal-catalog/2.0.0` is defined in the closed JSON schema
`docs/schemas/research-proposal-catalog-v2.schema.json`. The server loader also
checks cross-object identity, source pins, reconstructed geometry and CIF contents.
The separate version `.pins.json` binds the actual catalogue; the validator is not
hard-coded to three compositions or one output count.

- **Source** fixes the COD record/revision and exact source CIF bytes, with the
  observed capture kind and license evidence. Formula matching alone is insufficient.
- **Parent** fixes source, captured reference ID, integer repeats, cell and all
  original sites. `legacy_parent_id` preserves the original generator identity.
- **State** fixes parent, sorted explicit site edits, integer micro-percent lattice
  change, unrelaxed status and conditions. `2,000,000` micro-percent means +2%,
  not pressure. Source rounded coordinates remain rounded coordinates.
- **Occurrence** preserves original batch SHA, `/candidates/N` locator, old candidate
  ID and complete original CIF bytes/hash. No original file is rewritten for deduplication.
- **Group** is a source/host-phase-specific reduced-composition display grouping.
  It is not a native material ID or a declaration that all structures with this
  formula are the same material state. State formulas retain actual supercell counts.

IDs use SHA-256 of UTF-8 JSON with recursively sorted object keys, retained array
order, no whitespace and unescaped Unicode. Finite numbers use plain decimal
notation without exponent spelling or trailing decimal zeros; coordinate values
use the generators' 14-significant-digit CIF precision. The hashed fields are:

| ID prefix | Exact hashed projection |
|---|---|
| `proposal-source` | `cif_sha256`, original captured `record_id` such as `cod-1526507` |
| `proposal-parent` | `source_id`, `reference_id`, `repeats`, `cell`, `atoms` |
| `proposal-state` | `parent_id`, `edits`, `strain_micro_percent`, `conditions`, `status` |
| `proposal-group` | `source_id`, reduced integer `composition` |
| `proposal-occurrence` | `source_batch_sha256`, `source_locator`, `legacy_candidate_id`, `cif_sha256` |

The shared zero-strain Mg7AlB16 recipe has one state and two occurrences. Its two
CIF hashes differ because generator comments differ. Deduplication requires the
same pinned parent, normalized recipe and conditions, plus exact agreement of
reconstructed geometry. It is neither a CIF-hash grouping nor a formula grouping.
No fuzzy strain tolerance, symmetry-equivalence search or physical equivalence
claim is applied. Different source pins remain different source-bound groups.

## Rebuild and verification

```sh
python scripts/build_discovery_research_catalogue.py --check
python -m unittest scripts/tests/test_build_discovery_research_catalogue.py
# With the existing Gemmi validation runtime, without downloading dependencies:
python scripts/build_discovery_research_catalogue.py --check --require-gemmi
```

`--check` compares exact catalogue and pin-file bytes. `--write` is an explicit
local generation operation; it does not publish, submit calculations or write a
database. A new source batch requires an intentionally changed input manifest
and new output version, source/structural validation and engineering review.

The builder accepts only the two documented generator contracts, checks the
input-byte hashes and frozen source snapshot, reconstructs parent sites and edits,
checks composition/cell/CIF identity, and retains provenance aliases. Gemmi, when
available, additionally parses every original CIF and checks its inventory and
coordinates. An unavailable Gemmi runtime is reported; `--require-gemmi` fails
instead of silently claiming independent parsing.

Bounds are 100 states, 200 occurrences, 96 original sites per parent, three edited
sites per state, ±10% linear cell change and 1 MiB output. Exceeding a bound fails;
the builder never silently truncates. Unknown fields, orphan links, duplicate IDs,
modified source pins, inherited physical values, fabricated scores/reviews and
inconsistent CIFs are rejected. Output counts derive from validated entries.

## Research-cycle and display boundary

`getResearchCatalogue()` returns validated `sources`, `parents`, `states`, `groups`
and `occurrences`. UI code imports types only and receives this server projection.
A main row may show a composition group and its number of states; expansion must
show the selected state's actual modifications, conditions and source files.
The primary occurrence gives a reproducible default download, while all original
occurrences remain inspectable. Array order follows the manually selected source
batches and implies no scientific preference.

Research cases can reference the catalogue version, group/state IDs and occurrence
CIF hash. A later calculation must identify its actual input, model, run and output;
it does not retroactively relax or score these source states. High bandwidth, high
carrier density and geometric construction are research strategies, not measured
properties assigned to these proposals. Published RPS assessments continue to use
their existing campaign/action/resource/review contract. Website display does not
create a formal RPS release or independent scientific approval.
