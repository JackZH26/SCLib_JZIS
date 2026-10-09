# Materials source recovery: first 16-material pilot

Status: implemented; retained-record binding corrected and locally replayed on 2026-10-09. Source/state review remains pending. Original pilot date: 2026-10-08.

The old queue contained 232 tasks, including 200 proposed for its first batch. The current public API was rechecked for all 200 exact material IDs: all returned HTTP 200 with matching ID/formula, between identical version fences (`bcf2d85`, dataset `v2026.09.03`, API `1`). This checks current availability and identity, not completeness or scientific validity. Earlier field-verification receipts do not establish that 200 original papers were fully reviewed.

Sixteen materials were selected across high-pressure hydrides, calculated materials, composition series, processing-dependent samples and criterion-dependent transitions. All 16 original arXiv papers were retrieved with explicit revisions and PDF byte hashes. Their expressions were inspected with page/span hashes; three high-risk tables were also visually checked. This is AI-assisted source inspection, not human approval or an independent experiment. Full papers/passages remain outside the repository.

## Delivered increment

| Measure | Actual result |
|---|---:|
| Legacy IDs checked/available | 200/200 |
| Pilot materials checked / primary PDF available | 16/16 |
| Source observations with original page/span pins | 55 |
| Selected pending literal field candidates | 34 |
| Pilot materials retaining unresolved sample/state questions | 16 |
| Primary-source access blocked | 0 |
| Canonical facts changed / human-approved facts / production DB writes | 0/0/0 |

The 55 observations and 34 candidates overlap; they are not 89 independent new facts. The other 184 queue materials have not received this pilot's original-source inspection.

## Per-material source observations and remaining questions

| Material | Original source | Checked result and remaining association |
|---|---|---|
| (La,Y)H6 | [2012.04787](https://arxiv.org/abs/2012.04787) | H6 is reported at 237 ± 5 K. Nearby H10 values/pressures must not transfer to H6; exact measurement pressure/criterion remain unresolved. |
| Nb4C3O2 | [2403.06380](https://arxiv.org/abs/2403.06380) | The paper reports unstrained 25 K and 2% strain 29 K, while the retained catalogue has 23 K. Calculation/state association needs review. Original ω units remain explicit; no silent overwrite or conversion. |
| MgH26 | [2308.15031](https://arxiv.org/abs/2308.15031) | The calculated table gives 200 GPa, μ*=0.1, λ=0.55, ωlog=1282 K and solver-dependent Tc=22/23/23 K. This is theoretical and differs from the neighboring LaMg3H28 result. |
| CaFe0.93Co0.07AsH | [1312.5818](https://arxiv.org/abs/1312.5818) | The retained 23 K is described beside x=0.07, while other paper statements use x=0.09. Source-internal composition conflict remains visible. Synthesis pressure is separate from Tc measurement conditions. |
| CaFe0.95Ni0.05AsF | [0811.1147](https://arxiv.org/abs/0811.1147) | Nominal x=0.05 and 12 K are reported; pellet transport method is identified. Refined occupancy and precise Tc criterion remain unresolved. |
| Re6Se8Cl2 | [1906.10785](https://arxiv.org/abs/1906.10785) | Approximately 9 K follows current annealing/doping of flakes. Post-treatment composition/device identity cannot automatically be assigned to pristine Re6Se8Cl2. |
| SmFe0.80Co0.20AsO | [1007.5121](https://arxiv.org/abs/1007.5121) | The x=0.1/0.15/0.2 series yields 14/15.5/9 K. Composition-specific assignment is retained; duplicate occurrences from one paper are not independent experiments. |
| Ba3Rh4Ge16 | [2112.00644](https://arxiv.org/abs/2112.00644) | A 7 K polycrystalline result is supported by several measurement methods. Multiple expressions are not multiple independent studies; inferred coupling is separate from DFPT. |
| CrB2 | [2109.15213](https://arxiv.org/abs/2109.15213) | Single-crystal superconductivity reaches approximately 7 K near 100 GPa. Ambient TN≈88.5 K is not Tc; the 12 GPa antiferromagnetic subexperiment is not the whole-study pressure maximum. |
| (Mo0.96Ti0.04)0.8B2 | [2302.14272](https://arxiv.org/abs/2302.14272) | The carbon-free metal-deficient AlB2-type sample reaches 7 K. Carbon-doped samples without a transition down to 1.8 K remain censored negative controls, not Tc=0. |
| Nb2P5 | [2010.05737](https://arxiv.org/abs/2010.05737) | The 2.6 K result, high-pressure synthesis and separate structural/transport preparations are distinguished. Synthesis/pressing pressures do not establish Tc measurement pressure. |
| Be0.024Al0.976 | [1907.07597](https://arxiv.org/abs/1907.07597) | The VCA alloy table reports 1.18 K. A bracketed constituent-metal experimental value does not experimentally validate this exact alloy. |
| Nb4Cu0.2SiSb2 | [2208.04834](https://arxiv.org/abs/2208.04834) | Approximately 1.2 K and a resistive midpoint near 1.16 K are kept distinct. The midpoint is not assigned an unprinted 50% criterion or the parent compound's heat-capacity result. |
| NbScTiZr | [2311.00195](https://arxiv.org/abs/2311.00195) | As-cast/800°C/1000°C samples have 7.9/9/8.7 K, respectively. The eutectic BCC/HCP processing states are distinct; a cited older value is not a new measurement. |
| Re7Ta3 | [2402.07580](https://arxiv.org/abs/2402.07580) | The α-Mn-type I-43m branch differs from hexagonal related alloys. A retained onset and a model-input Tc remain distinct; TRSB is not asserted. |
| Ta2PdSe5 | [1412.6983](https://arxiv.org/abs/1412.6983) | Susceptibility 2.6 K and transport onset/midpoint/zero 2.5/2.2/2.0 K remain separate. Main phase and impurity/sample identity still need review. |

## Implementation and safeguards

`scripts/build_materials_recovery_batch.py` reuses the existing literal extractor. Each admitted rule freezes candidate ID, paper/capture identity, page, field/value and the complete reviewed subject/conditions. Drift or source ambiguity fails generation; an unknown pressure is not filled from an adjacent material. All 34 selected conditions were reviewed: 33 have no inferred pressure, and only the CrB2 Tc=7 K expression carries its explicit approximately 100 GPa pressure.

Two earlier draft candidates were excluded because of concrete source-condition mismatches: the H6/H10 adjacency and the CrB2 pressure scope. The private 36-row draft ledger remains unchanged, with two appended exclusion events; the current selection is 34. A “50% resistivity” explanation absent from the pinned NbCu expression was reduced to “resistive midpoint.”

The independent installed seed `api/services/resources/material_recovery_batch_20261008_seed.json` leaves the old 39-candidate primary seed intact. Its loader only merges onto unchanged current record IDs/hashes and the exact formula. Changed/excluded records hide that observation window. Repeated merges do not duplicate candidates. No candidate or observation grants approval, ML-training permission or canonical correction.

### Retained-record binding correction (2026-10-09)

The first pilot generator received `raw_archive.records[].raw`, a deliberately cropped public display projection. Omitted fields included `ambient_sc`, `paper_type`, `credibility_tier` and `tc_regime`. Hashing that projection produced different IDs/digests from the complete `material.current_records()` used by the runtime guard. Offline replay of the exact `62a80e4` guard against independently pinned public snapshots confirmed that all 31 pilot references differed, suppressing all 16 new observation windows. The guard returned the pre-existing report before mutation, so prior enrichment and canonical records remained intact. Earlier local merge checks reused projected input records and did not establish runtime compatibility.

The builder now requires each material's complete retained `records` plus its API `record_coverage` DTO. Each review-spec row must independently freeze `record_coverage_sha256`. It checks the coverage version, material, denominator, hash, authority flags, complete inventory of 1–32 records and unique offsets; every paper/ID/digest must agree with the complete record. Missing, partial, stale or contradictory bindings fail generation. The seed uses those verified coverage pins. `raw_archive.records[].raw` is not an accepted identity source. Coverage is an integrity anchor for the inspected snapshot, not proof that a snapshot is still current: the unchanged runtime guard still checks the actual current records.

For this correction, 39 complete records were reconstructed from the retained public detail snapshots by removing only known derived display envelopes. Every resulting record matched both the independently captured coverage ID and full-record SHA256. A redacted or incomplete projection that failed either check would have been rejected. All 34 candidates were re-extracted and reselected only when every nonidentity field exactly matched the prior inspected candidate, including source paper/capture/page/span, value, complete subject/conditions and authority. All 55 observation objects, their locators, summaries and unresolved questions are unchanged. The seed ID and dependent retained-reference, candidate, report and seed hashes were updated; no fact was promoted or reassigned to another paper.

The Materials detail page adds a default-collapsed primary-source inspection block with conditions, conflicts, remaining questions and original PDF page links. Its recovery metadata download uses an explicit nested allowlist; full passages, local paths and extra private context are excluded.

Corrected seed `materials-primary16-2026-10-09-v2`: 160,123 bytes; file SHA256 `88ab9d4216ab15693cfa680e0c5d72937c62292408d8961db609b8374c9e0ff4`; canonical seed digest `ea347f50f1e440960f309e7bb4365c305a583c43576f90709568caeb0c6cbc81`. The original acceptance receipt in `docs/data/discovery-batches-20261008/local-acceptance-v1.json` remains a historical record of the first seed; its merge result is superseded by the full-record replay described here.

## Validation and next action

Original UI validation passed 42 frontend tests and TypeScript checking. This binding repair changes no UI or runtime merge logic. Targeted Python validation passed 64 tests across recovery, record coverage and the original primary seed. Two small frozen public fixtures exercise the shipped seed against the full records for Nb4C3O2 and Ba3Rh4Ge16, including the previously omitted fields, a zero-candidate observation window and multiple occurrences from one paper. Synthetic cases reject cropped records and missing, stale or contradictory coverage; they also preserve condition/source/span checks.

Independent private replay with all 39 coverage-verified full records admits all 16 windows, adds the same 34 pending facts and exposes the same 55 observations. Existing candidates remain byte-for-byte intact, repeated merges are identical, and changed/excluded references or changed formulas still suppress the corresponding window. The runtime merger, extractor, identity calculation and earlier primary/classification seeds are byte-identical to `62a80e4`. This is an offline replay of frozen snapshots, not a new claim about live production state. No API call, production database write or scientific approval was performed for the repair.

Next work is precise sample/state review and supplemental evidence for the listed conflicts, followed by explicit authorized correction where justified. Deployment, production data changes and claims that the full 200-task queue is complete are outside this delivered increment.
