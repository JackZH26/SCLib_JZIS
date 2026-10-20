## Scope

Gating specifies an applied-voltage protocol, not its microscopic mechanism. A solid dielectric can accumulate interfacial charge; an electrolyte can also change oxygen content, drive redox or move ions. Whether a particular experiment is predominantly electrostatic requires evidence about the actual material, temperature, time and voltage history. Reversible resistance alone is insufficient: Jeong's VO2 study demonstrated reversible conductance switching associated with oxygen-vacancy formation. That experiment is a mechanism control, not a superconducting discovery. [R8](#ref-source-cd5c2b85b8e3a53c)

Keep the early platforms separate. Ueno and colleagues reported gated SrTiO3 in a paper published online on 12 October 2008. Ye and colleagues reported ZrNCl with a transition temperature of 15.2 K; that paper appeared online on 22 November 2009 and in the February 2010 issue. The online and issue dates describe one ZrNCl paper, not separate discoveries. The accessible author-institution records support the material and attribution; the checked ZrNCl abstract does not specify an onset, midpoint or zero-resistance criterion. No exact SrTiO3 transition temperature or common criterion is assigned from these limited records. [R2](#ref-source-3c6933981eaa417d) [R3](#ref-source-831c3a9c5619ac1d)

## Mathematical assumptions

For a uniform planar device with constant areal capacitance $C_A$, an electron-accumulation convention gives $\Delta n_{2D}=C_A\Delta V/e$, where $e>0$. If the measured total differential capacitance $C(V)=dQ/dV$ varies with voltage, use $\Delta n_{2D}=(Ae)^{-1}\int C(V)\,dV$ for gated area $A$. Multiplying the endpoint capacitance by the entire voltage interval is generally wrong. Caviglia explicitly integrated the nonlinear response of the SrTiO3 dielectric. [R1](#ref-source-e9e3a49b753191bc)

In a simple positive-capacitance model, $C_A^{-1}=C_{g,A}^{-1}+C_{q,A}^{-1}$ accounts for geometric and quantum capacitances in series, with $C_{q,A}=e^2\partial n_{2D}/\partial\mu$. Traps, leakage, negative compressibility and spatially nonuniform channels require a richer treatment. For two gates, the ideal charge estimate is $en_{2D}=C_{t,A}(V_t-V_{t0})+C_{b,A}(V_b-V_{b0})$. Offset voltages and dielectric calibration are assumptions to report, not quantities fixed by the formula. [R1](#ref-source-e9e3a49b753191bc) [R6](#ref-source-117f1ab64b772ff1) [R7](#ref-source-e8160470a5b03301)

Sajadi calls the gate-derived quantity a doping density, not a measured mobile-carrier density: correlations and edge conduction complicate that identification. The author's supplementary Table 1 uses AFM thicknesses and assumed relative permittivities of 4 for hBN and 3.9 for SiO2 to calculate geometric areal capacitances:

| Device and gate | Dielectric stack | Calculated capacitance (nF/cm²) |
| --- | --- | --- |
| M1 top | 5.8 nm hBN | 611 |
| M1 bottom | 18 nm hBN + 285 nm SiO2 | 11.4 |
| M2 top | 8 nm hBN | 443 |
| M2 bottom | 29 nm hBN | 122 |

In a uniform planar model, the layers in M1's bottom dielectric are in series. Omitting its SiO2 layer would overestimate that capacitance by about 17 times. This is a local calculation from rounded source inputs, not an experimental recalibration. The geometric approximation does not include every quantum-capacitance, contact-screening or trapping effect.

Even a fixed estimated density does not specify both gate voltages: with constant capacitances, $c_t\Delta V_t+c_b\Delta V_b=0$ leaves the voltage-weighted sum unchanged while their difference changes. This identity does not demonstrate an unchanged transverse field, current path or superconducting state. Similarly, $Q=\int I_gdt$ is transferred charge, without assigning its partition among the channel, traps and chemical reactions. Geometry arithmetic does not measure mobile carriers. [R7](#ref-source-e8160470a5b03301) [R8](#ref-source-cd5c2b85b8e3a53c)

## Experimental criteria

Caviglia's LaAlO3/SrTiO3 device used the substrate as a back-gate dielectric. Its capacitance depended on sweep history; conditioning at the highest positive voltage produced reproducible sweeps, and the resulting zero-voltage state was not the as-grown state. The superconducting dome used temperatures extracted from a BKT resistance model, reaching approximately 0.310 K. The 0.400 K normal-state resistance and 1.5 K capacitance measurements are separate observables. Preserve the fit model and preparation history when comparing this dome with other systems. [R1](#ref-source-e9e3a49b753191bc)

Fatemi's monolayer WTe2 device 1 illustrates why one transition has several temperatures. At bottom/top gate voltages 4/5 V, resistance reached 90% of its normal value near 0.820 K, 50% near 0.580 K and zero near 0.350 K. Device 2 reached a midpoint near 0.950 K but retained residual resistance attributed to a device imperfection. The two devices and criteria must not be collapsed into “zero resistance at 1 K.” Their Hall and capacitance estimates broadly agreed, with low-density deviations discussed as possibly inhomogeneous transport. [R6](#ref-source-117f1ab64b772ff1)

MoS2 provides a related criterion warning. Ye established a gate-controlled dome in a band insulator. In Lu's later author manuscript, the phase-diagram panel uses 90% of the normal resistance at 15 K, whereas the remaining analysis uses 50%. A corresponding low-temperature state is labeled 2.63 K by the former criterion and 2.37 K by the latter. Keep those labels distinct from BKT temperatures or high-field boundaries. The layer-localization and spin–orbit interpretation also depends on the device model and field orientation. [R4](#ref-source-e8b9a66d143832fb) [R5](#ref-source-cba51ab2111ccf0a)

Sajadi's M1 device uses the characteristic temperature $T_{1/2}$ where the measured resistance reaches half its value at 1 K. The 1 K reference is not $T_c$. Supplementary section S8 explicitly distinguishes characteristic parameters from precise critical parameters; gradual transitions and limited contact arrangements constrain their interpretation. Different fractions of the normal resistance produce different characteristic fields and derived lengths.

At 20 mK, M1 reaches a roughly 0.3 ohm experimental noise floor for the reported gate-derived density above $7\times10^{12}\,\mathrm{cm}^{-2}$. This is finite measurement sensitivity under specified conditions, not exact mathematical zero or a transition at 20 mK. Its sheet-resistivity estimate additionally assumes that current spreads little outside a chosen rectangle, with width/length about 10. A four-terminal resistance does not remove uncertainty in that current path. No new numerical $T_c$ or thermodynamic phase boundary is extracted here. [R7](#ref-source-e8160470a5b03301)

## Limits and disputes

Jeong's VO2 evidence went beyond reversible transport: conductance persisted after the ionic liquid was removed, vanadium core-level spectra changed, and reverse gating in oxygen-18 produced an isotope depth profile measured by secondary-ion mass spectrometry. Ungated regions receiving the same isotope exposure served as controls. These results support chemical modification in those devices; they do not prove that every ionic-liquid-gated superconductor follows the same mechanism. Full supplementary procedures and quantitative vacancy reconstruction remain outside this scoped review. [R8](#ref-source-cd5c2b85b8e3a53c)

A useful electrostatic interpretation therefore compares leakage and dwell-time behavior, sweep recovery, independent charge estimates, thickness dependence and before/after structural or chemical evidence. No single low-leakage threshold or unchanged spectrum proves the absence of all reactions. State the sensitivity and spatial sampling of each control. Conversely, hysteresis can arise from trapping in a dielectric and is not by itself proof of electrochemistry. [R1](#ref-source-e9e3a49b753191bc) [R8](#ref-source-cd5c2b85b8e3a53c)

A gate-induced dome does not uniquely identify a pairing mechanism or a quantum critical point. Strong in-plane critical fields require analysis of orbital geometry, spin–orbit coupling and the chosen resistive threshold; they do not automatically establish triplet pairing. Switching a quantum spin Hall material into a superconducting regime creates an opportunity to investigate topology, but does not by itself demonstrate a topological superconducting gap or Majorana modes. [R4](#ref-source-e8b9a66d143832fb) [R5](#ref-source-cba51ab2111ccf0a) [R6](#ref-source-117f1ab64b772ff1) [R7](#ref-source-e8160470a5b03301)

## Discovery implications

Treat the device and voltage history as part of the material record: dielectric or electrolyte, thickness, gate geometry, charging temperature, dwell time, leakage, reset protocol and independent carrier estimate. Separate superconducting onset, midpoint, measured zero and model-extracted BKT temperatures. Use chemistry-sensitive controls to decide whether a changed state belongs under electrostatic tuning or compositional modification. The source-linked records below preserve reported observations and explicit unknowns; they are not a ranking of intrinsic material performance. These records use unknown for equilibrium because their checked provenance does not establish a thermodynamic equilibrium state; this is not evidence of nonequilibrium. [R1](#ref-source-e9e3a49b753191bc) [R5](#ref-source-cba51ab2111ccf0a) [R6](#ref-source-117f1ab64b772ff1) [R8](#ref-source-cd5c2b85b8e3a53c)

## Related topics

Continue with [chemical doping](/scwiki/chemical-doping), [zero resistance](/scwiki/zero-resistance), [critical fields](/scwiki/critical-fields), [two-dimensional superconductivity](/scwiki/two-dimensional-interfaces) and [topological superconductivity](/scwiki/topological-superconductivity).
