## Scope

A credible claim of a new superconducting material needs convergent, reproducible evidence tied to a documented sample and conditions. A resistance drop, diamagnetic background or partly levitating fragment is a candidate observation, not a unique identification. This page uses LK-99 as a measurement-control case study. Lee and colleagues' July 2023 preprint claimed ambient-pressure superconductivity above 400 K; that claim is not accepted as a measured material Tc here. Selected independent studies instead found alternative explanations or non-superconducting samples. Those results apply to their investigated specimens and do not constitute a test of every possible composition. [R1](#ref-source-cd8f3ac578e82497) [R2](#ref-source-0d5220e22a764bd4) [R3](#ref-source-a2986ca87572851e) [R4](#ref-source-4065b69b701c07cd)

## Experimental criteria

Preserve synthesis records, composition, phase analysis, specimen identifiers, dimensions and contact positions. Connect transport, magnetic and thermodynamic observations to the same specimen where practicable, or to traceably matched pieces with documented differences. Diffraction and microscopy have detection limits; nominal chemical formulas do not guarantee homogeneous doping or exclude minority phases. Puphal and colleagues found spatially inhomogeneous Cu concentrations in their crystals even while their structural analysis identified the lead-apatite phase. [R3](#ref-source-a2986ca87572851e)

Report raw voltages, excitation current, polarity, temperature calibration, field, sweep direction, stability and uncertainty. Four-terminal wiring reduces ordinary contact-voltage contamination but does not make every contact configuration diagnostic. Change current and voltage contacts, reverse current, check heating and inspect reproducibility across cycles. State a resistance bound at the instrument's sensitivity rather than claiming an exact measured zero. Constant thermoelectric offsets and current-dependent thermal effects need different controls. [R5](#ref-source-c8143afdf96ce96f) [R6](#ref-source-0c63f38b6789c792)

A magnetic assessment should distinguish a diamagnetic background, zero-field-cooled shielding and field-cooled flux expulsion. Record holder subtraction, volume or mass normalization, sample shape and ferromagnetic contributions. Geometry, pinning and granularity complicate any conversion to a superconducting volume fraction. Combine these observations with appropriate thermodynamic measurements where sensitivity and sample size permit; a missing resolvable anomaly constrains a claim only in relation to those limits. This is an evidence plan, not a demand that every experimental platform deliver identical signals. [R2](#ref-source-0d5220e22a764bd4) [R3](#ref-source-a2986ca87572851e) [R7](#ref-source-37f27e50dbdcf3a5)

## What the LK-99 controls show

Zhu and colleagues measured Cu2S controls and mixtures containing different Cu2S fractions. In the checked in-press article, pure Cu2S changes from about 13.7 Ω cm at 385.6 K to 0.006 Ω cm at 381.5 K, with a heating–cooling hysteresis of 13.1 K. The lower resistivity is finite. Their Cu2S-rich mixture also shows a sharp resistivity change and a magnetic anomaly. These observations provide an alternative explanation for selected transition-like features; they do not establish superconductivity or explain every magnetic signal in every synthesis. The order of this structural transition is not a universal rule for excluding all possible superconducting transitions. [R2](#ref-source-0d5220e22a764bd4)

Puphal and colleagues' sulfur-free crystal study attempted four-point room-temperature transport and found resistance above several megaohms. Their magnetic measurements cover 2–800 K and identify weak ferromagnetic contributions alongside diamagnetism. Optical transparency alone is not their decisive transport test. Some displayed magnetization data retain holder offsets, while a separate large-sample calibration explicitly subtracts the holder contribution. Keep those protocols distinct. Merging of cooling histories at the start of a measurement range is not by itself a critical temperature. [R3](#ref-source-a2986ca87572851e)

Wang and colleagues compared half-levitating and non-levitating fragments. Both groups were insulating in the investigated 165–300 K interval. Their magnetic results and shape-dependent torque analysis show how soft ferromagnetism can accompany half levitation without the claimed superconductivity. The fitted activation scale is not a superconducting gap. A levitation video therefore cannot replace transport and magnetic controls, and a ferromagnetic contribution must not automatically be assigned to Cu2S. [R4](#ref-source-4065b69b701c07cd)

## Mathematical assumptions

For a linear resistor with a constant voltage offset, an original current-reversal example gives

$$
V_+=IR+V_0,\qquad V_-=-IR+V_0,\qquad
\widehat R=\frac{V_+-V_-}{2I}.
$$

Nine independent cases recover the imposed resistance and constant offset. With each voltage error bounded by 10 nV at an exact 1 mA current, the worst-case resistance error is 10 μΩ. This is a deterministic bound, not a statistical confidence interval. Current uncertainty, changing thermal offsets, nonlinearity and moving contacts require additional analysis; some thermoelectric effects reverse with current and survive this subtraction. [R5](#ref-source-c8143afdf96ce96f) [R6](#ref-source-0c63f38b6789c792)

A separate four-node resistor network has two conducting branches and voltage probes at their midpoints. Equal branch resistance ratios give a zero midpoint voltage even though the input resistance and dissipated power remain positive. Twenty-seven cases verify Kirchhoff's equations and energy balance, including imbalanced branches. This constructed transfer-resistance counterexample demonstrates why geometry and alternative paths matter. It is not a reconstruction of any LK-99 experiment. [R5](#ref-source-c8143afdf96ce96f)

For a homogeneous ellipsoid with linear intrinsic SI volume susceptibility χ and demagnetizing factor N,

$$
H_{\rm int}=H_{\rm a}-NM,\qquad
\chi_{\rm app}=\frac{M}{H_{\rm a}}=\frac{\chi}{1+N\chi}.
$$

Twelve independent cases check this relation and its inverse. In the idealized χ = −1, N = 0.5 case, χapp = −2; its magnitude does not imply a 200% superconducting volume fraction. The assumed uniform ellipsoid does not model a granular irregular fragment, hysteretic ferromagnet or pinned vortex distribution. Mass susceptibilities and cgs values cannot be inserted without conversion. [R7](#ref-source-37f27e50dbdcf3a5)

## Standards and reporting

The original preprint invokes electric-field or resistivity criteria and cites application-oriented books. Its references 16 and 17 are Wang's electrical-engineering book and Ekin's low-temperature measurement book, not the text of an IEC standard. Separately, the official public scope of IEC 61788-1:2006 concerns critical-current measurement in specified Nb-Ti composite conductors in a liquid-helium bath. An engineering threshold for a known conductor is not a universal certification that an unfamiliar material hosts a new superconducting phase. The paid standard's full clauses have not been checked here. [R1](#ref-source-cd8f3ac578e82497) [R8](#ref-source-183e82eda528f417)

Preserve unsuccessful batches and negative controls alongside successful-looking traces. Independent groups should document composition, measurement sensitivity and protocol differences before calling results a replication or contradiction. A provisional editorial progression can separate a candidate anomaly, reproducible transport evidence and convergent bulk evidence. These are proposed reporting categories, not an official certification scheme. Share data, calibrations, analysis code and versioned corrections sufficiently to test competing explanations. [R2](#ref-source-0d5220e22a764bd4) [R3](#ref-source-a2986ca87572851e) [R4](#ref-source-4065b69b701c07cd) [R6](#ref-source-0c63f38b6789c792)

## Limits and disputes

This review checks selected primary passages and a limited set of figures. It does not reproduce raw experimental measurements, compare every manuscript version or establish the properties of every claimed LK-99 preparation. The original claim is explicitly a preprint; the independent examples above are synthetic controls with stated assumptions. Apparent agreement among several measurements is strongest when they share a traceable phase, specimen history and temperature or field scale. Unresolved differences should remain visible rather than being replaced by a single categorical label. [R1](#ref-source-cd8f3ac578e82497) [R2](#ref-source-0d5220e22a764bd4) [R3](#ref-source-a2986ca87572851e) [R4](#ref-source-4065b69b701c07cd)

## Discovery implications

Allocate effort to observations that discriminate among superconductivity, structural transitions, current-path artifacts and magnetic torque. For a candidate, prioritize reproducible synthesis, contact permutations, phase-resolved characterization and quantitative magnetic controls before advertising an exceptional Tc. State precisely which alternative each new test excludes, which remain possible and what independent work would change the conclusion. This makes an unusual signal useful to research even when its first interpretation fails. [R2](#ref-source-0d5220e22a764bd4) [R3](#ref-source-a2986ca87572851e) [R4](#ref-source-4065b69b701c07cd)

## Related topics

Continue with [zero resistance](/scwiki/zero-resistance), [the Meissner effect](/scwiki/meissner-effect), [room-temperature superconductivity](/scwiki/open-questions/n1), and [measurement methods](/scwiki/experimental-methods).
