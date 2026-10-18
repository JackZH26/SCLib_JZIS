## Scope

Antiferromagnetic spin fluctuations are a candidate pairing interaction with substantial weight at a nonzero momentum transfer. A repulsive interaction can favor a gap that changes sign between the states it connects. This is a model-dependent mechanism proposal: observing magnetism, or finding superconductivity near an antiferromagnetic phase, does not establish causation. [R1](#ref-source-eaa3beeed4368f46)

Keep three questions separate: are magnetic fluctuations present; do they change systematically with superconductivity; and can a consistently specified interaction reproduce pairing and other observables? An affirmative answer to the first two does not by itself answer the third. The relevant Fermi surfaces, orbitals, frequency dependence and competing channels must be specified.

## Mathematical assumptions

A dressed particle-particle eigenproblem can be written, with $k_B=1$ and $k$ including momentum and Matsubara frequency, as

$$-\frac{T}{N}\sum_{k'}\Gamma^{pp}(k,k')G_\uparrow(k')G_\downarrow(-k')\phi(k')=\Lambda(T)\phi(k).$$

Here $N$ is the number of lattice sites and the Green functions and irreducible pairing vertex must belong to the same approximation. A leading eigenvalue reaching one signals a pairing instability within that treatment; it is not a measurement of a material transition. The selected review gives this equation and distinguishes spin, charge and fully irreducible contributions. [R1](#ref-source-eaa3beeed4368f46)

A local static illustration, checked by separate matrix calculations, uses two patches with positive single-spin density-of-states weights $N_h,N_e$, a common pairing cutoff, constant gaps and real reciprocal interactions $U_h,U_e,V\ge0$. After the common energy logarithm is factored out, define $\eta\Delta_i=-\sum_jV_{ij}N_j\Delta_j$, with $V_{he}=V_{eh}=V$. The rescaling $x_i=\sqrt{N_i}\Delta_i$ gives a symmetric matrix with diagonal elements $-U_iN_i$ and off-diagonal element $-V\sqrt{N_hN_e}$. This is a separate static model, not a reduction validated against the review's dynamical calculation.

Its larger eigenvalue is

$$\eta_+=-\frac{U_hN_h+U_eN_e}{2}+\sqrt{\frac{(U_hN_h-U_eN_e)^2}{4}+V^2N_hN_e}.$$

For nonnegative intrapatch repulsions it is positive precisely when $V^2>U_hU_e$. The trace is nonpositive and the determinant is $(U_hU_e-V^2)N_hN_e$, establishing this threshold within the two-dimensional model. If both $U_i$ vanish and $V>0$, $\eta_+=V\sqrt{N_hN_e}$ and $\Delta_h/\Delta_e=-\sqrt{N_e/N_h}$. If all interactions vanish, the kernel is zero and no preferred gap ratio is selected. A 432-case check compares direct and symmetrized eigensolvers, exact rational determinants and threshold cases. These are illustrative pairing strengths, not the phonon spectral coupling $\lambda$, a calculated transition temperature, or a fit to any material.

A second independent check shows why a wavevector alone cannot select the gap symmetry. With lattice spacing one, both $\cos k_x-\cos k_y$ and $\cos k_x+\cos k_y$ reverse sign under $\mathbf Q=(\pi,\pi)$. Under a ninety-degree rotation the former changes sign while the latter does not. Their values on the actual Fermi surface and their interaction-weighted eigenvalues still differ. A sign-reversal condition is therefore insufficient to select a unique representation.

## Experimental criteria

Neutron, RIXS and NMR measurements have different response functions, selection rules and energy windows. In the magnetic low-frequency limit, NMR relaxation has the schematic dependence $1/(T_1T)\propto\sum_{\mathbf q,\alpha\perp H}|A_\alpha(\mathbf q)|^2\lim_{\omega\to0}\chi''_\alpha(\mathbf q,\omega)/\omega$. The hyperfine weights and perpendicular spin components matter. The cited spin-chain paper supplies the response formula; it does not make that chain a superconducting-material example. NMR is not a momentum-resolved magnetic spectrum. [R7](#ref-source-e5c4ccac05133124)

RIXS intensities also require a scattering model. Ament and colleagues' indirect-RIXS treatment contains charge and spin response contributions whose relative weights depend on incident energy and the stated core-hole approximation. A measured peak should not automatically be identified with the pairing kernel. This abstract-scoped example is not a derivation for every direct-RIXS geometry. [R8](#ref-source-824b2cddc30b3c2a)

A superconducting spin resonance can reflect feedback of a sign-changing gap through coherence factors. Its interpretation still needs the normal-state response and a susceptibility calculation; it is not independent proof that the resonance caused pairing. [R1](#ref-source-eaa3beeed4368f46)

The Tsuei–Kirtley review describes phase-sensitive evidence for predominantly d-wave pairing in specified optimally doped cuprates. Such symmetry evidence constrains mechanisms without uniquely identifying their microscopic origin. No sample-specific temperature or raw-data reanalysis is added here. [R5](#ref-source-e933e3bbd4beade6)

## Limits and disputes

Mazin and colleagues proposed a compound-specific sign-changing extended-s state for fluorine-doped LaFeAsO. Their published note 8 revises the initial identification of the magnetic instability involved in the doping argument. Reading only the abstract can miss that qualification. Kuroki and colleagues' five-orbital RPA study likewise has parameter-dependent s- and d-wave competition. Neither result assigns one state to every iron-based material. [R3](#ref-source-7c2b55d128348e6c) [R4](#ref-source-f80a18149666bd31)

Kuroki's 2009 erratum corrects an orbital-to-band transformation error affecting the original gap plot. For the displayed parameter set, the corrected diagonal band gap is fully open on the Fermi surface. The authors retain strong anisotropy and parameter-dependent nodal or competing d-wave possibilities. Cite the original together with the erratum; the original nodal plot is not the corrected result. This check reads the erratum text, not a reproduction of its band calculation. [R4](#ref-source-f80a18149666bd31) [R6](#ref-source-6570d4401413e026)

Monthoux–Pines report strong-coupling calculations for a YBCO model, including sensitivity to the spin spectrum and impurity treatment. Their calculated temperature is a theoretical result under chosen parameters. Agreement with selected data is a test of that model, not a mechanism proof that can be transferred to unrelated samples. [R2](#ref-source-7755cb2d156620a8)

A kernel validated for one cuprate must not be transferred unchanged to iron-based compounds or nickelates. Band occupation, orbital weights, interlayer coupling and pressure or strain can alter the relevant low-energy problem. Nickelate material records remain separate; this entry makes no new nickelate gap assignment. Compare normal self-energy, gap structure, magnetic response and competing channels using compatible parameters.

## Discovery implications

Record the measured composition, phase and conditions; spectral normalization and coverage; electronic structure; and the approximation linking response to pairing. Compare alternative channels and report the prediction that could discriminate them. Numerical convergence, agreement with one observable and uniqueness of a mechanism are separate checks. This article's finite-model calculations establish algebraic consistency only.

## Related topics

Continue with [BCS theory](/scwiki/bcs-weak-coupling), [Eliashberg theory](/scwiki/eliashberg-strong-coupling), [multiband pairing](/scwiki/multiband-pairing), [s± pairing](/scwiki/s-plus-minus), and [nickelates](/scwiki/nickelates).
