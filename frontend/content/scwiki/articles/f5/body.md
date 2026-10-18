## Scope

A Majorana operator is self-adjoint. A Majorana zero mode additionally represents a zero-energy degree of freedom of a specified Hamiltonian, localized at an end, boundary or defect in an appropriate setting. Decomposing an ordinary fermion into two self-adjoint operators is always possible; that algebra alone establishes neither spatial separation nor topological protection. Here the ideal chain, experimental readout and claims about fault-tolerant computation are treated separately. [R1](#ref-source-ade538b429fdd847)

Chiral two-dimensional pairing and one-dimensional superconducting chains provide distinct theoretical settings. Read and Green connect the weak-pairing spinless chiral state to non-Abelian quasiholes; its weak-pairing terminology is not a synonym for weak interaction strength. A proposed Hamiltonian or boundary solution does not establish the pairing state or topology of a measured solid. [R2](#ref-source-a33c639b7db4f05a)

## Mathematical assumptions

Fix the normalization $\{\gamma_i,\gamma_j\}=2\delta_{ij}$ and $\gamma_i^\dagger=\gamma_i$. Then $c=(\gamma_1+i\gamma_2)/2$, $n=c^\dagger c=(1+i\gamma_1\gamma_2)/2$ and the occupation parity is $P=(-1)^n=1-2n=-i\gamma_1\gamma_2$. Papers may normalize the operators or label parity signs differently. Mixing a factor $1/\sqrt2$ from another convention into these equations would spoil the fermionic anticommutator. [R1](#ref-source-ade538b429fdd847) [R6](#ref-source-a3c2dc153700478a)

For a uniform spinless chain, use hopping $t$, chemical potential $\mu$, real pairing $\Delta$, lattice spacing one and open ends. The bulk excitation spectrum satisfies $E(k)^2=(2t\cos k+\mu)^2+4\Delta^2\sin^2k$. The gapped topological domain is $|\mu|<2|t|$ with $\Delta\ne0$; $|\mu|=2|t|$ closes the gap. At $\mu=0$ and $t=\Delta>0$, the ideal finite chain has exactly unpaired endpoint operators. More general finite chains can have overlap splitting: exponential localization does not imply exactly zero energy at every length. [R1](#ref-source-ade538b429fdd847)

Our bounded calculation checks the Majorana algebra, compares eight small-chain many-body spectra with independently constructed BdG spectra, verifies exact endpoint commutators at the special point, and follows decreasing overlap splitting for one sequence of increasing chain lengths. These are model checks. They do not fit a device, establish a universal prefactor or exclude oscillatory splitting at other parameters. [R1](#ref-source-ade538b429fdd847)

The minimal two-site model makes a useful distinction explicit. With $\delta=(\mu_L+\mu_R)/2$ and $\epsilon=(\mu_L-\mu_R)/2$, its even and odd energies are $E_e^\pm=-\delta\pm\sqrt{\delta^2+\Delta^2}$ and $E_o^\pm=-\delta\pm\sqrt{\epsilon^2+t^2}$. At $t=\Delta$ and zero onsite energies the ground states coincide. Detuning one site leaves this ideal degeneracy intact, whereas common detuning gives a quadratic splitting and changing $t-\Delta$ gives a linear one. Direct four-state diagonalization checks these relations; they explain why a two-site sweet spot is not equivalent to generic long-chain protection. [R6](#ref-source-a3c2dc153700478a)

## Experimental criteria

In the ideal grounded-superconductor tunneling setup analyzed by Law, Lee and Ng, a Majorana resonance can produce conductance $2e^2/h$. Interpreting a measured peak requires the actual coupling, resolution, temperature and competing states. Pan and Das Sarma model trivial low-energy peaks from mechanisms including confinement and disorder, and discuss limitations of end-to-end correlations in short wires. Their theoretical alternatives are reasons to test a signal, not a diagnosis of every later experiment. [R3](#ref-source-1b46269f3dd05cd6) [R4](#ref-source-dca781066e96eecc)

Aghaee and colleagues, published on 19 February 2025, report interferometric single-shot fermion-parity readout. Their selected results include millisecond-scale parity dwell times and approximately 1% assignment error at an optimized measurement time. The paper explicitly states that the measurements do not uniquely distinguish topological Majorana modes from suitably tuned low-energy Andreev states. It also constrains the alternatives through support at both wire ends and weak coupling to other low-energy states. Preserve both the achieved readout and that unresolved interpretation. [R5](#ref-source-e3824a8727c3ec54)

Van Loo and colleagues, published online on 11 February 2026, read out the parity of a minimal InSb–Al quantum-dot chain through quantum capacitance. The selected author text reports lifetimes exceeding a millisecond and contrasts the readout with a local charge sensor unable to distinguish parity at the sweet spot. The authors explicitly describe limited protection in this two-site device. The accepted-author version was uploaded on 6 October 2026; that upload is not the experiment's publication date. [R6](#ref-source-a3c2dc153700478a)

Spectroscopy, parity lifetime, readout fidelity, robustness, fusion and exchange probe different properties. Report the measured observable and the alternatives addressed by that particular protocol. A parity readout result alone does not demonstrate a non-Abelian exchange operation or a fault-tolerant processor. There is no platform-independent checklist in which every local zero-bias feature automatically advances toward a universal confirmation threshold. [R4](#ref-source-dca781066e96eecc) [R5](#ref-source-e3824a8727c3ec54) [R6](#ref-source-a3c2dc153700478a)

A 10 July 2026 preprint by Zatelli and colleagues reports coherent parity oscillations in coupled minimal Kitaev chains. The authors distinguish partial protection at the sweet spot from the unprotected degeneracy-lifting operations used for rotation. No journal acceptance was verified here; this is not a demonstrated braid or a certified gate fidelity. [R9](#ref-source-818818441532a8ec)

## Limits and disputes

The 2018 article “Quantized Majorana conductance” was retracted on 8 March 2021. The authors' notice describes undisclosed charge-jump corrections, a mislabeled axis and recalibration shifting plateau values above the claimed quantized conductance. The withdrawn positive claim is retained only as a historical record with its retraction notice. It cannot validate a device, and its retraction does not itself settle every other Majorana proposal. [R7](#ref-source-6a7f18eec743e89d) [R8](#ref-source-f127bb2d99183698)

This review checks selected original chain and readout passages, two-site energy equations, the author-institution retraction text and bounded calculations. The transport alternatives remain at original-abstract scope here; full device datasets, supplementary analyses, final-version comparisons and platform-by-platform fusion or braiding audits remain open. Complete scientific acceptance has not been reached. Neither commercial terminology nor a manuscript upload date closes those gaps. [R1](#ref-source-ade538b429fdd847) [R4](#ref-source-dca781066e96eecc) [R5](#ref-source-e3824a8727c3ec54) [R6](#ref-source-a3c2dc153700478a) [R8](#ref-source-f127bb2d99183698)

## Discovery implications

Keep the operator convention, physical geometry, bulk-gap assumptions and measurement protocol attached to each claim. Search for a reproducible combination of localization, controlled perturbations and protocol-specific evidence, while reporting failed or ambiguous tests. Separate a useful quantum-device component from a verified topological phase and from a demonstrated computational operation. This article does not make a worldwide priority claim or certify a material family from a single resonance. [R1](#ref-source-ade538b429fdd847) [R4](#ref-source-dca781066e96eecc) [R5](#ref-source-e3824a8727c3ec54) [R6](#ref-source-a3c2dc153700478a)

## Related topics

Continue with [topological superconductivity](/scwiki/topological-superconductivity), [time-reversal-invariant topology](/scwiki/time-reversal-invariant-topological-superconductivity), [Chern number](/scwiki/chern-number), [chiral pairing](/scwiki/chiral-pairing) and [Andreev reflection](/scwiki/andreev-reflection).

For a dated comparison of spectroscopy, control and exchange criteria, see [the Majorana identification question](/scwiki/open-questions/n4).
