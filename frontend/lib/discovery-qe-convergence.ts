import { coordinateSha256 } from "@/lib/discovery-site-candidates";
import { QE_RESULT_VERSION, type QeResultReading } from "@/lib/discovery-qe-result";

export const QE_CONVERGENCE_VERSION = "discovery-qe-sampled-convergence/1.0.0";
export const QE_STUDY_LIMIT = 16;
export const QE_STUDY_AXES = {
  mesh: "k-point mesh",
  ecutwfc: "Wavefunction cutoff (Ry)",
  ecutrho: "Charge-density cutoff (Ry)",
  degauss: "Smearing width (Ry)",
} as const;
export type QeStudyAxis = keyof typeof QE_STUDY_AXES;
const fail = (message: string): never => { throw new Error(message); };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
type Report = QeResultReading["report"];

function validateReport(report: Report) {
  if (report.version !== QE_RESULT_VERSION || report.input_kind !== "execution" || report.status !== "scf_reported_converged" || report.settings.calculation !== "scf") fail("Use electronically converged, fixed-geometry SCF readings. Initialization and relaxation runs cannot enter this study.");
  if (report.settings.nspin !== 1) fail("This comparison requires spin-unpolarized runs. Magnetic branch identity needs a separate comparison.");
  const energy = report.observations.total_energy, error = report.convergence.scf_error_hartree;
  if (!energy || energy.unit !== "Hartree/cell" || !Number.isFinite(energy.value) || error === null || !Number.isFinite(error) || error < 0) fail("Every reading needs a finite native total energy and SCF error in Hartree.");
  const count = Object.values(report.composition).reduce((sum, value) => sum + value, 0);
  if (!Number.isInteger(count) || count < 1 || report.observations.final_atoms?.length !== count) fail("The atom inventory is inconsistent.");
  return count;
}

/** Only readings produced by the local native-file reader enter the UI queue.
 * A matching digest checks byte consistency, not execution authenticity. */
export async function compareQeReadings(input: QeResultReading[], axis: QeStudyAxis, tolerance: number) {
  const readings = structuredClone(input);
  if (!Object.hasOwn(QE_STUDY_AXES, axis)) fail("Choose a supported numerical parameter.");
  if (readings.length < 3 || readings.length > QE_STUDY_LIMIT) fail(`Choose 3 to ${QE_STUDY_LIMIT} readings for one numerical parameter.`);
  if (!Number.isFinite(tolerance) || tolerance <= 0) fail("Enter a positive energy tolerance in Hartree per atom.");
  const baseline = readings[0].report, atomCount = validateReport(baseline);
  const fixedSettings = (report: Report) => {
    const settings: Partial<Report["settings"]> = { ...report.settings };
    delete settings[axis];
    return settings;
  };
  for (const reading of readings) {
    if (reading.json !== JSON.stringify(reading.report, null, 2) + "\n" || await coordinateSha256(reading.json) !== reading.sha256) fail("A reading has changed since its native files were checked. Read the original files again.");
    const report = reading.report;
    validateReport(report);
    if (report.candidate_id !== baseline.candidate_id || report.candidate_cif_sha256 !== baseline.candidate_cif_sha256 || !equal(report.source_reference, baseline.source_reference) || !equal(report.composition, baseline.composition)) fail("Select readings for the same source-linked candidate and coordinate bytes.");
    if (!equal(report.pseudopotentials, baseline.pseudopotentials)) fail("The exact UPF files and their metadata must match across the study.");
    if (!equal(fixedSettings(report), fixedSettings(baseline))) fail("More than the selected parameter differs. Keep all other prepared settings fixed, including smearing, mesh shifts, masses, charge and SCF controls.");
    if (report.engine.name !== baseline.engine.name || report.engine.version !== baseline.engine.version || report.engine.xml_format !== baseline.engine.xml_format || report.engine.xml_units !== baseline.engine.xml_units) fail("Use the same supported engine and output format.");
  }
  const parameter = (r: QeResultReading) => r.report.settings[axis];
  if (new Set(readings.map(r => JSON.stringify(parameter(r)))).size !== readings.length) fail("Repeated parameter values are not independent refinement points. Remove duplicate settings.");
  const rank = (r: QeResultReading) => axis === "mesh" ? r.report.settings.mesh.reduce((a, b) => a * b, 1) : r.report.settings[axis];
  readings.sort((a, b) => (rank(a) - rank(b)) * (axis === "degauss" ? -1 : 1));
  if (axis === "mesh" && readings.some((r, i) => i > 0 && r.report.settings.mesh.some((n, j) => n < readings[i - 1].report.settings.mesh[j]))) fail("Mesh refinement must keep or increase every direction. A larger product alone is not a refinement sequence.");
  const reference = readings.at(-1)!, referenceEnergy = reference.report.observations.total_energy!.value;
  const points = readings.map(reading => ({ reading_sha256: reading.sha256, preparation_id: reading.report.preparation_id,
    parameter: parameter(reading), energy_hartree_per_cell: reading.report.observations.total_energy!.value,
    difference_from_last_hartree_per_atom: (reading.report.observations.total_energy!.value - referenceEnergy) / atomCount,
    scf_error_hartree_per_atom: reading.report.convergence.scf_error_hartree! / atomCount,
    maximum_force_hartree_per_bohr: reading.report.observations.forces?.maximum_atom_norm ?? null }));
  const tail = points.slice(-3), energies = tail.map(point => point.energy_hartree_per_cell);
  const spread = (Math.max(...energies) - Math.min(...energies)) / atomCount;
  const maximumScfError = Math.max(...tail.map(point => point.scf_error_hartree_per_atom));
  const assessment = maximumScfError >= tolerance ? "scf_precision_insufficient" as const : spread <= tolerance ? "sampled_window_within_tolerance" as const : "sampled_window_outside_tolerance" as const;
  const report = { version: QE_CONVERGENCE_VERSION, axis, parameter_label: QE_STUDY_AXES[axis],
    candidate_id: baseline.candidate_id, candidate_cif_sha256: baseline.candidate_cif_sha256, source_reference: baseline.source_reference,
    atom_count: atomCount, tolerance: { value: tolerance, unit: "Hartree/atom", origin: "user_requested" },
    ordering: axis === "degauss" ? "decreasing smearing width" : axis === "mesh" ? "componentwise nondecreasing mesh" : "increasing cutoff",
    reference_reading_sha256: reference.sha256, points,
    sampled_window: { point_count: 3, reading_sha256s: tail.map(point => point.reading_sha256), energy_spread_hartree_per_atom: spread,
      maximum_reported_scf_error_hartree_per_atom: maximumScfError, assessment },
    scope: { claim: "Observed energy sensitivity over the last three supplied refinement points at fixed remaining settings.",
      limit_established: false, joint_numerical_convergence_established: false, force_or_stress_convergence_assessed: false,
      execution_authenticated: false, stable_host_validated: false, tc_calculated: false, scientific_acceptance: false, database_write: false,
      caveats: ["A finite sampled plateau is not a proof of an infinite-cutoff, dense-mesh or zero-smearing limit.",
        "Mesh and smearing need joint examination; numerical broadening is not experimental temperature.",
        "SCF error is an engine estimate, not a rigorous bound on total-energy accuracy.",
        "Absolute total energies cannot rank different compositions, geometries or pseudopotentials."] },
    readings: readings.map(reading => ({ sha256: reading.sha256, filename: reading.filename, report: reading.report })) };
  const json = JSON.stringify(report, null, 2) + "\n", sha256 = await coordinateSha256(json);
  return { report, json, sha256, filename: `sclib-qe-convergence-${sha256.slice(0, 16)}.json` };
}
export type QeConvergenceReading = Awaited<ReturnType<typeof compareQeReadings>>;
