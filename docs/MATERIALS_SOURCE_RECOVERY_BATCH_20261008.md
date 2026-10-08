# Materials source recovery: first 16-material pilot

Status: implemented and locally tested; pending source/state review. Date: 2026-10-08.

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

The Materials detail page adds a default-collapsed primary-source inspection block with conditions, conflicts, remaining questions and original PDF page links. Its recovery metadata download uses an explicit nested allowlist; full passages, local paths and extra private context are excluded.

Final seed: 160,123 bytes; file SHA256 `c0edc63260ed88688bc62ed58d4f6a8dedcf95366a5c7965cfaa37ca6d47dc1b`; canonical seed digest `e90c55ced760fdb55d82def0a3a0af4ba64dbf041966ce0c04291dbab5f58edd`.

## Validation and next action

Targeted validation passed 20 Python tests and 42 frontend tests, plus TypeScript checking. Actual local merging passed for all 16 current snapshots; the existing private candidate importer reused the final 34 selected facts without canonical writes. Tests cover exact record binding, withdrawal/change, idempotence, original-seed preservation, condition drift, source identity, repeated spans, nested metadata redaction and the two concrete scope errors.

Next work is precise sample/state review and supplemental evidence for the listed conflicts, followed by explicit authorized correction where justified. Deployment, production data changes and claims that the full 200-task queue is complete are outside this delivered increment.
