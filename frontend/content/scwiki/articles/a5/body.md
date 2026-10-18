## Scope

A superconducting gap is an energy scale in a specified excitation spectrum. Its magnitude, momentum dependence and relative phase answer different questions. A suppression of spectral weight is not automatically a superconducting gap, and a fitted gap does not automatically define the temperature of bulk superconductivity. This entry organizes observations and model assumptions rather than ranking materials by a single gap ratio.

Specify whether $\Delta$ denotes an order-parameter amplitude, a quasiparticle excitation threshold or a parameter extracted from a broadened spectrum. The relation between these quantities depends on the model. Keep the measured signal, the fit and the inferred state separate; otherwise apparently similar numbers can describe different observables.

## Mathematical assumptions

For a clean, isotropic, single-band weak-coupling BCS model, the quasiparticle spectrum and zero-temperature limiting ratio are

$$E_{\mathbf k}=\sqrt{\xi_{\mathbf k}^{\,2}+|\Delta|^2},\qquad \frac{2\Delta_0}{k_BT_c}=2\pi e^{-\gamma_E}\simeq3.528.$$

Here $\xi_{\mathbf k}$ is measured from the chemical potential and $\gamma_E$ is Euler's constant. The existing BCS entry checks the gap equation and numerical limit. The ratio is not a universal threshold for identifying superconductivity or an interaction. Strong coupling and anisotropy require their own treatment; Carbotte's review abstract describes deviations from simple BCS results without supplying a universal correction. [R1](#ref-source-ba10e800a1246bf6) [R2](#ref-source-2da854ce10895b5e)

With a constant normal density of states $N_n$ and the same spin convention in numerator and denominator, the ideal normalized density of states at positive excitation energy is

$$\frac{N_s(E)}{N_n}=\begin{cases}0,&0\le E<|\Delta|,\\ E/\sqrt{E^2-|\Delta|^2},&E>|\Delta|.\end{cases}$$

The factor above the edge follows from the change of variable $E=\sqrt{\xi^2+|\Delta|^2}$ with the usual Bogoliubov spectral weights. The ideal edge is singular but integrable. A local numerical check integrates it up to a finite energy and recovers the corresponding normal-state $\xi$ interval. The check assumes no lifetime broadening, gap anisotropy or experimental convolution. [R1](#ref-source-ba10e800a1246bf6)

In this magnitude-only model, replacing a gap by its negative leaves the excitation energies unchanged. Likewise, independently summing two uncoupled spectral contributions cannot recover their relative sign. This is a limited counterexample to inferring phase from a gap magnitude; it does not say that every interference-sensitive spectrum is phase blind.

## Experimental criteria

Use the following as a reporting map adapted from the pinned chapter. Each interpretation needs the stated model and a sample-specific source; these rows do not certify any material dataset. Selected review and theory passages now support tunneling, optical and point-contact interpretation limits, alongside the earlier ARPES and bulk-probe context. Complete control-by-control verification of the other probe rows remains open.

| Probe | Recorded quantity | What must be controlled |
|---|---|---|
| Tunneling or STS | Differential conductance versus bias | Tip and sample spectra, thermal/instrumental broadening, matrix elements and surface variation [R7](#ref-source-d687e60f83e71f36) |
| ARPES | Momentum-resolved photoemission intensity | Occupation, resolution, matrix elements and surface state; a leading edge is not automatically a gap amplitude |
| Optical or THz spectroscopy | Frequency-dependent electrodynamic response | Scattering, multiple bands and the model linking absorption to an excitation threshold [R8](#ref-source-aa5ec58b03d1a3ef) [R9](#ref-source-9394f6a65db2d109) |
| Heat capacity | Entropy and bulk excitation contribution | Lattice/magnetic backgrounds and normalization; no direct phase measurement |
| Penetration depth or thermal transport | Low-energy electromagnetic or heat response | Disorder, nonlocality, background and multiple excitation channels |
| Andreev or point-contact spectroscopy | Interface current and conductance | Barrier transparency, heating, contact regime and channel mixing [R10](#ref-source-d09edec8bdd2b452) [R11](#ref-source-dc8f626a5df50714) |

A tunnel conductance resembles the sample density of states only under counterelectrode and matrix-element assumptions; the selected Fischer review gives the thermal convolution and explains the resolution role of lock-in modulation. Do not identify every conductance peak with $\Delta$. Optical interpretation also depends on scattering and multiband weights: the selected Dressel review compares competing fits, while Seibold and colleagues distinguish DOS peaks, excitation thresholds and collective absorption within a disordered model. These are source-scoped cautions, not a new fit to any specimen. Photoemission and thermodynamic probes constrain other aspects; magnitude-sensitive measurements alone do not determine relative phase. [R3](#ref-source-e933e3bbd4beade6) [R7](#ref-source-d687e60f83e71f36) [R8](#ref-source-aa5ec58b03d1a3ef) [R9](#ref-source-9394f6a65db2d109)

For point contacts, a barrier model is only part of the interpretation. Sheet and colleagues distinguish dissipative thermal contacts from a diffusive regime without significant local heating; non-ballistic does not always mean thermal. Kumar and Sheet show how multiple constrictions can mix responses in a network model. These examples motivate contact controls; they neither diagnose every observed peak nor prove that every unconventional spectrum is an artifact. [R10](#ref-source-d09edec8bdd2b452) [R11](#ref-source-dc8f626a5df50714)

Hardy and colleagues report a strong linear term in the penetration-depth change of YBa2Cu3O6.95 single crystals over approximately 3–25 K using a 900 MHz resonator. This is evidence relevant to low-energy excitations under their sample conditions, not a direct measurement of gap phase. The present check covers the publisher abstract. [R4](#ref-source-b7bc48c845a47b53)

By contrast, Tsuei and Kirtley use scanning SQUID measurements of NCCO/PCCO tricrystals to test phase-sensitive predictions. Their designed frustrated geometry produces a half-flux signal, while two unfrustrated NCCO geometries serve as controls. The inference depends on junction geometry and the associated model, not merely on observing a spectral dip. Selected author-manuscript passages and the control description were checked; the image fits were not independently reproduced. [R6](#ref-source-7700f02a5390b1cf)

## Limits and disputes

Nodes, relative sign and topology are distinct. A low-temperature power law can constrain low-energy excitations without uniquely selecting a pairing representation. A fully open gap on each Fermi-surface sheet can coexist with a relative sign change between sheets. Disorder and sample inhomogeneity must be considered before translating a temperature dependence into a symmetry assignment. [R3](#ref-source-e933e3bbd4beade6)

A zero-bias feature alone is not a unique topology test. Identify its field, temperature, position and junction dependence, then compare explicit alternative models. Likewise, a spectroscopic gap-closing temperature must not silently replace a resistive or thermodynamic $T_c$ in a gap ratio. These are inference and reporting limits, not a claim that one alternative explains every observed feature.

Choi and colleagues' MgB2 result is an anisotropic Eliashberg calculation of distinct band-dependent gap scales. Treat those calculated gaps as theory and compare them with separately identified measurements. The pinned chapter's DOI was mismatched; the correct source is nature00898. That correction does not validate a universal multiband gap ratio or independently reproduce the calculation. [R5](#ref-source-7c4eac077ae5e221)

## Discovery implications

Record the specimen, pressure or strain, temperature criterion, spectral resolution, fit model and uncertainty together. Compare probes on the same or demonstrably comparable specimens. A disagreement can expose a surface effect, background assumption or a second energy scale; it should remain visible until tested.

A useful next measurement distinguishes competing interpretations. Establish which observation would separate a change of magnitude from a change of phase, and which control would rule out a contact artifact or another ordered state. Gap measurements constrain models; they do not replace a complete evidence chain for superconductivity.

## Related topics

Connect to [BCS theory](/scwiki/bcs-weak-coupling), [multiband pairing](/scwiki/multiband-pairing), [s± pairing](/scwiki/s-plus-minus), [specific heat](/scwiki/specific-heat-jump), [critical fields](/scwiki/critical-fields), and [zero resistance](/scwiki/zero-resistance).
