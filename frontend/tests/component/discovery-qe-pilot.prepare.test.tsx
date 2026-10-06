/** Opt-in preparation harness using real supplied UPFs; skipped during ordinary CI.
 * It prepares immutable local inputs only. It never invokes the solver or network.
 */
import { expect, test, vi } from "vitest";
import { webcrypto, createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync, renameSync, rmSync, chmodSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { prepareResearchModel } from "@/lib/discovery-research-model";
import { prepareQeInput, type QeSettings } from "@/lib/discovery-qe-input";

const hash = (bytes: string | Uint8Array) => createHash("sha256").update(bytes).digest("hex");
const enabled = process.env.SCLIB_QE_PILOT_PREPARE_INPUT;

test.skipIf(!enabled)("prepare the explicitly requested nine-job real-UPF Mg7AlB16 pilot", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const request = JSON.parse(readFileSync(enabled!, "utf8")) as { output: string; upfs: Record<"Mg" | "Al" | "B", string>; source_receipts: string[] };
  const output = resolve(request.output), root = resolve(process.cwd(), "..");
  expect(existsSync(output)).toBe(false);
  const upfs = (Object.keys(request.upfs) as Array<keyof typeof request.upfs>).map(element => {
    const bytes = new Uint8Array(readFileSync(request.upfs[element]));
    return { element, name: basename(request.upfs[element]), bytes, sha256: hash(bytes) };
  });
  // Official-library exact bytes already captured for this pilot, not synthetic test headers.
  const expectedHashes = { Mg: "c6420b82107b1fe96a798a0232093dacb0e0917dbb49bccbff5f845525b2810a", Al: "450c947cbbf30c33a5a77685bbe9a270947816f8a93837c02c749d0ee4e3ab4a", B: "4a41b06dfc361efde113fc033a06b9103e6d09df58f6f167c44b47e5ed082135" };
  upfs.forEach(file => expect(file.sha256).toBe(expectedHashes[file.element]));
  const catalogue = getResearchCatalogue();
  const states = catalogue.states.filter(state => state.formula === "Mg7AlB16").sort((a, b) => a.strain_micro_percent - b.strain_micro_percent);
  expect(states.map(s => s.strain_micro_percent)).toEqual([-2000000, 0, 2000000]);
  const written: Array<{ path: string; bytes: number; sha256: string }> = [];
  mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
  const staging = mkdtempSync(join(dirname(output), ".preparing-qe-pilot-")); chmodSync(staging, 0o700);
  const save = (path: string, content: string | Uint8Array) => {
    expect(path.startsWith("/") || path.includes("..")).toBe(false);
    const target = join(staging, path); mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
    writeFileSync(target, content, { flag: "wx", mode: 0o600 });
    const actual = readFileSync(target); expect(hash(actual)).toBe(hash(content));
    const pin = { path, bytes: actual.length, sha256: hash(actual) }; written.push(pin); return pin;
  };
  const json = (value: unknown) => JSON.stringify(value, null, 2) + "\n";
  const jobs: Array<Record<string, unknown>> = [], recipeFiles: Array<Record<string, unknown>> = [];
  try {
    for (const path of [
      "scripts/prepare_discovery_qe_pilot.py", "frontend/tests/component/discovery-qe-pilot.prepare.test.tsx",
      "frontend/lib/discovery-research-model.ts", "frontend/lib/discovery-research-catalogue.ts", "frontend/lib/discovery-qe-input.ts",
      "frontend/lib/discovery-combined-candidates.ts", "frontend/lib/discovery-site-candidates.ts", "frontend/lib/discovery-structures.ts",
      "frontend/lib/discovery-qe-convergence.ts", "frontend/lib/discovery-qe-result.ts",
      "frontend/lib/discovery-research-catalogues/2026-10-06-retained-coordinate-proposals-v2.json",
      "frontend/lib/discovery-research-catalogues/2026-10-06-retained-coordinate-proposals-v2.pins.json",
      "frontend/public/research-pilots/discovery-structure-coordinates-2026-10-05.json",
    ]) recipeFiles.push(save(`recipe/${path}`, readFileSync(join(root, path))));
    const provenanceReceipts = request.source_receipts.map((path, index) => save(`source-receipts/${index}-${basename(path)}`, readFileSync(path)));
    for (const state of states) {
      const model = await prepareResearchModel(catalogue, state.id);
      const strainTag = state.strain_micro_percent === 0 ? "zero" : state.strain_micro_percent < 0 ? "minus02" : "plus02";
      const aliases = catalogue.occurrences.filter(o => o.state_id === state.id);
      save(`states/${strainTag}/lineage.json`, json(model.lineage));
      save(`states/${strainTag}/original-state.json`, json(state));
      for (const alias of aliases) save(`states/${strainTag}/original-${alias.cif_sha256.slice(0, 16)}.cif`, alias.cif_text);
      save(`states/${strainTag}/regenerated-batch.json`, json(model.batch));
      for (const size of [2, 4, 6]) {
        const settings: QeSettings = { calculation: "scf", ecutwfc: 60, ecutrho: 480, mesh: [size, size, size], shifts: [0, 0, 0], charge: 0, nspin: 1,
          smearing: "mv", degauss: 0.02, conv_thr: 1e-10, electron_maxstep: 100, mixing_beta: 0.3, max_seconds: 300,
          ionic_steps: 100, etot_conv_thr: 1e-4, forc_conv_thr: 1e-3,
          species: [{ element: "Mg", mass_amu: 24.305, starting_magnetization: null }, { element: "Al", mass_amu: 26.9815385, starting_magnetization: null }, { element: "B", mass_amu: 10.81, starting_magnetization: null }] };
        const prepared = await prepareQeInput(model.batch, model.candidateId, settings, upfs);
        expect(prepared.manifest.scope.calculation_executed).toBe(false);
        expect(prepared.manifest.expected_valence_electrons).toBe(121);
        expect(prepared.manifest.pseudopotentials.every(p => p.functional === "PBE" && p.pseudo_type === "PAW")).toBe(true);
        const id = `mgb2-al-${strainTag}-k${size}`, directory = `jobs/${id}`;
        const execution = save(`${directory}/${prepared.manifest.files.execution.filename}`, prepared.executionInput);
        const initialization = save(`${directory}/${prepared.manifest.files.initialization.filename}`, prepared.initializationInput);
        const manifest = save(`${directory}/${prepared.filename}`, prepared.json);
        expect(execution.sha256).toBe(prepared.manifest.files.execution.sha256);
        expect(initialization.sha256).toBe(prepared.manifest.files.initialization.sha256);
        expect(manifest.sha256).toBe(prepared.sha256);
        for (const upf of upfs) save(`${directory}/pseudo/${upf.name}`, upf.bytes);
        jobs.push({ id, directory, catalogue_state_id: state.id, catalogue_group_id: state.group_id, strain_micro_percent: state.strain_micro_percent,
          mesh: settings.mesh, atom_count: state.atoms.length, lineage: model.lineage, qe_preparation_id: prepared.manifest.id,
          execution_input: execution, initialization_input: initialization, preparation_manifest: manifest,
          pseudopotentials: prepared.manifest.pseudopotentials, warnings: prepared.manifest.warnings,
          execution_status: "not_run", execution_receipt: null, native_result: null });
      }
    }
    expect(jobs).toHaveLength(9);
    const plan = { schema_version: "discovery-qe-pilot-plan/1.0.0", id: "2026-10-06-mg7alb16-fixed-geometry-mesh-pilot",
      status: "prepared_not_executed", prepared_at_utc: new Date().toISOString(),
      repository_base_commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim(),
      source_identity_basis: "Exact copied recipe files and hashes bind local changes beyond the repository base commit.",
      catalogue_version: catalogue.version, requested_formula: "Mg7AlB16", recipe_files: recipeFiles, source_receipts: provenanceReceipts,
      model: { geometry: "Unrelaxed fixed source-derived coordinates; no pressure assigned.", charge: 0, nspin: 1, spin_orbit: false,
        functional: "PBE", pseudopotential_type: "PAW", expected_valence_electrons: 121,
        smearing_interpretation: "Marzari-Vanderbilt numerical broadening, not a temperature.",
        charge_and_spin_scope: "Explicit calculation model for this pilot; does not backfill the source proposal's unresolved physical state." },
      predeclared_comparison: { comparator_contract: "discovery-qe-sampled-convergence/1.0.0", axis: "mesh", separate_study_per_catalogue_state: true,
        meshes: [[2, 2, 2], [4, 4, 4], [6, 6, 6]], tolerance: { value: 1e-4, unit: "Hartree/atom" },
        energy_window: "(max E - min E) / 24 across all three mesh points of the same state", require_max_scf_error_per_atom_strictly_below_tolerance: true,
        incomplete_or_failed_runs: "No comparison result; retain the actual execution failure and unresolved points.",
        matched_inputs: "Same state/CIF, composition, UPFs, engine/version and all settings except mesh.",
        result_scope: "Finite sampled mesh sensitivity at fixed cutoffs and smearing. No infinite-mesh or joint convergence claim." },
      assigned_execution_bounds: { maximum_cpu_cores: 4, maximum_memory_gib: 12, total_wall_seconds: 3600,
        external_per_job_wall_seconds: 450, qe_max_seconds_per_input: 300, execution_order: "sequential", rps_campaign_budget: null,
        enforcement: "Coordinator must apply actual external CPU, memory and total-wall limits. QE max_seconds alone is not a wall watchdog." },
      exclusions: ["No cross-composition or cross-geometry absolute-energy ranking", "No relaxation, formation/hull energy, phonon stability or Tc calculation", "No ambient-pressure or room-temperature claim", "No scientific approval, RPS score, training authorization or production data write"],
      jobs, scope: { calculation_executed: false, initialization_checked: false, numerical_convergence_established: false, scientific_acceptance: false, database_write: false } };
    const planPin = save("pilot-plan.json", json(plan));
    save("bundle-manifest.json", json({ schema_version: "discovery-qe-pilot-files/1.0.0", pilot_plan: planPin, files: [...written] }));
    const sums = written.map(file => `${file.sha256}  ${file.path}`).join("\n") + "\n";
    writeFileSync(join(staging, "SHA256SUMS"), sums, { flag: "wx", mode: 0o600 });
    expect(existsSync(output)).toBe(false); renameSync(staging, output);
    console.log(JSON.stringify({ output, jobs: jobs.length, pilot_plan_sha256: planPin.sha256, prepared_not_executed: true }));
  } catch (error) { rmSync(staging, { recursive: true, force: true }); throw error; }
}, 120000);
