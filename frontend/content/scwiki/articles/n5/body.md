## Scope

The microscopic origin of strange-metal behavior remains an open question across material families. Approximately linear low-temperature resistivity is an important observation, but it does not uniquely specify a scattering mechanism, establish the absence of quasiparticles, or identify the interaction responsible for superconductivity. A useful explanation must reproduce several observables in a defined regime and survive comparison with alternatives. This is a selected evidence map, not an exhaustive ranking of all proposed theories. [R1](#ref-source-67da95cac5481029)

Three questions should remain separate: what relaxes electrical current, what broadens a single-particle excitation, and what produces the measured response function? Their answers can differ. An apparent rate inferred using carrier density and effective mass is model dependent. A coefficient near $k_BT/\hbar$ is not, by itself, a microscopic derivation or a universal transport bound. [R1](#ref-source-67da95cac5481029) [R4](#ref-source-14387c003c0b024d)

## Experimental criteria

Grissonnanche and colleagues use angle-dependent magnetoresistance in Nd-LSCO to separate an anisotropic residual contribution from an approximately isotropic temperature-dependent rate. Their extraction depends on the band model, energy scale and geometry. At the lower measurement temperatures, some field orientations remain superconducting; these cannot silently enter an all-normal-state fit. This is a stronger constraint than a straight resistivity curve alone, while still being an inference tied to its experimental conditions. [R2](#ref-source-374c8bc13ced83e8)

Optical measurements add frequency dependence and spectral-weight information. Romero and colleagues resolve a narrower channel and a broad background in FeTe1−xSex films. The selected author analysis has a finite frequency resolution and a restricted fitting interval. Such a decomposition should be compared with competing response models, rather than assumed to prove that every apparent optical component represents a distinct microscopic carrier population. [R3](#ref-source-05b2d5ff6757b5eb) [R6](#ref-source-dea2ebb88fe95936)

Campbell and colleagues report a connection between fluctuating magnetic moments and strange-metal transport in LSCO at high fields, with changes when moments freeze. The checked publisher abstract supports this material-specific association. It does not alone establish the mechanism in every cuprate or distinguish all theories of magnetic fluctuations. Full measurement details remain outside this source check. [R9](#ref-source-62781c6eb802b997)

## Two constructive model routes

Patel, Guo, Esterlis and Sachdev's 2023 theory couples two-dimensional fermions to critical scalar modes, with spatially random Yukawa interactions about a nonzero mean. In a large-$N$ ensemble, interaction disorder produces linear resistivity while a different coupling can dominate the single-particle self-energy. This offers a mechanism for separating current relaxation from spectral broadening. Its proposed generality is a theoretical claim with stated approximations, not a material-by-material experimental identification. [R4](#ref-source-14387c003c0b024d)

Patel, Lunts and Albergo subsequently simulate a different, specified spin–fermion construction. The selected published-version text uses two bands, two auxiliary flavors, zero mean Yukawa coupling and typically a $40\times40$ lattice averaged over ten disorder realizations. An extended region with localized, gapless magnetic fluctuations supports strange-metal transport. The transport rate is inferred from Matsubara conductivity and a zero-frequency spline extrapolation; its coupling comparison uses two disorder strengths at matched rescaled tuning parameters. Avoid turning that comparison into independence from every Hamiltonian parameter. [R5](#ref-source-f7ac8e7f2cfae198)

Fratini and colleagues' paper, published on **24 September 2026**, develops another route through the two-dimensional t–J model. The checked author version and final supplement use finite-temperature and low-temperature Lanczos calculations, including twisted-boundary averaging. Single-hole clusters reach 24 sites and finite-density clusters 20 sites. Selected results connect broad current spectra to an apparent thermal optical width. Gaussian broadening and d.c. extrapolation remain part of the calculation; noninteracting boundary-average benchmarks do not prove exact interacting thermodynamic-limit transport. [R6](#ref-source-dea2ebb88fe95936)

## Mathematical assumptions

For the regular dissipative conductivity at positive frequency, choose a current-spectrum normalization that absorbs charge and volume constants, and set $k_B=\hbar=1$. The thermal relation reads

$$
\sigma_1(\omega)=\frac{1-e^{-\omega/T}}{\omega}C(\omega),
\qquad C(-\omega)=e^{-\omega/T}C(\omega).
$$

It concerns the response and its unsymmetrized spectrum; it is not a declaration that every metal has a finite regular d.c. limit. A separate zero-frequency delta function, if present, requires separate treatment. For finite $C(0)$, the regular limit is $\sigma_1(0)=C(0)/T$. [R6](#ref-source-dea2ebb88fe95936)

An original four-level example verifies detailed balance and the corresponding transition weights in 24 thermal cases. A separate illustrative positive-frequency envelope, $C(\omega)=2\exp[-(\omega/100)^2]$, gives $\rho=T/2$ and a half-width close to $1.59T$ for four temperatures between 0.1 and 1. The envelope is broad and temperature independent; its negative-frequency branch follows detailed balance. This is a bounded response example, not a microscopic Hamiltonian construction or a validation of the optical sum rule across temperatures. It demonstrates why a thermal response width alone need not identify a carrier collision time.

A second independent illustration assumes elastic scattering on a circular Fermi surface. If $W(\theta)$ is an angular transition-rate density, the departure rate weights $W$, whereas the current mode weights $W(1-\cos\theta)$. Eight discretized collision operators verify that forward-peaked scattering can leave a large departure rate but a much smaller current-relaxation rate. Particle conservation is checked independently. These quasiparticle examples explain an inference problem; they do not establish quasiparticles in a strange metal. [R1](#ref-source-67da95cac5481029)

## Noise and the interpretation of carriers

Chen and colleagues measure suppressed noise in YbRh2Si2 nanowires compared with a gold control and specified diffusive Fermi-liquid expectations. Their selected author text uses long-wire measurements to constrain electron–phonon cooling, and interprets the short-wire result as evidence against well-defined quasiparticle carriers in the examined regime. Effective Fano factors come from a finite-temperature, bias-dependent analysis; they are not direct measurements of a fractional elementary charge. [R7](#ref-source-96657a33251c13ee)

Polyak, Khrapai and Tikhonov question that interpretation through contact resistance and energy relaxation. Their model allows current redistribution between the film and its gold covering, includes an added contact contribution fitted to resistance, and omits some contact and amplifier noise terms. These qualifications matter when comparing their alternative with the original controls. This review has not independently refitted either analysis and does not adjudicate the dispute. A low noise level should therefore be reported with its device and thermal assumptions. [R8](#ref-source-be020ff1e20fbae5) [R7](#ref-source-96657a33251c13ee)

## Limits and disputes

The reviewed models explain overlapping features without yet establishing one microscopic origin across all strange metals. Large-$N$ control, finite-system numerical convergence and experimental agreement answer different questions. Keep extrapolation, disorder averaging, response normalization and temperature windows visible. In particular, a model producing narrow and broad optical features from one carrier type does not by itself overturn a two-channel interpretation in a different material. [R4](#ref-source-14387c003c0b024d) [R5](#ref-source-f7ac8e7f2cfae198) [R6](#ref-source-dea2ebb88fe95936) [R3](#ref-source-05b2d5ff6757b5eb)

## Discovery implications

A discriminating program should jointly compare transport, optical response, magnetic fluctuations, thermodynamics and, where feasible, noise. Test how controlled disorder, filling or field changes both the candidate mechanism and its predicted observables. The random-interaction model's proposed spatial magnetic probes offer one concrete direction; independent contact and thermal calibration offer another. These are proposed validation priorities. Reproducing a resistivity exponent or fitting a thermal rate does not certify a pairing mechanism or predict a new material's $T_c$. [R5](#ref-source-f7ac8e7f2cfae198) [R7](#ref-source-96657a33251c13ee) [R8](#ref-source-be020ff1e20fbae5)

## Related topics

Continue with [strange-metal observations](/scwiki/strange-metals), [Planckian dissipation](/scwiki/planckian-dissipation), [parallel conducting channels](/scwiki/parallel-conduction-channels), and [the question of a unified pairing mechanism](/scwiki/open-questions/n2).
