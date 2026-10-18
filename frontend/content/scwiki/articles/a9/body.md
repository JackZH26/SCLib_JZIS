## Scope

Andreev reflection converts an electron-like excitation in a normal conductor into a reflected hole-like excitation at a superconducting interface. In the conventional subgap process, charge of magnitude $2e$ enters the condensate. Andreev's original calculation treats a slowly varying excitation near the Fermi surface; the selected scan shows subgap evanescence and reversal of velocity. Retroreflection is an approximation with a specified band and energy regime, not a universal trajectory rule. [R1](#ref-source-18bd294c2b4c06a7)

This is an interface probe. Conductance depends on the contact as well as the superconducting state, so a fitted gap scale or an enhanced subgap signal is not automatically a measurement of bulk pairing symmetry. Keep interface scattering, normal-state background and sample conditions attached to an interpretation.

## Mathematical assumptions

For one incident channel, let $A(E)$ and $B(E)$ be Andreev and normal reflection probabilities with consistent flux normalization. The charge-conductance weight is $1+A-B$. Under purely subgap reflection, probability conservation gives $A+B=1$, hence the weight is $2A$. A factor of two in this ideal charge conversion does not imply that every measured junction has twice its normal-state conductance.

The original BTK abstract describes a tunable interface barrier. To check an explicit limit independently, take a spin-degenerate, single-channel, time-reversal-symmetric normal barrier of transmission $\mathcal T$, separated from an ideal conventional s-wave Andreev reflector. At zero energy the round-trip Andreev phase is $-1$, giving

$$A(0)=\left(\frac{\mathcal T}{2-\mathcal T}\right)^2,\qquad \frac{G_{NS}}{G_N}=\frac{2\mathcal T}{(2-\mathcal T)^2}.$$

For a one-dimensional delta barrier with matched velocities, define $Z$ so that $\mathcal T=1/(1+Z^2)$. Summing coherent electron–hole round trips gives $A(0)=1/(1+2Z^2)^2$. The transparent limit has conductance ratio two; the tunnel limit is suppressed. Independent complex-amplitude sums check twelve barrier/energy cases. This is an ideal scattering check, not a reanalysis of BTK's full finite-bias treatment. [R2](#ref-source-bcd31ef90f21ff0a)

Beenakker's later lectures give, at zero temperature, bias and magnetic field, $G_{NS}=(4e^2/h)\sum_n\mathcal T_n^2/(2-\mathcal T_n)^2$ and $G_N=(2e^2/h)\sum_n\mathcal T_n$. These are two-terminal formulas for the stated coherent NS model, with normal scattering separated from the ideal superconducting boundary. The original 1992 paper is retained separately at abstract scope. [R5](#ref-source-02f3aac52d07be56) [R3](#ref-source-8165cabd8e37fbe8)

Equal normal conductance does not determine the superconducting conductance. For example, transmission sets $(1,0)$ and $(1/2,1/2)$ have the same sum but different sums of $\mathcal T_n^2/(2-\mathcal T_n)^2$. This independent counterexample explains why a contact resistance alone cannot specify a multichannel junction.

For an elastic spectrum $g_0(E)$ whose temperature dependence is held fixed, thermal smearing is a convolution with the Fermi derivative:

$$G(V,T)=\int dE\,g_0(E)\frac{\operatorname{sech}^2[(E-eV)/(2k_BT)]}{4k_BT}.$$

The kernel integrates to one and preserves a constant conductance. Three numerical checks compare the convolution to the derivative of its corresponding current integral. The check uses a synthetic smooth spectrum, not a BTK fit. A temperature-dependent gap, bias-dependent barrier, nonequilibrium distribution or heating requires additional modeling; arbitrary lifetime broadening is not equivalent to thermal convolution.

## Experimental criteria

Blonder and Tinkham's 1983 experimental abstract reports Cu-Nb point contacts spanning metallic to tunneling behavior and agreement with the model over a range of contact resistances. This entry checks that qualitative observation only. Contact dimensions, individual spectra and parameter uncertainties remain unverified here; no transition temperature is extracted. [R6](#ref-source-851c482722643e96)

Report contact preparation, normal-state resistance, wiring, crystal direction, current or excitation amplitude, field and temperature. Compare contact dimensions with mean free path and coherence length before choosing a ballistic or diffusive description. Repeat contacts and test heating and critical-current artifacts. Preserve the background normalization and its uncertainty; these are editorial requirements for assessing a claim, not one universally valid apparatus recipe.

A constant series resistance $R_s$ gives $G_{\mathrm{meas}}=G_{\mathrm{int}}/(1+R_sG_{\mathrm{int}})$ when the internal response is differentiated consistently. Ignoring it can change an apparent enhancement or fitted transparency. This circuit identity assumes the series element is bias independent; it does not describe thermal feedback or nonlinear leads.

## Limits and disputes

Asano, Tanaka and Kashiwaya's theoretical abstract associates a sign-changing pair potential with zero-energy surface states and a zero-bias conductance peak. This is a model result about a surface, not a new experimental proof of bulk symmetry. The broad Kashiwaya–Tanaka review is retained as a bibliographic pointer; its detailed calculations have not been checked here. [R7](#ref-source-cbbdb7f1a746a8f4) [R4](#ref-source-eb20b5a729cf98da)

A peak alone does not establish a Majorana mode, spin-triplet pairing or a unique mechanism. Model comparison should address ordinary bound states and junction effects, and test the predicted orientation, field, temperature and spatial dependence. Surface roughness and mixed trajectories can change the inference. A phase-sensitive experiment and a local conductance spectrum answer different questions.

## Discovery implications

Use interface spectroscopy to constrain candidate gap and scattering models, then seek independent bulk and phase-sensitive evidence. Report competing parameter sets and failed alternatives alongside a best fit. A good fit can support consistency with a model while leaving parameter uniqueness and microscopic causation unresolved. Preserve that distinction in both prose and machine-readable records.

## Related topics

Compare [gap probes](/scwiki/superconducting-gap), [zero resistance](/scwiki/zero-resistance), [BCS theory](/scwiki/bcs-weak-coupling), [multiband pairing](/scwiki/multiband-pairing), and [s± pairing](/scwiki/s-plus-minus).
