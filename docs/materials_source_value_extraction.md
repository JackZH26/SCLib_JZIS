# Bounded literal source values

`materials-literal-extractor/1.2.0` provides a read-only, source-scoped path for
fourteen fields previously labelled `paper_field_extractor_not_implemented`.
It returns useful printed source values for review. It does not accept a
material-state association, modify a retained record, normalize a scientific
quantity, or authorize public release or ML training.

## Field contract

| Field | Required local meaning and printed unit | Source role |
| --- | --- | --- |
| `hc1_source_value` | Lower critical field or Hc1; T, mT, Oe, kOe, G or gauss | reported property |
| `gap_energy_source_value` | Explicit superconducting/BCS/pairing/tunnelling gap context; eV, meV, micro-eV or K | reported property |
| `gap_ratio_source_value` | Explicit gap ratio or 2Δ/kBTc; no physical unit | reported property |
| `electronic_specific_heat_coefficient_source_value` | Electronic specific-heat or Sommerfeld coefficient; finite J/mJ/micro-J per mol or mol-atom per K² notation | reported property |
| `debye_temperature_source_value` | Debye temperature or ΘD; K, mK or kelvin | reported property |
| `isotope_effect_exponent` | Explicit isotope exponent/coefficient; no physical unit | reported property |
| `dtc_dp_source_value` | Explicit dTc/dP or pressure derivative of Tc; K/mK per printed pressure unit | reported property |
| `maximum_applied_pressure_source_value` | Explicit maximum/highest applied pressure or pressures up to a value; printed pressure unit | study extent |
| `meissner_fraction_percent` | Explicit Meissner fraction; percent or % | reported property |
| `transition_width_source_value` | Explicit superconducting/resistive transition width; K, mK or kelvin | reported property |
| `minimum_temperature_k` | Explicit lowest/minimum measurement temperature or named measurement down to a value; K, mK or kelvin | measurement limit |
| `t_cdw_k` | Explicit CDW ordering/transition temperature; K, mK or kelvin | reported order transition |
| `t_afm_k` | Explicit Néel or AFM ordering/transition temperature; K, mK or kelvin | reported order transition |
| `t_sdw_k` | Explicit SDW ordering/transition temperature; K, mK or kelvin | reported order transition |

The historical `REFERENCE_ONLY_FIELDS` and `PAPER_UNIMPLEMENTED_FIELDS`
group names remain for compatibility. They no longer bypass the implemented
bounded extraction path or force an unimplemented status. External reference
routes remain suggestions, not proof that a third-party lookup found a value.

## Source fidelity and scope

The existing source validator, source-paper equality, formula formatting
normalization, sentence/newline/semicolon segmentation and candidate identity
logic are reused. A source must belong to the retained record's paper. The
target formula must occur in the same inspected segment. A foreign compound
or an explicit single-element comparison can prevent assignment. A nearby
formula, catalogue family, earlier paragraph or plausible alias is insufficient.
The passage grammar does not add anaphora or alias equivalence. The separately
captured thermal-table path below uses explicit column and row binding.

`value` and `raw_value` are the exact original substring from the printed
amount through its unit, including inequalities, ranges, parenthetical
uncertainty, ± notation and supported TeX unit wrappers. Printed relation
words such as below, above, about and approximately remain in that value/span;
a bound or approximation must not display as an exact point. `quantity` is `null`.
`source_value.normalization` is `none`; no K-to-energy, mol-atom-to-mol-formula,
magnetic-field, pressure or uncertainty conversion is performed. All span
offsets are Python Unicode codepoints into the original capture, end-exclusive.
The value, unit and cue spans each carry the SHA-256 of their exact substring.
TeX commands are retained as text and never executed.

`source_value` additionally carries `raw_unit`, `raw_uncertainty`, `field_cue`,
`role` and bounded qualifiers for cited/qualified, calculation/model,
fit/estimate and inference/unmeasured context. These qualifiers disclose local
wording; they are not proof of a measurement, calculation validity or citation
ownership. Native indexed chunks keep their existing `legacy_unknown` source
kind and unverified publication-revision/source-content status.

Bare Δ, ΔT, α and γ require a direct named meaning. A thermal difference,
crystal angle or lattice-fit coefficient does not supply a gap, transition
width, isotope exponent or electronic coefficient. Shielding fraction is not
Meissner fraction. A heat-capacity jump ratio is not the superconducting gap
ratio. Diffraction/measurement temperature and a lower measurement bound are
not order transitions. Generic λ is not electron-phonon coupling without an
explicit EPC meaning. Unit prefixes such as mT/s or K/m, dimensionless values
followed by physical units/percent and malformed electronic-coefficient powers
are withheld.

Ratios and isotope exponents also require a complete expression ending or a
finite separated prose connector. Unknown trailing units/words and unsupported
scientific or TeX scale factors are withheld rather than dropped. This guard
does not claim exhaustive unit recognition and deliberately limits recall.

Maximum applied pressure is a study extent, not the pressure of a selected Tc.
Recognized pressure-range, increasing-pressure and apparatus-capacity wording
is also withheld from selected Tc pressure even when it does not match the
narrower maximum-field grammar. The extractor does not calculate dTc/dP from
a pressure series, infer a transition from absence down to a limit, or create
Hc/lambda/gap values by formula.

## Coverage and bounded reading

- A local candidate gives `pending_review` unless the existing retained-value
  coverage rules apply. Every candidate retains false scientific acceptance,
  ML approval, release and database-change authority flags.
- No usable capture gives `not_extracted` with
  `original_source_capture_not_supplied`; it is not a statement about the paper.
- Inspected captures without a local match give `not_found_in_checked_sources`
  with `bounded_source_value_grammar_has_incomplete_recall`. This is a bounded
  extraction result, never whole-paper absence.
- Existing API paper/record/chunk/character/time budgets, source hold checks,
  fair candidate response windows, late source-currentness check and
  `Cache-Control: private, no-store` remain in force. A bounded response is not
  the entire source or all retained records.

The scientific value parser, field-unit registry, source-intake grants,
canonical material fields and historical packaged primary-source seed are
unchanged. Historical packaged candidates remain version 1.0.1 and keep their IDs;
newly extracted candidates use 1.2.0 and include source-value metadata in their
identity. Formal reviewed Tc field overlays remain a separate unfinished path.

## Validation and remaining limits

The regression suite labels fourteen positive grammar fixtures as synthetic.
It checks negative semantic cues, incomplete units, uncertainty, inequalities,
exact TeX/source spans, stable IDs, same-paper/formula scope, deduplication and
immutable inputs. Native API validation reads all fourteen through fresh
owned PostgreSQL/Redis services, preserving private response and hold behavior.
Those tests establish bounded behavior, not extraction precision or recall on
the catalogue.

Short genuine retained excerpts are tested separately. The BiTeCl passage in
arXiv:1501.06203 explicitly reports pressures up to 50.8 GPa and yields only a
study-extent value. Its publication revision remains unresolved. A Cs paper's
Nb0.07-CVS gap and a Mo paper's anaphoric Sommerfeld/Debye values are withheld
because the exact target formula is absent in the same segment; no formula is
prepended to make a test pass. The retained Mo shielding text does not become
a Meissner fraction. Source-file and excerpt hashes are pinned in the tests
and validation receipt. These examples are not a complete authentic gold set.

The finite English grammar misses other languages, OCR damage, equations
with unsupported layout, cross-sentence material bindings and most tables.
It deliberately withholds ambiguous multi-subject and negative cases; that
conservative behavior can miss valid values. Supported cited, fitted or model
values remain pending with qualifiers; those qualifiers do not establish
citation ownership or material-state scope. Further recall work needs
source-specific subject/table binding and independently annotated examples,
followed by separate material-state and lifecycle review before any promotion.

## Thermal tables in 1.2.0

The primary-HTML capture adapter now retains exact header-cell and caption
spans in its captured text. Rectangular, unspanned tables may produce two new
literal row types: Debye temperature with a printed K/mK/kelvin row unit, and
the electronic specific-heat coefficient with a complete supported molar
heat-capacity unit. A bare γ row additionally needs a captured heat-capacity or
specific-heat caption. A named Sommerfeld/electronic coefficient supplies its
own meaning. These rules do not cover arbitrary tables or infer a unit.

All header and row-cell spans must match the capture and appear in order;
the row label must equal the first captured cell. The selected formula must
match exactly one full column header. Changed labels, reordered or overlapping
cells, missing header captures, unsupported powers, footnote-suffixed numbers,
ragged tables and spanning HTML cells cannot supply these thermal candidates.
Comparison headers containing citations remain unmatched until a separate
review resolves the reference and composition. Old adapters retain their
existing supported structure fields but cannot supply the new thermal rows.

For these candidates `raw_value` is the exact numerical **cell**, while
`source_value.raw_unit` comes from the separately pinned row-label substring.
`unit_basis: table_row_label` makes that separation explicit. `table_binding`
retains header, label and optional caption pins. The UI displays amount and
row unit together, explains the unit location and includes these pins in its
redacted metadata download. It does not offer the passage-only literal-intake
action for a table candidate. No existing append/intake contract is broadened.

An offline replay of the captured arXiv:1603.02892 Table II (PDF page 5)
recovers four previously missed candidates: γ/ΘD values 3.16/492 for
Mo5P1.1B1.9 and 3.07/501 for Mo5PB2. The printed units remain mJ/mol-at./K²
and K. The prose's 3.16(1)/492(2) values are not substituted for the table's
unqualified printed numbers. Mo5P1.07B1.93 and its uncertainty-bearing refined
formula remain unmatched; the two cited comparison columns remain unmatched.
This is two source-study compositions, **not four completed catalogue fields**.
The original PDF and text hashes and the replay are retained in the private
audit directory; AI visual inspection does not establish independent human
review, publication equivalence or selected-record association.

The existing 19-material, 323-capture historical snapshot was also replayed:
321 material/source pairs retained the same extracted content after excluding
the same two generated sources; versioned IDs change on re-extraction. This
is a bounded regression sample, not a new 200-material accuracy benchmark.

The live chunk adapter does not fabricate table structure from plain prose.
Tables need the explicit primary-source capture path and subsequent review.
This change does not ingest these private captures, update production fields
or resolve missingness for the full catalogue.

The passage grammar also withholds Kelvin-valued gap wording such as
“gap at 9 K” and “gap energy below 9 K” unless an explicit property assignment
is present. A temperature condition near a gap is insufficient to identify an
energy value; an explicit printed Kelvin assignment remains unconverted.
