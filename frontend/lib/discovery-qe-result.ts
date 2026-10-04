import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";
import { prepareQeInput, qeFileSha256, QE_INPUT_VERSION, UPF_BYTE_LIMIT, type PreparedQe, type QeFile } from "@/lib/discovery-qe-input";
import { coordinateSha256 } from "@/lib/discovery-site-candidates";

export const QE_RESULT_VERSION = "discovery-qe-output-reading/1.0.0";
export const QE_RESULT_LIMITS = { manifest: 1024 * 1024, input: 1024 * 1024, xml: 8 * 1024 * 1024, stdout: 8 * 1024 * 1024 };
export type QeResultFiles = { manifest: QeFile; input: QeFile; xml: QeFile; stdout: QeFile; pseudos: QeFile[] };
const BOHR_ANGSTROM = 0.529177210903;
const fail = (message: string): never => { throw new Error(message); };
const copy = (file: QeFile, maximum: number, label: string) => {
  if (!file || typeof file.name !== "string" || file.name.length > 256 || !ArrayBuffer.isView(file.bytes) || Object.prototype.toString.call(file.bytes) !== "[object Uint8Array]" || !file.bytes.length || file.bytes.length > maximum) return fail(`Choose a complete ${label} file within the stated size limit.`);
  return { name: file.name, bytes: new Uint8Array(file.bytes) };
};
const decode = (file: QeFile) => { try { return new TextDecoder("utf-8", { fatal: true }).decode(file.bytes); } catch { return fail(`${file.name}: expected UTF-8 text.`); } };
const children = (node: Element, name: string) => [...node.children].filter(child => child.tagName === name);
function nodeAt(node: Element, path: string, optional = false): Element | null {
  for (const part of path.split("/")) {
    const matches = children(node, part);
    if (optional && !matches.length) return null;
    if (matches.length !== 1) return fail(`QE XML needs exactly one ${path}.`);
    node = matches[0];
  }
  return node;
}
const node = (root: Element, path: string) => nodeAt(root, path)!;
const text = (root: Element, path: string) => node(root, path).textContent?.trim() ?? "";
const real = (raw: string, label: string) => {
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$/.test(raw)) return fail(`Invalid numeric value in ${label}.`);
  const value = Number(raw.replace(/[dD]/, "e"));
  return Number.isFinite(value) ? value : fail(`Non-finite value in ${label}.`);
};
const number = (root: Element, path: string) => real(text(root, path), path);
const integer = (value: number, label: string) => Number.isSafeInteger(value) && value >= 0 ? value : fail(`Invalid nonnegative integer in ${label}.`);
const bool = (root: Element, path: string) => { const value = text(root, path); return value === "true" ? true : value === "false" ? false : fail(`Invalid boolean in ${path}.`); };
const equal = (actual: unknown, expected: unknown, label: string) => { if (actual !== expected) fail(`${label} differs from the prepared input.`); };
const close = (actual: number, expected: number, label: string, relative = 1e-10, absolute = 0) => {
  if (Math.abs(actual - expected) > Math.max(absolute, relative * Math.abs(expected))) fail(`${label} differs from the prepared input.`);
};
const vector = (element: Element, length: number) => {
  const tokens = (element.textContent?.trim() ?? "").split(/\s+/);
  if (tokens.length !== length) return fail(`Invalid vector size in ${element.tagName}.`);
  return tokens.map(value => real(value, element.tagName));
};
function xmlDocument(source: string) {
  if (/<!\s*(?:DOCTYPE|ENTITY)/i.test(source)) fail("XML document types and entities are unsupported.");
  const doc = new DOMParser().parseFromString(source, "application/xml"), root = doc.documentElement;
  if (doc.querySelector("parsererror") || root.localName !== "espresso" || root.namespaceURI !== "http://www.quantum-espresso.org/ns/qes/qes-1.0") fail("Choose a complete QE data-file-schema.xml file.");
  equal(root.getAttribute("Units"), "Hartree atomic units", "QE XML units");
  const creator = node(root, "general_info/creator"), format = node(root, "general_info/xml_format");
  if (creator.getAttribute("NAME") !== "PWSCF" || creator.getAttribute("VERSION") !== "7.5" || format.getAttribute("NAME") !== "QEXSD" || format.getAttribute("VERSION") !== "25.05.21") fail("This reader supports PWSCF 7.5 with QEXSD 25.05.21. Other versions need a matching reader.");
  node(root, "closed");
  return root;
}

function checkSpecies(root: Element, expected: PreparedQe["manifest"], magneticSeeds: boolean) {
  const list = children(root, "species"); equal(Number(root.getAttribute("ntyp")), expected.pseudopotentials.length, "Species count");
  equal(list.length, expected.pseudopotentials.length, "Species inventory");
  list.forEach((item, index) => {
    const pseudo = expected.pseudopotentials[index], setting = expected.settings.species[index];
    equal(item.getAttribute("name"), pseudo.element, "Species order");
    equal(text(item, "pseudo_file"), pseudo.filename, "Pseudopotential filename");
    close(number(item, "mass"), setting.mass_amu, "Atomic mass");
    if (magneticSeeds && expected.settings.nspin === 2) close(number(item, "starting_magnetization"), setting.starting_magnetization!, "Starting spin fraction");
  });
}
function structure(root: Element, expected: PreparedQe["manifest"], matchPositions: boolean) {
  equal(Number(root.getAttribute("nat")), expected.candidate.atoms.length, "Atom count");
  const basis = ["a1", "a2", "a3"].map(axis => vector(node(root, `cell/${axis}`), 3));
  basis.forEach((row, i) => row.forEach((value, j) => close(value * BOHR_ANGSTROM, expected.cell_vectors_angstrom[i][j], "Fixed lattice vectors (angstrom)", 1e-8, 1e-8)));
  const rows = children(node(root, "atomic_positions"), "atom"); equal(rows.length, expected.candidate.atoms.length, "Atom inventory");
  return rows.map((row, index) => {
    const atom = expected.candidate.atoms[index]; equal(row.getAttribute("name"), atom.element, "Atom species order");
    equal(Number(row.getAttribute("index")), index + 1, "Atom index");
    const cartesian = vector(row, 3), z = cartesian[2] / basis[2][2], y = (cartesian[1] - z * basis[2][1]) / basis[1][1], x = (cartesian[0] - y * basis[1][0] - z * basis[2][0]) / basis[0][0];
    const fractional = [x, y, z];
    if (!fractional.every(Number.isFinite)) fail("Invalid fractional coordinates in QE XML.");
    if (matchPositions) fractional.forEach((value, j) => { const difference = value - atom.fractional[j]; if (Math.abs(difference - Math.round(difference)) > 1e-8) fail("Atomic positions differ from the prepared input."); });
    return { source_atom_id: atom.id, element: atom.element, fractional, cartesian_bohr: cartesian };
  });
}
const scalar = (root: Element, path: string, unit: string) => { const entry = nodeAt(root, path, true); if (!entry) return null; const raw = entry.textContent?.trim() ?? ""; return { raw, value: real(raw, path), unit, xml_path: `output/${path}` }; };

/** Reads native file reports only after the caller has reconstructed the preparation manifest. */
export function readQeNativeOutput(prepared: PreparedQe, kind: "execution" | "initialization", xml: string, stdout: string) {
  const expected = prepared.manifest, settings = expected.settings, root = xmlDocument(xml), input = node(root, "input"), output = node(root, "output");
  if ((stdout.match(/Program PWSCF\s+v\.7\.5\s+starts/g) ?? []).length !== 1 || (stdout.match(/JOB DONE\./g) ?? []).length !== 1 || /Error in routine|MPI_ABORT/i.test(stdout)) fail("Choose one complete PWSCF 7.5 stdout log without fatal engine errors.");
  const stdoutNumber = (pattern: RegExp, label: string) => {
    const matches = [...stdout.matchAll(pattern)];
    if (matches.length !== 1) return fail(`The stdout log needs one ${label} report.`);
    return real(matches[0][1], label);
  };
  equal(stdoutNumber(/number of atoms\/cell\s*=\s*(\d+)/g, "atom count"), expected.candidate.atoms.length, "Stdout atom count");
  equal(stdoutNumber(/number of atomic types\s*=\s*(\d+)/g, "species count"), expected.pseudopotentials.length, "Stdout species count");
  // Native stdout rounds this summary to two decimal places; XML carries the precise count.
  close(stdoutNumber(/number of electrons\s*=\s*([+\-\d.eEdD]+)/g, "electron count"), expected.expected_valence_electrons, "Stdout electron count", 0, 0.005000001);
  const control = node(input, "control_variables");
  equal(text(control, "calculation"), settings.calculation, "Calculation type");
  equal(text(control, "prefix"), `sclib_${expected.id.split(":")[1].slice(0, 16)}${kind === "initialization" ? "_check" : ""}`, "Run prefix");
  const nstep = number(control, "nstep"); equal(nstep, kind === "initialization" ? 0 : settings.calculation === "scf" ? 1 : settings.ionic_steps, "Step limit");
  equal(text(control, "restart_mode"), "from_scratch", "Restart mode");
  close(number(control, "max_seconds"), settings.max_seconds, "CPU limit");
  equal(bool(control, "forces"), true, "Force output"); equal(bool(control, "stress"), true, "Stress output");
  checkSpecies(node(input, "atomic_species"), expected, true); checkSpecies(node(output, "atomic_species"), expected, false);
  structure(node(input, "atomic_structure"), expected, true);
  const finalStructure = structure(node(output, "atomic_structure"), expected, kind === "initialization" || settings.calculation === "scf");
  equal(text(input, "dft/functional"), "PBE", "Input functional"); equal(text(output, "dft/functional"), "PBE", "Output functional");
  for (const parent of [input, output]) {
    if ([...node(parent, "dft").children].some(item => item.tagName !== "functional")) fail("Additional DFT corrections need a method-specific reader.");
  }
  for (const [path, flag] of [["lsda", settings.nspin === 2], ["noncolin", false], ["spinorbit", false]] as const) {
    equal(bool(input, `spin/${path}`), flag, "Input spin model");
    equal(bool(output, `magnetization/${path}`), flag, "Output spin model");
  }
  for (const [path, value] of [["basis/ecutwfc", settings.ecutwfc / 2], ["basis/ecutrho", settings.ecutrho / 2], ["bands/tot_charge", settings.charge], ["electron_control/conv_thr", settings.conv_thr / 2], ["electron_control/max_nstep", settings.electron_maxstep], ["electron_control/mixing_beta", settings.mixing_beta]] as const) close(number(input, path), value, path);
  equal(text(input, "bands/occupations"), "smearing", "Occupations"); equal(text(input, "bands/smearing"), settings.smearing, "Smearing method");
  close(real(node(input, "bands/smearing").getAttribute("degauss") ?? "", "degauss"), settings.degauss / 2, "Smearing width (Hartree)");
  close(number(output, "basis_set/ecutwfc"), settings.ecutwfc / 2, "Output wavefunction cutoff");
  close(number(output, "basis_set/ecutrho"), settings.ecutrho / 2, "Output density cutoff");
  equal(text(input, "electron_control/diagonalization"), "davidson", "Diagonalization");
  const grid = node(input, "k_points_IBZ/monkhorst_pack");
  [1, 2, 3].forEach((axis, i) => { equal(Number(grid.getAttribute(`nk${axis}`)), settings.mesh[i], "K-point mesh"); equal(Number(grid.getAttribute(`k${axis}`)), settings.shifts[i], "K-point offsets"); });
  equal(text(input, "cell_control/cell_dynamics"), "none", "Fixed cell model");
  equal(text(input, "ion_control/ion_dynamics"), settings.calculation === "relax" ? "bfgs" : "none", "Ionic dynamics");
  if (settings.calculation === "relax") { close(number(control, "etot_conv_thr"), settings.etot_conv_thr / 2, "Ionic energy threshold"); close(number(control, "forc_conv_thr"), settings.forc_conv_thr / 2, "Force threshold"); }
  const converged = bool(output, "convergence_info/scf_conv/convergence_achieved");
  const scfSteps = integer(number(output, "convergence_info/scf_conv/n_scf_steps"), "SCF steps");
  const scfError = number(output, "convergence_info/scf_conv/scf_error");
  if (scfError < 0 || scfSteps > settings.electron_maxstep || (converged && (scfSteps === 0 || scfError > settings.conv_thr / 2 * (1 + 1e-8)))) fail("The XML convergence report conflicts with the declared electronic stopping threshold.");
  const exitStatus = integer(number(root, "exit_status"), "QE exit status");
  const ionic = nodeAt(output, "convergence_info/opt_conv", true);
  const ionicConverged = ionic ? bool(ionic, "convergence_achieved") : null;
  const ionicSteps = ionic ? integer(number(ionic, "n_opt_steps"), "Ionic steps") : null;
  if (ionicSteps !== null && ionicSteps > settings.ionic_steps) fail("The optimization step count exceeds the prepared limit.");
  if (ionicConverged && !converged) fail("The ionic and electronic convergence reports conflict.");
  if (settings.calculation === "relax" && !ionic) fail("The relaxation output is missing its optimization status.");
  if (kind === "initialization" && (scfSteps !== 0 || converged || ionicConverged === true || ![0, 255].includes(exitStatus))) fail("Initialization input conflicts with executed or converged output.");
  const initialized = kind === "initialization";
  const status = initialized ? "initialization_only" : exitStatus !== 0 ? "incomplete" : !converged ? "scf_not_converged" : settings.calculation === "relax" && !ionicConverged ? "ionic_not_converged" : settings.calculation === "relax" ? "relaxation_reported_converged" : "scf_reported_converged";
  const energy = initialized ? null : scalar(output, "total_energy/etot", "Hartree/cell");
  const fermi = initialized ? null : scalar(output, "band_structure/fermi_energy", "Hartree");
  const electrons = initialized ? null : scalar(output, "band_structure/nelec", "electrons/cell");
  if (electrons) close(electrons.value, expected.expected_valence_electrons, "Output valence electrons");
  if (!initialized && converged && (!energy || !electrons)) fail("Converged output is missing total energy or the electron count.");
  if (converged) {
    const finals = [...stdout.matchAll(/!\s+total energy\s*=\s*([+\-\d.eEdD]+)\s+Ry/g)];
    if (!finals.length) fail("The stdout log has no converged total-energy report.");
    close(real(finals.at(-1)![1], "stdout total energy"), energy!.value * 2, "XML/stdout total energy", 0, 1e-8);
    const iterations = [...stdout.matchAll(/convergence has been achieved in\s+(\d+)\s+iterations/g)];
    if (!iterations.length || Number(iterations.at(-1)![1]) !== scfSteps) fail("The stdout and XML convergence iteration counts differ.");
    if (ionicConverged) {
      const steps = [...stdout.matchAll(/bfgs converged in\s+\d+\s+scf cycles and\s+(\d+)\s+bfgs steps/g)];
      if (!steps.length || Number(steps.at(-1)![1]) !== ionicSteps) fail("The stdout and XML optimization step counts differ.");
    }
  }
  if (initialized && (nodeAt(output, "total_energy", true) || /!\s+total energy/.test(stdout))) fail("Initialization files contain a conflicting final energy.");
  const forceNode = initialized ? null : nodeAt(output, "forces", true);
  const forces = forceNode ? vector(forceNode, expected.candidate.atoms.length * 3) : null;
  if (forceNode && (forceNode.getAttribute("rank") !== "2" || forceNode.getAttribute("dims")?.trim().split(/\s+/).join(" ") !== `3 ${expected.candidate.atoms.length}`)) fail("Unexpected force array dimensions.");
  const stressNode = initialized ? null : nodeAt(output, "stress", true), stress = stressNode ? vector(stressNode, 9) : null;
  if (stressNode && (stressNode.getAttribute("rank") !== "2" || stressNode.getAttribute("dims")?.trim().split(/\s+/).join(" ") !== "3 3")) fail("Unexpected stress array dimensions.");
  const maximumForce = forces ? Math.max(...expected.candidate.atoms.map((_, i) => Math.hypot(...forces.slice(i * 3, i * 3 + 3)))) : null;
  return { status, engine: { name: "PWSCF", version: "7.5", xml_format: "QEXSD 25.05.21", xml_units: "Hartree atomic units", reported_exit_status: exitStatus,
    created_date: node(root, "general_info/created").getAttribute("DATE"), created_time: node(root, "general_info/created").getAttribute("TIME"),
    nprocs: integer(number(root, "parallel_info/nprocs"), "MPI processes"), nthreads: integer(number(root, "parallel_info/nthreads"), "threads") },
    convergence: { electronic_reported: converged, scf_steps: scfSteps, scf_error_hartree: initialized ? null : scfError, electronic_threshold_hartree: settings.conv_thr / 2,
      ionic_reported: ionicConverged, ionic_steps: ionicSteps, basis_sampling_convergence_established: false },
    observations: { total_energy: energy, fermi_energy: fermi, valence_electrons: electrons,
      forces: forces ? { values: forces, unit: "Hartree/bohr", layout: "atom-major xyz", maximum_atom_norm: maximumForce } : null,
      stress: stress ? { values: stress, unit: "Hartree/bohr^3", layout: "3 by 3 native tensor" } : null,
      final_atoms: initialized ? null : finalStructure },
    interpretation: "QE etot is a computational-cell energy with the selected smearing contribution. It is not formation energy, energy above hull or a measured thermodynamic free energy.",
    consistency: { prepared_geometry_checked: true, method_subset_checked: true, species_filenames_checked: true,
      stdout_energy_checked: converged, pseudopotential_execution_bytes_attested: false, execution_authenticated: false },
    scientific_scope: { target_temperature_k: null, target_pressure_gpa: null, stable_host_validated: false, phonons_calculated: false, tc_calculated: false,
      scientific_acceptance: false, ml_training_approved: false, database_write: false } };
}

export async function inspectQeResult(input: QeResultFiles) {
  const files = { manifest: copy(input.manifest, QE_RESULT_LIMITS.manifest, "manifest"), input: copy(input.input, QE_RESULT_LIMITS.input, "input"),
    xml: copy(input.xml, QE_RESULT_LIMITS.xml, "XML"), stdout: copy(input.stdout, QE_RESULT_LIMITS.stdout, "stdout") };
  if (!Array.isArray(input.pseudos) || !input.pseudos.length || input.pseudos.length > 8) fail("Select the original 1 to 8 UPF files.");
  const pseudos = input.pseudos.map(file => copy(file, UPF_BYTE_LIMIT, "UPF"));
  let manifest: PreparedQe["manifest"];
  try { manifest = JSON.parse(decode(files.manifest)); } catch { return fail("The preparation manifest is not valid JSON."); }
  if (!manifest || manifest.version !== QE_INPUT_VERSION || !manifest.construction_request || !manifest.candidate || !manifest.settings) fail("Choose an original SCLib Quantum ESPRESSO preparation manifest.");
  const batch = await generateCombinedCandidates(manifest.construction_request);
  const prepared = await prepareQeInput(batch, manifest.candidate.id, manifest.settings, pseudos);
  if (await qeFileSha256(files.manifest.bytes) !== prepared.sha256) fail("The manifest or UPF bytes do not match the reproducible preparation. Select the original files.");
  const inputHash = await qeFileSha256(files.input.bytes);
  const kind = inputHash === prepared.manifest.files.execution.sha256 ? "execution" : inputHash === prepared.manifest.files.initialization.sha256 ? "initialization" : fail("The input file differs from both original prepared decks.");
  const reading = readQeNativeOutput(prepared, kind, decode(files.xml), decode(files.stdout));
  const captured = await Promise.all(Object.entries(files).map(async ([role, file]) => ({ role, filename: file.name, bytes: file.bytes.length, sha256: await qeFileSha256(file.bytes) })));
  const report = { version: QE_RESULT_VERSION, input_kind: kind, preparation_id: prepared.manifest.id,
    candidate_id: prepared.manifest.candidate.id, candidate_cif_sha256: prepared.manifest.candidate.cif_sha256,
    parent_id: prepared.manifest.parent_id, composition: prepared.manifest.candidate.composition, source_reference: prepared.manifest.source_reference,
    settings: prepared.manifest.settings, pseudopotentials: prepared.manifest.pseudopotentials, files: captured,
    ...reading, authority: "Local file consistency reading; no authenticated execution receipt or scientific approval." };
  const json = JSON.stringify(report, null, 2) + "\n", sha256 = await coordinateSha256(json);
  return { report, json, sha256, filename: `sclib-qe-output-${sha256.slice(0, 16)}.json` };
}
export type QeResultReading = Awaited<ReturnType<typeof inspectQeResult>>;
