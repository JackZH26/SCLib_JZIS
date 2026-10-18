## Scope

A Chern number characterizes a smooth, isolated family of quantum subspaces over a closed two-dimensional parameter surface. In a periodic crystal that surface can be the Brillouin-zone torus. The normal-state occupied-electron subspace and the negative-energy Bogoliubov–de Gennes (BdG) subspace are different constructions: calculate and label them separately. Local Berry curvature, an integer band invariant and an observed transport coefficient should not be used interchangeably. [R1](#ref-source-5052964ec3dcf748) [R4](#ref-source-a33c639b7db4f05a) [R5](#ref-source-688ad98fc33198c0)

The TKNN work connects a gap in a two-dimensional electron problem to quantized Hall conductance. Haldane's later lattice model shows that Landau levels are not required for a nonzero quantized Hall response. These are foundational model results, not evidence that a normal-state Chern band necessarily becomes a topological superconductor. Here their original publisher abstracts establish this historical context; complete original-paper audits remain open. [R1](#ref-source-5052964ec3dcf748) [R2](#ref-source-9b742057f40ad284)

## Mathematical assumptions

Use the convention of the [Berry-curvature article](/scwiki/berry-curvature): $\mathcal A_i=i\Psi^\dagger\partial_i\Psi$ for an orthonormal frame of the selected subspace, $\mathcal F_{xy}=\partial_x\mathcal A_y-\partial_y\mathcal A_x-i[\mathcal A_x,\mathcal A_y]$, and $C=(2\pi)^{-1}\int_{\rm BZ}\mathrm{Tr}\,\mathcal F_{xy}\,d^2k$. The subspace must remain separated from its complement throughout the Brillouin zone. Degeneracies inside the selected multiplet do not invalidate its total invariant, but arbitrary individual-band assignments at those degeneracies can fail. [R5](#ref-source-688ad98fc33198c0)

A nonzero invariant obstructs a single globally smooth periodic frame. One uses compatible local frames or a gauge-invariant discrete construction. For a continuous deformation that preserves the subspace gap and the closed integration surface, the integer cannot change. This is a statement about the quantum-state bundle, not an identification of momentum-space Berry curvature with the Gaussian curvature of a physical surface. [R5](#ref-source-688ad98fc33198c0)

For the clean, zero-temperature filled-electron-band response, with electron charge $-e$, $e>0$, positive $(k_x,k_y)$ orientation and $j_x=\sigma_{xy}E_y$, the convention used here gives $\sigma_{xy}=-Ce^2/h$. This sign follows the anomalous velocity and charge current used in F2; reversing orientation or the curvature definition changes the displayed relation. A partially occupied metallic band need not give an integer Hall response even when its complete band has an integer Chern number. Do not apply this electron charge-transport formula to a BdG integer without deriving the appropriate physical response. [R1](#ref-source-5052964ec3dcf748) [R4](#ref-source-a33c639b7db4f05a) [R6](#ref-source-113ed6da444bd207) [R7](#ref-source-381ad96944c0fa47)

For a bounded numerical example, take $H=\sin k_x\,\sigma_x+\sin k_y\,\sigma_y+(m+\cos k_x+\cos k_y)\sigma_z$, with dimensionless momenta and a fixed energy unit. The lower-band curvature is $\Omega_{xy}=\mathbf d\cdot(\partial_x\mathbf d\times\partial_y\mathbf d)/(2|\mathbf d|^3)$ in our convention. Analytic gap zeros occur only at $m=-2,0,2$. The lower-band values at $m=-3,-1,1,3$ are respectively $0,1,-1,0$. These are illustrative Hamiltonian results, not measured material properties. [R5](#ref-source-688ad98fc33198c0) [R6](#ref-source-113ed6da444bd207)

We compare normalized-overlap lattice sums on $12^2$, $24^2$ and $48^2$ meshes against an independently integrated analytic curvature on $64^2$ and $128^2$ meshes. Pointwise phase changes leave the result unchanged; reversing one momentum direction reverses its sign. We also reject the analytically identified gap-closing points. A positive gap sampled on a finite grid alone would not exclude an unsampled closing in a general Hamiltonian. [R5](#ref-source-688ad98fc33198c0)

## Experimental criteria

For a normal-state Hall interpretation, identify the carrier subspace, occupation, bulk gap and response convention. Hatsugai's original work relates the bulk TKNN integer to edge-state winding for a square-lattice quantum Hall model. The measured presence of an edge signal is not by itself a complete reconstruction of that model's invariant; boundary conditions, additional states and the probe must be addressed. The full edge-state proof is not reproduced here. [R1](#ref-source-5052964ec3dcf748) [R3](#ref-source-98d514f68fd6edc2)

For superconductivity, specify the Nambu basis, negative-energy projector and a bulk quasiparticle gap. Read and Green distinguish weak and strong pairing in a spinless continuum chiral p-wave model: positive and negative chemical potential give distinct phases, separated at zero chemical potential under their assumptions. Their weak-pairing phase is connected to weak coupling, but the two phrases are not synonymous. Their selected edge calculation uses a prescribed gap function and a domain wall between the phases to obtain a chiral Majorana branch; it does not solve a material-specific self-consistent edge. [R4](#ref-source-a33c639b7db4f05a)

A time-reversal-breaking signal does not establish a full quasiparticle gap or a nonzero BdG Chern number. A zero-bias feature likewise does not supply the negative-energy projector or identify a chiral boundary mode. Charge Hall response is especially delicate: Read and Green explicitly discuss collective response and the order of limits, rather than equating it to the paired-state topological integer. No sample-specific transition-temperature records are assigned to this theoretical article. [R4](#ref-source-a33c639b7db4f05a)

## Limits and disputes

In the Fukui–Hatsugai–Suzuki method, normalized overlaps define links and a principal-branch logarithm defines plaquette flux. Overlaps must not vanish. The finite-grid integer is gauge invariant, but agreement with the continuum requires adequate resolution and an isolated subspace. The multiplet version uses the determinant of the overlap matrix. In our $+i$ connection convention, the curvature flux is minus the oriented overlap-product phase; translate the original paper's imaginary-connection convention explicitly. [R5](#ref-source-688ad98fc33198c0)

Selected author pages and a visual check of the discrete equations support this account. Full final-version comparisons, the TKNN and Hatsugai derivations, interacting/disordered invariants, edge-spectrum computations and material data remain outside the completed checks. Complete scientific acceptance has not been reached. A lattice-model regression is neither an experimental replication nor proof that every proposed topological superconductor is correctly classified. [R1](#ref-source-5052964ec3dcf748) [R3](#ref-source-98d514f68fd6edc2) [R4](#ref-source-a33c639b7db4f05a) [R5](#ref-source-688ad98fc33198c0)

## Discovery implications

A useful report names the Hamiltonian, selected projector, orientation, gap criterion, mesh sequence and independent checks before giving an integer. For superconducting candidates, repeat the analysis for the actual pairing structure and compare appropriate boundary or response predictions with measurements. Preserve the distinction between a promising normal band, a model BdG phase and an established property of a specimen. [R4](#ref-source-a33c639b7db4f05a) [R5](#ref-source-688ad98fc33198c0)

## Related topics

Compare [Berry curvature](/scwiki/berry-curvature), [quantum metric](/scwiki/quantum-metric), [chiral pairing](/scwiki/chiral-pairing) and [topological superconductivity](/scwiki/topological-superconductivity).
