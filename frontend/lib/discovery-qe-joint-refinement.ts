import { coordinateSha256 } from "@/lib/discovery-site-candidates";
import { QE_RESULT_VERSION, type QeResultReading } from "@/lib/discovery-qe-result";
import { QE_STUDY_LIMIT } from "@/lib/discovery-qe-convergence";

export const QE_JOINT_VERSION = "discovery-qe-mesh-smearing-study/1.0.0";
type Report = QeResultReading["report"];
const fail = (message: string): never => { throw new Error(message); };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const cellId = (mesh: number[], width: number) => JSON.stringify([mesh, width]);
const spread = (values: number[], count: number) => (Math.max(...values) - Math.min(...values)) / count;

function validate(report: Report) {
  if (report.version !== QE_RESULT_VERSION || report.input_kind !== "execution" || report.status !== "scf_reported_converged" || report.settings.calculation !== "scf" || report.settings.nspin !== 1) fail("Use electronically converged, spin-unpolarized, fixed-geometry SCF readings.");
  const energy = report.observations.total_energy, error = report.convergence.scf_error_hartree;
  if (!energy || energy.unit !== "Hartree/cell" || !Number.isFinite(energy.value) || error === null || !Number.isFinite(error) || error < 0) fail("Each reading needs a finite native energy and nonnegative SCF error in Hartree.");
  const counts = Object.values(report.composition), count = counts.reduce((sum, n) => sum + n, 0);
  if (!counts.length || counts.some(n => !Number.isSafeInteger(n) || n < 1) || report.observations.final_atoms?.length !== count) fail("The native atom inventory is inconsistent.");
  if (report.settings.mesh.length !== 3 || report.settings.mesh.some(n => !Number.isInteger(n) || n < 1 || n > 64) || !Number.isFinite(report.settings.degauss) || report.settings.degauss <= 0 || report.settings.degauss > 1) fail("The prepared mesh or smearing width is invalid.");
  return count;
}

/** The queue contains locally checked native files, not arbitrary uploaded result JSON.
 * A finite parameter grid describes sensitivity; it cannot authenticate execution. */
export async function compareQeMeshSmearing(input: QeResultReading[], tolerance: number) {
  const readings = structuredClone(input);
  if (readings.length < 3 || readings.length > QE_STUDY_LIMIT) fail(`Choose 3 to ${QE_STUDY_LIMIT} native readings for this study.`);
  if (!Number.isFinite(tolerance) || tolerance <= 0) fail("Enter a positive energy tolerance in Hartree per atom.");
  const baseline = readings[0].report, atomCount = validate(baseline);
  const fixed = (report: Report) => { const { mesh: _mesh, degauss: _width, ...settings } = report.settings; return settings; };
  for (const reading of readings) {
    if (reading.json !== JSON.stringify(reading.report, null, 2) + "\n" || await coordinateSha256(reading.json) !== reading.sha256) fail("A reading has changed. Read its original native files again.");
    const report = reading.report;
    validate(report);
    if (report.candidate_id !== baseline.candidate_id || report.candidate_cif_sha256 !== baseline.candidate_cif_sha256 || report.parent_id !== baseline.parent_id || !equal(report.source_reference, baseline.source_reference) || !equal(report.composition, baseline.composition)) fail("Use the same source-linked candidate and exact coordinate bytes.");
    if (!equal(report.pseudopotentials, baseline.pseudopotentials)) fail("The exact UPF files and metadata must match.");
    if (!equal(fixed(report), fixed(baseline))) fail("Only mesh and smearing width may vary. Keep cutoffs, smearing method, shifts, charge, masses and SCF controls fixed.");
    if (!["name", "version", "xml_format", "xml_units"].every(k => report.engine[k as keyof Report["engine"]] === baseline.engine[k as keyof Report["engine"]])) fail("Use the same supported engine and output format.");
  }
  const meshes = [...new Map(readings.map(r => [JSON.stringify(r.report.settings.mesh), r.report.settings.mesh])).values()]
    .sort((a, b) => a.reduce((x, n) => x * n, 1) - b.reduce((x, n) => x * n, 1));
  const widths = [...new Set(readings.map(r => r.report.settings.degauss))].sort((a, b) => b - a);
  if (meshes.length < 2 || widths.length < 2) fail("Include at least two different meshes and two smearing widths. Use the single-parameter study when only one varies.");
  if (meshes.some((mesh, i) => i > 0 && mesh.some((n, axis) => n < meshes[i - 1][axis]))) fail("Mesh refinement must retain or increase every direction; a larger product alone is insufficient.");
  const byCell = new Map<string, QeResultReading>();
  for (const reading of readings) {
    const key = cellId(reading.report.settings.mesh, reading.report.settings.degauss);
    if (byCell.has(key)) fail("Duplicate mesh–smearing combinations cannot be averaged or counted as new refinement points.");
    byCell.set(key, reading);
  }
  // Explicit nulls retain missing combinations; no interpolation or zero filling.
  const cells = meshes.flatMap(mesh => widths.map(width => {
    const reading = byCell.get(cellId(mesh, width));
    return { mesh, smearing_width_ry: width, reading_sha256: reading?.sha256 ?? null,
      energy_hartree_per_cell: reading?.report.observations.total_energy!.value ?? null,
      scf_error_hartree_per_atom: reading ? reading.report.convergence.scf_error_hartree! / atomCount : null };
  }));
  const missing = cells.filter(cell => cell.reading_sha256 === null).map(cell => ({ mesh: cell.mesh, smearing_width_ry: cell.smearing_width_ry }));
  const tailMeshes = meshes.slice(-3), tailWidths = widths.slice(-3);
  const windowCells = cells.filter(cell => tailMeshes.some(mesh => equal(mesh, cell.mesh)) && tailWidths.includes(cell.smearing_width_ry));
  const ready = meshes.length >= 3 && widths.length >= 3 && missing.length === 0;
  const range = ready ? spread(windowCells.map(cell => cell.energy_hartree_per_cell!), atomCount) : null;
  const maximumScfError = ready ? Math.max(...windowCells.map(cell => cell.scf_error_hartree_per_atom!)) : null;
  const rowRanges = widths.map(width => {
    const samples = tailMeshes.map(mesh => byCell.get(cellId(mesh, width)));
    return { smearing_width_ry: width, mesh_count: samples.filter(Boolean).length,
      energy_range_hartree_per_atom: tailMeshes.length === 3 && samples.every(Boolean) ? spread(samples.map(r => r!.report.observations.total_energy!.value), atomCount) : null };
  });
  const finestMeshSamples = tailWidths.map(width => byCell.get(cellId(meshes.at(-1)!, width)));
  const finestWidthRange = tailWidths.length === 3 && finestMeshSamples.every(Boolean) ? spread(finestMeshSamples.map(r => r!.report.observations.total_energy!.value), atomCount) : null;
  const assessment = missing.length ? "incomplete_grid" as const : !ready ? "insufficient_axis_samples" as const
    : maximumScfError! >= tolerance ? "scf_precision_insufficient" as const
    : range! <= tolerance ? "sampled_window_within_tolerance" as const : "sampled_window_outside_tolerance" as const;
  const ordered = cells.flatMap(cell => { const reading = byCell.get(cellId(cell.mesh, cell.smearing_width_ry)); return reading ? [reading] : []; });
  const report = { version: QE_JOINT_VERSION, candidate_id: baseline.candidate_id, candidate_cif_sha256: baseline.candidate_cif_sha256,
    source_reference: baseline.source_reference, atom_count: atomCount,
    tolerance: { value: tolerance, unit: "Hartree/atom", origin: "user_requested" },
    axes: { meshes, smearing_widths_ry: widths, ordering: "componentwise nondecreasing meshes; decreasing smearing widths" },
    coverage: { scope: "cross_product_of_parameter_values_in_supplied_readings", supplied: readings.length, expected: cells.length, missing }, cells,
    mesh_sensitivity_by_width: rowRanges, smallest_three_width_range_at_finest_mesh_hartree_per_atom: finestWidthRange,
    sampled_window: { assessment, meshes: tailMeshes, smearing_widths_ry: tailWidths, required_point_count: 9,
      energy_range_hartree_per_atom: range, maximum_reported_scf_error_hartree_per_atom: maximumScfError },
    scope: { claim: "Native QE etot sensitivity over the three finest supplied meshes and three smallest supplied smearing widths.",
      numerical_limit_established: false, joint_numerical_convergence_established: false, zero_smearing_extrapolated: false,
      force_or_stress_convergence_assessed: false, execution_authenticated: false, stable_host_validated: false,
      tc_calculated: false, scientific_acceptance: false, database_write: false,
      caveats: ["This finite grid does not establish the infinite-mesh or zero-smearing limit.",
        "QE etot includes the selected smearing contribution. No entropy correction or extrapolation is applied.",
        "Numerical broadening does not assign an experimental temperature.",
        "SCF error is an engine estimate, not a rigorous total-energy accuracy bound.",
        "An incomplete observed parameter cross-product receives no joint-window assessment."] },
    readings: ordered.map(reading => ({ sha256: reading.sha256, filename: reading.filename, report: reading.report })) };
  const json = JSON.stringify(report, null, 2) + "\n", sha256 = await coordinateSha256(json);
  return { report, json, sha256, filename: `sclib-qe-mesh-smearing-${sha256.slice(0, 16)}.json` };
}
export type QeJointReading = Awaited<ReturnType<typeof compareQeMeshSmearing>>;
