## Scope

The Meissner effect describes magnetic flux exclusion from superconducting material in the appropriate equilibrium, low-field state. It adds information beyond persistent current or zero resistance. The London brothers explicitly distinguished their magnetic-state condition from an acceleration-only description that can retain the initial field. Their historical equations are used here in a modern SI convention, within a stated local model. [R2](#ref-source-0590b237a1d87de4)

The 1933 Meissner–Ochsenfeld report compares the external field around tin and lead before and after cooling through the transition. It also describes field retained in the cavity of a hollow lead tube. A field in that cavity is not a measurement of field penetrating the superconducting wall. Selected pages of a reproduction containing the original German and an English translation were checked; the historical experiment was not independently reproduced. [R1](#ref-source-512705f3e64d88d7)

Separate zero-field-cooled shielding, field-cooled magnetization and hysteresis. A type-II specimen can contain vortices, and pinning can prevent equilibration during cooling or field sweeps. Thus a protocol-dependent signal should not be labeled complete equilibrium flux expulsion. The vortex review supplies qualitative context; it is not a calibration of a particular sample's volume fraction. [R6](#ref-source-82f53ca35625217d)

## Mathematical assumptions

In a homogeneous, isotropic, vortex-free local London model, with displacement current neglected, combine the magnetic London relation with Ampere's law and $\nabla\cdot\mathbf B=0$:

$$\nabla\times\mathbf j=-\frac{\mathbf B}{\mu_0\lambda^2},\qquad \nabla\times\mathbf B=\mu_0\mathbf j,\qquad \nabla^2\mathbf B=\frac{\mathbf B}{\lambda^2}.$$

For a half-space $x>0$ with parallel surface field $B(0)=B_0$ and bounded field at depth, the solution is $B(x)=B_0e^{-x/\lambda}$. The surface boundary and exclusion of a growing solution matter; the differential equation alone does not specify an arbitrary specimen's field map. These are modern local-model deductions, not a claim that London theory covers every superconducting state. [R2](#ref-source-0590b237a1d87de4)

For an infinite slab $-a<x<a$ with equal parallel fields on its two faces, no vortices and constant $\lambda$, the same boundary-value problem gives

$$\frac{B(x)}{B_0}=\frac{\cosh(x/\lambda)}{\cosh(a/\lambda)},\qquad \chi_{\parallel}=\frac{\langle B\rangle}{B_0}-1=\frac{\lambda}{a}\tanh\!\left(\frac{a}{\lambda}\right)-1.$$

Here $2a$ is the full thickness and $B_0=\mu_0H_a$. A local finite-difference solution independently checks the field profile and its spatial average. A thick slab tends toward $\chi_{\parallel}=-1$; a very thin slab in this parallel geometry has much weaker shielding even when the entire slab obeys the superconducting model. This is not a formula for a perpendicular-field thin film or a porous specimen.

Demagnetization is a separate shape effect. For an ellipsoid along a principal axis, with uniform scalar susceptibility in SI, let $H_{\mathrm{int}}=H_a-NM$ and $M=\chi H_{\mathrm{int}}$. Then

$$\chi_{\mathrm{app}}=\frac{M}{H_a}=\frac{\chi}{1+N\chi}.$$

For the perfect-diamagnet limit $\chi=-1$, this gives $\chi_{\mathrm{app}}=-1/(1-N)$, for $N<1$. A sphere has $N=1/3$, so an uncorrected magnitude of 1.5 is consistent with this ideal geometry, not a 150% superconducting volume. The Prozorov–Kogan manuscript defines the convention and explains why nonellipsoidal specimens need additional treatment. Its numerical arbitrary-shape results are not reproduced here. [R5](#ref-source-37f27e50dbdcf3a5)

In a single-component carrier convention, $\lambda^{-2}=\mu_0n_sq^2/m^*$. Count charge, mass and density consistently: pair density is not electron density. For a uniform thin film with thickness $d\ll\lambda$ and negligible dissipative response, the sheet kinetic inductance is $L_k=\mu_0\lambda^2/d$. Equating magnetic-model current response and carrier kinetic energy checks this normalization. Inferring a bulk penetration depth from a sheet response therefore requires thickness and a response model; multiband or nonlocal systems need their corresponding treatment.

## Experimental criteria

Report specimen dimensions, field orientation and amplitude, cooling and sweep history, magnetic moment normalization, background subtraction and the assumed geometry. For AC or microwave probes, include frequency, amplitude and the conversion from the measured response. These are reporting requirements; a successful model inversion is not an independent demonstration of its assumptions.

Hardy and colleagues report a linear contribution to the penetration-depth change of YBa2Cu3O6.95 single crystals over approximately 3–25 K with a 900 MHz resonator. This abstract-scoped observation constrains low-energy excitations. It does not directly measure gap phase or uniquely identify the pairing representation; sample disorder and electrodynamics belong in the interpretation. No transition temperature is extracted here. [R3](#ref-source-b7bc48c845a47b53)

## Limits and disputes

Shielding and expulsion can differ because of field history, geometry, connectivity and pinning. A small signal alone does not distinguish a small superconducting region from a measurement or geometry limitation. Conversely, a connected superconducting shell can screen a nonsuperconducting interior; a shielding measurement alone cannot establish the interior's volume fraction. The historical hollow-tube observation makes the distinction between material and enclosed space especially important. [R1](#ref-source-512705f3e64d88d7)

Božović and colleagues' overdoped LSCO study is retained as a reference for superfluid-density measurements, but this check confirms its bibliographic identity rather than reanalyzing its scaling data. Do not infer a pairing mediator from a correlation alone. Likewise, a measured total stiffness cannot be decomposed into conventional and geometric contributions merely by changing its label. Follow the dedicated geometric-superfluid-weight entry for that separate model question. [R4](#ref-source-b96ffab89d45664d)

## Discovery implications

Build a magnetic evidence package around discriminating measurements: cooling history for trapping, dimensions and orientation for demagnetization, thickness for sheet response, and transport or heat capacity on comparable specimens for complementary evidence. Preserve disagreements between probes until sample and analysis differences are tested.

Separate measured magnetic response, the fitted electrodynamic parameters and the microscopic interpretation. This keeps magnetic evidence useful for discovering superconductivity without turning one model-dependent inversion into an unqualified material property or mechanism assignment.

## Related topics

Compare [zero resistance](/scwiki/zero-resistance), [critical fields](/scwiki/critical-fields), [critical current](/scwiki/critical-current), [specific heat](/scwiki/specific-heat-jump), [superconducting gap](/scwiki/superconducting-gap), and [geometric superfluid weight](/scwiki/geometric-superfluid-weight).
