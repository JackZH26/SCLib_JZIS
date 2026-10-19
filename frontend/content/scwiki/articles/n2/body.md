## Scope

A shared mathematical language is available, but it is not yet a demonstrated, quantitatively predictive microscopic explanation of every unconventional superconductor in the sources reviewed here. Three goals should be distinguished: classifying order parameters, identifying a common dominant interaction, and predicting material-specific observables from independently constrained inputs. Success at one level does not establish the others. Scalapino's spin-fluctuation framework is an influential proposed connection across several families, not a proof that every family has an identical mechanism. [R1](#ref-source-eaa3beeed4368f46) [R2](#ref-source-1fe5a46dbbba61a4) [R10](#ref-source-51a15c56a9ac1472)

This question asks what would count as unification and what current examples actually test. It does not assume that cuprates, iron compounds, heavy-fermion materials and every newer platform must reduce to the same minimal Hamiltonian. Conversely, different gap symmetries do not by themselves require unrelated interactions: the same bilayer model can favor different pairing channels when its electronic structure changes. [R1](#ref-source-eaa3beeed4368f46) [R2](#ref-source-1fe5a46dbbba61a4)

## Mathematical assumptions

A schematic linearized singlet pairing equation is

$$
-\frac{T}{N}\sum_{K'}\Gamma^{pp}(K,K')G(K')G(-K')\phi(K')
=\lambda\phi(K).
$$

Here $K$ combines momentum and fermionic Matsubara frequency, $G$ is the normal-state dressed propagator, and $\Gamma^{pp}$ is the irreducible particle–particle vertex in a consistent normalization. Units use $k_B=1$; $N$ denotes the momentum-mesh normalization. Within the specified approximation, a leading eigenvalue reaching one signals a pairing instability. The eigenfunction describes a pairing structure, whereas the vertex and propagators encode more of the microscopic physics. Writing this equation does not solve for those inputs or establish the actual phase-ordering temperature. [R1](#ref-source-eaa3beeed4368f46) [R2](#ref-source-1fe5a46dbbba61a4)

An original two-channel example illustrates the inverse problem. For orthonormal real vectors $v,w$, define the dimensionless kernel

$$
\mathcal K_\mu=0.6\,vv^{\mathsf T}+\mu\,ww^{\mathsf T},\qquad -1\leq\mu\leq0.5.
$$

Every member has the same leading eigenvector $v$ and eigenvalue 0.6, yet its response to a source in the $w$ direction is $(I-\mathcal K_\mu)^{-1}w=w/(1-\mu)$. That response varies from 0.5 to 2 in the stated normalization. Seventy-two independently diagonalized examples verify the construction. The lesson is limited: a leading gap pattern alone need not uniquely identify a kernel. These matrices are not assigned to real materials or claimed to be realizable by distinct microscopic mechanisms; no transition temperature is inferred. [R1](#ref-source-eaa3beeed4368f46)

## A shared interaction can give different gaps

Maier and Scalapino studied a bilayer Hubbard model with $U/t=6$, filling 0.95 and a $2\times4\times4$ dynamic-cluster approximation. Increasing interlayer hopping changes the leading response from $d_{x^2-y^2}$ to sign-changing $s$ pairing. Their selected author text connects this change to intra- versus interlayer spin fluctuations. This is a concrete model example of related interactions producing different gap structures, not a material-by-material demonstration of one universal mechanism. [R2](#ref-source-1fe5a46dbbba61a4)

The same paper explicitly lacks the finite-size scaling needed to determine a thermodynamic transition temperature. Its quoted temperature estimates come from a cluster susceptibility divergence. Moreover, a larger pairing-interaction measure does not alone give the largest estimated transition: quasiparticle renormalization also changes. A unification claim must therefore compare both the interaction and the electronic response, not simply rank the strength of a proposed fluctuation. [R2](#ref-source-1fe5a46dbbba61a4)

## Model results depend on the question asked

Qin and colleagues' 2020 study concerns nearest-neighbor hopping only, moderate-to-strong interactions around $U/t=6$–8, and hole doping approximately 0.1–0.2. Its nonsuperconducting conclusion is restricted to that regime; the paper explicitly does not rule out superconductivity everywhere in the Hubbard model. Constrained-path auxiliary-field Monte Carlo introduces a trial-state-dependent systematic error, checked against narrow-cylinder DMRG. The comparison is valuable but does not turn the approximation into an exact solution of all sizes. [R3](#ref-source-74cc3f39d62d38b0)

Xu and colleagues instead include next-neighbor hopping, using $U/t=8$ and $t'/t=-0.2$ on the hole-doped side; a particle–hole mapping gives the positive-sign comparison for electron doping. The checked author manuscript combines twist averaging with a thermodynamic extrapolation followed by removal of the applied pairing field. It reports ground-state pairing coexisting with partially filled stripes and explicitly states that it has not predicted transition temperatures. A dome in a zero-temperature order parameter is not a calculated or measured $T_c$ dome. These studies ask different parameter-dependent questions, so their headlines should not be treated as direct contradictions. [R4](#ref-source-e7b3ac50f76789ac)

## Recent numerical evidence and its limits

Gu and colleagues' June 2026 neural-state paper reports stripe configurations and variational-energy improvements for specified Hubbard systems. Its final accuracy discussion says that $d$-wave correlations strengthen as the calculation improves and that further controlled calculations are needed for superconductivity conclusions. It should not be cited as a definitive absence-of-superconductivity proof. Periodic boundaries remove open edges, but they do not eliminate finite-size or variational errors. [R5](#ref-source-b417dbe2d449c0bb)

An August 2026 preprint by Rende and colleagues uses a translationally symmetric variational ansatz at $U/t=8$, $t'/t=-0.2$ and one-eighth hole doping. It reports long-distance pairing correlations and a finite extrapolated order parameter. Its discussion leaves thermodynamic coexistence with long-range stripe order unresolved. This is a dated preprint result with explicit ansatz and scaling assumptions, not an exact solution or a universal theory. Uniform one-body density in a symmetric state also does not preclude stripe signatures in correlation functions. [R6](#ref-source-095247a10e506437)

## Experimental criteria

Phase-sensitive observations constrain the order parameter, while identifying the dominant microscopic pairing interaction requires additional evidence. The original tricrystal-ring work provides a symmetry test in YBa₂Cu₃O₇−δ; that observation alone does not uniquely invert the pairing vertex. A stronger mechanism test compares momentum, frequency, orbital and temperature dependence across independent probes, together with changes induced by a controlled tuning parameter. Agreement should include observations not used to fit the proposed explanation. [R1](#ref-source-eaa3beeed4368f46) [R9](#ref-source-2e4d7fdb6c1797b7)

Several interactions can cooperate or compete. The checked nematic-fluctuation theory predicts enhancement under specified weak-coupling assumptions, rather than a universal pairing symmetry. The FeSe/SrTiO₃ interfacial-mode study considers enhancement on top of a magnetic pairing baseline. Those examples caution against treating magnetic, charge, orbital and lattice effects as mutually exclusive labels. Their presence or proximity in a phase diagram is not by itself a causal measurement of their contribution to pairing. [R7](#ref-source-24dd77640a555a0f) [R8](#ref-source-f9fe6e9bc3792dcc)

## Limits and disputes

A convincing unification should state its range of materials, independently constrained Hamiltonian, treatment of correlations and competing orders, and measurable predictions with errors. Cross-method agreement at one parameter point supports that point, not every lattice or composition. Numerical energy accuracy also does not automatically guarantee accurate long-distance response. The cited Hubbard studies are examples for evaluating this logic; they are not an exhaustive survey or a final settlement of all model phase diagrams. [R3](#ref-source-74cc3f39d62d38b0) [R4](#ref-source-e7b3ac50f76789ac) [R5](#ref-source-b417dbe2d449c0bb) [R10](#ref-source-51a15c56a9ac1472)

## Discovery implications

Compare proposed mechanisms through discriminating predictions: which changes in structure, filling, pressure or disorder alter the gap, collective response and competing phases together? Preserve failures and alternative explanations, and distinguish a broadly useful organizing principle from a quantitatively validated material theory. This research program can guide discovery even while a universal microscopic account remains unestablished within the reviewed evidence. [R1](#ref-source-eaa3beeed4368f46) [R7](#ref-source-24dd77640a555a0f) [R10](#ref-source-51a15c56a9ac1472)

## Related topics

Continue with [spin-fluctuation pairing](/scwiki/spin-fluctuation-pairing), [nematic fluctuations](/scwiki/nematic-fluctuation-pairing), [cuprates](/scwiki/cuprates), [iron-based superconductors](/scwiki/iron-based-superconductors), and [theoretical tools](/scwiki/theoretical-tools).
