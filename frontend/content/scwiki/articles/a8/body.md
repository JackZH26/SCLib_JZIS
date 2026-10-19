## Scope

Linear-temperature resistivity describes a measured dependence over a specified range. The fit $\rho(T)=\rho_0+AT$ needs a sample, current direction, field, temperature interval and residuals. A straight-looking trace is not by itself evidence for a quantum critical point, a universal lifetime or a pairing interaction. This entry treats transport phenomenology; the linked Planckian entry discusses lifetime interpretations.

Separate a finite-field normal state, the region affected by superconducting fluctuations, and a higher-temperature regime that may have different scattering. Martin and colleagues' Bi-based crystal abstract reports strongly anisotropic transport; an in-plane trend is not an isotropic resistivity law. [R1](#ref-source-a5d6480d08ee8555)

## Mathematical assumptions

A least-squares slope depends on both the model and the sampled window. For exact synthetic data $\rho=r_0+aT+bT^2$, equally weighted temperatures symmetric about $\bar T$ give

$$A_{\mathrm{fit}}=a+2b\bar T.$$

This follows by inserting the quadratic into $\operatorname{cov}(T,\rho)/\operatorname{var}(T)$. A narrower interval can hide curvature while changing the inferred slope. Independent synthetic fits confirm this counterexample; they are not fits to any material. Experimental model comparison also needs uncertainties, correlations and a justified treatment of residuals.

For a single isotropic Drude channel with temperature-independent carrier density $n$ and mass $m^*$, an inelastic pole relaxation rate $\gamma=\alpha k_BT/\hbar$ gives $A=\alpha m^*k_B/(ne^2\hbar)$. Thus a slope fixes $\alpha$ only after the carrier parameters and response model are specified. If those parameters change with temperature, differentiating resistivity produces additional terms. This conditional connection underlies the selected Legros analysis. [R4](#ref-source-c1ae7869b672a8e8)

For a circular, parabolic two-dimensional band with total degeneracy $g$, use total sheet density $n_{2D}=gk_F^2/(4\pi)$ and $k_BT_F=\hbar^2k_F^2/(2m^*)$. The preceding Drude model then yields

$$A_{\square}T_F=\frac{\alpha h}{g e^2}.$$

The familiar factor of two corresponds to $g=2$, not an arbitrary multiband system. A bulk slope converted per conducting plane uses $A_{\square}=A/d$ with the stated effective plane spacing $d$. Independent occupied-disk and algebra checks cover $g=1,2,4$; neither degeneracy nor a mass should be transferred between materials without justification.

Parallel channels add conductivities. As an independent scalar, zero-field example, let $r(T)=r_0+aT>0$ describe one channel and let $\sigma_b\ge0$ be a constant background conductivity in matching units. Then

$$\rho_{\mathrm{tot}}=\frac{r(T)}{1+\sigma_b r(T)},\qquad\frac{d\rho_{\mathrm{tot}}}{dT}=\frac{a}{[1+\sigma_b r(T)]^2}.$$

The total slope is generally temperature dependent even though the first channel's resistance is exactly linear. Nine numerical derivative checks verify this model. It is not a multiband fit; in magnetic field, conductivity tensors must be added before inversion. Adding scattering mechanisms within one channel is a different assumption from adding parallel conductivities.

## Experimental criteria

Legros and colleagues' earlier manuscript measures a Bi2212 film with nominal hole doping 0.23 in pulsed fields. Its 55 T trace and magnetoresistance-corrected, extrapolated zero-field curve are distinct datasets. The analysis estimates carrier parameters and geometric uncertainty; the checked passages do not turn its interpretation into a model-independent universal bound. [R4](#ref-source-c1ae7869b672a8e8)

Cao and colleagues measure four-probe transport in gated twisted bilayer graphene. Their linear regime depends on filling and a crossover temperature. The operational scattering coefficient uses density and mass from low-temperature quantum oscillations; those assumptions matter when interpreting higher-temperature transport. The selected passages do not establish one shared microscopic mechanism across material families. [R5](#ref-source-8135909144b6b16b)

Romero and colleagues' earlier manuscript studies two 100 nm FeTe1-xSex films, x = 0.45 and 0.35, over 0.2–3 THz. Its narrow-channel fits use 20–40 K and report coefficients 3.02 and 2.42 in $\Gamma=\Gamma_0+\alpha k_BT/h$. These are channel-specific fit results, not coefficients of the total DC resistivity. [R6](#ref-source-05b2d5ff6757b5eb)

Record the raw voltage/current or conductivity data, geometry, composition, field direction, fit interval and uncertainty model. Identify excluded transition regions and test alternative fit windows and curvature. A successful fit does not establish that its parameters are uniquely identifiable. Normal-state measurement temperatures remain separate from superconducting transition temperatures in the records below.

## Limits and disputes

Frequency conventions can create a factor-of-$2\pi$ error. For a Drude denominator $\Gamma-i\nu$ with ordinary frequency $\nu$, the corresponding pole rate is $\gamma=1/\tau=2\pi\Gamma$ in a denominator $\gamma-i\omega$, where $\omega=2\pi\nu$. Consequently $\Gamma=\alpha k_BT/h$ converts to $\gamma=\alpha k_BT/\hbar$. State the denominator and linewidth convention before comparing coefficients. This is a convention check, not a new measurement of a lifetime.

A shared temperature exponent does not identify a unique microscopic interaction. Drude transport, optical fits and single-particle lifetimes measure or infer different quantities. Extrapolating carrier parameters, suppressing superconductivity by field, or neglecting a parallel channel can affect an inferred coefficient. Report these choices alongside any claimed universality rather than treating the fit exponent as a proof.

Cooper's LSCO study and Bruin's cross-metal comparison remain bibliographic starting points here. Their complete datasets and numerical conclusions have not been reanalyzed in this entry. Selected manuscript checks above also leave final-version comparison and full uncertainty reproduction open. [R2](#ref-source-1610fd228e679225) [R3](#ref-source-e6d342432f3409ae)

## Discovery implications

Use linear-T transport to organize experiments, not to rank superconductors or predict a transition temperature by itself. A stronger comparison holds sample state, probe definition and fitting procedure fixed, then asks whether independent optical, thermodynamic or quantum-oscillation information supports the same parameter interpretation. Retain counterexamples and failed fits; correlation with superconductivity does not identify its cause.

## Related topics

Continue with [Planckian dissipation](/scwiki/planckian-dissipation), [zero resistance](/scwiki/zero-resistance), [critical fields](/scwiki/critical-fields), [specific heat](/scwiki/specific-heat-jump), [cuprates](/scwiki/cuprates), and [multiband pairing](/scwiki/multiband-pairing).
