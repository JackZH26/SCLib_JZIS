## Scope

Material-specific first-principles calculations have made substantial progress, but the reviewed studies do not establish a generally reliable, uncertainty-calibrated prediction of $T_c$ across strongly correlated superconductors. A useful answer must identify the predicted observable: a pairing tendency, zero-temperature order, excitation gap, mean-field instability, or thermodynamic transition. These are different targets. Predicting a trend can be valuable without already predicting an absolute transition temperature. [R4](#ref-source-51a15c56a9ac1472) [R5](#ref-source-12f2513b257d7194) [R7](#ref-source-a57ef549f45fe74c)

Here, **ab initio** concerns how the Hamiltonian and interactions are constructed; it does not remove approximations from their solution. A calculation should disclose fitted inputs, the correlated orbital space, screened interactions, treatment of double counting, solver limitations and convergence. A declared absence of material-by-material fitting is distinct from a proof that the chosen functional or embedding is exact. [R5](#ref-source-12f2513b257d7194) [R6](#ref-source-2b331df83384bc5c)

## What conventional calculations demonstrate

Sanna, Pellegrini and Gross developed a superconducting density-functional approximation informed by an Einstein-phonon Eliashberg reference system. Their final paper compares transition temperatures and gaps with measurements for selected conventional superconductors. The calculation uses phonons from density-functional perturbation theory and static-RPA Coulomb screening. Its constants are calibrated to the reference model, rather than fitted separately to each compound. This is a concrete computational achievement within stated approximations, not a universal benchmark for strongly correlated pairing. [R1](#ref-source-f9aa25c4ae4f8b5d)

The same paper distinguishes the auxiliary Kohn–Sham pairing potential from a physical excitation gap. Agreement of an approximate gap equation with a reference calculation must therefore be tied to the quantity actually compared. A plotted auxiliary gap should not silently become an experimental gap or a measured $T_c$ in a database. [R1](#ref-source-f9aa25c4ae4f8b5d)

## Two cuprate advances and their boundaries

Cui and colleagues calculate ground-state pairing using ab initio density-matrix embedding, with a finite $2\times2$ impurity and primarily a coupled-cluster solver. They recover selected pressure and layer trends. Phonons and temperature effects are omitted; the reported auxiliary bulk gap is not the interacting bulk excitation gap. Their conversion to a temperature invokes a weak-coupling relationship whose applicability is explicitly qualified. Incomplete charge self-consistency, implicit doping and omitted long-wavelength orders remain limitations. This work supports progress in material-specific pairing calculations, rather than an independently established finite-temperature prediction protocol. [R2](#ref-source-809aa49ee911889b)

Bacq-Labreuil and colleagues combine charge-self-consistent DFT with cluster DMFT. Their selected author manuscript uses zero-temperature exact diagonalization with a discrete bath; a fictitious temperature sets a Matsubara mesh. Superconductivity is then evaluated in a post-processing step with other orbitals frozen in their normal state. The authors explicitly distinguish zero-temperature order from $T_c$ and leave calculation of the actual transition, including phase fluctuations, for further work. Thus the mesh temperature is not a computed transition. The local solver's name also does not make the finite-bath embedding exact for the entire material. [R3](#ref-source-0fac414ae312f585)

## Mathematical assumptions

For a noninteracting block Hamiltonian, eliminating auxiliary orbitals gives the exact retained-orbital Green's function

$$
G_{dd}(z)=\left[z-\epsilon_d-V^\dagger(z-H_p)^{-1}V\right]^{-1}.
$$

Here $z$ is complex energy, $\epsilon_d$ a scalar energy, $H_p$ a Hermitian auxiliary block and $V$ a coupling column. The term $V^\dagger(z-H_p)^{-1}V$ retains frequency dependence. This algebraic identity explains one reason a static reduced Hamiltonian needs justification; it is not a derivation of an interacting pairing vertex. Choices of orbital space and retained energy window matter when constructing practical effective descriptions. [R6](#ref-source-2b331df83384bc5c)

An original three-orbital illustration compares direct matrix inversion with this elimination for 60 parameter/frequency choices. They agree to numerical precision. Replacing the eliminated term by its zero-frequency value changes the selected Green's functions, with a largest relative difference of about 46% in this deliberately chosen set. That percentage is an illustrative error, not an error bar for either cuprate paper. All energies use arbitrary common units; no material, interaction or superconducting transition is simulated.

Even a correctly computed magnetic scale is not itself $T_c$. In a half-filled, one-orbital, two-site repulsive Hubbard example, the singlet–triplet separation is

$$
J_{\rm dimer}=\frac{\sqrt{U^2+16t^2}-U}{2}
=\frac{4t^2}{U}+O(t^4/U^3),\qquad U\gg |t|.
$$

The previously checked finite-dimer calculation gives about 21% and 6% overestimation by the leading term at $U/t=4$ and $8$, respectively. Neither the exact finite-system splitting nor its asymptotic approximation establishes superconductivity. The example illustrates why a descriptor, its approximation and a bulk ordering temperature require separate validation. [R8](#ref-source-2f6a1c773323226a)

## Experimental criteria

A useful validation chain connects specified crystal structure and composition to electronic inputs, an adequately controlled many-body calculation and the intended experimental observable. Report convergence with orbital basis, cluster size, bath discretization or sampling where applicable; separate numerical convergence from errors in the physical model. Cross-method agreement on a matched Hamiltonian is evidence about that Hamiltonian, not automatic validation of its correspondence to a compound. [R4](#ref-source-51a15c56a9ac1472) [R5](#ref-source-12f2513b257d7194) [R6](#ref-source-2b331df83384bc5c)

The temperature question adds another layer. A nonzero pairing amplitude or a mean-field instability can occur without the phase coherence required for a thermodynamic superconducting transition. Dimensionality, superfluid stiffness and long-distance fluctuations must be addressed in the applicable regime. A two-dimensional phase-stiffness bound is neither a three-dimensional universal formula nor a procedure that turns any calculated gap into $T_c$. [R7](#ref-source-a57ef549f45fe74c)

## Limits and disputes

This selected review does not rank every available method, exclude successful calculations in particular correlated families, or independently reproduce the quoted ab initio studies. Final-version comparison of the cluster-DMFT author manuscript, complete supplements and broad material benchmarks remain open. The underlying methodological question is quantitative: how much do plausible changes in input structure, screening, correlated subspace and solver treatment move the predicted observable? A single successful comparison cannot answer this for an entire material class. [R4](#ref-source-51a15c56a9ac1472) [R5](#ref-source-12f2513b257d7194) [R6](#ref-source-2b331df83384bc5c)

## Discovery implications

Use calculations to generate testable candidates with an explicit evidence level. Store the structure, conditions, method and predicted quantity together; compare against measurements on the corresponding sample and distinguish onset, bulk magnetic and zero-resistance criteria. Favor prospective checks on withheld materials and preserve failed predictions. This is a proposed validation standard: the aim is increasingly reliable material prediction, while retaining the difference between a promising pairing trend and a demonstrated transition temperature. [R4](#ref-source-51a15c56a9ac1472) [R7](#ref-source-a57ef549f45fe74c)

## Related topics

Continue with [theoretical tools](/scwiki/theoretical-tools), [cuprates](/scwiki/cuprates), [unifying pairing mechanisms](/scwiki/open-questions/n2), and [flat-band temperature bounds](/scwiki/open-questions/n10).
