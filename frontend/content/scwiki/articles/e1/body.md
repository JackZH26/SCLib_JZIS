## Scope

Pressure changes interatomic distances, electronic bandwidths, lattice vibrations and phase stability. It can also change the material itself through structural conversion or chemical reaction. A diamond anvil cell identifies an apparatus; it does not establish a purely hydrostatic stress state at the sample. Pressure medium, temperature, loading history and sample geometry belong to every quantitative comparison. [R1](#ref-source-c1c9ef4bc5cf71dd) [R2](#ref-source-a631bcd83d23567b) [R5](#ref-source-8b901b9c6008c434)

This article concerns measurements while pressure is applied. A state retained after rapid pressure release has a different thermodynamic and kinetic history. Deng's 2026 pressure-quench paper explicitly separates creating a phase under load, releasing pressure and characterizing the recovered state. Its reported 151 K scale must not be pooled with an in-situ pressure curve. Here only its abstract and introductory protocol are checked; the detailed transition criterion and recovery evidence require a separate review. [R7](#ref-source-14d1e9e0097f7ffb)

## Mathematical assumptions

With tensile stress positive, define $P=-\mathrm{tr}(\sigma)/3$ and $s_{ij}=\sigma_{ij}+P\delta_{ij}$. Then $\sigma_{ij}=-P\delta_{ij}+s_{ij}$ with $\mathrm{tr}(s)=0$. Hydrostatic stress has $s=0$; equal mean pressure does not imply equal deviatoric stress. For a symmetric stress tensor, $\sqrt{3s_{ij}s_{ij}/2}$ is a rotationally invariant scalar measure of deviatoric magnitude. It summarizes stress anisotropy, but does not identify its orientation or predict superconductivity. These definitions and rotation identities were checked on illustrative tensors. [R1](#ref-source-c1c9ef4bc5cf71dd)

A measured pressure dependence is a path through several changing variables. Within a differentiable single phase, $dT_c/dP=\sum_a(\partial T_c/\partial x_a)(dx_a/dP)$ is a chain rule, not evidence that any one variable causes pairing. Phase conversion, hysteresis or a changed resistance criterion can invalidate a single smooth derivative across the whole dataset. Even an ideal dome has different local slopes on opposite sides of its maximum. [R2](#ref-source-a631bcd83d23567b) [R4](#ref-source-df0c15d62982f853)

For an illustrative weak-coupling model, write

$$
\begin{aligned}
T_c(P)&=A\Theta(P)\exp[-1/\lambda(P)],\\
\Theta&=\hbar\omega_c/k_B.
\end{aligned}
$$

Here $\Theta$ is a cutoff temperature in kelvin, $A$ is dimensionless, and $\lambda>0$ is the effective attractive coupling of this simplified model. It is not automatically an experimentally determined Eliashberg coupling. The BCS source gives the weak-coupling cutoff form; the pressure derivative below is a local chain-rule calculation. Within one smooth phase and with $A$ fixed,

$$
\frac{d\ln T_c}{dP}=\frac{d\ln\Theta}{dP}
+\frac{1}{\lambda^2}\frac{d\lambda}{dP}.
$$

If $A$ varies, add $d\ln A/dP$. Pressure units must agree in both terms. For a synthetic example at $\lambda=0.25$, a cutoff slope of $0.02\ \mathrm{GPa}^{-1}$ and coupling slope of $-0.003\ \mathrm{GPa}^{-1}$ give $d\ln T_c/dP=-0.028\ \mathrm{GPa}^{-1}$: a rising cutoff need not raise $T_c$.

This example requires a positive cutoff and coupling. It excludes a separately treated Coulomb pseudopotential, strong-coupling corrections, multiple bands and structural changes. It neither predicts a hydride or FeSe transition nor shows which variable causes pairing. A phase conversion cannot be represented by differentiating one smooth expression through the boundary. [R8](#ref-source-ba10e800a1246bf6) [R5](#ref-source-8b901b9c6008c434)

## Experimental criteria

Torikachvili and colleagues used sample-resistance anomalies, cross-checked against manganin, to locate freezing-related changes in pressure media. Their room-temperature manganin calibration and low-temperature Pb manometer are distinct measurements. Between 300 and 90 K, pressure was estimated by interpolation; below 90 K it was assumed constant. Data used for the anomaly analysis came from slow warming near 0.35 K per minute. These details prevent the loading pressure from silently becoming the pressure at every temperature. The silicone-oil freezing points were not unambiguously determined. [R1](#ref-source-c1c9ef4bc5cf71dd)

Medvedev's Fe1.01Se study reports an approximately 36.7 K resistive transition at 8.9 GPa and a decrease at higher pressures. At 15 GPa the roughly 25 K transition did not reach zero resistance, in a mixed-phase regime. The selected transport Methods describe DC van der Pauw measurements, ruby checks at both room and low temperature and a reported spatial pressure spread no greater than 0.05 GPa. Silicone oil is specified in the separate Mössbauer paragraph; this review does not assign that medium to transport without evidence. [R2](#ref-source-a631bcd83d23567b)

Gao's original abstract reports resistive measurements of mercury cuprates under quasihydrostatic pressures and a maximum of 164 K for the three-layer member. It does not, at this checked scope, establish a zero-resistance or thermodynamic criterion. The full 1994 methods remain inaccessible here, so no more precise criterion is manufactured for the material record. A family trend in that report is not a universal positive pressure coefficient for superconductors. [R3](#ref-source-6d09a24a26a15997)

The bilayer nickelate report combines resistance signatures with a separate magnetic experiment. Its Methods distinguish transport run 2 with KBr from runs 1, 3 and 4 without a pressure medium; the diffraction setup instead uses silicone oil. Pressure calibration is by room-temperature ruby fluorescence. The high-pressure magnetic setup uses powder without another pressure medium. Residual resistance and sample-specific onset criteria remain explicit. In sulfur and lanthanum hydrides, pressure also helps produce or stabilize the hydrogen-rich phases being measured. Pairing a transport curve with a proposed structure requires attention to synthesis history, phase fractions and the conditions of each probe. [R4](#ref-source-df0c15d62982f853) [R5](#ref-source-8b901b9c6008c434) [R6](#ref-source-1e6e868a12cdd34f)

## Limits and disputes

A small spread in pressure inferred from calibrant readings does not reconstruct the full sample stress tensor. Conversely, a frozen medium need not produce the same shear stress in every geometry. Hydrostaticity is an experimental condition to assess, not a binary quality label inferred solely from the material name. The freezing study's calibration assumptions and unresolved oil anomalies should remain attached to any reuse of its data. [R1](#ref-source-c1c9ef4bc5cf71dd)

Onset, midpoint, zero resistance and magnetic or thermodynamic signatures answer different questions. The high-pressure FeSe curves broaden and coexist with a structurally transformed fraction; a surviving conducting path is not a direct bulk-volume measurement. Likewise, a structural measurement at room temperature cannot by itself establish the complete structure at a low-temperature transition. This entry retains the historical report's conditions without generalizing its magnetic conclusions to every later FeSe experiment. [R2](#ref-source-a631bcd83d23567b) [R4](#ref-source-df0c15d62982f853)

## Discovery implications

Design a pressure series around alternatives that the measurements can distinguish:

1. **Match the pressure to the measurement.** Record the calibrant, its temperature and any interpolation. Torikachvili's room-temperature manganin and low-temperature Pb readings are not interchangeable; the freezing analysis uses a slow warming path.
2. **Keep each probe's setup separate.** Medvedev's room-temperature diffraction does not supply a complete low-temperature structural map. In the nickelate experiment, transport run 2 used KBr, other transport runs used no medium, and diffraction used silicone oil. Do not transfer one setup's pressure medium to every result.
3. **Check the return path.** Record unloading and subsequent sample characterization. Recovery of the starting phase does not establish identical loading and unloading curves or the lifetime of a retained state. The selected FeSe text reports phase recovery after pressure release; it is not a complete hysteresis audit.

These are editorial comparison rules. A pressure gradient, intrinsic broadening, phase conversion and kinetic trapping remain different explanations to test. Static loading alone does not establish thermodynamic equilibrium. The five material records in this entry now mark equilibrium as **unknown** because the checked source scopes do not establish it; this does not assert that those experiments were nonequilibrium. Differences between probes should be explained, not averaged into one transition. [R1](#ref-source-c1c9ef4bc5cf71dd) [R2](#ref-source-a631bcd83d23567b) [R4](#ref-source-df0c15d62982f853)

For transferable discovery records, preserve composition, pressure interval, medium, calibrant, temperature, protocol and transition criterion. Quote a slope only over its stated phase and pressure interval. Keep ambient recovered states, in-situ high-pressure phases and theoretical estimates separately searchable. Pressure can expose useful physics without guaranteeing a recoverable ambient material or a technologically useful conductor. [R5](#ref-source-8b901b9c6008c434) [R6](#ref-source-1e6e868a12cdd34f) [R7](#ref-source-14d1e9e0097f7ffb)

## Related topics

Continue with [strain engineering](/scwiki/strain), [organic superconductors](/scwiki/organic-charge-transfer-superconductors), [hydride superconductors](/scwiki/hydride-superconductors), [iron-based superconductors](/scwiki/iron-based-superconductors) and [zero-resistance criteria](/scwiki/zero-resistance).
