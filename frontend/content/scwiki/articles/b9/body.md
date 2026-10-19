## Scope

Resonating valence bond, or RVB, denotes a family of correlated-state constructions built from quantum superpositions of singlet bonds. Anderson's 1987 proposal connected singlets in a correlated insulator to superconductivity after doping. It is a theoretical route, not a diagnosis obtained merely by finding a superconductor near an insulator. The original article's indexed abstract was checked; its complete argument remains outside this source review. [R1](#ref-source-5a6026d6455bf7a0)

RVB is not synonymous with a particular quantum spin liquid, a universal pairing boson or a directly measurable order parameter. A chosen wavefunction, projection and treatment of emergent gauge dynamics determine its physical predictions. The Lee–Nagaosa–Wen formulation distinguishes the redundancy used to represent electrons from the low-energy gauge structure of a state. [R2](#ref-source-2f6a1c773323226a)

## Mathematical assumptions

A singlet on ordered sites $i,j$ is $|s_{ij}\rangle=(|\uparrow_i\downarrow_j\rangle-|\downarrow_i\uparrow_j\rangle)/\sqrt2$. Different products of such bonds need not be orthogonal. An independent four-spin illustration takes $A=|s_{12}s_{34}\rangle$ and $B=|s_{14}s_{23}\rangle$, with the stated orientation fixing their relative sign. Direct expansion gives $\langle A|B\rangle=-1/2$, so the normalized superposition is $(A-B)/\sqrt3$, not $(A-B)/\sqrt2$.

For the periodic four-site spin Hamiltonian $H=J\sum_{i=1}^4\mathbf S_i\cdot\mathbf S_{i+1}$ with $J>0$, direct action on this superposition gives energy $-2J$ and zero eigenvector residual. An equal incoherent mixture of the two bond coverings has energy $-3J/2$. The difference demonstrates quantum interference in a specified finite spin problem. Neither result establishes bulk topological order or superconductivity: this model has no mobile charge degrees of freedom.

To distinguish a strong-coupling approximation from an exact scale, consider a two-site, one-orbital Hubbard model with two electrons, hopping $t$ and repulsion $U>0$. Exact diagonalization of its six-state sector gives a singlet–triplet splitting

$$J_{\mathrm{dimer}}=\frac{\sqrt{U^2+16t^2}-U}{2}\simeq\frac{4t^2}{U}\quad(U\gg|t|).$$

Four independent matrix calculations agree with the exact expression. At $U/|t|=4$, the leading expression overestimates the splitting by about 20.7%; at 32 the error is about 0.39%. The local exchange scale and its expansion do not by themselves predict a pairing temperature in a doped lattice. Multiorbital charge-transfer materials require additional assumptions before using this one-band reduction.

A projected-electron construction writes $c_{i\sigma}=b_i^\dagger f_{i\sigma}$ with $b_i^\dagger b_i+\sum_\sigma f_{i\sigma}^\dagger f_{i\sigma}=1$. It represents the reduced local Hilbert space containing an empty site and two singly occupied spin states. The equality specifies physical matrix elements within that constrained space, not a canonical electron operator identity on the enlarged unconstrained space. Under the internal redundancy $f_i\to e^{i\theta_i}f_i$, $b_i\to e^{i\theta_i}b_i$, the electron remains invariant. A spinon pair alone changes phase; the accompanying charge factor cancels it. Three explicit phase checks confirm this cancellation. A gauge-fixed factorization into spin and charge averages is an approximation, not separate observation of either factor. [R2](#ref-source-2f6a1c773323226a)

An independent Gaussian response illustration minimizes

$$F(a,A)=\frac{\rho_b}{2}(A-a)^2+\frac{\rho_f}{2}a^2,\qquad \rho_{\mathrm{eff}}=\frac{\rho_b\rho_f}{\rho_b+\rho_f}.$$

Here $A$ is a normalized external field, $a$ an internal field, and nonnegative coefficients describe two sectors within this quadratic model. The fraction requires $\rho_b+\rho_f>0$. If both coefficients vanish, $F=0$ for every field: the physical stiffness is zero and minimization does not select an internal field; the undefined fraction is not evaluated. Direct minimizations and exact quadratic checks cover these boundaries. A finite $\rho_f$ does not provide charged stiffness when $\rho_b=0$. This is a restricted response illustration: non-Gaussian and compact gauge fluctuations are absent, and it is not a universal experimental law.

## Experimental criteria

Establish the insulating state's magnetic and structural properties before naming it a spin liquid. Vaknin and colleagues' neutron-diffraction study of undoped La2CuO4-y reports magnetic superlattice evidence for antiferromagnetism. That parent-state observation must be retained alongside the historical RVB proposal. A measured superconducting gap symmetry may constrain candidate states without uniquely selecting their microscopic explanation. [R7](#ref-source-9dda11fbf0c41f73)

Lefebvre and colleagues mapped kappa-(ET)2Cu[N(CN)2]Cl using helium pressure, proton NMR and ac susceptibility. The selected manuscript uses a 0.5 T field for NMR and no static field for the susceptibility measurement; it restricts hydrostatic sweeps to conditions above helium solidification. The authors report inhomogeneous phase coexistence but do not resolve whether it is macroscopic or mesoscopic. These conditions belong to kappa-Cl and cannot be transferred to a different organic salt. [R3](#ref-source-2cc5358d54a65217)

For kappa-(BEDT-TTF)2Cu2(CN)3, Shimizu and colleagues' abstract reports no NMR indication of long-range order down to 32 mK, despite a susceptibility-derived exchange scale around 250 K. Neither number is a superconducting transition temperature. Kurosaki and colleagues separately studied its pressure-dependent NMR and resistivity phase diagram. The existence of neighboring superconductivity does not identify the insulating state's excitations as its pairing mechanism. Those two sources remain abstract-scoped here. [R4](#ref-source-9d15cd9236072f5c) [R5](#ref-source-0443485ac20d3a8c)

## Limits and disputes

Pustogow and colleagues' 2023 strain-transport study favors a low-entropy, spin-gapped valence-bond-solid interpretation of the organic candidate's 6 K anomaly. The 140 nm crystal is coupled to a PET substrate; quoted hydrostatic-equivalent pressures are inferred by comparison with transport data. The paper acknowledges that a gapped chiral spin liquid is not ruled out without a discriminating experiment. It also assigns sharp resistance jumps to mounting-related microcracks. A transport anomaly or phase-diagram shape alone must not be promoted to an unambiguous microscopic spin-state determination. [R6](#ref-source-5e0dcd80e8b64a1b)

The Lee–Nagaosa–Wen review itself notes an experimental mismatch in the doping dependence of the Gaussian U(1) prediction for the temperature slope of superfluid density. Thus the simple response construction above has an explicit historical limitation. Naming a redundant representation U(1), SU(2) or Z2 is not sufficient to establish the corresponding emergent low-energy phase. [R2](#ref-source-2f6a1c773323226a)

Pseudogaps, Fermi arcs, singlet correlations and d-wave pairing each admit more than one theoretical description. Test a specified RVB state against physical correlation functions, charge stiffness, spectral weight, symmetry and disorder responses. Treating all these observations as interchangeable proof would remove the very distinctions needed to compare mechanisms. Full final-version, data and material-specific calculations remain open.

## Discovery implications

Track a controlled doping or bandwidth path with independently established magnetic, structural and superconducting observables. Distinguish tuning the filling from changing hopping, disorder or lattice geometry. Preserve the local constraints of a theoretical model and calculate gauge-invariant observables before assigning a material interpretation. A finite singlet-energy gain is a useful model check, not an experimentally verified route to high-temperature superconductivity.

## Related topics

Compare [quantum spin liquids](/scwiki/spin-liquids-and-superconductivity), [spin fluctuations](/scwiki/spin-fluctuation-pairing), [superconducting gap](/scwiki/superconducting-gap) and [charge fluctuations](/scwiki/charge-fluctuation-pairing).
