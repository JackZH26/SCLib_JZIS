## Scope

Migdal–Eliashberg theory describes a frequency-dependent electronic self-energy and pairing response to a retarded interaction. The renormalization function $Z$ and anomalous self-energy $\phi$ define $\Delta=\phi/Z$. A phonon-mediated calculation needs an electronic structure, phonon spectrum and interaction model; a large fitted coupling is not by itself evidence for a microscopic mechanism.

Migdal's original paper treats a normal metal and explicitly says that extension to the superconducting state requires a separate investigation. Its selected vertex discussion uses a separation of electronic and lattice scales with specified momentum regimes. The inherited DOI points to an unrelated primatology article; the correct historical JETP scan is retained without inventing a DOI. [R1](#ref-source-21442c6eb33d9b94)

## Mathematical assumptions

Use phonon **energy** $\Omega$ and Matsubara energies $\omega_n=(2n+1)\pi k_BT$; factors of $\hbar$ are absorbed when converting angular frequencies to energies. For the isotropic spectral function $a(\Omega)=\alpha^2F(\Omega)$, define

$$\lambda=2\int_0^\infty\frac{a(\Omega)}{\Omega}\,d\Omega,\qquad K(\nu)=2\int_0^\infty\frac{\Omega a(\Omega)}{\Omega^2+\nu^2}\,d\Omega.$$

Thus $K(0)=\lambda$. Neither this spectral coupling nor a band-resolved coupling matrix is an arbitrary pairing eigenvalue. The selected review derives the imaginary-axis equations under stated electronic-density-of-states and symmetry approximations. [R7](#ref-source-d56b04dc0b32c796)

An independent positive-mode example writes $a(\Omega)=\sum_i\lambda_i\Omega_i\delta(\Omega-\Omega_i)/2$. It gives $\lambda=\sum_i\lambda_i$ and $K(\nu)=\sum_i\lambda_i\Omega_i^2/(\Omega_i^2+\nu^2)$. With normalized weights $w_i=\lambda_i/\lambda$, the logarithmic energy is $\Omega_{\log}=\Omega_{\rm ref}\exp[\sum_iw_i\ln(\Omega_i/\Omega_{\rm ref})]$; the arbitrary positive reference cancels. The second moment is $\langle\Omega^2\rangle=\sum_iw_i\Omega_i^2$.

One mode with $\lambda=1$ at energy $\Omega_0$ and two modes with couplings $1/2$ at $\Omega_0/2$ and $2\Omega_0$ have the same $\lambda$ and $\Omega_{\log}$. Their root-mean-square energies differ by a factor $\sqrt{17/8}$, and at $\nu=\Omega_0/2$ their kernels are exactly $4/5$ and $49/68$ (approximately 0.8 and 0.72059). This independently checked counterexample shows why two scalar summaries do not specify the full spectral problem. The differing kernels alone do not establish different transition temperatures without solving the corresponding equations.

For an isotropic, particle-hole-symmetric constant-density-of-states model with a fixed phonon kernel and **zero Coulomb term**, the linearized gap equation is

$$Z_n\Delta_n=\pi k_BT\sum_m K(\omega_n-\omega_m)\frac{\Delta_m}{|\omega_m|}.$$

The sum covers positive and negative fermion frequencies. The normal-state $Z_n$ must be calculated from the same kernel; omitting it changes the theory. We solve the equivalent symmetric positive-frequency eigenproblem, locating the temperature where its largest eigenvalue reaches one. Increasing the retained positive frequencies from 16 to 128 gives $k_BT_c/\Omega_0\simeq0.11462$ for a single mode with $\lambda=1$. For a 10 meV mode this is about 13.30 K, consistent with the review's model benchmark. It is not an experimental transition or a prediction for a named material. [R7](#ref-source-d56b04dc0b32c796)

A scalar logarithmic Coulomb reduction has the conditional form $\mu^*=\mu/[1+\mu\ln(E_{\rm el}/E_c)]$. It assumes well-separated cutoffs and the stated constant-density-of-states treatment. Reducing the energy range in two successive steps gives the same result as one step; independently checked differentiation gives $d\mu^*/d\ln(E_{\rm el}/E_c)=-(\mu^*)^2$. Report the cutoff with the number: changing the cutoff while keeping $\mu^*$ fixed changes the model. Morel–Anderson's original abstract and the later review are distinct evidence scopes. [R8](#ref-source-9f48e16ab7691de5) [R7](#ref-source-d56b04dc0b32c796)

## Experimental criteria

Choi and colleagues' MgB2 work uses anisotropic first-principles Eliashberg calculations to connect band-dependent gaps with a common calculated transition. These are theoretical results. The corrected DOI is **nature00898**, not the inherited unrelated **nature00992**. Agreement with observations must be assessed with sample and computational conditions preserved. [R4](#ref-source-7c4eac077ae5e221)

Drozdov and colleagues' sulfur-hydride author abstract reports resistive, magnetic-field and susceptibility evidence, with an isotope comparison. It attributes the high-temperature phase to likely H3S formed from pressurized H2S. This entry retains that version-specific attribution and does not claim a new structural identification or independent reanalysis. [R5](#ref-source-8b901b9c6008c434)

The cited lanthanum-superhydride paper is by **Somayazulu and colleagues**, not Drozdov. Its publisher abstract describes four-probe transport drops at 180–200 GPa and supporting characterization. Do not combine its sample, pressure or criterion with a different LaH10 report merely because both discuss lanthanum hydrides. No sample-specific transition value is extracted here. [R6](#ref-source-77b774e18b0f50c7)

For a material calculation, preserve the crystal phase, pressure, stability analysis, electronic and phonon meshes, spectral normalization, Coulomb treatment and convergence. Distinguish harmonic from anharmonic phonons and isotropic from anisotropic or multiband kernels. An inverted tunneling spectrum is model-dependent evidence, not a direct measurement of the interaction function.

## Limits and disputes

McMillan and Allen–Dynes expressions summarize particular Eliashberg solutions; they are not universal bounds. The Allen–Dynes abstract explicitly identifies errors at large coupling and correction factors depending on spectral shape. A fixed-spectrum strong-coupling asymptote does not prove that a real crystal remains stable while its coupling increases without limit. Their full original derivations and datasets are outside this scoped check. [R2](#ref-source-aa8182fe7a3d8d0c) [R3](#ref-source-0620df96ebbf2a66)

A small phonon-to-electron energy ratio alone does not certify every approximation. Narrow bands, unusual momentum structure, phonon feedback and polaron physics require specific analysis. Chubukov and colleagues' abstract compares a model's Migdal results with quantum Monte Carlo and identifies a breakdown of some normal-state properties. This is a model result, not a universal numerical coupling threshold for all materials. [R9](#ref-source-50bdf310cb30a289)

Real-axis spectra require analytic continuation and its numerical checks. An imaginary-axis gap value is not automatically a measured spectral edge; finite damping and multiple bands complicate that correspondence. Replacing the phonon kernel with a spin or charge fluctuation interaction requires a new justification of the approximation and evidence chain.

## Discovery implications

Use spectral calculations to test a candidate mechanism against consistent thermodynamic, spectroscopic and structural evidence. Compare sensitivity to the Coulomb term and phonon treatment rather than selecting whichever inputs yield the largest transition temperature. Keep numerical convergence, validity of the physical approximation and agreement with experiment as three separate judgments.

## Related topics

See [BCS theory](/scwiki/bcs-weak-coupling), [multiband pairing](/scwiki/multiband-pairing), [isotope effects](/scwiki/isotope-effect), [specific heat](/scwiki/specific-heat-jump), and [superconducting gaps](/scwiki/superconducting-gap).
