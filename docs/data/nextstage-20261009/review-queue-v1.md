# Source review queue and retrieval question inventory

Version: 2026-10-09-v1. Generated from pinned public metadata.

All decisions remain pending. This is an AI-assisted acquisition draft, not human adjudication,
a gold set, an executed retrieval benchmark or an approved training dataset.

The [machine-readable package](review-preparation-v1.json) retains original source revisions,
page/span hashes, Result references, input pins and every unresolved condition.

## Sixteen material reviews

### (La,Y)H6

Material: `mat:layh6`. Reviewers: unassigned. Decision: pending.

The source reports a 237 ± 5 K transition assigned to the hexahydride; the main text also describes a shelf possibly caused by that phase. H10 values and pressures cannot be transferred to H6.

Inspected source windows:

- tc_kelvin: 237 ± 5 K. Scope: Hexahydride assignment; not H10's 253 K. [2012.04787v1, p. 1](https://arxiv.org/pdf/2012.04787v1#page=1).
- measurement_method: Four-probe electrical resistance. Scope: Shared experimental protocol; occurrence association pending. [2012.04787v1, p. 6](https://arxiv.org/pdf/2012.04787v1#page=6).
- sample_state: Additional shelf; possible H6 phase. Scope: Author-qualified assignment, not a pure-phase certificate. [2012.04787v1, p. 6](https://arxiv.org/pdf/2012.04787v1#page=6).

Resolve before accepting a label:

- Exact pressure and criterion of the retained 237 K occurrence remain unresolved.
- La:Y ratio, H4/YH6 impurities and phase assignment need sample-level review.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Nb4C3O2

Material: `mat:nb4c3o2`. Reviewers: unassigned. Decision: pending.

The paper's unstrained Nb4C3O2 paragraph reports 25 K, rising to 29 K at 2% strain. The current 23 K occurrence must not be silently replaced or matched by abstract ordering.

Inspected source windows:

- tc_kelvin: 25.00 K. Scope: Anisotropic Migdal–Eliashberg paragraph; conflicts with retained 23 K association. [2403.06380v1, p. 5](https://arxiv.org/pdf/2403.06380v1#page=5).
- tc_kelvin: 29.00 K. Scope: Strained state, separate from unstrained occurrence. [2403.06380v1, p. 5](https://arxiv.org/pdf/2403.06380v1#page=5).
- omega_log_source_value: 243 meV. Scope: Original source unit; not an observed temperature. [2403.06380v1, p. 4](https://arxiv.org/pdf/2403.06380v1#page=4).
- calculation_method: McMillan–Allen–Dynes and anisotropic Migdal–Eliashberg. Scope: Two author-reported model contexts remain separate. [2403.06380v1, p. 5](https://arxiv.org/pdf/2403.06380v1#page=5).

Resolve before accepting a label:

- Resolve the current 23 K occurrence against the paper's material and method assignments.
- Author-reported 243 meV frequency remains in its original unit; no K conversion is promoted.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### MgH26

Material: `mat:mgh26`. Reviewers: unassigned. Decision: pending.

Table 1 binds MgH26 to 200 GPa, μ*=0.1 and distinct calculated Tc methods. Its 23 K is a model result; it is not the 164 K prediction for LaMg3H28.

Inspected source windows:

- pressure_gpa: 200 GPa. Scope: Table 1 MgH26 column. [2308.15031v2, p. 7](https://arxiv.org/pdf/2308.15031v2#page=7).
- tc_kelvin: McMillan 22 K; Allen–Dynes 23 K; Eliashberg 23 K. Scope: Table 1 second material column, visually checked. [2308.15031v2, p. 7](https://arxiv.org/pdf/2308.15031v2#page=7).
- lambda_eph: 0.55. Scope: Table 1 MgH26 column. [2308.15031v2, p. 7](https://arxiv.org/pdf/2308.15031v2#page=7).
- omega_log_source_value: 1282 K. Scope: Table 1 MgH26 column. [2308.15031v2, p. 7](https://arxiv.org/pdf/2308.15031v2#page=7).
- mu_star: 0.1. Scope: Table 1 calculation note. [2308.15031v2, p. 7](https://arxiv.org/pdf/2308.15031v2#page=7).

Resolve before accepting a label:

- No experimental superconductivity is established by this source.
- The 2×2×2 phonon sampling and molecular-H phase remain model limitations.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### CaFe0.93Co0.07AsH

Material: `mat:cafe0.93co0.07ash`. Reviewers: unassigned. Decision: pending.

Zero resistance appears from x≥0.07. The text adjoining pages 7–8 links the maximum onset to x=0.07, while the abstract and later phase-diagram discussion use x=0.09. This is a source-internal composition issue.

Inspected source windows:

- tc_criterion: Zero resistance from x≥0.07. Scope: Composition-series evidence, not automatic exact-sample binding. [1312.5818v2, p. 7](https://arxiv.org/pdf/1312.5818v2#page=7).
- pressure_gpa: 2 GPa; 1273 K; 30 min. Scope: Synthesis only; not superconducting measurement pressure. [1312.5818v2, p. 4](https://arxiv.org/pdf/1312.5818v2#page=4).
- measurement_method: Electrical resistivity and magnetic susceptibility. Scope: Original composition series. [1312.5818v2, p. 7](https://arxiv.org/pdf/1312.5818v2#page=7).

Resolve before accepting a label:

- Resolve nominal versus analyzed x and the conflicting maximum-Tc assignments before updating the 23 K occurrence.
- The 2 GPa synthesis pressure is not the measurement pressure.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### CaFe0.95Ni0.05AsF

Material: `mat:cafe0.95ni0.05asf`. Reviewers: unassigned. Decision: pending.

The source assigns its 12 K optimum to nominal Ni x=0.05. Measurements concern sintered solid-state-reaction samples; nominal doping is not a verified local occupancy map.

Inspected source windows:

- tc_kelvin: 12 K at x=0.05. Scope: Abstract nominal composition-series association. [0811.1147v2, p. 1](https://arxiv.org/pdf/0811.1147v2#page=1).
- sample_form: Sintered pellets. Scope: Shared preparation protocol. [0811.1147v2, p. 4](https://arxiv.org/pdf/0811.1147v2#page=4).
- measurement_method: Four-probe DC electrical resistivity. Scope: 2–300 K measurement range, not Tc itself. [0811.1147v2, p. 4](https://arxiv.org/pdf/0811.1147v2#page=4).

Resolve before accepting a label:

- Refined Ni content and exact Tc criterion of the retained occurrence need review.
- Measurement pressure is not supplied in the inspected window.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Re6Se8Cl2

Material: `mat:re6se8cl2`. Reviewers: unassigned. Decision: pending.

The approximately 9 K transition belongs to annealed/doped devices. The nominal parent formula must not imply pristine Re6Se8Cl2 is intrinsically superconducting.

Inspected source windows:

- tc_kelvin: Below approximately 9 K. Scope: After current annealing, not pristine material. [1906.10785v1, p. 4](https://arxiv.org/pdf/1906.10785v1#page=4).
- measurement_method: Longitudinal and Hall resistance. Scope: Exfoliated flakes, approximately 100–500 nm thick. [1906.10785v1, p. 4](https://arxiv.org/pdf/1906.10785v1#page=4).
- sample_form: Bulk single-crystal devices also studied. Scope: Distinct from exfoliated flakes. [1906.10785v1, p. 24](https://arxiv.org/pdf/1906.10785v1#page=24).

Resolve before accepting a label:

- Post-anneal Cl stoichiometry and the exact retained device remain unresolved.
- No single Tc criterion or universal transition is inferred across devices.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Ba3Rh4Ge16

Material: `mat:ba3rh4ge16`. Reviewers: unassigned. Decision: pending.

The 7 K source study combines transport, magnetization, heat capacity and μSR on a polycrystalline material. Several retained measurement records remain one paper, not independent replication.

Inspected source windows:

- tc_kelvin: 7.0 K. Scope: Combined experimental study. [2112.00644v1, p. 1](https://arxiv.org/pdf/2112.00644v1#page=1).
- sample_form: Polycrystalline; arc melted and annealed. Scope: 1000 °C for 20 h preparation. [2112.00644v1, p. 1](https://arxiv.org/pdf/2112.00644v1#page=1).
- space_group: I4/mmm. Scope: Powder refinement; no coordinates validated by this batch. [2112.00644v1, p. 2](https://arxiv.org/pdf/2112.00644v1#page=2).

Resolve before accepting a label:

- Exact criterion and occurrence-to-specimen correspondence remain pending.
- The inferred coupling parameter is not an independent DFPT measurement.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### CrB2

Material: `mat:crb2`. Reviewers: unassigned. Decision: pending.

The selected paper concerns pressure-induced superconductivity after antiferromagnetic suppression. Ambient TN≈88.5 K and room-temperature XRD pressures are not superconducting Tc conditions.

Inspected source windows:

- tc_kelvin: Approximately 7 K near 100 GPa. Scope: Author-reported pressure dependence, not ambient Tc. [2109.15213v1, p. 3](https://arxiv.org/pdf/2109.15213v1#page=3).
- sample_form: Al-flux-grown single crystals. Scope: Selected experimental paper. [2109.15213v1, p. 3](https://arxiv.org/pdf/2109.15213v1#page=3).
- competition: TN≈88.5 K. Scope: Antiferromagnetic transition, not Tc. [2109.15213v1, p. 4](https://arxiv.org/pdf/2109.15213v1#page=4).

Resolve before accepting a label:

- Associate each retained Tc and each linked paper with its own pressure and criterion.
- This inspection does not certify ambient superconductivity or the highest-pressure phase purity.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### (Mo0.96Ti0.04)0.8B2

Material: `mat:(mo0.96ti0.04)0.8b2`. Reviewers: unassigned. Decision: pending.

The carbon-free source composition is the 7 K superconductor. Carbon-doped x=0.12 and 0.16 controls show no resistivity drop down to 1.8 K, which is a detection limit rather than Tc=0.

Inspected source windows:

- tc_kelvin: 7.0 K. Scope: x=0 parent; not carbon-doped controls. [2302.14272v1, p. 1](https://arxiv.org/pdf/2302.14272v1#page=1).
- crystal_structure: AlB2 type; P6/mmm. Scope: Dominant phase, not a pure-phase assertion. [2302.14272v1, p. 4](https://arxiv.org/pdf/2302.14272v1#page=4).
- negative_control: No resistivity drop down to 1.8 K. Scope: Censored result for x=0.12/0.16; not a zero-temperature value. [2302.14272v1, p. 15](https://arxiv.org/pdf/2302.14272v1#page=15).

Resolve before accepting a label:

- Exact physical specimen and pressure association remain pending.
- A nominal metal-deficient formula is not a validated occupancy model.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Nb2P5

Material: `mat:nb2p5`. Reviewers: unassigned. Decision: pending.

Nb2P5 is synthesized under pressure and quenched before characterization. Single-crystal diffraction and a pressed dense-polycrystal transport specimen must remain separate sample roles.

Inspected source windows:

- tc_kelvin: Approximately 2.6 K. Scope: Resistivity, magnetization and specific-heat study. [2010.05737v1, p. 1](https://arxiv.org/pdf/2010.05737v1#page=1).
- space_group: Pnma; orthorhombic. Scope: Single-crystal structure determination. [2010.05737v1, p. 2](https://arxiv.org/pdf/2010.05737v1#page=2).
- sample_form: Dense polycrystal pressed from crystals at 6 GPa. Scope: Preparation condition, not measurement pressure. [2010.05737v1, p. 2](https://arxiv.org/pdf/2010.05737v1#page=2).
- pressure_gpa: 3.5 GPa. Scope: Synthesis pressure only. [2010.05737v1, p. 2](https://arxiv.org/pdf/2010.05737v1#page=2).

Resolve before accepting a label:

- The 3.5 GPa reaction and 6 GPa pressing pressures are not Tc measurement conditions.
- Transport, diffraction and magnetic specimen correspondence needs review.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Be0.024Al0.976

Material: `mat:be0.024al0.976`. Reviewers: unassigned. Decision: pending.

Table I's Be:Al 24:976 row is a virtual-crystal calculation. The bracketed 1.18 K refers to the doping metal, not an experimental confirmation of the exact alloy.

Inspected source windows:

- tc_kelvin: 1.18 K. Scope: Table I model column; bracketed value belongs to doping metal. [1907.07597v2, p. 4](https://arxiv.org/pdf/1907.07597v2#page=4).
- composition_identity: Be:Al = 24:976. Scope: Equivalent decimal composition is a proposal, not refined occupancy. [1907.07597v2, p. 4](https://arxiv.org/pdf/1907.07597v2#page=4).
- calculation_method: Virtual-crystal approximation; McMillan / Allen–Dynes. Scope: Model comparison, not observed superconductivity. [1907.07597v2, p. 4](https://arxiv.org/pdf/1907.07597v2#page=4).

Resolve before accepting a label:

- No exact-alloy experimental confirmation is established here.
- The virtual-crystal/Debye interpolation assumptions require model-scope retention.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Nb4Cu0.2SiSb2

Material: `mat:nb4cu0.2sisb2`. Reviewers: unassigned. Decision: pending.

The approximate 1.2 K abstract value is refined to a 1.16 K resistive midpoint in Figure 4/Table 3. Interstitial Cu lowers Tc relative to the parent; no parent heat-capacity jump is transferred to this child.

Inspected source windows:

- tc_kelvin: 1.16 K. Scope: Figure 4 and Table 3; zero applied field. [2208.04834v1, p. 6](https://arxiv.org/pdf/2208.04834v1#page=6).
- tc_criterion: Resistive midpoint. Scope: Distinct from approximate abstract value. [2208.04834v1, p. 6](https://arxiv.org/pdf/2208.04834v1#page=6).
- sample_form: Polycrystalline solid-state-reaction samples. Scope: Shared preparation; refined occupancy remains separate. [2208.04834v1, p. 2](https://arxiv.org/pdf/2208.04834v1#page=2).

Resolve before accepting a label:

- Exact refined Cu occupancy and retained sample association remain pending.
- No child-specific heat-capacity confirmation is inferred from the parent row.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### NbScTiZr

Material: `mat:nbsctizr`. Reviewers: unassigned. Decision: pending.

The source compares as-cast and annealed eutectic samples: 7.9 K, 9 K at 800 °C, and 8.7 K at 1000 °C. Mixed bcc/hcp microstructure and processing conditions prevent one universal Tc assignment.

Inspected source windows:

- tc_kelvin: 7.9 K. Scope: As-cast sample. [2311.00195v1, p. 1](https://arxiv.org/pdf/2311.00195v1#page=1).
- tc_kelvin: 9 K. Scope: Different processed state. [2311.00195v1, p. 1](https://arxiv.org/pdf/2311.00195v1#page=1).
- tc_kelvin: 8.7 K. Scope: Different processed state. [2311.00195v1, p. 1](https://arxiv.org/pdf/2311.00195v1#page=1).
- crystal_structure: Eutectic bcc and hcp phases. Scope: Not a single ordered crystal prototype. [2311.00195v1, p. 1](https://arxiv.org/pdf/2311.00195v1#page=1).

Resolve before accepting a label:

- Attach each retained measurement occurrence to the correct annealed specimen.
- Exact phase fraction, composition and criterion need sample-level review.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Re7Ta3

Material: `mat:re7ta3`. Reviewers: unassigned. Decision: pending.

Re7Ta3 belongs to the noncentrosymmetric α-Mn branch, not the hexagonal Hf/Zr branch in the same table. The article uses a 2.69 K model input; the retained 2.6 K onset remains distinct.

Inspected source windows:

- space_group: α-Mn type; I-43m. Scope: Table I second material column; not hexagonal Re7Hf3/Re7Zr3. [2402.07580v1, p. 2](https://arxiv.org/pdf/2402.07580v1#page=2).
- tc_kelvin: 2.69 K. Scope: Ordered list Ta is second; not a replacement for retained onset. [2402.07580v1, p. 4](https://arxiv.org/pdf/2402.07580v1#page=4).
- measurement_method: ZFC/FCC magnetization at 1 mT. Scope: Shared alloy measurement protocol. [2402.07580v1, p. 3](https://arxiv.org/pdf/2402.07580v1#page=3).

Resolve before accepting a label:

- Reconcile the susceptibility onset with the source's 2.69 K input and measurement-specific criteria.
- TRSB or an unconventional pairing state is not established by this extraction.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### Ta2PdSe5

Material: `mat:ta2pdse5`. Reviewers: unassigned. Decision: pending.

The source separates susceptibility onset 2.6 K from resistive onset 2.5 K, midpoint 2.2 K and zero 2.0 K. A small Pd7Se4 impurity is retained as a specimen limitation.

Inspected source windows:

- tc_kelvin: Approximately 2.6 K. Scope: DC magnetization in 10 Oe. [1412.6983v3, p. 2](https://arxiv.org/pdf/1412.6983v3#page=2).
- tc_kelvin: Onset 2.5 K; midpoint 2.2 K; zero 2.0 K. Scope: Three distinct criteria; not three independent studies. [1412.6983v3, p. 2](https://arxiv.org/pdf/1412.6983v3#page=2).
- space_group: Monoclinic C2/m. Scope: Powder refinement with Pd7Se4 impurity. [1412.6983v3, p. 2](https://arxiv.org/pdf/1412.6983v3#page=2).
- sample_form: Polycrystalline; solid-state reaction. Scope: Nominal Ta:Pd:Se source ratio 2:1:5.5 includes excess Se. [1412.6983v3, p. 2](https://arxiv.org/pdf/1412.6983v3#page=2).

Resolve before accepting a label:

- Exact occurrence-to-specimen association remains pending.
- Missing measurement pressure is not interpreted as ambient by this batch.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

### SmFe0.80Co0.20AsO

Material: `mat:smfe0.80co0.20aso`. Reviewers: unassigned. Decision: pending.

The x=0.20 member is assigned 9 K in the composition series. Two retained susceptibility occurrences from the same paper do not establish two independent experiments. The 0.15 member's critical fields are not transferred.

Inspected source windows:

- tc_kelvin: 9 K. Scope: Three composition-series values aligned in the abstract. [1007.5121v3, p. 1](https://arxiv.org/pdf/1007.5121v3#page=1).
- sample_form: Polycrystalline; solid-state reaction. Scope: Shared preparation protocol. [1007.5121v3, p. 3](https://arxiv.org/pdf/1007.5121v3#page=3).
- space_group: P4/nmm; tetragonal. Scope: Series refinement, not validated site occupancies. [1007.5121v3, p. 3](https://arxiv.org/pdf/1007.5121v3#page=3).
- measurement_method: Four-probe resistivity, heat capacity and magnetization. Scope: Shared measurement apparatus and protocol. [1007.5121v3, p. 3](https://arxiv.org/pdf/1007.5121v3#page=3).

Resolve before accepting a label:

- Nominal x=0.20 to refined composition and exact specimen remains pending.
- No measurement pressure or uniquely defined Tc criterion is established in the inspected window.

Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.

## Sixty draft retrieval questions

40 English and 20 Chinese questions. All are unassigned to a split and not run.
Related source questions and known retrospective cases must not be treated as independent held-out examples.

1. What transition is assigned to (La,Y)H6 in arXiv:2012.04787v1, including uncertainty? (`review-question:mat:layh6:1`; en; numerical)

2. Can the H10 pressure and 253 K transition be assigned to the H6 occurrence? (`review-question:mat:layh6:2`; en; comparison_or_clarification)

3. (La,Y)H6 的 La:Y 比例、相纯度、压力和判据是否已经明确？ (`review-question:mat:layh6:3`; zh; mixed_source_context)

4. Which unstrained and 2% strained Tc values does arXiv:2403.06380 report for Nb4C3O2? (`review-question:mat:nb4c3o2:1`; en; numerical)

5. Does a catalogue value of 23 K identify the same Nb4C3O2 state as the source's 25 or 29 K calculations? (`review-question:mat:nb4c3o2:2`; en; comparison_or_clarification)

6. Nb4C3O2 的这些 Tc 是实验测量还是计算结果，能否跨应变状态合并？ (`review-question:mat:nb4c3o2:3`; zh; mixed_source_context)

7. What Tc methods, pressure, lambda and omega-log qualify the MgH26 row in arXiv:2308.15031? (`review-question:mat:mgh26:1`; en; numerical)

8. Can MgH26's computed table row be replaced with a LaMg3H28 result from the same paper? (`review-question:mat:mgh26:2`; en; comparison_or_clarification)

9. MgH26 的 22、23、23 K 分别属于哪些求解方法，是否表示三次独立实验？ (`review-question:mat:mgh26:3`; zh; mixed_source_context)

10. What Co fraction and Tc are paired in arXiv:1312.5818 for CaFe0.93Co0.07AsH? (`review-question:mat:cafe0.93co0.07ash:1`; en; numerical)

11. Is synthesis pressure in this paper a measurement pressure for the retained Tc occurrence? (`review-question:mat:cafe0.93co0.07ash:2`; en; comparison_or_clarification)

12. CaFe0.93Co0.07AsH 的 x=0.07 与 x=0.09 是否属于同一样品状态？ (`review-question:mat:cafe0.93co0.07ash:3`; zh; mixed_source_context)

13. What nominal Ni fraction and pellet Tc does arXiv:0811.1147 report? (`review-question:mat:cafe0.95ni0.05asf:1`; en; numerical)

14. Does the inspected source window establish onset, midpoint or zero-resistance Tc for CaFe0.95Ni0.05AsF? (`review-question:mat:cafe0.95ni0.05asf:2`; en; comparison_or_clarification)

15. CaFe0.95Ni0.05AsF 的名义组成能否直接作为已审核的实际样品组成？ (`review-question:mat:cafe0.95ni0.05asf:3`; zh; mixed_source_context)

16. What transition and treatment context are retained for Re6Se8Cl2 in arXiv:1906.10785? (`review-question:mat:re6se8cl2:1`; en; numerical)

17. Can a transition after annealing identify the untreated Re6Se8Cl2 bulk phase without a post-treatment sample association? (`review-question:mat:re6se8cl2:2`; en; comparison_or_clarification)

18. Re6Se8Cl2 的退火薄片与原始材料身份是否已经对应，缺少哪些核查？ (`review-question:mat:re6se8cl2:3`; zh; mixed_source_context)

19. What sample form and transition does arXiv:2112.00644 report for Ba3Rh4Ge16? (`review-question:mat:ba3rh4ge16:1`; en; numerical)

20. Is the retained lambda for Ba3Rh4Ge16 inferred from reported measurements or a native DFPT result? (`review-question:mat:ba3rh4ge16:2`; en; comparison_or_clarification)

21. Ba3Rh4Ge16 的方法推断与第一性原理计算应如何区分，来源定位在哪里？ (`review-question:mat:ba3rh4ge16:3`; zh; mixed_source_context)

22. What pressure range and superconducting transition are inspected in arXiv:2109.15213 for CrB2? (`review-question:mat:crb2:1`; en; numerical)

23. Is 88.5 K a superconducting Tc, and does the 12 GPa AF substudy define the maximum pressure of the entire paper? (`review-question:mat:crb2:2`; en; comparison_or_clarification)

24. CrB2 的常压反铁磁结果能否直接证明约 100 GPa 下同一状态的磁序？ (`review-question:mat:crb2:3`; zh; mixed_source_context)

25. What transition is reported for carbon-free (Mo0.96Ti0.04)0.8B2 in arXiv:2302.14272? (`review-question:mat:(mo0.96ti0.04)0.8b2:1`; en; numerical)

26. Does no observed transition down to 1.8 K in the carbon-doped sample mean Tc equals zero? (`review-question:mat:(mo0.96ti0.04)0.8b2:2`; en; comparison_or_clarification)

27. 碳掺杂与未掺杂的 (Mo0.96Ti0.04)0.8B2 能否共享同一个超导标签？ (`review-question:mat:(mo0.96ti0.04)0.8b2:3`; zh; mixed_source_context)

28. What Tc is inspected for Nb2P5 in arXiv:2010.05737? (`review-question:mat:nb2p5:1`; en; numerical)

29. Can Nb2P5 synthesis or pressing pressure be treated as superconducting measurement pressure? (`review-question:mat:nb2p5:2`; en; comparison_or_clarification)

30. Nb2P5 的 Tc 判据和实际测量压力是否已完成样品级对应？ (`review-question:mat:nb2p5:3`; zh; mixed_source_context)

31. What model and Tc qualify Be0.024Al0.976 in arXiv:1907.07597? (`review-question:mat:be0.024al0.976:1`; en; numerical)

32. Do bracketed elemental-metal experiments independently validate the virtual-crystal Be-Al alloy calculation? (`review-question:mat:be0.024al0.976:2`; en; comparison_or_clarification)

33. Be0.024Al0.976 的 VCA 结果能否标注为实测超导转变？ (`review-question:mat:be0.024al0.976:3`; zh; mixed_source_context)

34. How are the approximately 1.2 K and 1.16 K transitions described in arXiv:2208.04834? (`review-question:mat:nb4cu0.2sisb2:1`; en; numerical)

35. Does the inspected paper explicitly print a 50% criterion, and can a parent heat-capacity result be transferred to Nb4Cu0.2SiSb2? (`review-question:mat:nb4cu0.2sisb2:2`; en; comparison_or_clarification)

36. Nb4Cu0.2SiSb2 与母体材料的热容、输运结果是否属于同一实验样品？ (`review-question:mat:nb4cu0.2sisb2:3`; zh; mixed_source_context)

37. What Tc values belong to the cast, 800 C and 1000 C NbScTiZr states in arXiv:2311.00195? (`review-question:mat:nbsctizr:1`; en; numerical)

38. Can the 7.9, 9 and 8.7 K values be collapsed into one state-independent NbScTiZr training label? (`review-question:mat:nbsctizr:2`; en; comparison_or_clarification)

39. NbScTiZr 的退火温度是不是超导测量温度，来源中如何区分？ (`review-question:mat:nbsctizr:3`; zh; mixed_source_context)

40. Which Re7Ta3 structural states and transition descriptions appear in arXiv:2402.07580? (`review-question:mat:re7ta3:1`; en; numerical)

41. Does an onset transition establish time-reversal-symmetry breaking or validate an unrelated model input? (`review-question:mat:re7ta3:2`; en; comparison_or_clarification)

42. Re7Ta3 的 alpha-Mn I-43m 与六方相能否合并为同一个材料状态？ (`review-question:mat:re7ta3:3`; zh; mixed_source_context)

43. Which susceptibility and transport transition criteria qualify Ta2PdSe5 in arXiv:1412.6983? (`review-question:mat:ta2pdse5:1`; en; numerical)

44. Are 2.6, 2.5, 2.2 and 2.0 K interchangeable Tc measurements, and is the impurity association resolved? (`review-question:mat:ta2pdse5:2`; en; comparison_or_clarification)

45. Ta2PdSe5 的起始、中点、零电阻与磁化率判据应如何分别保留？ (`review-question:mat:ta2pdse5:3`; zh; mixed_source_context)

46. How do Tc values differ at x=0.1, 0.15 and 0.2 in arXiv:1007.5121? (`review-question:mat:smfe0.80co0.20aso:1`; en; numerical)

47. Do duplicate records of SmFe0.80Co0.20AsO establish independent replication? (`review-question:mat:smfe0.80co0.20aso:2`; en; comparison_or_clarification)

48. SmFe0.80Co0.20AsO 的 9 K 能否与其他 Co 掺杂比例的 14 或 15.5 K 合并？ (`review-question:mat:smfe0.80co0.20aso:3`; zh; mixed_source_context)

49. What source-state limitations and counterexamples qualify the proposed TiNb2Mo comparison? (`review-question:source-check:agm001228974`; en; comparison_or_mechanism)

50. What source-state limitations and counterexamples qualify the proposed HfNbTa comparison? (`review-question:source-check:agm001271506`; en; comparison_or_mechanism)

51. What source-state limitations and counterexamples qualify the proposed TiZr comparison? (`review-question:source-check:agm003157370`; en; comparison_or_mechanism)

52. What source-state limitations and counterexamples qualify the proposed NaAuH3 comparison? (`review-question:source-check:agm002489249`; en; comparison_or_mechanism)

53. What source-state limitations and counterexamples qualify the proposed Cr2Re comparison? (`review-question:source-check:agm003203668`; en; comparison_or_mechanism)

54. What source-state limitations and counterexamples qualify the proposed N2TiZr comparison? (`review-question:source-check:agm002346313`; en; comparison_or_mechanism)

55. What source-state limitations and counterexamples qualify the proposed Be4ZrRh comparison? (`review-question:source-check:agm003204399`; en; comparison_or_mechanism)

56. What source-state limitations and counterexamples qualify the proposed Nb6GaSb comparison? (`review-question:source-check:agm003262771`; en; comparison_or_mechanism)

57. YZr3N4 的来源结果、结构状态与对照是否支持实验超导或室温超导结论？请保留未解决条件。 (`review-question:source-check:agm003559755`; zh; comparison_or_mechanism)

58. Nb2TiMo 的来源结果、结构状态与对照是否支持实验超导或室温超导结论？请保留未解决条件。 (`review-question:anchor:nb2timo-bcc`; zh; comparison_or_mechanism)

59. HfNbTa 的来源结果、结构状态与对照是否支持实验超导或室温超导结论？请保留未解决条件。 (`review-question:anchor:hfnbta-bcc`; zh; comparison_or_mechanism)

60. MgB2 with Al or C substitution 的来源结果、结构状态与对照是否支持实验超导或室温超导结论？请保留未解决条件。 (`review-question:anchor:mgb2-al-c`; zh; comparison_or_mechanism)
