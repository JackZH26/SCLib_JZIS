## Scope

Theoretical tools answer different questions: whether a model has a pairing instability, how a sample responds, or which approximation is defensible. This handbook connects twelve approved topics to their inputs, outputs and limitations. A solver result is conditional on the Hamiltonian, numerical convergence and physical approximations; it is not an experimental transition record. The J1–J12 identifiers remain stable even where an old planning label needed scientific correction. [R1](#ref-source-ba10e800a1246bf6) [R6](#ref-source-b06e417872e240c9) [R7](#ref-source-51a15c56a9ac1472)

## Mathematical assumptions

State the degrees of freedom, interactions, energy and length units, boundary conditions and limit being taken before comparing calculations. Distinguish an exact identity within a model from an approximation to a real material. The accompanying independent checks cover mass weighting, a four-state atomic Green function, Fourier interpolation, a scalar Cooper-channel flow and complex Bogoliubov matrices. They do not run a material DFT calculation, an interacting impurity solver or a full multichannel renormalization group. [R6](#ref-source-b06e417872e240c9) [R8](#ref-source-12f2513b257d7194) [R11](#ref-source-2b331df83384bc5c) [R12](#ref-source-0aec6d266727d631)

## J1 — BCS mean-field theory

BCS theory constructs a coherent many-electron paired state and a self-consistent gap. In the elementary isotropic model, the quasiparticle energy is $E_k=\sqrt{\xi_k^2+|\Delta|^2}$, with energies measured relative to the chemical potential. The familiar exponential transition scale assumes a weak attractive interaction, an energy shell and a sufficiently smooth density of states. Specify whether that density counts one spin or both; changing the convention without changing the coupling produces a different exponent. [R1](#ref-source-ba10e800a1246bf6)

The Cooper problem instead places two added electrons above an inert Fermi sea. Its instability motivates pairing but does not replace the many-body gap and number equations. A BCS gap solution describes pair formation within the approximation; phase fluctuations, spatial inhomogeneity and competing order can alter the observed transition. A material's similar gap ratio is therefore a consistency check, not unique proof of a phonon mechanism. Use the full band and symmetry assumptions when extending the elementary model. [R1](#ref-source-ba10e800a1246bf6) [R2](#ref-source-d0ec754310a67e88)

## J2 — Eliashberg theory

Eliashberg theory retains the frequency dependence of the interaction and electronic self-energy. A phonon-mediated calculation needs an electron–phonon spectral function, a treatment of the effective Coulomb interaction and an explicitly chosen isotropic, anisotropic or multiband approximation. The gap and mass-renormalization functions are coupled. A converged solution on a Matsubara grid also needs frequency-cutoff and temperature checks; numerical precision alone does not justify neglecting vertex corrections or changes in the phonon system. [R3](#ref-source-d56b04dc0b32c796)

The selected Marsiglio review provides a simple Einstein-spectrum benchmark, while Choi and colleagues' MgB2 calculation illustrates why band-dependent interactions and gaps can matter. Neither example licenses using one averaged coupling for every material. A Matsubara gap value is not automatically the measured tunnelling gap: real-frequency continuation and spectral features require care. Preserve how the Coulomb parameter was chosen and which electronic and phonon inputs were computed, fitted or assumed. The reviewed examples are scoped checks, not independent reproduction of every numerical result. [R3](#ref-source-d56b04dc0b32c796) [R4](#ref-source-7c4eac077ae5e221)

## J3 — McMillan and Allen–Dynes estimates

Compact transition-temperature estimates summarize solutions of a specified electron–phonon theory; they do not replace its inputs. Allen and Dynes use a logarithmic phonon-frequency scale and introduce strong-coupling and spectral-shape corrections. An implementation should name which version it evaluates, preserve the effective Coulomb parameter, and state whether its frequency input is an energy, angular frequency or temperature. A number copied between these conventions without conversion can be wrong even when the expression looks familiar. [R5](#ref-source-0620df96ebbf2a66)

The original abstract describes the accuracy of the modified McMillan estimate for the materials known at that time and its failure at larger coupling. That historical comparison is not a universal modern applicability boundary. Report sensitivity to the spectrum and Coulomb input, and compare a compact estimate with a suitably converged Eliashberg solution when justified. Here the original abstract was checked; the inaccessible original fit derivation and dataset are not claimed as fully reviewed. No fitted or hypothetical estimate is entered into the experimental Tc filter. [R5](#ref-source-0620df96ebbf2a66) [R3](#ref-source-d56b04dc0b32c796)

## J4 — DFT and density-functional perturbation theory

DFT and DFPT connect an electronic-structure approximation to forces, harmonic phonons and response functions. The mass-weighted force-constant matrix $D=M^{-1/2}KM^{-1/2}$ has eigenvalues $\omega^2$, where $K$ is the energy Hessian. Its eigenvalues are not superconducting transition temperatures. An independent two-mass calculation checks the translational zero mode and shows that negative curvature produces a negative squared frequency; removing that sign would conceal an instability. [R6](#ref-source-b06e417872e240c9)

Baroni and colleagues' selected formulation requires self-consistent induced charge and potential. Metallic calculations couple momentum sampling to the smearing treatment; arbitrary numerical smearing is not a physical electronic temperature. The electron–phonon spectral function also differs from the transport-weighted spectrum. Specify structure, exchange-correlation approximation, basis, sampling and response convergence before interpreting a prediction. Harmonic stability alone neither establishes superconductivity nor tests anharmonic effects, strong correlations or every competing structure. The independent checks here verify elementary mechanics, not a full first-principles workflow. [R6](#ref-source-b06e417872e240c9)

## J5 — Hubbard-model QMC and DMRG

Quantum Monte Carlo and density-matrix renormalization group methods address interacting lattice models across different coupling regimes; they are not collectively weak-correlation methods. LeBlanc and colleagues compare several algorithms for specified two-dimensional Hubbard parameters. Agreement must be assessed observable by observable and after the relevant finite-size, temperature and algorithmic extrapolations. Agreement in ground-state energy alone does not establish a particular pairing state or a finite superconducting transition temperature. [R7](#ref-source-51a15c56a9ac1472)

In the reviewed auxiliary-field formulation, particle-hole symmetry protects the half-filled model with zero next-nearest hopping from the sign problem. Away from that setting, a constrained-path calculation adds trial-state-dependent systematic error and is not generally variational. DMRG requires checks of retained states or bond dimension, truncation error, cylinder length and width, boundary conditions and competing metastable patterns. Taking cylinder length to infinity does not take its width to the two-dimensional thermodynamic limit. Historical computational sizes in a 2015 benchmark are not current hardware limits. [R7](#ref-source-51a15c56a9ac1472)

## J6 — Dynamical mean-field theory

Single-site DMFT replaces a lattice environment by a self-consistent quantum impurity bath. It retains local temporal fluctuations through a frequency-dependent self-energy; it is not simply static Hartree-Fock theory. For the specified local-interaction models, its large-coordination limit becomes exact with the appropriate hopping scaling. Applied in finite dimensions, the single-site construction omits nonlocal self-energy components, so spatial correlations may require extensions or independent checks. [R8](#ref-source-12f2513b257d7194)

The impurity Green function must equal the local lattice Green function after self-consistency. The Weiss propagator describing the bath is not generally the bare local lattice propagator. An independent four-state thermal calculation verifies the atomic-limit spectral weights and Green function, but does not validate a finite-hopping DMFT solution. State the impurity solver, bath or frequency discretization, interaction convention and convergence criteria. Two lattices with the same noninteracting density of states need not have identical magnetic response or ordered phases; local single-particle agreement is a narrower result. [R8](#ref-source-12f2513b257d7194)

## J7 — RPA, fluctuation exchange and pairing kernels

Random-phase and fluctuation-exchange approaches organize selected interaction diagrams into response and pairing approximations. Their names do not specify the entire calculation: identify the bare or dressed propagators, orbital interaction matrix, retained channels and self-consistency. Bickers, Scalapino and White's original abstract describes self-consistent conserving approximations for two-particle correlations. Conservation properties are useful constraints, but do not make an approximation exact for arbitrary coupling or establish a measured material's pairing mechanism. [R10](#ref-source-822deb97a8e9dde0)

Scalapino's selected review passages discuss a DCA vertex decomposition and a particle-particle Bethe–Salpeter eigenproblem. They illustrate how a momentum-dependent interaction and dressed propagators enter pairing analysis; those particular results must not be relabelled as an RPA or FLEX benchmark. An eigenvalue reaching the stated instability condition is conditional on the kernel and approximation. Check competing channels, resolution and the treatment of fluctuations before equating its temperature scale with a bulk experimental Tc. The full original conserving-functional derivation remains outside the reviewed scope. [R9](#ref-source-eaa3beeed4368f46) [R10](#ref-source-822deb97a8e9dde0)

## J8 — Tight-binding and Wannier models

Wannier functions provide a localized representation of a chosen Bloch subspace. Unitary rotations within an isolated manifold preserve its projector but change the orbital shapes and hopping representation. With entangled bands, selecting the subspace and selecting its gauge are distinct tasks. The frozen inner energy window constrains which states are retained; outside it, projected bands can differ from the original calculation. A compact model therefore needs its orbital basis and energy windows, not just an attractive band plot. [R11](#ref-source-2b331df83384bc5c)

Interpolation relies on localization, a sufficient momentum mesh and adequate real-space hopping range. Independent Fourier recovery of a known finite-range model succeeds, while an undersampled distant hopping aliases into a different term despite perfect agreement on the sampled grid. Validate intermediate momenta and relevant observables. Nonzero Chern invariants can obstruct an exponentially localized representation of the isolated manifold; a different subspace or hybrid construction must be described explicitly. This check is not a material wannierization or proof that an empirical tight-binding fit is unique. [R11](#ref-source-2b331df83384bc5c)

## J9 — Renormalization group

Renormalization group methods track how an effective description changes as higher-energy modes are removed. The retained channels, cutoff, self-energy treatment and truncation determine what a flow can establish. In Shankar's stated Fermi-surface setting, angular Cooper channels decouple at one loop. With the normalization $g=V_l/(4\pi)$ and $\ell=\ln(\Lambda_0/\Lambda)$, the selected equation gives $dg/d\ell=-g^2$. Negative coupling is attractive in this convention. [R12](#ref-source-0aec6d266727d631)

Independent numerical integration agrees with $g(\ell)=g_0/(1+g_0\ell)$ before its pole: attraction grows and repulsion decreases in this restricted flow. The divergence marks an instability and loss of perturbative control, not a measured Tc or a solved ordered state. The source explicitly warns that otherwise irrelevant terms can generate an attractive channel through the Kohn–Luttinger mechanism. Thus the simple positive-channel flow does not prove that every repulsive system remains a stable normal metal. Nested surfaces and additional channels require their own analysis. [R12](#ref-source-0aec6d266727d631)

## J10 — Quantum geometry and Berry methods

Band eigenvectors carry geometric information beyond the dispersion. A quantum metric and Berry curvature can be constructed from the projector onto a specified band or subspace, with carefully stated normalization and gauge conventions. The selected Liang manuscript uses a metric normalization twice the convention used in the linked Wiki geometry article. Comparing numerical coefficients without reconciling that factor would produce a false disagreement. Degenerate or touching bands also require a suitable subspace treatment rather than unstable single-band derivatives. [R13](#ref-source-fa7a165c8c344a63)

Geometric quantities can enter superfluid response, but a nonzero metric alone does not prove superconductivity. Peotta and Törmä's flat-band result has explicit interaction, isolation and pairing assumptions. Huhtinen and colleagues further show why order-parameter relaxation and representation dependence matter when differentiating the free energy. State what is held fixed and what is reoptimized before calling a curvature a physical stiffness. A frozen-field derivative and a relaxed response are not interchangeable; the full multiband response calculation remains a separate task. [R14](#ref-source-72f7ddb9f13bbd81) [R15](#ref-source-fdf091e09e7f4a6f)

## J11 — Ginzburg–Landau theory

Ginzburg–Landau theory organizes a free-energy expansion in a complex order parameter and its spatial gradients. Its coefficients and applicable temperature range must be specified; in its conventional derivation it is controlled near the transition. A homogeneous minimum, a linearized upper-critical-field calculation and a vortex-lattice solution are different problems. The type-I/type-II boundary of the elementary isotropic model should not be transferred without qualification to every anisotropic or multicomponent material. [R16](#ref-source-89f5503f5e470385)

Brandt's ideal vortex-lattice calculation illustrates how field, the Ginzburg–Landau parameter and lattice structure affect magnetic observables. Its assumptions exclude arbitrary disorder and pinning, and the commonly used London-limit variance is valid only in a restricted regime. Solving a phenomenological equation with chosen coefficients does not identify a microscopic pairing mechanism. Report boundary conditions, gauge, mesh and free-energy comparisons when several solutions exist; numerical convergence to one stationary configuration alone does not establish that it is the global equilibrium state. [R17](#ref-source-65b23b74f5402e26)

## J12 — Bogoliubov–de Gennes equations

Bogoliubov–de Gennes theory writes a quadratic paired Hamiltonian in a particle-and-hole basis. For a complete finite fermionic basis, Hermitian normal block $h$ and antisymmetric pairing matrix $\Delta$, one convention is $\mathcal H=\begin{pmatrix}h&\Delta\\\Delta^\dagger&-h^T\end{pmatrix}$. The doubled description has particle-hole redundancy, not twice as many independent physical states. Independent complex-matrix checks verify Hermiticity and paired eigenvalues in this convention; a reduced spin block can use different notation. [R18](#ref-source-ade538b429fdd847)

Specify whether the pairing field is imposed or determined self-consistently, together with density, boundaries and the physical basis. Kitaev's selected chain model provides a controlled example of bulk and boundary structure, but a near-zero eigenvalue by itself does not prove a protected experimental Majorana mode. Finite-size splitting, competing localized states and model perturbations must be considered. A self-consistent mean-field solution also does not include every collective or correlation effect. Numerical particle-hole symmetry is a necessary algebra check, not a topological classification or material validation. [R18](#ref-source-ade538b429fdd847)

## Experimental criteria

Compare calculated and measured quantities with matching sample conditions and definitions. A pairing eigenvalue, a harmonic phonon, a local spectral gap and an experimental zero-resistance criterion are different observables. Keep model temperatures out of the measured-Tc catalogue. Predictions should specify independent tests that could reject the assumed mechanism, structure or parameter set. [R4](#ref-source-7c4eac077ae5e221) [R6](#ref-source-b06e417872e240c9) [R7](#ref-source-51a15c56a9ac1472)

## Limits and disputes

Each of the twelve sections has a named review scope. Some references were checked only at abstract level; others use selected author-manuscript passages with final-version comparisons still open. Independent small-model checks verify the stated algebra and counterexamples, not all numerical methods or every cited material. Complete scientific acceptance, full derivations, supplementary datasets and material-level reproduction remain open. [R5](#ref-source-0620df96ebbf2a66) [R7](#ref-source-51a15c56a9ac1472) [R10](#ref-source-822deb97a8e9dde0) [R12](#ref-source-0aec6d266727d631)

## Discovery implications

Choose the simplest defensible model that can distinguish the proposed explanation from a concrete alternative. Carry its uncertainty into any material ranking. A useful workflow moves between structural evidence, electronic and interaction models, numerical convergence and experimentally testable observables; agreement at one stage does not remove assumptions at the next. Retain failed fits and competing states rather than reporting only the most favorable transition estimate. [R6](#ref-source-b06e417872e240c9) [R7](#ref-source-51a15c56a9ac1472) [R11](#ref-source-2b331df83384bc5c)

## Related topics

Read [BCS theory](/scwiki/bcs-weak-coupling), [Eliashberg theory](/scwiki/eliashberg-strong-coupling), [spin fluctuations](/scwiki/spin-fluctuation-pairing), [quantum metric](/scwiki/quantum-metric), [geometric superfluid weight](/scwiki/geometric-superfluid-weight), [Majorana states](/scwiki/majorana-zero-modes), [experimental methods](/scwiki/experimental-methods), and [flat-band temperature limits](/scwiki/open-questions/n10).
