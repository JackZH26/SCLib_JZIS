## Scope

Heat capacity probes the change of entropy with temperature. A superconducting anomaly can therefore provide a bulk thermodynamic check that complements resistance and magnetic screening. A peak alone does not identify its cause: magnetic, structural and charge-order transitions can also produce anomalies. This article separates an ideal electronic heat-capacity jump from the measured total signal and from an empirical trend across different samples.

Use $C$ on a declared basis: per mole, per unit mass, per volume or for the entire sample. The normalization of the normal-state electronic coefficient $\gamma_n$ must match. Experiments often measure $C_p$, while a simple electronic model evaluates heat capacity with a fixed spectrum and volume. Their difference may be small for an appropriate low-temperature solid, but that approximation should be justified when quantitative precision matters.

## Mathematical assumptions

For an isotropic single-band weak-coupling BCS model with a smooth density of states, define the electronic jump on cooling as $\Delta C_e=C_{es}(T_c^-)-C_{en}(T_c^+)$. Its limiting value is

$$
\frac{\Delta C_e}{\gamma_nT_c}=\frac{12}{7\zeta(3)}\simeq1.426.
$$

Here $C_{en}=\gamma_nT$ in the assumed low-temperature normal state. The number is a model benchmark, not a threshold that every superconductor must pass. Johnston gives the limiting expression in Eq. (22) of the cited author manuscript. [R1](#ref-source-85009580cf550887)

Entropy follows from $dS=C\,dT/T$ under the specified thermodynamic constraints. For a continuous transition with equal extrapolated zero-temperature entropies in the compared phases,

$$
S_s(T_c)-S_n(T_c)=\int_0^{T_c}\frac{C_s(T)-C_n(T)}{T}\,dT=0.
$$

The normal curve below $T_c$ is a defined reference, not a directly accessible zero-field equilibrium phase. Background subtraction and low-temperature extrapolation therefore affect the test. A first-order transition has latent heat and requires a different treatment. Do not force this continuous-transition construction onto such a dataset.

An independent numerical check for this entry solved the constant-density-of-states gap equation, integrated the quasiparticle entropy and differentiated it near $T_c$. The normalized jump approaches 1.426 as the cutoff and numerical step are controlled; the normalized entropy reaches the normal-state value at the transition. This checks the stated model and conventions, not a material dataset. The entropy and heat-capacity relations are consistent with the selected manuscript equations. [R1](#ref-source-85009580cf550887)

## Experimental criteria

Start from the measured heat capacity and report addenda, sample mass and calibration uncertainty. A fit such as $C_n/T=\gamma_n+\beta T^2$ assumes a linear electronic term and a low-temperature lattice contribution. It can fail if extra excitations or nearby transitions matter. State the temperature interval and uncertainty of the background, and show how another reasonable background changes the inferred anomaly.

A field used to suppress superconductivity is not automatically a perfect normal-state reference. Check whether it reaches the normal state over the relevant range and whether it changes magnetic or other contributions. Use the same units and sample basis in the field and zero-field curves. Show transition width, the chosen thermodynamic $T_c$ and the entropy comparison, rather than only a peak height.

Compare with resistance and screening on the same or demonstrably comparable specimen. A consistent anomaly with the expected field response strengthens the case for bulk superconductivity. Failure to resolve an anomaly may instead reflect sensitivity, sample size, a small superconducting fraction or an incorrect baseline. It leaves thermodynamic confirmation incomplete; it does not by itself establish absence of superconductivity. These are reporting and interpretation criteria from the pinned chapter, not independently verified measurements.

## Limits and disputes

The phenomenological alpha model retains the BCS normalized gap shape while varying $\alpha=\Delta(0)/(k_BT_c)$ in the thermodynamic calculation. Padamsee and colleagues describe its quasiparticle construction in their abstract. A successful fit is not a microscopic derivation of the interaction. [R2](#ref-source-456cad7bcd596be8)

Within that model the jump scales as $1.426(\alpha/\alpha_{\rm BCS})^2$. This does not mean that the entire entropy or heat-capacity curve can simply be multiplied by that factor: the occupation functions also change. Gap anisotropy or multiple coupled bands can alter the normalized jump. Multiple bands do not necessarily broaden a single sharp transition; disorder, phase mixtures and a distribution of local transition temperatures are separate issues. [R1](#ref-source-85009580cf550887)

Bud'ko, Ni and Canfield report an empirical relation $\Delta C_p/T_c\propto T_c^2$ for their substituted Ba122 series together with specified literature samples. Equivalently, the jump itself scales as $T_c^3$ within that comparison. This is a dataset-dependent observation, not a fundamental law or a stand-alone proof of a pairing mechanism. The current check covers the publisher abstract, not a reanalysis of the data. [R3](#ref-source-f075b0cef0106abc)

## Discovery implications

Use an anomaly to constrain a proposed state together with independent probes. Ask which part of the temperature dependence is reliable, how much of the sample participates, and whether competing backgrounds could produce the same result. Preserve disagreement between probes and the uncertainty in extrapolated quantities.

A useful next experiment resolves a specific ambiguity: a field-dependent background, an uncertain phase fraction, a residual low-temperature term or an alternative gap distribution. Comparing a single normalized jump to 1.426 cannot uniquely select gap symmetry, coupling strength or a mediator. These are model-discrimination questions, not new experimental findings.

## Related topics

Connect heat capacity to [zero resistance](/scwiki/zero-resistance), [the Meissner effect](/scwiki/meissner-effect), [critical fields](/scwiki/critical-fields), [the BCS baseline](/scwiki/bcs-weak-coupling), and [multiband pairing](/scwiki/multiband-pairing).
