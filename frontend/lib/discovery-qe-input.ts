import { generateCombinedCandidates, type CombinedBatch, type CombinedCandidate } from "@/lib/discovery-combined-candidates";
import { coordinateSha256 } from "@/lib/discovery-site-candidates";

export const QE_INPUT_VERSION = "discovery-qe-input/1.0.0";
export const UPF_BYTE_LIMIT = 8 * 1024 * 1024;
export type QeFile = { name: string; bytes: Uint8Array };
export type QeSettings = {
  calculation: "scf" | "relax"; ecutwfc: number; ecutrho: number;
  mesh: number[]; shifts: number[]; charge: number; nspin: 1 | 2;
  smearing: "mv" | "gaussian" | "fd"; degauss: number;
  conv_thr: number; electron_maxstep: number; mixing_beta: number; max_seconds: number;
  ionic_steps: number; etot_conv_thr: number; forc_conv_thr: number;
  species: Array<{ element: string; mass_amu: number; starting_magnetization: number | null }>;
};

const fail = (message: string): never => { throw new Error(message); };
function finite(value: number, min: number, max: number, label: string, integer = false) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) fail(`Check ${label}; allowed range is ${min} to ${max}${integer ? " (integers)" : ""}.`);
  return value;
}
const num = (value: number) => Object.is(value, -0) || Math.abs(value) < 1e-15 ? "0" : Number(value.toPrecision(15)).toString();
// Pass an owned byte view: older WebCrypto runtimes reject cross-realm ArrayBuffers.
export const qeFileSha256 = async (bytes: Uint8Array) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes)))).map(value => value.toString(16).padStart(2, "0")).join("");

/** Inspect exact local UPF bytes. This is a format/scope check, not a pseudopotential validation. */
export async function inspectQeUpf(file: QeFile) {
  const name = file.name, bytes = new Uint8Array(file.bytes);
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.upf$/i.test(name)) fail("Use a UPF filename containing only ASCII letters, numbers, underscores, dots and hyphens.");
  if (!bytes.length || bytes.length > UPF_BYTE_LIMIT) fail("Each UPF file must contain between 1 byte and 8 MiB.");
  let source: string;
  try { source = new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { return fail("UPF files must be UTF-8 XML."); }
  if (/<!\s*(?:DOCTYPE|ENTITY)/i.test(source)) fail("UPF XML declarations with document types or entities are unsupported.");
  const xml = new DOMParser().parseFromString(source, "application/xml");
  const root = xml.documentElement;
  const headers = [...root.children].filter(node => node.tagName === "PP_HEADER");
  if (xml.querySelector("parsererror") || root.tagName !== "UPF" || !/^2(?:\.|$)/.test(root.getAttribute("version") ?? "") || headers.length !== 1) fail("Choose a well-formed UPF 2 XML file with one PP_HEADER.");
  const header = headers[0];
  const attr = (key: string) => (header.getAttribute(key) ?? "").trim();
  const element = attr("element");
  if (!/^[A-Z][a-z]?$/.test(element)) fail("UPF element is missing or invalid.");
  const functional = attr("functional").replace(/\s+/g, " ").toUpperCase();
  if (!["PBE", "SLA PW PBX PBC"].includes(functional)) fail("This preparation workflow supports PBE UPF files only.");
  const relativistic = attr("relativistic").toLowerCase();
  if (!["scalar", "no"].includes(relativistic) || !["f", "false", ".false."].includes(attr("has_so").toLowerCase())) fail("Choose scalar-relativistic or nonrelativistic UPF files without spin-orbit coupling.");
  if (!["NC", "US", "USPP", "PAW"].includes(attr("pseudo_type").toUpperCase()) || !["f", "false", ".false."].includes(attr("is_coulomb").toLowerCase())) fail("A supported NC, US or PAW pseudopotential is required.");
  const parse = (raw: string) => /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$/.test(raw) ? Number(raw.replace(/[dD]/, "e")) : NaN;
  const valence = finite(parse(attr("z_valence")), 0.000001, 118, "UPF valence electron count");
  const recommendation = (key: string) => { const value = parse(attr(key)); return Number.isFinite(value) && value > 0 ? value : null; };
  return { filename: name, sha256: await qeFileSha256(bytes), byte_length: bytes.length, element, functional: "PBE" as const,
    raw_functional: attr("functional"), relativistic, pseudo_type: attr("pseudo_type"), valence_electrons: valence,
    header_cutoffs_ry: { wavefunction: recommendation("wfc_cutoff"), charge_density: recommendation("rho_cutoff") },
    provenance: "User-selected local bytes; provider and license are not independently established." };
}
export type QePseudo = Awaited<ReturnType<typeof inspectQeUpf>>;

export function qeCellVectors(cell: CombinedCandidate["cell"]) {
  const { a, b, c, alpha, beta, gamma } = cell, rad = Math.PI / 180;
  const cx = c * Math.cos(beta * rad);
  const cy = c * (Math.cos(alpha * rad) - Math.cos(beta * rad) * Math.cos(gamma * rad)) / Math.sin(gamma * rad);
  const cz = Math.sqrt(c * c - cx * cx - cy * cy);
  if (![a, b, c, cz].every(value => Number.isFinite(value) && value > 0)) fail("The candidate cell has an invalid Cartesian basis.");
  return [[a, 0, 0], [b * Math.cos(gamma * rad), b * Math.sin(gamma * rad), 0], [cx, cy, cz]];
}

function validateSettings(settings: QeSettings, candidate: CombinedCandidate, pseudos: QePseudo[]) {
  if (!["scf", "relax"].includes(settings.calculation)) fail("Choose SCF or fixed-cell ionic relaxation.");
  finite(settings.ecutwfc, 1, 5000, "wavefunction cutoff (Ry)");
  finite(settings.ecutrho, settings.ecutwfc, 20000, "charge-density cutoff (Ry)");
  for (const [values, label, min, max] of [[settings.mesh, "k-point mesh", 1, 64], [settings.shifts, "k-point offsets", 0, 1]] as const) {
    if (!Array.isArray(values) || values.length !== 3) fail(`Specify all three ${label} values.`);
    values.forEach(value => finite(value, min, max, label, true));
  }
  finite(settings.charge, -96, 96, "cell charge (electrons removed)");
  if (![1, 2].includes(settings.nspin)) fail("Choose a spin model.");
  if (!["mv", "gaussian", "fd"].includes(settings.smearing)) fail("Choose a supported smearing method.");
  finite(settings.degauss, 1e-6, 1, "smearing width (Ry)");
  finite(settings.conv_thr, 1e-14, 0.01, "electronic convergence threshold (Ry)");
  finite(settings.electron_maxstep, 1, 2000, "electronic iteration limit", true);
  finite(settings.mixing_beta, 0.001, 1, "mixing beta");
  finite(settings.max_seconds, 1, 86400, "CPU time limit (seconds)");
  finite(settings.ionic_steps, 1, 1000, "ionic step limit", true);
  finite(settings.etot_conv_thr, 1e-12, 0.1, "ionic energy threshold (Ry)");
  finite(settings.forc_conv_thr, 1e-12, 0.1, "force threshold (Ry/bohr)");
  const elements = Object.keys(candidate.composition).sort();
  const sameElements = (items: Array<{ element: string }>) => items.length === elements.length && JSON.stringify(items.map(item => item.element).sort()) === JSON.stringify(elements);
  if (!sameElements(settings.species) || !sameElements(pseudos) || new Set(pseudos.map(item => item.filename)).size !== pseudos.length) fail("Provide exactly one mass entry and one uniquely named UPF file for each candidate element, with no extra elements.");
  for (const species of settings.species) {
    finite(species.mass_amu, 0.1, 500, `${species.element} atomic mass (u)`);
    if (settings.nspin === 1 && species.starting_magnetization !== null) fail("Spin-unpolarized inputs must not retain magnetic seeds.");
    if (settings.nspin === 2) finite(species.starting_magnetization as number, -0.999999, 0.999999, `${species.element} starting spin fraction`);
  }
  if (settings.nspin === 2 && settings.species.every(item => item.starting_magnetization === 0)) fail("Use a nonzero starting spin fraction for at least one species, or choose spin-unpolarized.");
  const electrons = pseudos.reduce((sum, item) => sum + item.valence_electrons * candidate.composition[item.element], 0) - settings.charge;
  if (!Number.isFinite(electrons) || electrons <= 0) fail("The chosen charge leaves no valence electrons.");
  return electrons;
}

/** Regenerate the coordinate proposal and re-read exact UPF bytes before constructing any deck. */
export async function prepareQeInput(batch: CombinedBatch, candidateId: string, input: QeSettings, files: QeFile[]) {
  const saved = structuredClone(batch), settings = structuredClone(input);
  if (!files.length || files.length > 8) fail("Select 1 to 8 local UPF files.");
  const originals = files.map(file => ({ name: file.name, bytes: new Uint8Array(file.bytes) }));
  const verified = await generateCombinedCandidates(saved.requested);
  if (JSON.stringify(saved) !== JSON.stringify(verified)) fail("The candidate batch differs from its reproducible source construction. Generate it again.");
  const candidate = verified.candidates.find(item => item.id === candidateId);
  if (!candidate) return fail("Choose a candidate from the current batch.");
  const pseudos = await Promise.all(originals.map(inspectQeUpf));
  pseudos.sort((a, b) => a.element.localeCompare(b.element, "en"));
  settings.species.sort((a, b) => a.element.localeCompare(b.element, "en"));
  const electrons = validateSettings(settings, candidate, pseudos);
  const basis = qeCellVectors(candidate.cell);
  const settingsHash = await coordinateSha256(JSON.stringify({ candidate_id: candidate.id, settings, pseudos, version: QE_INPUT_VERSION }));
  const prefix = `sclib_${settingsHash.slice(0, 16)}`;
  const deck = (dryRun: boolean) => [
    "! SCLib prepared input. Numerical convergence and physical state are not established.",
    `! Candidate: ${candidate.id}`, `! Candidate CIF SHA-256: ${candidate.cif_sha256}`,
    `! Input contract: ${QE_INPUT_VERSION}`, `! Settings and UPF metadata SHA-256: ${settingsHash}`,
    ...(dryRun ? ["! Initialization check only: nstep=0. No SCF or relaxation result."] : []),
    "&CONTROL", ` calculation = '${settings.calculation}',`, " restart_mode = 'from_scratch',",
    ` prefix = '${prefix}${dryRun ? "_check" : ""}',`, " pseudo_dir = './pseudo',", " outdir = './out',",
    ` nstep = ${dryRun ? 0 : settings.calculation === "scf" ? 1 : settings.ionic_steps},`,
    ` max_seconds = ${num(settings.max_seconds)},`, " tprnfor = .true.,", " tstress = .true.,",
    ...(settings.calculation === "relax" ? [` etot_conv_thr = ${num(settings.etot_conv_thr)},`, ` forc_conv_thr = ${num(settings.forc_conv_thr)},`] : []), "/",
    "&SYSTEM", " ibrav = 0,", ` nat = ${candidate.atoms.length},`, ` ntyp = ${pseudos.length},`,
    ` ecutwfc = ${num(settings.ecutwfc)},`, ` ecutrho = ${num(settings.ecutrho)},`, ` tot_charge = ${num(settings.charge)},`,
    ` nspin = ${settings.nspin},`, " noncolin = .false.,", " lspinorb = .false.,",
    ...(settings.nspin === 2 ? settings.species.map((item, i) => ` starting_magnetization(${i + 1}) = ${num(item.starting_magnetization!)},`) : []),
    " occupations = 'smearing',", ` smearing = '${settings.smearing}',`, ` degauss = ${num(settings.degauss)},`, "/",
    "&ELECTRONS", ` conv_thr = ${num(settings.conv_thr)},`, ` electron_maxstep = ${settings.electron_maxstep},`,
    ` mixing_beta = ${num(settings.mixing_beta)},`, " diagonalization = 'david',", " startingpot = 'atomic',", " startingwfc = 'atomic+random',", "/",
    ...(settings.calculation === "relax" ? ["&IONS", " ion_dynamics = 'bfgs',", "/"] : []),
    "ATOMIC_SPECIES", ...pseudos.map((item, i) => `${item.element} ${num(settings.species[i].mass_amu)} ${item.filename}`),
    "CELL_PARAMETERS angstrom", ...basis.map(vector => vector.map(num).join(" ")),
    "ATOMIC_POSITIONS crystal", ...candidate.atoms.map(atom => `${atom.element} ${atom.fractional.map(num).join(" ")}`),
    "K_POINTS automatic", `${settings.mesh.join(" ")} ${settings.shifts.join(" ")}`, "",
  ].join("\n");
  const executionInput = deck(false), initializationInput = deck(true);
  const warnings = pseudos.flatMap(item => {
    const warnings: string[] = [];
    if (item.header_cutoffs_ry.wavefunction && settings.ecutwfc < item.header_cutoffs_ry.wavefunction) warnings.push(`${item.element}: wavefunction cutoff is below the UPF header suggestion.`);
    if (item.header_cutoffs_ry.charge_density && settings.ecutrho < item.header_cutoffs_ry.charge_density) warnings.push(`${item.element}: charge-density cutoff is below the UPF header suggestion.`);
    return warnings;
  });
  const manifest = { version: QE_INPUT_VERSION, id: `qe-input:${settingsHash}`, candidate, parent_id: verified.parent_id,
    source_reference: verified.source_reference, construction_request: verified.requested, settings, pseudopotentials: pseudos,
    expected_valence_electrons: electrons, cell_vectors_angstrom: basis, warnings,
    files: { execution: { filename: `${prefix}.in`, sha256: await coordinateSha256(executionInput) }, initialization: { filename: `${prefix}-check.in`, sha256: await coordinateSha256(initializationInput) } },
    method: { engine: "Quantum ESPRESSO pw.x", documentation: "https://www.quantum-espresso.org/Doc/INPUT_PW.html", functional: "PBE from consistent UPF headers; no input_dft override",
      geometry: "Periodic 3D cell; fixed lattice vectors; ionic positions relaxed only if calculation=relax.",
      spin: "One type per element; collinear only; no same-element antiferromagnetic sublattices or spin-orbit coupling.",
      charge: "Positive tot_charge removes electrons; non-neutral periodic cells use a compensating homogeneous background.",
      smearing: "Numerical occupation broadening; not an assigned experimental temperature.",
      solver_defaults: "Unlisted pw.x options use the installed engine defaults. Capture its version and output for reproducibility." },
    scope: { status: "prepared_input", calculation_executed: false, initialization_checked: false, numerical_convergence_established: false,
      relaxed: false, energy_calculated: false, stability_validated: false, tc_calculated: false, scientific_acceptance: false,
      ml_training_approved: false, database_write: false, target_temperature_k: null, target_pressure_gpa: null },
    next_checks: ["Keep the exact selected UPF bytes in ./pseudo and verify every file hash.", "Run the separate nstep=0 initialization input with your installed pw.x.",
      "Capture engine version, execution command, resources, stdout and all input hashes.", "Converge basis, k mesh, smearing, bands and electronic/ionic thresholds for the chosen observable.",
      "Compare relevant structural, charge and magnetic states before interpreting stability or superconductivity."] };
  const json = JSON.stringify(manifest, null, 2) + "\n";
  return { executionInput, initializationInput, manifest, json, sha256: await coordinateSha256(json), filename: `${prefix}.json` };
}
export type PreparedQe = Awaited<ReturnType<typeof prepareQeInput>>;
