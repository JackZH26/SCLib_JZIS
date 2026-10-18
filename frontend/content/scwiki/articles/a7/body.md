## Scope

Critical current is a limit defined for a specimen, measurement protocol and operating conditions. Transport measurements use a voltage or electric-field criterion; magnetization measurements infer a current through a model; the depairing current describes loss of stability of a superconducting state within a specified theory. These quantities must not share an unlabeled performance ranking. [R5](#ref-source-25347d9dbd8e915f)

Blatter and colleagues explicitly distinguish depinning and depairing current densities in their review abstract. Pinning, thermal fluctuations and vortex motion affect practical current transport. A measured threshold can instead be limited by weak connections or heating; its mechanism requires evidence beyond the value of the current itself. [R2](#ref-source-82f53ca35625217d)

## Mathematical assumptions

For voltage taps separated by length $L$, define the mean longitudinal electric-field criterion $E_c=V_c/L$. Using the same measured $I_c$, distinguish the nominal superconducting cross-section $A_s$ from the entire conductor area $A_t$:

$$J_c=\frac{I_c}{A_s},\qquad J_e=\frac{I_c}{A_t}=fJ_c,\qquad f=\frac{A_s}{A_t}.$$

Here $J_e$ is an engineering current density for the stated whole-conductor area. Nominal superconducting area does not resolve nonuniform current paths or pores. A different definition of non-copper area, filament area or cable area requires a different label. These identities compare area conventions; they do not correct a damaged conductor or infer intrinsic microscopic current density.

A simple sensitivity calculation illustrates why the criterion matters. If a measured interval is modeled by $E=E_0(J/J_0)^n$ with positive constant $n$, changing the criterion by a factor $r$ changes the inferred current by $r^{1/n}$. For $n=20$, a tenfold criterion change gives a factor of about 1.122. This is an illustrative power-law calculation, not a measured exponent or a universal transport law. [R5](#ref-source-25347d9dbd8e915f)

The magnetic force density is the vector product $\mathbf F=\mathbf J\times\mathbf B$. For current perpendicular to the induction, its magnitude at the threshold becomes $F_p=J_cB$ if a static pinning-force balance is the applicable model. In SI units this is N/m³; resistive heating instead has power density $\mathbf E\cdot\mathbf J$ in W/m³. A parallel configuration has no force from this cross product. Replacing $B$ by $\mu_0H$ requires an additional approximation, especially near self-field conditions.

For an explicit geometry check, take an infinite slab of full thickness $2a$, field parallel to its faces, constant $J_c$ and fully developed opposite critical-state branches. Neglect demagnetization, reversible magnetization and creep. Ampere's law gives $|dB/dx|=\mu_0J_c$. With $x$ measured across the thickness, the ideal branch profiles are $B_\pm(x)=\mu_0[H_a\pm J_c(a-|x|)]$. Their spatial averages give

$$M_\pm=\pm\frac{J_ca}{2},\qquad \Delta M=M_+-M_-=J_ca,\qquad J_c=\frac{\Delta M}{a}.$$

$\Delta M$ is the full vertical loop width in A/m; $a$ is the half-thickness in metres. Numerically integrating these stated profiles verifies the factor and dimensions. This is a local derivation under ideal assumptions, not a reanalysis of Bean's original data. Bean's 1962 paper is the historical source; its full text was not available in this check. Do not transfer this slab expression to arbitrary films, cylinders, partial penetration or field-dependent $J_c$. [R1](#ref-source-39e3e980bd8a0271)

## Experimental criteria

Keep enough information to reconstruct both the measured threshold and the conversion to a current density. The following is an editorial reporting guide, not a table of certified material records.

| Measurement | Record with the result | Interpretation boundary |
|---|---|---|
| Transport | Temperature, field magnitude and orientation, voltage-tap spacing, electric-field criterion, current ramp or pulse duration, duty cycle, area convention | Contact heating, current sharing and voltage offsets can change the inferred threshold |
| Magnetization | Magnetic moment, volume, dimensions, field history, sweep rate, elapsed time and background subtraction | Conversion to current requires a geometry and critical-state model |
| Conductor or cable | Superconducting fraction, whole-conductor area, length, strain and thermal stabilization | Layer current density and engineering current density answer different questions |
| Depairing model | Model, temperature regime, geometry and stability assumptions | A calculated instability is not automatically the measured transport limit |

MacManus-Driscoll and colleagues studied YBCO films grown with BaZrO3 added to the target. Their selected manuscript passages report improved in-field transport at 75.5 K, despite lower transition temperature or self-field current in some samples. The rotated field remained perpendicular to current. This comparison illustrates distinct performance measures, not proof of a different pairing mechanism. No electric-field criterion was extracted here, so no numerical current record is tabulated. [R3](#ref-source-51c947cf11bea72e)

Larbalestier and colleagues' 2014 paper is a primary Bi-2212 round-wire study, not a general engineering review. Its earlier author manuscript distinguishes whole-conductor $J_e$ from superconducting-area $J_c$ and compares short specimens with a demonstration coil. This entry uses that distinction without importing a cross-family ranking; the final published dataset and all measurement criteria were not independently re-extracted. [R4](#ref-source-c1a5f8c50328f68e)

## Limits and disputes

An irreversible magnetic response and the upper critical field are different observables. A loss of measurable hysteresis or a transport threshold need not locate the destruction of superconductivity. Report the criterion, time scale and field history rather than silently equating an irreversibility line with $H_{c2}$. Thermally activated creep is one reason different observation times can yield different apparent current limits. [R2](#ref-source-82f53ca35625217d)

A fitted pinning-curve exponent or angular peak does not uniquely identify a defect. Compare microscopy, processing controls and temperature/angle dependence. In the checked YBCO manuscript, the detailed composition of the small second-phase particles is not conclusively established; describing every particle as chemically proven BaZrO3 would overstate the evidence. [R3](#ref-source-51c947cf11bea72e)

## Discovery implications

Separate a better transport path, stronger pinning, a larger superconducting fraction and a higher depairing limit as distinct hypotheses. Compare controlled specimens under matched conditions before assigning an improvement to a microscopic mechanism. A gain in current-carrying performance does not by itself demonstrate higher $T_c$, a new pairing interaction or a new superconducting phase.

Preserve the measured signal, uncertainty and analysis conventions together. If the voltage criterion, geometry or thermal history is unavailable, retain that gap in the record. A useful follow-up is the measurement that discriminates between the competing limits, rather than another unsupported performance ranking. [R5](#ref-source-25347d9dbd8e915f)

## Related topics

Connect to [critical fields](/scwiki/critical-fields), [zero resistance](/scwiki/zero-resistance), [Meissner effect](/scwiki/meissner-effect), [BCS theory](/scwiki/bcs-weak-coupling), and [superconducting gap](/scwiki/superconducting-gap).
