## Scope

Superconducting applications combine materials with cryogenics, mechanical support, electronics and protection. This handbook connects ten approved topics to the physical function that superconductivity provides and the conditions required to assess a device. Historical demonstrations, design specifications and current operator explanations are identified separately. A material's transition temperature is not an equipment operating temperature, and a successful component does not establish the performance of an entire installation. [R2](#ref-source-684ee630b8b083a8) [R3](#ref-source-c43ec6c74bbdf714) [R7](#ref-source-f2533bc529f46a76)

## Mathematical assumptions

Compare like quantities: magnetic field at a named location, current with a stated criterion, power versus stored energy, and sensor efficiency referenced to a defined input. Independent calculations here test an ideal two-junction interference model, a finite charge-basis qubit Hamiltonian and a hypothetical rotating annulus. They do not certify a magnet, reproduce a detector calibration or establish service life. Engineering margins and uncertainty must accompany device-level claims. [R5](#ref-source-654ce5462e87aa22) [R8](#ref-source-4807a9ed7d6653f1) [R12](#ref-source-70cba2aaed2e7595)

## K1 — Power transmission cables

Superconducting cables aim to carry large currents in a compact conductor, but the conductor choice is project-specific. The 2019 manufacturer-authored Bi-2223 review identifies copper-reinforced, spliced Bi-2223 wire in the AmpaCity three-phase coaxial cable and dates its long-term grid trial from 2014. It must not be relabelled as a REBCO installation merely because the planning outline named REBCO long wires. The two conductor families require separate manufacturing and qualification evidence. [R1](#ref-source-6293adce09208657)

Assess usable current under the cable's field, temperature, strain and joint conditions, with the voltage criterion and area convention retained. Adding mechanical reinforcement can improve strength while reducing engineering current density when the entire conductor cross-section is counted. Low resistance in the superconducting path does not eliminate cryogenic loads, joint heating or alternating-current losses. Compare a complete installation over its load cycle, including cooling and fault response, before claiming an energy or cost advantage. The reviewed passage supports the conductor identification and historical deployment context; it does not independently quantify AmpaCity's total operating losses or long-term reliability. [R1](#ref-source-6293adce09208657)

## K2 — MRI magnets

The selected MRI review describes conventional whole-body systems using liquid-helium-cooled NbTi coils, commonly operating near 4.2 K. That temperature is a cooling condition, not the material's transition temperature. The main magnet must provide a field with suitable spatial uniformity and stability across the intended imaging region. A larger central field alone does not specify image quality or make two scanners equivalent. Geometry, gradients, radio-frequency hardware and reconstruction also matter. [R2](#ref-source-684ee630b8b083a8)

Shorter magnets and wider bores change the balance between conductor quantity, peak field, field uniformity and accessibility. Reduced-helium and conduction-cooled designs can change installation requirements, but they still need refrigeration, thermal margins and protection against local heating. The source's product examples describe the state considered in its 2022 manuscript; they are not a current market ranking. The engineering discussion here does not provide clinical advice or assert that every magnet of a named material has the same operating limits. Detailed scanner qualification, final review-version comparison and the underlying device datasets remain separate checks. [R2](#ref-source-684ee630b8b083a8)

## K3 — Accelerator magnets

Accelerator dipoles bend charged-particle trajectories; quadrupoles focus the beam. Their field profiles, apertures and operating cycles impose different requirements. CERN's 5 December 2023 report describes a 7.2 m Nb3Sn quadrupole prototype for the High-Luminosity LHC, following earlier LHC use of NbTi. The reported third full-length prototype reached 16.53 kA in tests at both 1.9 K and 4.5 K, while planned operation was at 1.9 K. These are distinct test conditions, not interchangeable operating specifications. [R3](#ref-source-c43ec6c74bbdf714)

The same report links improved performance to changes in support-shell dimensions, assembly stress and production procedures after earlier prototypes were limited at 4.5 K. A useful comparison therefore includes conductor properties, mechanical loading, cooling and the specific magnet test, rather than attributing every improvement to chemical composition. Reaching a current target is an important milestone but does not independently establish beam performance, complete series-production acceptance or current fleet readiness. The Wiki records this as a dated prototype result; further system qualification requires its own evidence. [R3](#ref-source-c43ec6c74bbdf714)

## K4 — Fusion magnets

Magnetic-confinement fusion devices use different coils for different field functions. ITER's technical overview describes Nb3Sn in its toroidal-field and central-solenoid systems, and NbTi in the four largest poloidal-field coils. Its quoted peak fields refer to named parts of the magnet system: the toroidal-coil maximum and the central-solenoid maximum are not the same measurement location. Cooling near liquid-helium temperatures is also distinct from the plasma temperature. [R4](#ref-source-9ca58981555e968d)

Coils, structural supports, cable jackets, cooling circuits and feeders form an engineered system. High-temperature superconducting current leads in a feeder should not be confused with the material used throughout the main winding. Nor are all ITER coils superconducting: the overview identifies copper conductors for in-vessel vertical-stability and edge-localized-mode coils. Treat the page's design capabilities and intended operation as design information. A magnet specification does not demonstrate a completed fusion campaign, sustained net electricity generation or commercial reactor availability. Those outcomes require separately dated operational evidence. [R4](#ref-source-9ca58981555e968d)

## K5 — SQUID sensors and readout

A superconducting quantum interference device converts flux-dependent Josephson interference into an electrical signal. For an ideal loop with two identical sinusoidal junctions and negligible self-inductance, maximizing their summed currents gives $I_{\max}=2I_0|\cos(\pi\Phi/\Phi_0)|$. This independently checked limit explains periodicity; unequal junctions leave a nonzero minimum at half a flux quantum. It is not a complete sensor-noise calculation. Tesche and Clarke's original abstract explicitly includes inductance, junction asymmetry, resistive shunts and noise when assessing performance. [R5](#ref-source-654ce5462e87aa22)

Practical sensitivity depends on the pickup geometry, flux-to-voltage transfer, bandwidth and noise environment. A noise density must carry its frequency normalization and refer to the correct input quantity. NIST's detector-readout project illustrates SQUID ammeters and multiplexing used to read cryogenic sensor arrays, together with room-temperature electronics. The SQUID readout and the sensor that absorbs a photon are distinct components. Neither an ideal interference curve nor the presence of a SQUID establishes the final instrument's energy resolution. The complete original noise derivation and device-specific calibration remain outside this scoped check. [R5](#ref-source-654ce5462e87aa22) [R6](#ref-source-3fd82d6f06095581)

## K6 — Superconducting nanowire photon detectors

An SNSPD uses a biased superconducting nanowire and readout circuit to register photon-induced detection events. Efficiency, timing jitter, dark counts, recovery and maximum usable rate are separate metrics. Reddy and colleagues' 2020 experiment reported 98.0 ± 0.5% system detection efficiency at 1550 nm using MoSi, not WSi or NbN. Its definition refers to photons entering the fiber pigtail outside the cryostat, so the reported system efficiency must not be replaced by an internal absorption or conversion efficiency. [R7](#ref-source-f2533bc529f46a76)

The selected final-paper passages describe operation at 720–780 mK with optimized polarization. For the 50 μm device, series resistance in the readout changed pulse behavior and suppressed problems that otherwise affected operation. These conditions belong with the headline value. Do not combine this efficiency with another paper's best timing or dark-count result as though one device achieved them together. This is a dated experimental example, not an assertion of a current world record. The full calibration supplement, uncertainty reconstruction and raw detection traces have not yet been independently reviewed. [R7](#ref-source-f2533bc529f46a76)

## K7 — Superconducting qubits

Josephson circuits supply a nonlinear quantum element whose lowest levels can encode a qubit. The transmon model uses $H=4E_C(\hat n-n_g)^2-E_J\cos\hat\varphi$, where $E_C=e^2/(2C_\Sigma)$ and $\hat n$ counts Cooper pairs. Koch and colleagues show that increasing $E_J/E_C$ strongly suppresses sensitivity to offset charge, while reducing relative anharmonicity more slowly. The latter must remain sufficient to distinguish the intended transition from leakage to higher levels. [R8](#ref-source-4807a9ed7d6653f1)

Independent diagonalization in the charge basis checks this tradeoff across six energy ratios and verifies convergence under an increased charge cutoff. Absolute anharmonicity approaches a scale of order $E_C$; confusing it with relative anharmonicity would misstate the result. The calculation does not include fabricated junction defects, all environmental noise, driven gates or measurement electronics. A stable transition in this model is not a measured coherence time, gate fidelity or fault-tolerant processor. The original 2007 design paper supplies a foundational model, not a benchmark for present-day hardware. [R8](#ref-source-4807a9ed7d6653f1)

## K8 — Magnetic levitation

Magnetic levitation is a family of systems, not a single superconducting material. JR Central's operator explanation describes liquid-helium-cooled NbTi magnets onboard SCMAGLEV vehicles. Propulsion uses powered guideway coils, while motion relative to other guideway coils generates levitation and guidance forces. This architecture must not be described simply as a YBCO bulk floating over permanent magnets. A low-loss superconducting magnet also does not imply a train that consumes no electrical energy. [R9](#ref-source-5cdba326c3439d40)

Bulk-superconductor demonstrations provide a different example. The publisher-indexed abstract and excerpt of Wang and colleagues' 2002 paper describe a YBaCuO-bulk test vehicle over an NdFeB guideway and date the first reported test to 31 December 2000. That limited source access does not establish all load, speed or stability claims. Distinguish the demonstrated configuration from a transport service: propulsion, guidance, cooling, emergency support and operating reliability must be assessed for the actual system. This handbook preserves both examples and their evidence boundaries without declaring every maglev system superconducting or every prototype commercially deployed. [R9](#ref-source-5cdba326c3439d40) [R10](#ref-source-7be734c7e3d7c08e)

## K9 — Microwave resonators and filters

Superconducting films can reduce conductor loss in microwave structures, but zero direct-current resistance does not imply zero microwave surface resistance. Resonator measurements must distinguish loaded from unloaded quality factor and account for coupling, dielectric loss, packaging and heating. Xin and colleagues compared unpatterned YBCO wafers with patterned stripline structures using different current distributions. Their selected methods include thermal control and a change of measurement method at high input power. [R11](#ref-source-579a5cc38efb09e7)

The observed absence of patterning-induced degradation applied to the tested films and procedures; it is not a theorem about every fabrication process. Some comparisons also rescaled between frequencies using an assumed frequency-squared resistance dependence. Retain that assumption when interpreting agreement. Nonlinear response can limit power handling and generate unwanted frequencies even where small-signal loss is low. For a filter, quote frequency, temperature, bandwidth, insertion loss and power conditions together. The reviewed resonator experiment motivates these checks but does not establish the performance or current deployment of a particular communications filter. [R11](#ref-source-579a5cc38efb09e7)

## K10 — Flywheel energy storage

A superconducting flywheel stores kinetic energy in a rotating mass; its superconducting bearing reduces contact friction. This differs from storing energy directly in a magnetic field. RTRI's 15 April 2015 system description reports a four-ton rotor supported by a bearing cooled to 50 K, with a yttrium-containing superconducting coil and a superconducting bulk on the shaft. It lists 300 kW output, 100 kWh storage and a maximum speed of 6,000 rpm; grid-connection tests were still planned in that document. [R12](#ref-source-70cba2aaed2e7595)

Rotational energy is $E=I\omega^2/2$. Usable energy between two speeds depends on their squared difference, not just the maximum speed. Dividing the stated 100 kWh by 300 kW gives an ideal 20 minutes, not a measured discharge duration or round-trip efficiency. An independent uniform-annulus calculation illustrates why mass distribution matters; it does not reconstruct the actual layered rotor. Vacuum equipment, cooling, motor-generator losses, containment and maintenance remain part of system assessment. The source's historical capacity claim is preserved without repeating an absolute promise of unlimited lifetime or zero total loss. [R12](#ref-source-70cba2aaed2e7595)

## Experimental criteria

For each device, retain material, geometry, cooling, measurement reference, date and operating conditions. Identify whether the cited result is a model, component test, integrated demonstration or operational report. Reliability and efficiency need a stated duration and system boundary. Current or field targets, detector efficiency and storage capacity cannot be merged into a generic measure of superconducting quality. [R3](#ref-source-c43ec6c74bbdf714) [R7](#ref-source-f2533bc529f46a76) [R12](#ref-source-70cba2aaed2e7595)

## Limits and disputes

The ten sections have individual review records. Some use selected final-paper passages; others use author manuscripts, institutional engineering reports, reviews or explicitly limited abstract access. Full scientific acceptance remains open, including supplementary calibration, final-version comparisons and complete device records. The historical examples establish neither present-day records nor universal superiority over alternative technologies. [R2](#ref-source-684ee630b8b083a8) [R5](#ref-source-654ce5462e87aa22) [R7](#ref-source-f2533bc529f46a76) [R10](#ref-source-7be734c7e3d7c08e)

## Discovery implications

Select materials against the application: usable current and mechanical margin for a cable, field quality for a magnet, noise and coupling for a sensor, or losses and control for a quantum circuit. A higher transition temperature can change cooling options but does not settle every engineering constraint. A useful development claim specifies which independently measurable system property should improve and which tradeoffs may worsen. [R1](#ref-source-6293adce09208657) [R2](#ref-source-684ee630b8b083a8) [R8](#ref-source-4807a9ed7d6653f1) [R11](#ref-source-579a5cc38efb09e7)

## Related topics

Explore [critical current](/scwiki/critical-current), [experimental methods](/scwiki/experimental-methods), [theoretical tools](/scwiki/theoretical-tools), and [flat-band temperature limits](/scwiki/open-questions/n10).
