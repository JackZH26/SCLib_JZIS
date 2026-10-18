## Scope

Isotope substitution changes nuclear mass while keeping the element the same. The resulting response of a transition temperature can constrain lattice involvement, provided the compared samples have controlled chemistry and structure. It does not, by itself, identify the complete pairing interaction. This entry distinguishes a mass derivative, a finite comparison between samples and a microscopic explanation.

The classic mercury reports by Maxwell and Reynolds and colleagues, and Fröhlich's early theory paper, are historical starting points. Their bibliographic identities are checked here; their original experimental curves and derivations are not. No mercury exponent is extracted from those metadata records. [R3](#ref-source-eff5a2a1c455e7f6) [R4](#ref-source-e8a489943f13c9f8) [R5](#ref-source-51114e33276df5b9)

## Mathematical assumptions

For element $i$, with other masses and specified sample conditions held fixed, define

$$\alpha_i=-\frac{\partial\ln T_c}{\partial\ln M_i},\qquad \widehat\alpha_i=-\frac{\ln(T_{c,2}/T_{c,1})}{\ln(M_{i,2}/M_{i,1})}.$$

The finite estimate averages a slope over the chosen interval; it equals the local derivative only for an appropriate limiting interval or a power law. Use the mean mass implied by measured isotope abundances, not automatically an integer isotope label. A partial coefficient is not the total $\alpha_{\rm tot}=\sum_i\alpha_i$. This sum describes a common logarithmic scaling of all component masses under the same constraints. [R2](#ref-source-60ffd9b4ef2c9ccd)

For a harmonic mode with fixed force constant, $\omega\propto M^{-1/2}$. If the transition scale is proportional to that frequency and all dimensionless interaction parameters remain mass independent, differentiation gives $\alpha=1/2$. The fixed-parameter condition is essential. A measured deviation challenges that restricted model, not every possible electron–phonon theory. [R2](#ref-source-60ffd9b4ef2c9ccd)

An illustrative two-mass optical oscillator makes the distinction concrete. If $\omega^2=K(1/M_1+1/M_2)$ and $T_c\propto\omega$, direct differentiation gives

$$\alpha_1=\frac{M_2}{2(M_1+M_2)},\qquad \alpha_2=\frac{M_1}{2(M_1+M_2)},\qquad \alpha_1+\alpha_2=\frac12.$$

Each partial coefficient can be below one half even in this harmonic construction. These equations are a local illustrative derivation, checked against numerical mass derivatives; they are not a fit to MgB2 or a microscopic pairing calculation.

For uncertainty propagation let $N=\ln(T_{c,2}/T_{c,1})$ and $D=\ln(M_{i,2}/M_{i,1})$. First-order propagation for $\widehat\alpha=-N/D$ gives

$$\sigma_\alpha^2\simeq\frac{\operatorname{Var}(N)}{D^2}+\frac{N^2\operatorname{Var}(D)}{D^4}-\frac{2N\operatorname{Cov}(N,D)}{D^3}.$$

This linear approximation requires small uncertainties relative to the resolved mass interval. Shared calibration errors can be correlated; treating all temperatures as independent can misstate the uncertainty. The analytic gradient was checked against finite differences. Those arithmetic checks do not establish experimental precision.

## Experimental criteria

Bud'ko and colleagues report MgB2 isotope samples with magnetic onsets at 40.2 K for boron-10 and 39.2 K for boron-11. They use 25 G, warming after zero-field cooling, and a 2% onset of the low-temperature diamagnetic signal. Heat capacity also shows the shift. Their reported boron coefficient is $0.26\pm0.03$, a partial coefficient. Using nominal masses 10 and 11 gives about 0.264 from the stated temperatures; this only checks arithmetic, not enrichment or their error estimate. [R1](#ref-source-22ad55507a1e49c5)

A separate study by Hinks, Claus and Jorgensen measures both components. Its author manuscript reports partial coefficients of $0.30(1)$ for boron and $0.02(1)$ for magnesium, with total $0.32(1)$. Its magnetic protocol uses 1 G and compares extrapolated onset with a 10% criterion. These values belong to that study and must not be assembled from unrelated samples or criteria. The authors explicitly discuss possible impurity effects in their magnesium comparison. [R2](#ref-source-60ffd9b4ef2c9ccd)

For a new comparison, report enrichment, composition, structure, defects, preparation history and the exact temperature criterion. Characterize spectral frequency shifts where feasible. Back-exchange can test reversibility, but annealing itself may change the specimen. Repeat controls and uncertainty estimates are needed before assigning a shift exclusively to mass. These are editorial reporting recommendations, not claims that every cited study performed every control.

## Limits and disputes

A small response for one element does not exclude its contribution to a coupled vibrational system. Conversely, a nonzero response does not reconstruct the full electron–phonon spectral function or uniquely determine a mediator. Mass-dependent interactions, anharmonicity and structural changes require explicit models; the sign or size alone cannot settle them. The cited Hinks manuscript discusses alternatives to its own interaction-parameter interpretation. [R2](#ref-source-60ffd9b4ef2c9ccd)

Do not merge resistive onset, zero resistance, magnetic screening and a calorimetric transition into one unqualified temperature. The material records below preserve the magnetic criterion actually checked. Pressure and equilibrium classifications not established in the selected passages remain unknown. Comparing isotope coefficients from different studies also requires their sample preparation and systematic uncertainties.

## Discovery implications

Ask which controlled observation would separate a direct mass dependence from a changed sample. Joint measurements of structure, composition, vibrational spectra and independent superconducting probes can narrow the interpretation. Preserve null results and disagreements rather than treating the isotope exponent as a pass/fail label.

A quantitative theory should predict the response of the same observable under the same substitution and constraints. Agreement with one coefficient is a consistency check; a credible explanation must also confront the remaining measurements. These are model-discrimination criteria, not a new material discovery.

## Related topics

Read the [BCS baseline](/scwiki/bcs-weak-coupling), [multiband pairing](/scwiki/multiband-pairing), [heat-capacity evidence](/scwiki/specific-heat-jump), [Meissner screening](/scwiki/meissner-effect), and [zero resistance](/scwiki/zero-resistance) alongside an isotope comparison.
