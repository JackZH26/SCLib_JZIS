## Scope

BCS theory provides a microscopic pairing framework and a useful weak-coupling reference point. This article concerns its equilibrium, single-band, isotropic implementation with a smooth density of states and an effective attraction near the Fermi surface. Those assumptions define a model, not a classification of every superconductor. Agreement with one numerical ratio does not uniquely identify a pairing interaction. [R1](#ref-source-ba10e800a1246bf6)

The Cooper problem asks what happens when two electrons interact above an otherwise inert, filled Fermi sea. In the idealized attractive-shell model, a bound pair exists below the two-particle continuum for arbitrarily weak net attraction. The filled sea and its excluded states are essential to this result. It is not a claim that every attractive potential binds two isolated electrons in vacuum, nor is the two-electron calculation alone a construction of the finite-density superconducting state. [R2](#ref-source-d0ec754310a67e88)

## Mathematical assumptions

Write the attractive matrix element as $-V$, with $V>0$. Let $N(0)$ count states of **one spin** per unit energy, using the same volume normalization as $V$, so $\lambda=N(0)V$ is dimensionless. The energy cutoff is $E_c=\hbar\omega_c$, where $\omega_c$ is an angular frequency. With $\xi$ measured relative to the chemical potential, the excitation spectrum and gap equation are

$$
E(\xi)=\sqrt{\xi^2+|\Delta|^2},
$$

$$
1=\lambda\int_0^{E_c}\frac{\tanh[E(\xi)/(2k_BT)]}{E(\xi)}\,d\xi.
$$

The positive-energy integral already accounts for the symmetric negative-energy interval in the momentum-sum formulation. Inserting a two-spin density of states without changing the prefactor doubles the effective coupling. At zero temperature this model gives $\Delta_0=E_c/\sinh(1/\lambda)$. For $\lambda\ll1$, the usual limiting forms are

$$
k_BT_c\simeq\frac{2e^\gamma}{\pi}E_c e^{-1/\lambda},
$$

$$
\frac{2\Delta_0}{k_BT_c}\simeq2\pi e^{-\gamma}\simeq3.528.
$$

Here $\gamma$ is the Euler–Mascheroni constant; $2e^\gamma/\pi\simeq1.134$. These are model results, not a measured transition temperature. We use modern $\Delta$ notation for the single-quasiparticle threshold; creating two quasiparticles costs at least $2\Delta$ in this idealized spectrum. The original paper used different notation and rounded numerical estimates. [R1](#ref-source-ba10e800a1246bf6)

## Experimental criteria

A useful comparison needs a gap measurement and a separately specified superconducting transition criterion on a comparable sample. Report whether the measured quantity is a single-particle threshold, a pair-breaking energy or a fitted spectral parameter. State temperature, magnetic field, sample composition and uncertainty before calculating a gap ratio. A peak separation must not silently be substituted for $\Delta_0$.

Then compare more than one observable: the temperature evolution of the gap, electronic thermodynamics and magnetic response constrain different aspects of the state. Distinguish a consistency test of the isotropic weak-coupling model from evidence for a particular microscopic mediator. No sample-specific $T_c$ or gap value is added to the material-comparison catalogue by this theoretical article. [R1](#ref-source-ba10e800a1246bf6)

## Limits and disputes

The general pairing construction should not be equated with a universal weak-coupling phonon mechanism. A frequency-dependent interaction, several coupled bands, an anisotropic gap or a rapidly varying density of states requires a more suitable equation. Phase fluctuations can also separate a pairing scale from the temperature at which long-range or quasi-long-range coherence develops. The simple gap equation above does not calculate that fluctuation problem.

The familiar isotope exponent $\alpha=-d\ln T_c/d\ln M=1/2$ follows in this model when the cutoff has harmonic mass scaling and the remaining effective parameters are mass-independent. More generally, differentiating $k_BT_c=A E_c\exp(-1/\lambda)$ with mass-independent $A$ gives $\alpha=-d\ln E_c/d\ln M-\lambda^{-2}d\lambda/d\ln M$. Coupling or structural changes therefore prevent inferring the exponent from the cutoff alone; compensating mass dependences can also produce $\alpha=1/2$. This local derivative is not an experimental fit. Likewise, a nonstandard gap ratio can motivate tests of stronger coupling or anisotropy; it does not, by itself, prove a named alternative mechanism. These applicability cautions are editorial model guidance, not new experimental findings. [R1](#ref-source-ba10e800a1246bf6)

## Discovery implications

Use BCS as a controlled baseline: define the band model, interaction window and normalization before fitting. Check that the inferred scales fit within the regime assumed by the calculation, rather than extrapolating an exponential formula into a flat-band or low-density regime. Compare alternative explanations using measurements that distinguish them. In particular, finding a Cooper instability is a starting point for a many-body theory, not the final demonstration of a material's phase coherence or pairing mediator. [R2](#ref-source-d0ec754310a67e88)

A productive research record should retain which assumption failed, which observation exposed the failure and which additional measurement could decide between the remaining models. This is editorial guidance for using the baseline, not a claim of an experimentally established route to higher $T_c$.

## Related topics

Connect the model to [zero-resistance evidence](/scwiki/zero-resistance), [the Meissner effect](/scwiki/meissner-effect), [multiband pairing](/scwiki/multiband-pairing), and [two-dimensional coherence](/scwiki/two-dimensional-interfaces).
