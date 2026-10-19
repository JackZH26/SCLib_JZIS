## Scope

Alkali-doped fullerides combine molecular vibrations, narrow electronic bands and strong local interactions. Ideal A₃C₆₀ has three donated electrons in a molecular t₁ᵤ manifold with six spin-orbital states: half-filling describes electron counting, not a guarantee of metallic transport or superconductivity. The same nominal Cs₃C₆₀ composition supports fcc and A15 packings with different magnetic and pressure-dependent superconducting behavior. Specify composition, structure, preparation and measurement conditions before comparing temperatures. Pressure-induced equilibrium superconductivity and optically driven responses are separate evidence classes. [R5](#ref-source-e2b9d469a7c556df) [R4](#ref-source-5e6d3e7ed715ad6a) [R7](#ref-source-07be806c0002c690)

Nominal composition is not a sample assay. Ganin's fcc-rich powder had refined composition Cs₂.₉₀₁₍₆₎C₆₀ and an fcc fraction of about 86%, with minority phases. Its ambient-pressure magnetic insulating behavior illustrates why three donated electrons alone cannot define the phase. These preparation and phase-fraction qualifications accompany the idealized A₃C₆₀ description. [R4](#ref-source-5e6d3e7ed715ad6a)

The 1991 potassium discovery already illustrates why one temperature is insufficient: the abstract reports a thin-film resistive onset near 16 K and essentially vanishing resistance by 5 K, while bulk magnetic and microwave measurements indicate an 18 K transition. The subsequent rubidium report gives a maximum of 28 K from bulk magnetic and microwave evidence. These abstract-level checks establish historical observations; they do not constitute a complete reassessment of the original specimens. [R1](#ref-source-51b1a52d16139e58) [R2](#ref-source-0fb5ae1290bd2998)

## Mathematical assumptions

One influential model represents each molecule by three effective p-like orbitals with local terms $H_U=U(n-3)^2/2$ and $H_J=J[2\mathbf S^2+\mathbf L^2/2]+5J(n-3)^2/6$. Angular momenta are dimensionless. In this convention ordinary Hund exchange has $J=-J_H<0$; integrating out Jahn–Teller vibrations can instead give $J=-J_H+J_{JT}>0$. This static reduction requires the coherent electronic scale $ZW$ to lie below the relevant phonon energy. It should not be applied across the whole bandwidth range without checking retardation. [R5](#ref-source-e2b9d469a7c556df)

At exactly three electrons, the model multiplets $^4S$, $^2D$ and $^2P$ have energies $15J/2$, $9J/2$ and $5J/2$, with respective degeneracies 4, 10 and 6. They account for $\binom{6}{3}=20$ local states. Positive effective $J$ favors the low-spin $^2P$ multiplet; negative $J$ favors $^4S$. This is an algebraic check of the effective local Hamiltonian, not a measured molecular spectrum or proof of superconducting order. [R5](#ref-source-e2b9d469a7c556df)

The heuristic Cooper-channel amplitude $A^*\simeq ZU-10J/3$ illustrates how correlations can reduce repulsion relative to an inverted exchange. For illustrative fixed ratios $U/W=0.5$ and $J/W=0.05$, its sign changes at $Z=1/3$. Simultaneously the coherent bandwidth is $ZW$: decreasing $Z$ does not supply an unlimited transition-temperature gain. The published argument explicitly allows deviations near the Mott boundary; its underlying DMFT model uses an infinite-coordination Bethe lattice. No self-consistent DMFT calculation or measured transition follows from this toy sweep. [R5](#ref-source-e2b9d469a7c556df)

## Experimental criteria

For fcc Cs₃C₆₀, Ganin and colleagues report a pressure-dependent magnetic onset: 25.6 K at 1.3 kbar has only about 0.1% shielding, whereas 29.7 K at 2.2 kbar has about 12%. The maximum is approximately 35 K near 7 kbar, equivalent to 0.7 GPa. Measurements use 20 Oe, zero-field-cooled/field-cooled protocols and a tin pressure reference. A15 Cs₃C₆₀ reaches a separately reported maximum near 38 K; its value must not be assigned to the fcc sample. [R3](#ref-source-634d02f3c2bfde0d) [R4](#ref-source-5e6d3e7ed715ad6a)

The fcc study also separates magnetic ordering near 2.2 K from the A15 ordering scale near 46 K. Neither is a superconducting transition. Multiphase powders and small shielding fractions require particular care when locating the first superconducting signal. The magnetometry pressure range ends near 10.6 kbar; the separate diffraction measurements extend to much higher pressures. Combining those ranges would falsely imply that superconductivity was measured throughout the structural experiment. [R4](#ref-source-5e6d3e7ed715ad6a)

Published online on 9 June 2026, Shchukin and colleagues tune Rb uptake in nanostructured C₆₀ films. Figure 2f labels Rb₂.₇₁C₆₀ with $T_{\mathrm{onset}}=22.4$ K and $T_{\mathrm{zero}}=7.0$ K, and Rb₂.₉₈C₆₀ with 26.4 K and 14.5 K. The former criterion is a local resistivity maximum; the latter uses $d\rho/dT<5\times10^{-4}$ mΩ cm K⁻¹ in the plotted low-temperature window. It is a stated operational criterion, not an instrument-independent definition of exact zero resistance. [R8](#ref-source-64cd48d99353501a)

That experiment uses Raman analysis with relative scattering cross sections to estimate composition, and van der Pauw transport. The 10 μA intercalation current differs from the 1 μA resistance-probe current. Stoichiometry, grain connectivity, thickness and transition criterion must accompany any comparison with bulk rubidium fullerides. The supplement and underlying transport datasets have not been independently reanalyzed here. [R8](#ref-source-64cd48d99353501a)

## Limits and disputes

Mitrano's optical study and Budden's longer-lived driven response concern pumped K₃C₆₀. A finite-frequency inductive response and suppressed transient resistance constrain the nonequilibrium state, but do not by themselves establish an equilibrium thermodynamic transition. Budden's final Figure 4 separates two measurements at a 100 K base temperature and approximately 25 mJ cm⁻² pump fluence:

| Measurement | What the reported value means |
|---|---|
| Optical, Fig. 4a; 200 ps pump | Zero-frequency resistivity extrapolated from a Drude–Lorentz fit to transient optical conductivity; error bars reflect the fit confidence interval. |
| Electrical, Fig. 4b; 75 ps pump | Transient two-terminal resistance after contact correction from a separate static four-terminal measurement; the shaded band estimates calibration error. |

The electrical readout uses a 1 ns voltage probe pulse. The corrected resistance is compatible with zero within the stated calibration uncertainty, and recovers on a tens-of-nanoseconds timescale. This supports the authors' assignment of a metastable superconducting state; it does not turn the 100 K measurement condition into an equilibrium Tc. Neither the pump duration nor the probe duration is the state lifetime. Both records retain `transient-response` temperatures with no equilibrium Tc. Complete supplement review, raw-data refitting and comparison of alternative conductivity models remain open. [R6](#ref-source-6ee3670220e24ff1) [R7](#ref-source-07be806c0002c690)

The historical hole-doped C₆₀ claim at 52 K was retracted on 6 March 2003. The original paper and its notice are retained together for traceability; the withdrawn value is excluded from experimental transition records. The notice identifies concerns about device-measurement data following an independent investigation. A citation in an older, otherwise valid paper does not restore the withdrawn claim. [R9](#ref-source-091fb85b144daad9) [R10](#ref-source-8822fee6435cf8cc)

## Discovery implications

Fullerides motivate simultaneous control of bandwidth, local vibronic interactions, molecular valence and disorder. A superconducting dome near a Mott state is compatible with cooperation between phonons and correlations; it does not uniquely determine the pairing kernel. Neither a fully open gap nor proximity to a magnetic insulator proves that one interaction acts alone. Report model assumptions beside the experimental evidence used to constrain them. [R4](#ref-source-5e6d3e7ed715ad6a) [R5](#ref-source-e2b9d469a7c556df)

Current-driven intercalation offers a method for tuning samples rather than a new bulk temperature record. Reproducible optimization needs composition maps, measurement-current controls and comparable transition definitions. Keep pressure polymorphs and optically driven states separate when selecting targets: their conditions cannot be collapsed into a single family-wide Tc ranking. [R8](#ref-source-64cd48d99353501a) [R4](#ref-source-5e6d3e7ed715ad6a) [R7](#ref-source-07be806c0002c690)

## Related topics

Continue with [electron–phonon pairing](/scwiki/bcs-weak-coupling), [Eliashberg theory](/scwiki/eliashberg-strong-coupling), [Mottness](/scwiki/mottness-and-superconductivity), [s-wave pairing](/scwiki/s-wave) and [zero resistance and driven-state evidence](/scwiki/zero-resistance).
