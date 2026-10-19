## Scope

A narrow band can increase the number of electronic states available for pairing, while reducing the ordinary velocity-based contribution to current response. Pair formation and phase coherence must therefore be assessed separately. A large density of states is not a guarantee of high superconducting transition temperature, and a flat band need not be topological.

Peotta and Törmä derive a geometric contribution to superfluid weight within a multiband mean-field treatment. Their isolated-flat-band reduction assumes bandwidth much smaller than attraction, attraction much smaller than the gaps to other bands, and a suitable uniform orbital pairing field. The associated Chern bound includes interaction, filling and normalization factors; it is not a dimensionful stiffness greater than a bare integer. Julku and colleagues give a Chern-trivial Lieb-lattice example with finite geometric response, so a nonzero Chern number is sufficient for particular bounds, not necessary for every geometric contribution. [R1](#ref-source-fdf091e09e7f4a6f) [R2](#ref-source-b43340ce5c356e49)

## Mathematical assumptions

Consider an independent reduced pairing model with one flat state per spin per cell, effective attraction $G>0$ and half filling. Absorb the Hartree shift into the chemical potential and set the flat level at that chemical potential. The mean-field equation is

$$1=\frac{G}{2\Delta}\tanh\!\left(\frac{\Delta}{2k_BT}\right),\qquad \Delta(0)=\frac{G}{2},\qquad k_BT_{\mathrm{pair}}=\frac{G}{4}.$$

Twelve numerical cases solve the finite-temperature equation or verify the absence of a nonzero solution above its linearized onset. This linear pairing scale depends on the stated state-counting convention. It must not be transferred unchanged to a multiorbital lattice: the effective interaction includes orbital weights and differs from a bare on-site attraction.

To test whether pairing alone establishes coherence, take four disconnected attractive sites. Direct enumeration of all 256 occupation states at three attractions gives pair binding but no dependence of the spectrum or partition function on an intersite phase twist. The thermal trace of pair transfer between different sites is zero. Each site can bind two particles while the assembly carries no phase-stiffness response. The mean-field onset above is not a true finite-temperature superconducting transition in this atomic limit.

A second independent illustration keeps two exactly flat band energies but changes their eigenvectors in a fixed orbital basis. Compare a constant normalized vector with $u(k)=(\cos(k/2),\sin(k/2))$. The first has zero quantum metric; the second has

$$g_{kk}=\langle\partial_k u|\partial_k u\rangle-|\langle u|\partial_k u\rangle|^2=\frac14.$$

Twelve finite-difference fidelity checks reproduce these values, including a smooth momentum-dependent phase multiplying each vector. Identical dispersions therefore do not determine identical geometry. This Bloch-phase invariance does not remove the need to specify physical orbital positions, coupling to a field and the response of the pairing fields.

For the rotating vector, an imposed projected pair field has overlap $|\langle u(k-q)|u(k+q)\rangle|^2=\cos^2q$. With fixed $\Delta$ and level offset $\xi$, define $E(q)=\sqrt{\xi^2+\Delta^2\cos^2q}$ and the illustrative energy cost $E(0)-E(q)$. Six finite-difference comparisons, including the constant-vector case, give curvature $\Delta^2/E(0)$ for the rotating vector and zero for the constant one. If the pair phase gradient is $Q=2q$, its curvature is one quarter as large. This checks a frozen projected overlap response, not a self-consistent multiband stiffness or one-dimensional finite-temperature order.

For an isotropic superconducting sheet, define phase stiffness by $F/A=\rho_s|\nabla\theta-(2e/\hbar)\mathbf A|^2/2$. Then sheet kinetic inductance $L_\square$ gives $\rho_s=\hbar^2/(4e^2L_\square)$. Here the electromagnetic response coefficient is $D_s=1/L_\square=4e^2\rho_s/\hbar^2$; conventions using $D_s$ without the charge factors must be converted before comparing values. A hypothetical zero-temperature value of 10 nH per square gives $\rho_s(0)/k_B\approx0.784$ K and $\pi\rho_s(0)/(2k_B)\approx1.232$ K. This is an upper BKT scale only if the renormalized stiffness at the transition does not exceed the stated zero-temperature stiffness. In the equilibrium BKT regime, the jump uses $k_BT_{\mathrm{BKT}}=\pi\rho_s^{R}(T_{\mathrm{BKT}}^-)/2$, not a zero-temperature substitution. Finite-frequency inductive response and spatially inhomogeneous current paths require separate interpretation before applying that thermodynamic relation. This is a unit-conversion illustration, not a material measurement. [R4](#ref-source-be7282623ca96056) [R7](#ref-source-8f81510a80c35e3a)

## Experimental criteria

Cao and colleagues established gate-tunable superconducting transport in magic-angle twisted bilayer graphene. Their published device discussion uses four-probe measurements and deliberately non-superconducting Cr/Au contacts. These observations establish the platform, but do not uniquely separate phonon, electronic and geometric roles. Keep twist angle, density and transition criterion attached to the specific device rather than combining a maximum temperature from one device with a stiffness from another. [R3](#ref-source-90c67b111a6e919c)

Tanaka and colleagues infer total sheet stiffness from microwave kinetic inductance alongside four-probe transport. The reviewed earlier manuscript uses a 20 mK refrigerator base temperature and estimates about 40 mK for the wired device. Its circuit model includes a parallel electrode-proximitized edge, and the sheet conversion assumes the active region shares the device aspect ratio. The approximately 1 K scale across much of the dome uses half normal-state resistance; it is not automatically the zero-resistance or BKT temperature. Comparison with a conventional estimate supports a geometric interpretation without isolating a model-independent geometric fraction. These selected manuscript passages were checked; the complete published-version and raw-data comparison remains open. [R4](#ref-source-be7282623ca96056)

## Limits and disputes

The CsV3Sb5 discovery paper combines superconducting evidence with normal-state photoemission and band calculations. A kagome lattice, a van Hove feature, normal-state band topology and charge order are different observations. None alone measures quantum-metric superfluid weight or proves that geometry supplies the pairing interaction. Related potassium and rubidium compounds require their own specimen-specific review; no cross-compound temperature ranking is inferred here. [R5](#ref-source-d49026ec4f5a10a4)

A September 2026 preprint by Wang and colleagues studies a proposed pair-density-wave state with Bogoliubov Fermi surfaces. It predicts that residual zero-energy spectral weight can accompany reduced stiffness despite a positive geometric contribution. This is a model prediction, not an observed universal correlation. The current v2 title and abstract differ from the March v1 indexed by some services; this entry cites v2 explicitly and has checked only its abstract and version history. [R6](#ref-source-9cd5a81de8b8bedd)

As an editorial inference, neither the finite models above nor a fit to total stiffness identifies a unique pairing interaction. Orbital relaxation, remote bands, disorder and spatial inhomogeneity can alter quantitative comparisons. Full scientific acceptance remains open, including final-version checks, raw-data review and material-specific self-consistent response calculations.

## Discovery implications

As an editorial research workflow, optimize pairing and coherence together. State the bandwidth, interband separation, orbital interaction and filling; test the approximations before applying an isolated-band formula. Compare gap, transport and inductive response in the same specimen. Keep an inferred phase scale separate from measured resistive criteria, and preserve the uncertainty in the conventional baseline used to discuss geometry.

## Related topics

Continue with [geometric superfluid weight](/scwiki/geometric-superfluid-weight), [two-dimensional phase coherence](/scwiki/two-dimensional-interfaces), [multiband pairing](/scwiki/multiband-pairing) and [topological superconductivity](/scwiki/topological-superconductivity).
