## Scope

An isotropic, sign-preserving spin-singlet gap is the conventional s-wave reference. Three questions must nevertheless be separated: whether quasiparticles are fully gapped, how the order parameter transforms under crystal symmetry, and whether it changes sign between parts of the Fermi surface. A full gap answers the first question within the measurement's resolution; it does not settle the other two. [R1](#ref-source-ba10e800a1246bf6) [R3](#ref-source-fcdf63980c7fb4f9)

For a crystal with D4h (4/mmm) point-group symmetry, A1g denotes the fully symmetric even-parity representation. It permits a constant gap but also higher harmonics and accidental nodes. The centrosymmetric tetragonal group C4h (4/m) instead labels its fully symmetric representation Ag; use the actual crystal point group. In multiband systems, fully open gaps can have opposite signs on different sheets; see the separate s± entry. Identifying an s-wave state also does not, by itself, identify its microscopic pairing interaction. [R3](#ref-source-fcdf63980c7fb4f9) [R10](#ref-source-23fba654f3db5472) [R11](#ref-source-8279a9f7f0168d6e)

## Mathematical assumptions

The equilibrium, single-band, isotropic, constant-density-of-states weak-coupling BCS model gives $2\Delta(0)/(k_BT_c)\simeq3.528$ and $\Delta C/(\gamma T_c)\simeq1.426$, with $\gamma$ the normal electronic heat-capacity coefficient. These are limiting benchmarks, not mandatory ratios for every s-wave material. The existing independent gap and entropy checks establish these model limits; strong coupling, multiband structure and anisotropy require their own calculation. [R1](#ref-source-ba10e800a1246bf6)

To illustrate symmetry without fitting a material, take a circular Fermi surface centered at the tetragonal zone center and $\Delta(\phi)=\Psi f(\phi)$, where

$$f(\phi)=1+r\cos(4\phi).$$

Rotations by $\pi/2$, reflections and inversion leave this function unchanged. For $|r|<1$ it is positive everywhere; at $|r|=1$ four zeros touch the Fermi surface without sign reversal; for $|r|>1$ there are eight sign-changing nodes. Their presence changes with a parameter rather than being required by A1g symmetry. This global fourfold example is distinct from Mishra and colleagues' local twofold harmonic on a selected off-center pocket. [R3](#ref-source-fcdf63980c7fb4f9)

For clean weak-coupling separable pairing with uniform angular density-of-states weight, the illustrative heat-capacity jump is

$$\frac{\Delta C}{\gamma T_c}=\frac{12}{7\zeta(3)}\frac{\langle f^2\rangle^2}{\langle f^4\rangle},\qquad \langle f^2\rangle=1+\frac{r^2}{2},\quad \langle f^4\rangle=1+3r^2+\frac{3r^4}{8}.$$

Independent angular sums and a thermal-kernel quadrature verify five cases. At $r=0.6$ the gap remains nodeless, while the jump is about $0.933$ rather than $1.426$. This shows why applying the isotropic ratio as a symmetry test can fail. It is a clean separable-model result, not a disorder simulation or a measured sample value. The cited BCS paper provides the underlying mean-field context; the angular calculation is our independent illustration. [R1](#ref-source-ba10e800a1246bf6)

For a real symmetric normal Hamiltonian $h$ and an imposed uniform real gap, the block matrix $\mathcal H=\begin{pmatrix}h&\Delta I\\\Delta I&-h\end{pmatrix}$ has energies $\pm\sqrt{\epsilon_n^2+\Delta^2}$. Six small-matrix checks confirm this relation with different scalar site potentials. It does not prove an unchanged self-consistent $T_c$: the normal eigenvalues, density of states and pairing matrix elements can change. Anderson's argument pairs exact time-reversed states; it is not a blanket guarantee against all chemical disorder, localization or magnetic scattering. This spectral identity relies on the imposed gap being a scalar multiple of the identity. For a site-dependent real gap matrix $D$, the squared block Hamiltonian contains $hD-Dh$ in its off-diagonal block. Two explicit nonuniform-gap counterexamples verify a nonzero commutator and the failure of a naive pairing of normal-state eigenvalues with site gaps; they do not solve the gap equation. [R2](#ref-source-8d0e592da8ec9c7b)

## Experimental criteria

A magnitude-sensitive quasiparticle spectrum cannot generally determine an interband sign. Six independent-band, broadened-DOS comparisons give identical spectra after reversing one band's gap sign. This deliberately excludes interband scattering and coherent phase-sensitive tunneling. Measurements sensitive to phase or sign need their own geometry and matrix-element analysis. Low-temperature activation alone also cannot distinguish an isotropic gap from a smaller nonzero gap minimum. [R1](#ref-source-ba10e800a1246bf6) [R3](#ref-source-fcdf63980c7fb4f9)

Hebel and Slichter's aluminum experiment used field cycling: nuclear spins relaxed in the superconducting state but were read out in the normal state. Its 0.94–4.2 K interval is a measurement range, not a range of transition temperatures. Nuclear relaxation tests a response with coherence effects; observing or missing a peak alone does not measure relative signs between bands. Only the original abstract has been checked here. [R4](#ref-source-99644bb2badd2d56)

Nagamatsu and colleagues' MgB2 report separates a zero-field four-probe resistance onset at 39 K from its 38 K end point, alongside magnetic measurements at 10 Oe. [R5](#ref-source-fade6558e7eafb2b)

Choi and colleagues subsequently calculated distinct band-dependent gaps using anisotropic electron–phonon theory. The discovery experiment and the gap calculation answer different questions; neither justifies assigning one fixed gap value to every MgB2 sample. The corrected Choi DOI is nature00898. [R6](#ref-source-7c4eac077ae5e221)

For lanthanum superhydrides, Somayazulu's sample A had room-temperature pressures of 188 GPa before and 196 GPa after cycling; pressure at the resistance change was not directly measured. The published account distinguishes four-probe data from contact-sensitive pseudo-four-probe configurations and mixed phases. Drozdov's later study reports additional field and isotope evidence, defines $T_c$ by resistance onset, and states that magnetization of its small samples remained unresolved. Neither transport report is a phase-sensitive measurement of gap sign. [R8](#ref-source-77b774e18b0f50c7) [R9](#ref-source-1e6e868a12cdd34f)

## Limits and disputes

Mishra and colleagues show node lifting in a model with weak pointlike scatterers treated in the Born approximation. Their single-sheet calculation can suppress $T_c$ too strongly; additional bands change that balance, while interband scattering cannot generally be discarded. This supports a conditional explanation of activated behavior after disorder, not the rule that disorder always preserves or improves s-wave superconductivity. [R3](#ref-source-fcdf63980c7fb4f9)

The ideal isotope value $\alpha=-d\ln T_c/d\ln M=1/2$ assumes a harmonic phonon scale and otherwise mass-independent model parameters. Sulfur-hydride isotope observations support phonon involvement within their experimental context. For lanthanum hydrides, the published methods discuss different hydride/deuteride phase mixtures and zero-point/anharmonic stability effects. Matching pressure, phase and preparation is therefore essential before interpreting a mass derivative. [R1](#ref-source-ba10e800a1246bf6) [R7](#ref-source-8b901b9c6008c434) [R9](#ref-source-1e6e868a12cdd34f)

## Discovery implications

Combine thermodynamics, spectroscopy, magnetic response and controlled perturbations. Keep disorder-induced carrier or structural changes separate from elastic scattering, and distinguish small gaps from true nodes within a stated temperature window. Track superconducting evidence, symmetry, relative phase and pairing interaction as separate conclusions. Full scientific acceptance, complete final-version comparisons and raw-data review remain open. [R2](#ref-source-8d0e592da8ec9c7b) [R3](#ref-source-fcdf63980c7fb4f9) [R9](#ref-source-1e6e868a12cdd34f)

## Related topics

Read [BCS theory](/scwiki/bcs-weak-coupling), [Eliashberg theory](/scwiki/eliashberg-strong-coupling), [s± pairing](/scwiki/s-plus-minus), [multiband pairing](/scwiki/multiband-pairing), and [energy gaps](/scwiki/superconducting-gap).
