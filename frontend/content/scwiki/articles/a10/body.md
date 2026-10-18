## Scope

Quasiparticle interference (QPI) uses spatial variations in scanning tunneling conductance to constrain electronic states and scattering. Elastic scattering can connect states of equal energy with momentum transfer $\mathbf q=\mathbf k'-\mathbf k$. A Fourier peak is a feature of a measured response, not a direct photograph of a Fermi surface or a uniquely identified order parameter. Keep the tunneling matrix element, defect channel and preprocessing attached to every interpretation.

In a weak-tunneling description with a sufficiently smooth tip spectrum and matrix element, low-temperature differential conductance can approximate a sample's local density of states. Thermal and instrumental convolution, spatially varying set points and orbital sensitivity can change that relation. A conductance map and an ideal local-density-of-states calculation should not be treated as interchangeable without testing these assumptions.

## Mathematical assumptions

With the convention $\tilde g(\mathbf q,E)=\sum_{\mathbf r}e^{-i\mathbf q\cdot\mathbf r}g(\mathbf r,E)$, a translated pattern obeys

$$g'(\mathbf r,E)=g(\mathbf r-\mathbf r_0,E),\qquad\tilde g'=e^{-i\mathbf q\cdot\mathbf r_0}\tilde g.$$

Its Fourier magnitude is unchanged, while its real and imaginary parts generally change. A real map satisfies $\tilde g(-\mathbf q)=\tilde g(\mathbf q)^*$. Independent discrete-transform checks verify both identities, an exactly sampled cosine and sampling aliases. Finite cropping can also change amplitudes; the exact translation identity assumes the whole pattern or periodic data, not two differently cropped fields.

For a periodic lattice with $N$ sites and one static, local defect at the origin, define an ideal electron-block response

$$\Lambda(\mathbf q,E)=\frac{1}{N}\sum_{\mathbf k}[G_0(\mathbf k,E)\,T(E)\,G_0(\mathbf k-\mathbf q,E)]_{11}.$$

Here $G_0$ is a retarded Nambu Green function and $T=[1-Vg_0]^{-1}V$, with $g_0=N^{-1}\sum_{\mathbf k}G_0$. The Fourier transform of the spin-resolved electron density-of-states change is

$$\delta\tilde\rho(\mathbf q,E)=-\frac{\Lambda(\mathbf q,E)-\Lambda(-\mathbf q,E)^*}{2\pi i}.$$

Taking just $-\operatorname{Im}\Lambda(\mathbf q)/\pi$ is insufficient for a general complex Fourier map. It becomes valid with the additional even-in-momentum response condition. Six independent checks compare full real-space resolvent inversion with the scattering expression on a ten-site, fixed-gap model; displaced defects expose the lost phase. This is a normalization and response check, not a cuprate or FeSe simulation. The selected Wang–Lee manuscript supplies the broader scattering framework and explicitly discusses off-shell and matrix-element limits. Its Eq. (1) includes both Nambu diagonal blocks; the expression here uses an explicitly spin-resolved electron block and a discrete lattice normalization. These local conventions and their checks are not a verbatim reproduction of the full source formula. [R2](#ref-source-6e0b3a25ead07f3c)

A joint-density-of-states construction counts candidate equal-energy connections but omits scattering amplitudes and coherence factors. In an ideal equal-magnitude, real-gap Fermi-surface limit, scalar and magnetic Born amplitudes contain $uu'-vv'$ and $uu'+vv'$. Setting $u=u'=1/\sqrt2$ and $v=\operatorname{sgn}(\Delta)/\sqrt2$ interchanges their zero/nonzero weights when the relative gap sign changes. This conditional example explains sensitivity to the impurity channel; it does not identify a real defect from one bright peak. [R2](#ref-source-6e0b3a25ead07f3c)

## Experimental criteria

Hoffman and colleagues' dispersing-QPI manuscript reports Bi2212 conductance imaging at 4.2 K. Selected pages describe two peak families with opposite energy trends and doping-dependent dispersion, interpreted against photoemission information. Its Science DOI ends in **1072640**. The inherited DOI ending in **1066974** instead identifies their distinct vortex-core modulation paper; these are not interchangeable evidence. [R1](#ref-source-e8e6ef56da103435) [R5](#ref-source-353efd52d3443260)

Sprau and colleagues' FeSe manuscript reports imaging at 280 mK. The relative-sign analysis uses the real parts at opposite energies, isolates an interband momentum region and places the Fourier origin at a defect. Selected supplementary passages vary the integration area and repeat the analysis on additional impurities. The reported sign inference is conditional on their scattering model and band assignment; it is not an inference from the absolute Fourier intensity alone. [R4](#ref-source-2f227038c5cf73a9)

Report field of view, pixel spacing, spatial drift correction, bias grid, temperature, excitation amplitude, tip condition, set-point protocol and defect selection. Preserve both raw and processed maps. State whether a displayed quantity is a complex transform, its real part, magnitude, power or a ratio: these operations retain different information. Explain normalization, windowing, background removal, symmetrization and peak uncertainties.

## Limits and disputes

For $N_x$ equally spaced pixels of spacing $a_x$, the periodic-transform length is $L_x=N_xa_x$ and angular-wavevector bin spacing is $2\pi/L_x$; the Nyquist bound is $\pi/a_x$. Using cycles per length removes the $2\pi$ factors. Zero padding interpolates the transform but does not create a larger measured field. A window trades spectral leakage against peak width, so bin spacing alone is not an experimental uncertainty or guaranteed resolving power.

Energy dispersion supports a scattering interpretation only together with band, defect and temperature/field controls. Weak dispersion over a limited window does not by itself prove charge order; Bragg, structural, moire and electronic features can overlap. Conversely, an order and QPI may coexist. The cuprate octet geometry must not be imposed on arbitrary multiband spectra.

The McElroy reference in the pinned chapter used an unrelated biology DOI, **nature02269**. The correct QPI paper is **nature01496**; its publisher identity is checked here, while its detailed data remain outside this entry's review. The original source is preserved and the replacement recorded. [R3](#ref-source-230ea3ac9496dc90)

## Discovery implications

Use QPI to compare explicit candidate electronic and scattering models against multiple observables. A useful claim states which alternatives the data discriminate, which are still compatible, and how uncertainty in defect identity or preprocessing changes the result. Combine gap-magnitude constraints with independent bulk and phase-sensitive evidence before assigning a pairing state or mechanism.

## Related topics

Continue with [superconducting gaps](/scwiki/superconducting-gap), [Andreev reflection](/scwiki/andreev-reflection), [cuprates](/scwiki/cuprates), [iron-based superconductors](/scwiki/iron-based-superconductors), [multiband pairing](/scwiki/multiband-pairing), and [s± pairing](/scwiki/s-plus-minus).
