## Scope

A reported zero resistance means that a specified measurement cannot resolve a resistive voltage under its current, geometry and acquisition conditions. It is evidence within a detection limit, not a measurement of a mathematically exact zero. Keep the measured signal, correction and uncertainty together; a display reading of zero does not specify all three. The uncertainty framework below is separate from a microscopic theory of superconductivity. [R6](#ref-source-0c63f38b6789c792)

Record transition onset, midpoint and the operational zero criterion separately. A conducting path need not occupy the whole specimen. As a simple counterexample, two ideal parallel channels have $R_{\mathrm{eff}}=R_1R_2/(R_1+R_2)$: one zero-resistance channel shorts a finite-resistance channel. This circuit result establishes no volume fraction or material identity. Magnetic and thermodynamic probes answer complementary questions.

## Mathematical assumptions

Suppose a corrected voltage estimate is $\hat V$ and the applied current estimate is $\hat I$. If independently justified intervals satisfy $|V-\hat V|\le U_V$ and $|I-\hat I|\le U_I<|\hat I|$, the triangle inequality gives a conditional bound:

$$\left|\frac{V}{I}\right|\le\frac{|\hat V|+U_V}{|\hat I|-U_I}.$$

This is a local interval calculation, not an automatically calibrated confidence statement. If the input intervals have probabilistic coverage, the output statement must retain that coverage model and their dependence. An operational threshold $|\hat V|<V_{\mathrm{cut}}$ alone does not establish $|V|<V_{\mathrm{cut}}$. Do not substitute a display digit or a noise standard deviation for a validated bound without explaining the choice. NIST's uncertainty guidance distinguishes uncertainty components, applied corrections and coverage. [R6](#ref-source-0c63f38b6789c792)

For a fixed linear resistance and equal opposite currents, model the readings as $V_+=IR+V_{0,+}+\epsilon_+$ and $V_-=-IR+V_{0,-}+\epsilon_-$. Then

$$\hat R=\frac{V_+-V_-}{2I}=R+\frac{V_{0,+}-V_{0,-}+\epsilon_+-\epsilon_-}{2I}.$$

A constant current-even offset cancels. Drift, a current-odd voltage, unequal currents or a changing specimen do not satisfy that cancellation. NIST's shunt report describes a thermoelectric contribution that reverses with the current and therefore survives ordinary reversal averaging. Its apparatus-specific thermal treatment is not a universal correction for superconducting samples. [R5](#ref-source-c8143afdf96ce96f)

With fixed known $I$, the voltage contribution to standard uncertainty is $u_R^2=[u_+^2+u_-^2-2\operatorname{cov}(V_+,V_-)]/(4I^2)$. Current uncertainty and model/systematic contributions must be included separately when present. Independent algebra and finite-outcome checks verify this conditional variance and show why assuming uncorrelated errors can fail. The check is not an instrument calibration. [R6](#ref-source-0c63f38b6789c792)

Converting resistance to resistivity as $\rho=RA/L$ additionally assumes the appropriate homogeneous current path, area $A$ and voltage-contact separation $L$. Four-terminal geometry does not by itself establish uniform current density. Conversely, a passive lumped loop with constant inductance $L_{\mathrm{loop}}$ and resistance obeys $I(t)=I_0e^{-Rt/L_{\mathrm{loop}}}$. A measured fractional decay no larger than $\varepsilon$ gives $R\le-L_{\mathrm{loop}}\ln(1-\varepsilon)/t$ only under that loop model. Vortex relaxation or changing inductance needs a different treatment.

## Experimental criteria

Halperin and Nelson's 1979 superconducting-film theory describes a vortex-unbinding regime, fluctuation conductivity and nonlinear resistivity. This supports a limited theoretical reference for thin-film analysis, not a universal fit or a pairing-symmetry test. The publisher abstract was checked; its full derivation has not yet been reviewed here. [R2](#ref-source-9e55a4505d9de546)

Use four-terminal measurements where the time scale and apparatus permit them, and state the actual geometry when they do not. Publish the voltage/current data, detection criterion, field orientation, temperature sweep, bandwidth or integration time and contact configuration. Check current dependence, contact stability and thermal response. Treat these as editorial evidence requirements rather than a claim that one fixed protocol fits every apparatus.

If contacts or backgrounds are subtracted, preserve the original reading and propagate the uncertainty of the subtraction. An independent magnetic or heat-capacity result on a comparable sample helps test a bulk interpretation. A low transport reading alone cannot exclude a connected minority phase, a short or an instrument limitation.

## Limits and disputes

Mitrano and colleagues' earlier author manuscript reports transient optical signatures in driven K3C60 and discusses a high-mobility alternative interpretation. Such spectra do not constitute a direct DC transport measurement. This check covers selected 2015 manuscript passages; the publisher record flags an update whose details have not been verified here. No optical crossover temperature is entered as an equilibrium transition. [R3](#ref-source-6ee3670220e24ff1)

Budden and colleagues complement optics with a 1 ns electrical probe of a driven K3C60 pellet at 100 K. The checked manuscript uses a two-terminal transient measurement with contact resistance calibrated against static four-terminal measurements. Figure 4 explicitly includes a calibration-related systematic uncertainty. A resistance compatible with zero in this driven experiment is not an equilibrium $T_{c,\mathrm{zero}}$. The numerical waveform and complete final journal version were not independently reanalyzed. [R4](#ref-source-07be806c0002c690)

These methods probe different observables and time windows. Keep optical extrapolation to zero frequency separate from electrical response, and distinguish either from long-time equilibrium transport. A very large photoconductivity can motivate further tests without resolving every question about phase coherence or magnetic expulsion.

## Discovery implications

A useful discovery report states which observations would distinguish a superconducting path from a contact artifact, minority phase or alternative conducting state. Repeat under controlled current and magnetic field, retain unsuccessful controls, and seek independent probes of the claimed phase. Field suppression supports an interpretation but does not uniquely identify a pairing interaction.

BCS theory is retained as a microscopic background reference, with its detailed treatment in the linked BCS entry. It is not the source for the measurement bounds or procedural requirements developed here. Keep operational transport evidence, theoretical interpretation and claims of bulk superconductivity distinct. [R1](#ref-source-ba10e800a1246bf6)

## Related topics

Read [Meissner evidence](/scwiki/meissner-effect), [specific heat](/scwiki/specific-heat-jump), [critical current](/scwiki/critical-current), [BCS theory](/scwiki/bcs-weak-coupling), [two-dimensional superconductivity](/scwiki/two-dimensional-interfaces), and [Planckian dissipation](/scwiki/planckian-dissipation).
