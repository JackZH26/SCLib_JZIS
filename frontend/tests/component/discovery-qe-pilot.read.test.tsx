/** Opt-in local reading of an actual coordinator capture. No solver or network.
 * Hash custody is kept separate from scientific or execution authentication.
 */
import { expect, test, vi } from "vitest";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync, renameSync, rmSync, chmodSync, lstatSync, realpathSync } from "node:fs";
import { basename, dirname, join, resolve, relative, sep } from "node:path";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { prepareResearchModel } from "@/lib/discovery-research-model";
import { inspectQeResultContext, type QeResultReading } from "@/lib/discovery-qe-result";
import { compareQeReadings } from "@/lib/discovery-qe-convergence";
import { verifyWorkspaceState } from "@/lib/discovery-research-workspace";
import * as cycle from "@/lib/discovery-research-cycle";

type FilePin = { path: string; bytes: number; sha256: string };
type Job = { id: string; directory: string; catalogue_state_id: string; strain_micro_percent: number; mesh: number[]; atom_count: number;
  lineage: Awaited<ReturnType<typeof prepareResearchModel>>["lineage"]; qe_preparation_id: string;
  execution_input: FilePin; initialization_input: FilePin; preparation_manifest: FilePin;
  pseudopotentials: { filename: string; sha256: string }[] };
type Step = { kind: "initialization" | "execution"; exit_code: number; timed_out: boolean; wall_seconds: number;
  input_sha256: string; stdout: FilePin; xml: FilePin | null; argv: string[]; mpirun_sha256: string; thread_environment: Record<string, string> };
type StepReading = { kind: Step["kind"]; reading: QeResultReading | null; reading_pin: FilePin | null; error: string | null; eligible: boolean };
type JobReading = { job: Job; receipt_pin: FilePin | null; steps: StepReading[]; step_receipts: Step[]; missing: boolean };
const hash = (value: string | Uint8Array) => createHash("sha256").update(value).digest("hex");
const json = (value: unknown) => JSON.stringify(value, null, 2) + "\n";
const PLAN = "1ea4ab79c7433d966f4ff393c4e8deda9adea6cc2cf7bcd42b6c65c0559da855";
const INVENTORY = "8d136014a5451461dfc77540c36fad76f1dda2fa227f3f63084ad6e586436e4e";
const PW = "1d66c7856f5d6b3cd9c66b8578e01512b16bbe907b4360e54234890712ccd6a1";
const enabled = process.env.SCLIB_QE_PILOT_READ_INPUT;

function local(base: string, path: string): Uint8Array {
  if (!/^[A-Za-z0-9_./-]+$/.test(path) || path.startsWith("/") || path.split("/").some(p => p === ".." || p === "")) throw new Error("Unsafe relative artifact path.");
  const target = resolve(base, path);
  const rel = relative(base, realpathSync(target));
  if (rel.startsWith(`..${sep}`) || rel === ".." || !lstatSync(target).isFile()) throw new Error("Artifact escaped its captured directory.");
  for (let p = target; p !== base; p = dirname(p)) if (lstatSync(p).isSymbolicLink()) throw new Error("Symlink artifact is unsupported.");
  if (lstatSync(target).size > 16 * 1024 * 1024) throw new Error("Artifact exceeds the local-reader limit.");
  return new Uint8Array(readFileSync(target));
}
function pinned(base: string, pin: FilePin) {
  const bytes = local(base, pin.path);
  expect(bytes.length).toBe(pin.bytes); expect(hash(bytes)).toBe(pin.sha256);
  return bytes;
}
const decode = (value: Uint8Array) => new TextDecoder("utf-8", { fatal: true }).decode(value);
const artifact = (pin: FilePin, version: string): cycle.ResearchArtifactPin => ({ artifact_id: pin.path, version, sha256: pin.sha256 });

test.skipIf(!enabled)("read actual nine-job pilot files and retain honest per-state decisions", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const request = JSON.parse(readFileSync(enabled!, "utf8")) as { bundle: string; capture: string; output: string; started_sha256: string; finished_sha256: string; runner_sha256: string; pw_sha256: string };
  const bundle = realpathSync(request.bundle), capture = realpathSync(request.capture), output = resolve(request.output), root = resolve(process.cwd(), "..");
  expect(existsSync(output)).toBe(false); expect(request.pw_sha256).toBe(PW);
  for (const key of ["started_sha256", "finished_sha256", "runner_sha256"] as const) expect(request[key]).toMatch(/^[a-f0-9]{64}$/);
  const planBytes = local(bundle, "pilot-plan.json"), inventoryBytes = local(bundle, "bundle-manifest.json");
  expect(hash(planBytes)).toBe(PLAN); expect(hash(inventoryBytes)).toBe(INVENTORY);
  const plan = JSON.parse(decode(planBytes)), inventory = JSON.parse(decode(inventoryBytes)) as { files: FilePin[]; pilot_plan: FilePin };
  for (const pin of [inventory.pilot_plan, ...inventory.files]) pinned(bundle, pin);
  expect(plan.predeclared_comparison).toMatchObject({ axis: "mesh", separate_study_per_catalogue_state: true,
    meshes: [[2, 2, 2], [4, 4, 4], [6, 6, 6]], tolerance: { value: 1e-4, unit: "Hartree/atom" } });
  const startedBytes = local(capture, "execution-started.json"), finishedBytes = local(capture, "execution-finished.json");
  expect(hash(startedBytes)).toBe(request.started_sha256); expect(hash(finishedBytes)).toBe(request.finished_sha256);
  const started = JSON.parse(decode(startedBytes)), finished = JSON.parse(decode(finishedBytes));
  const common = { version: "discovery-qe-pilot-execution/1.0.0", plan_sha256: PLAN, manifest_sha256: INVENTORY,
    pw_sha256: PW, runner_sha256: request.runner_sha256, scientific_acceptance: false, rps_score: null,
    execution_authentication: "coordinator_capture_not_formal_scientific_attestation" };
  expect(started).toMatchObject(common); expect(finished).toMatchObject(started);
  expect(Date.parse(finished.finished_at_utc)).toBeGreaterThanOrEqual(Date.parse(started.started_at_utc));
  expect(Number(started.cpu_max[0]) / Number(started.cpu_max[1])).toBeGreaterThan(0);
  expect(Number(started.cpu_max[0]) / Number(started.cpu_max[1])).toBeLessThanOrEqual(4);
  expect(started.memory_max_bytes).toBeGreaterThan(0); expect(started.memory_max_bytes).toBeLessThanOrEqual(12 * 2 ** 30);
  const jobs = plan.jobs as Job[];
  expect(jobs).toHaveLength(9); expect(new Set(jobs.map(j => j.id)).size).toBe(9);
  const captured = finished.jobs as Array<{ job_id: string; receipt_sha256: string; steps: number }>;
  expect(new Set(captured.map(j => j.job_id)).size).toBe(captured.length);
  expect(captured.every(j => jobs.some(p => p.id === j.job_id))).toBe(true);
  const catalogue = getResearchCatalogue(); expect(catalogue.version).toBe(plan.catalogue_version);
  mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
  const staging = mkdtempSync(join(dirname(output), ".reading-qe-pilot-")); chmodSync(staging, 0o700);
  const written: FilePin[] = [];
  const save = (path: string, value: string | Uint8Array): FilePin => {
    const target = join(staging, path); mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
    writeFileSync(target, value, { flag: "wx", mode: 0o600 });
    const pin = { path, bytes: readFileSync(target).length, sha256: hash(value) }; written.push(pin); return pin;
  };
  try {
    const planPin = save("custody/pilot-plan.json", planBytes);
    const startPin = save("custody/execution-started.json", startedBytes), finishPin = save("custody/execution-finished.json", finishedBytes);
    for (const path of ["scripts/read_discovery_qe_pilot.py", "frontend/tests/component/discovery-qe-pilot.read.test.tsx",
      "frontend/lib/discovery-qe-result.ts", "frontend/lib/discovery-qe-convergence.ts", "frontend/lib/discovery-research-cycle.ts",
      "frontend/lib/discovery-research-workspace.ts", "frontend/lib/discovery-research-model.ts"]) save(`reader-recipe/${path}`, readFileSync(join(root, path)));
    const results: JobReading[] = [];
    for (const job of jobs) {
      const selected = captured.find(row => row.job_id === job.id);
      if (!selected) {
        expect(existsSync(join(capture, job.directory, "execution-receipt.json"))).toBe(false);
        results.push({ job, receipt_pin: null, steps: [], step_receipts: [], missing: true }); continue;
      }
      const raw = local(capture, `${job.directory}/execution-receipt.json`); expect(hash(raw)).toBe(selected.receipt_sha256);
      const receipt = JSON.parse(decode(raw)); expect(receipt).toMatchObject({ ...started, job_id: job.id, catalogue_state_id: job.catalogue_state_id });
      expect(Date.parse(receipt.job_started_at_utc)).toBeGreaterThanOrEqual(Date.parse(started.started_at_utc));
      expect(Date.parse(receipt.job_finished_at_utc)).toBeLessThanOrEqual(Date.parse(finished.finished_at_utc));
      const receiptPin = save(`custody/${job.id}-execution-receipt.json`, raw);
      const steps = receipt.steps as Step[]; expect(steps).toHaveLength(selected.steps);
      expect(steps.map(s => s.kind)).toEqual(["initialization", "execution"].slice(0, steps.length)); expect(steps.length).toBeLessThanOrEqual(2);
      const readings: StepReading[] = [];
      for (const step of steps) {
        const input = job[`${step.kind}_input`]; expect(step.input_sha256).toBe(input.sha256);
        expect(step.stdout.path).toBe(`${job.directory}/${step.kind === "execution" ? "pw.out" : "initialization.out"}`);
        expect(Number.isInteger(step.exit_code)).toBe(true); expect(typeof step.timed_out).toBe("boolean");
        expect(step.wall_seconds).toBeGreaterThanOrEqual(0); expect(step.mpirun_sha256).toMatch(/^[a-f0-9]{64}$/);
        expect(step.thread_environment).toEqual({ OMP_NUM_THREADS: "1", OPENBLAS_NUM_THREADS: "1", MKL_NUM_THREADS: "1" });
        expect(step.argv.slice(1, 6)).toEqual(["--allow-run-as-root", "--bind-to", "core", "-np", "4"]);
        expect(step.argv.slice(-2)).toEqual(["-in", basename(input.path)]);
        const stdout = pinned(capture, step.stdout);
        if (!step.xml) { readings.push({ kind: step.kind, reading: null, reading_pin: null, error: "Native XML was not captured.", eligible: false }); continue; }
        expect(step.xml.path).toBe(`${job.directory}/${step.kind}.xml`); const xml = pinned(capture, step.xml);
        const files = { manifest: { name: basename(job.preparation_manifest.path), bytes: pinned(bundle, job.preparation_manifest) },
          input: { name: basename(input.path), bytes: pinned(bundle, input) }, xml: { name: basename(step.xml.path), bytes: xml },
          stdout: { name: basename(step.stdout.path), bytes: stdout }, pseudos: job.pseudopotentials.map(p => {
            const bytes = local(bundle, `${job.directory}/pseudo/${p.filename}`); expect(hash(bytes)).toBe(p.sha256); return { name: p.filename, bytes };
          }) };
        let reading: QeResultReading;
        try { reading = (await inspectQeResultContext(files)).reading; }
        catch (error) { readings.push({ kind: step.kind, reading: null, reading_pin: null, error: error instanceof Error ? error.message : String(error), eligible: false }); continue; }
        expect(reading.report.input_kind).toBe(step.kind); expect(reading.report.preparation_id).toBe(job.qe_preparation_id);
        expect(reading.report.candidate_id).toBe(job.lineage.generated_candidate_id);
        expect(reading.report.candidate_cif_sha256).toBe(job.lineage.generated_cif_sha256); expect(reading.report.settings.mesh).toEqual(job.mesh);
        if (step.kind === "initialization") { expect(reading.report.status).toBe("initialization_only"); expect(reading.report.observations.total_energy).toBeNull(); }
        const pin = save(`readings/${job.id}/${step.kind}.json`, reading.json); expect(pin.sha256).toBe(reading.sha256);
        readings.push({ kind: step.kind, reading, reading_pin: pin, error: null,
          eligible: step.kind === "execution" && step.exit_code === 0 && !step.timed_out && reading.report.status === "scf_reported_converged" });
      }
      results.push({ job, receipt_pin: receiptPin, steps: readings, step_receipts: steps, missing: false });
    }
    const studies: Array<Record<string, unknown>> = [];
    for (const stateId of [...new Set(jobs.map(j => j.catalogue_state_id))]) {
      const entries = results.filter(r => r.job.catalogue_state_id === stateId).sort((a, b) => a.job.mesh[0] - b.job.mesh[0]);
      expect(entries.map(e => e.job.mesh)).toEqual(plan.predeclared_comparison.meshes);
      const model = await prepareResearchModel(catalogue, stateId); entries.forEach(entry => expect(entry.job.lineage).toEqual(model.lineage));
      const tag = entries[0].job.id.replace(/^mgb2-al-/, "").replace(/-k2$/, "");
      const lineagePin = save(`studies/${tag}/model-lineage.json`, json(model.lineage));
      const selected = await cycle.researchStateFromCatalogue(catalogue, stateId);
      selected.structure = { artifact_id: model.candidateId, version: model.batch.version, sha256: model.lineage.generated_cif_sha256 };
      selected.conditions = { pressure_gpa: null, temperature_k: null, charge_state: 0, magnetic_state: "nonmagnetic" }; selected.relation_to_catalogue = "proposed_conditions";
      await verifyWorkspaceState(catalogue, stateId, selected);
      const aliases = catalogue.occurrences.filter(o => o.state_id === stateId);
      const execution = entries.map(e => e.steps.find(s => s.kind === "execution"));
      const ready = execution.every(e => e?.eligible) && entries.every(e => e.steps.find(s => s.kind === "initialization")?.reading?.report.status === "initialization_only"
        && e.step_receipts[0]?.exit_code === 0 && !e.step_receipts[0]?.timed_out);
      const readings = execution.flatMap(e => e?.reading ? [e.reading] : []);
      const input = cycle.createResearchCaseInput(selected, "geometry_construction");
      input.title = `Mg7AlB16 ${tag}: retained finite mesh review`;
      input.hypothesis = { statement: "This fixed, unrelaxed coordinate model may permit a resolved finite mesh sensitivity window before further method assessment.",
        competing_explanations: ["The retained mesh points resolve the declared finite window.", "Numerical sensitivity or an incomplete SCF prevents that interpretation."], critical_unknown: "Finite mesh sensitivity does not establish cutoff, smearing or physical convergence." };
      input.action = { ...input.action, kind: "computational_review", question: "Apply the pre-execution pilot plan to the retained outputs of this one coordinate state.",
        input_artifacts: [artifact(planPin, plan.schema_version), artifact(startPin, started.version), artifact(finishPin, finished.version), artifact(lineagePin, "discovery-research-model-lineage/1.0.0"),
          ...aliases.map(o => ({ artifact_id: o.id, version: catalogue.version, sha256: o.cif_sha256 })),
          ...entries.flatMap(e => e.receipt_pin ? [artifact(e.receipt_pin, started.version)] : []),
          ...readings.map(r => ({ artifact_id: r.filename, version: r.report.version, sha256: r.sha256 }))],
        prerequisites: [{ description: "Frozen input bytes, coordinator receipt pins and local coordinate replay agree.", status: "met" },
          { description: "All three same-state SCF readings are complete and electronically converged.", status: ready ? "met" : "unmet" }],
        numerical_protocol: { kind: "mesh", tolerance_hartree_per_atom: plan.predeclared_comparison.tolerance.value },
        branches: [{ id: "sampled_window", observable: "All three eligible points satisfy the declared finite-window tolerance.", decision: "continue", next_direction: "refine_method" },
          { id: "unresolved_window", observable: "A completed finite window exceeds tolerance or lacks SCF precision.", decision: "redirect", next_direction: "refine_method" },
          { id: "incomplete_native", observable: "A missing, failed, rejected or unconverged point prevents a three-point comparison.", decision: "redirect", next_direction: "refine_method" }] };
      let record = await cycle.prepareResearchCase(input);
      const preparedExport = await cycle.exportResearchCase(record); save(`studies/${tag}/case-prepared.json`, preparedExport.json);
      let comparison: Awaited<ReturnType<typeof compareQeReadings>> | null = null, comparisonError: string | null = null;
      if (ready) { try { comparison = await compareQeReadings(readings, "mesh", plan.predeclared_comparison.tolerance.value); } catch (error) { comparisonError = error instanceof Error ? error.message : String(error); } }
      const facts = entries.map((e, i) => ({ job_id: e.job.id, mesh: e.job.mesh, missing_receipt: e.missing, status: execution[i]?.reading?.report.status ?? "not_read", eligible: execution[i]?.eligible ?? false,
        reader_error: execution[i]?.error ?? null, reading: execution[i]?.reading_pin ?? null, receipt: e.receipt_pin,
        steps: e.step_receipts.map(step => { const result = e.steps.find(s => s.kind === step.kind)!; return {
          kind: step.kind, exit_code: step.exit_code, timed_out: step.timed_out, wall_seconds: step.wall_seconds,
          input_sha256: step.input_sha256, stdout: step.stdout, xml: step.xml, status: result.reading?.report.status ?? "not_read",
          reading: result.reading_pin, reader_error: result.error, comparison_eligible: result.eligible,
        }; }) }));
      const statusPin = save(`studies/${tag}/retained-status.json`, json({ version: "discovery-qe-pilot-state-reading/1.0.0", state_id: stateId, facts, comparison_error: comparisonError }));
      const note = "Post-run review of retained native files using the separately frozen pre-execution pilot plan; this case itself is not execution preregistration. QE etot includes the selected numerical smearing contribution (F = E - TS in the engine convention); it is not a measured thermodynamic free energy, hull energy or Tc. No cross-state energy ranking or scientific approval.";
      if (comparison) {
        save(`studies/${tag}/mesh-comparison.json`, comparison.json);
        record = await cycle.attachResearchReturn(record, await cycle.prepareQeStudyReturn(record, readings, { kind: "mesh", tolerance: plan.predeclared_comparison.tolerance.value }, note));
      } else record = await cycle.attachResearchReturn(record, { binding: record.binding, kind: "calculation_receipt_link", artifacts: [artifact(statusPin, "discovery-qe-pilot-state-reading/1.0.0"), artifact(finishPin, finished.version)],
        model_cif_sha256: model.lineage.generated_cif_sha256, findings: `${note} No three-point comparison was generated; inspect the pinned per-job statuses.`, remaining_unknowns: ["Missing or failed numerical points remain unresolved.", "Cutoff, smearing and physical convergence are unassessed."], numerical_assessment: "not_assessed", association: "researcher_linked_unverified" });
      const returnedExport = await cycle.exportResearchCase(record); save(`studies/${tag}/case-returned.json`, returnedExport.json);
      const branchId = !comparison ? "incomplete_native" : comparison.report.sampled_window.assessment === "sampled_window_within_tolerance" ? "sampled_window" : "unresolved_window";
      const branch = input.action.branches.find(b => b.id === branchId)!;
      record = await cycle.recordResearchDecision(record, { return_sha256: record.returns[0].return_sha256, branch_id: branch.id, decision: branch.decision, next_direction: branch.next_direction,
        reason: comparison ? `Retained outcome: ${comparison.report.sampled_window.assessment}. Review further method settings before physical interpretation.` : "An incomplete native study needs failure diagnosis and a revised bounded method plan; no numerical comparison is asserted." });
      const parentExport = await cycle.exportResearchCase(record); save(`studies/${tag}/case-decided.json`, parentExport.json);
      expect(await cycle.importResearchCase(parentExport.json)).toEqual(record);
      const next = cycle.createResearchCaseInput(selected, "geometry_construction");
      next.title = `Mg7AlB16 ${tag}: next method review`;
      next.action.question = comparison ? "Review the finite-window outcome and define a separately budgeted cutoff or smearing study before any new calculation." : "Review the retained incomplete outputs and engine limits before designing a separately budgeted replacement study.";
      next.action.input_artifacts = [artifact(statusPin, "discovery-qe-pilot-state-reading/1.0.0"), { artifact_id: parentExport.filename, version: "discovery-research-cycle-export/1.0.0", sha256: parentExport.sha256 }];
      const child = await cycle.deriveResearchCase(record, next), childExport = await cycle.exportResearchCase(child);
      save(`studies/${tag}/case-child.json`, childExport.json); expect(await cycle.importResearchCase(childExport.json)).toEqual(child);
      await verifyWorkspaceState(catalogue, stateId, child.definition.state); expect(child.returns).toEqual([]); expect(child.definition.evidence).toEqual(cycle.unknownResearchEvidence());
      studies.push({ catalogue_state_id: stateId, strain_micro_percent: entries[0].job.strain_micro_percent, facts,
        comparison_sha256: comparison?.sha256 ?? null, numerical_assessment: comparison?.report.sampled_window.assessment ?? "not_assessed",
        sampled_window: comparison?.report.sampled_window ?? null, decision: record.decision, parent_export_sha256: parentExport.sha256, child_export_sha256: childExport.sha256 });
    }
    const summary = { version: "discovery-qe-pilot-readback/1.0.0", read_at_utc: new Date().toISOString(), pilot_plan_sha256: PLAN, bundle_manifest_sha256: INVENTORY,
      execution_started_sha256: request.started_sha256, execution_finished_sha256: request.finished_sha256, runtime_pw_sha256: PW, runner_sha256: request.runner_sha256,
      custody: "Original frozen input bytes replayed locally against hashed coordinator-captured stdout/XML. Coordinator custody is not formal scientific attestation.",
      energy_scope: "Fixed unrelaxed models and numerical smearing; QE etot is not hull/formation energy, measured free energy, pressure assignment or Tc.",
      studies, authority: { scientific_acceptance: false, rps_score: null, published: false, database_write: false, execution_authenticated_by_reader: false },
      files: [...written] };
    const summaryPin = save("reading-summary.json", json(summary));
    save("SHA256SUMS", written.map(p => `${p.sha256}  ${p.path}`).join("\n") + "\n");
    renameSync(staging, output);
    console.log(JSON.stringify({ output, summary_sha256: summaryPin.sha256, studies: studies.map(s => ({ state: s.catalogue_state_id, assessment: s.numerical_assessment })) }));
  } catch (error) { rmSync(staging, { recursive: true, force: true }); throw error; }
}, 180000);
