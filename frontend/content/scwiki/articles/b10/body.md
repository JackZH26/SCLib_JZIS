## Scope

Hund coupling is an intra-atomic exchange interaction that changes the energies and fluctuations of multiorbital electrons. It can organize a correlated metallic state without identifying the interaction that produces superconductivity. Orbital-dependent masses, slow screening and local moments are normal-state constraints on a pairing theory; they do not specify its Cooper-channel eigenfunction.

The de' Medici–Mravlje–Georges three-orbital calculation illustrates a filling-dependent distinction. For two electrons, increasing Hund coupling can reduce quasiparticle coherence while moving the Mott threshold to stronger repulsion. The corresponding singly occupied and half-filled cases behave differently. This is the Janus effect in a specified model, not a universal monotonic relation between Hund coupling and transition temperature. [R1](#ref-source-2e4683ad42b430ca)

## Mathematical assumptions

Specify the correlated orbitals, their crystal-field energies and the interaction convention. In the Kanamori convention used here, $U$ penalizes opposite spins in one orbital, $U'$ couples opposite spins in different orbitals, and $U'-J$ couples parallel spins in different orbitals. Spin-flip and pair-hopping amplitudes are retained. For the usual degenerate-shell reduction with both amplitudes equal to $J$, we impose $U'=U-2J$. The review distinguishes this assumption from more general rotationally invariant interactions; the relation cannot be inferred from spin symmetry alone. [R2](#ref-source-8155406e83b90d41)

An independent finite-atom check constructs the full Fock-space Hamiltonian, including fermionic signs, for two and three orbitals. There is no hopping between atoms, bath or spin-orbit coupling. With two electrons and positive $J$, the two-orbital eigenvalues and degeneracies are

$$E=U-3J\ (3),\qquad U-J\ (2),\qquad U+J\ (1).$$

The lowest triplet is threefold degenerate. Keeping density interactions alone leaves only two states at this lowest energy and shifts the opposite-spin combination. It therefore changes the spin multiplet, even when the parameters retain the same names. Direct diagonalizations at three parameter sets verify this distinction; the omission is not a harmless numerical shortcut.

With three degenerate orbitals, the two-electron sector instead has energies $U-3J$, $U-J$ and $U+2J$, with degeneracies 9, 5 and 1. Counting all 15 states checks that spin and orbital multiplicities have both been included. These finite spectra provide a reproducible convention test before a lattice calculation; they are not a prediction of quasiparticle coherence.

Define the atomic charge-addition gap using ground-state energies at fixed electron number:

$$\Delta_{\mathrm{at}}(N)=E_0(N+1)+E_0(N-1)-2E_0(N).$$

For the three-orbital model at the tested repulsive parameters, direct diagonalization gives $\Delta_{\mathrm{at}}(1)=\Delta_{\mathrm{at}}(2)=U-3J$, but $\Delta_{\mathrm{at}}(3)=U+2J$. Nine numerical charge-gap checks reproduce these expressions. The half-filled shell responds differently to exchange. A finite atomic addition gap is neither a superconducting excitation gap nor a solid's critical interaction: bandwidth, hybridization and self-consistency are missing. The original Janus paper also separates this atomic argument from the low-coherence metallic regime. [R1](#ref-source-2e4683ad42b430ca)

Crystal-field splitting provides a second independent illustration. Put two orbital energies at $-\delta/2$ and $+\delta/2$, keep two electrons, and retain pair hopping. The mixed doubly occupied singlet has energy $U-\sqrt{\delta^2+J^2}$, while the triplet has energy $U-3J$. Four matrix checks confirm a crossing at $|\delta|=\sqrt8J$. For $U=6$, $J=1$ and $\delta=4$ in arbitrary energy units, the singlet is lower despite positive Hund coupling. This example excludes any unconditional statement that Hund exchange guarantees a high-spin ground state in a crystal.

## Experimental criteria

Separate an orbital-resolved theoretical self-energy from a measured band dispersion or a thermodynamic sum over bands. State the temperature, field, reference band calculation and fitting window. A mass comparison can depend on the chosen correlated subspace and ligand hybridization; one universal enhancement factor should not be transferred between iron compounds, ruthenates and nickelates.

Hardy and colleagues studied KFe2As2 using resistivity, calorimetry, thermal expansion and susceptibility. Their accepted manuscript reports a zero-field heat-capacity transition at 3.4 K and a 5.5 T, c-axis comparison for the normal-state curve. It warns that a large residual-resistivity ratio can reflect strong high-temperature scattering rather than exceptionally few defects. The normal-state coherence interpretation and the superconducting transition are separate observations; neither constitutes a direct measurement of a unique pairing interaction. Selected manuscript pages were checked, not the full raw data. [R5](#ref-source-76e58b04a07e6eca)

Yin, Haule and Kotliar compared iron compounds with DFT+DMFT while fixing the local interaction matrix. Their analysis connects orbital differentiation to structure and describes cancellation between direct and ligand-mediated hopping for the xy orbital. These are material calculations with explicit approximations. The paper's proposed structural optimization for superconductivity remains an inference, not an experimental demonstration that maximizing Hund coupling raises Tc. [R3](#ref-source-68d283623978d0b0)

## Limits and disputes

The Yin paper has a published erratum: the material label in Figures 1 and 2 is BaFe2As2, replacing the original BaFe2Se2 label. The corrected publisher PDF and appended erratum were checked, including a visual inspection of the correction. Preserve this identity when reusing the comparison. [R3](#ref-source-68d283623978d0b0) [R4](#ref-source-49e40a5d456ab475)

A reduced bare triplet interaction $U-3J$ can remain positive. In all three repulsive parameter sets checked above it does. Lowering one atomic energy relative to another does not demonstrate an attractive effective interaction between low-energy quasiparticles. A pairing calculation must include the relevant momentum, frequency, spin and orbital structure, along with normal-state renormalization and competing orders.

Spin freezing describes a dynamical regime over specified temperatures and timescales; it must not automatically be relabeled a zero-temperature magnetic phase. The finite-atom checks here cannot establish that regime because they contain no environment or relaxation process. Full final-version comparison, material-specific vertex calculations and independent experimental replication remain outside this entry's completed review.

A 2026 bilayer-nickelate calculation illustrates why the pairing problem must be evaluated separately. Maier and colleagues analyze a two-orbital Hubbard–Hund model with a cluster method. Its two-site instability is near 140 K, while the authors infer a scale around 100 K for the large-system model. Neither is a measured material Tc. The two-site cluster omits spatial phase fluctuations; larger clusters encounter a low-temperature fermion sign problem. These limitations bound the proposed interlayer pairing interpretation. [R6](#ref-source-e2a88a477c985a7e)

## Discovery implications

Vary filling, crystal-field splitting or structure within a clearly specified model, and compare normal-state predictions against multiple probes before solving the pairing problem. Record which interaction terms and vertex corrections are retained. Test whether a candidate enhancement survives reduced coherence and competing magnetism. Report the resulting pairing eigenfunction and its assumptions rather than ranking materials by $J$ or mass alone.

## Related topics

Compare [spin-fluctuation pairing](/scwiki/spin-fluctuation-pairing), [ferromagnetic fluctuations](/scwiki/ferromagnetic-fluctuations), [multiband pairing](/scwiki/multiband-pairing) and [RVB constructions](/scwiki/rvb-and-doped-mott-insulators).
