/** Explicit offline preparation: full real UPFs, no solver or network call. */
import { test, expect, vi } from "vitest";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, existsSync, mkdtempSync, renameSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { buildBatch12TaskPacks } from "@/lib/discovery-batch12-taskpacks";
import { prepareQeInput, type QeSettings } from "@/lib/discovery-qe-input";
const enabled = process.env.SCLIB_BATCH12_PREPARE_INPUT;
const hash = (b: string | Uint8Array) => createHash("sha256").update(b).digest("hex");
const pins = { Mg: "c6420b82107b1fe96a798a0232093dacb0e0917dbb49bccbff5f845525b2810a", Al: "450c947cbbf30c33a5a77685bbe9a270947816f8a93837c02c749d0ee4e3ab4a", B: "4a41b06dfc361efde113fc033a06b9103e6d09df58f6f167c44b47e5ed082135", C: "8a25fbf64c4fa257c68c01dc9a96e5b23c6a5ac0b09f45f271e1c946a65ed657" };
const masses = { Mg:24.305, Al:26.9815385, B:10.81, C:12.011 };
test.skipIf(!enabled)("prepare three paired studies and 36 real-UPF SCF decks", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const request = JSON.parse(readFileSync(enabled!, "utf8")) as { output: string; public_summary: string; upfs: Record<keyof typeof pins,string> };
  const output = resolve(request.output); expect(existsSync(output)).toBe(false);
  const files = (Object.keys(pins) as Array<keyof typeof pins>).map(element => {
    const bytes = new Uint8Array(readFileSync(request.upfs[element])); expect(hash(bytes)).toBe(pins[element]);
    return { element, name: basename(request.upfs[element]), bytes };
  });
  mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
  const staging = mkdtempSync(join(dirname(output), ".batch12-preparing-"));
  const written: Array<{ path: string; sha256: string; bytes: number }> = [];
  const json = (x: unknown) => JSON.stringify(x, null, 2) + "\n";
  const save = (path: string, data: string | Uint8Array) => {
    const target = join(staging, path); mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
    writeFileSync(target, data, { mode: 0o600, flag: "wx" });
    const bytes = readFileSync(target); const pin = { path, sha256: hash(bytes), bytes: bytes.length }; written.push(pin); return pin;
  };
  try {
    const p = await buildBatch12TaskPacks(), jobs: Array<Record<string,unknown>> = [];
    const planPin = save("factorial-plan.json", json(p));
    for (const path of ["frontend/lib/discovery-batch12-taskpacks.ts","frontend/lib/discovery-qe-input.ts","frontend/lib/discovery-combined-candidates.ts","frontend/lib/discovery-site-candidates.ts","frontend/lib/discovery-structures.ts","frontend/public/research-pilots/discovery-structure-coordinates-2026-10-05.json","frontend/tests/component/discovery-batch12.prepare.test.tsx"]) save(`recipe/${path}`, readFileSync(join(process.cwd(), "..", path)));
    for (const state of p.states) {
      const tag = `${state.role}-${state.strain_percent < 0 ? "minus" : "plus"}${Math.abs(state.strain_percent)}`;
      save(`states/${tag}.cif`, state.candidate.cif);
      const selected = files.filter(f => Object.hasOwn(state.candidate.composition, f.element));
      for (const mesh of p.protocol.meshes) {
        const settings: QeSettings = { calculation:"scf", ecutwfc:60, ecutrho:480, mesh, shifts:[0,0,0], charge:0, nspin:1,
          smearing:"mv", degauss:.02, conv_thr:1e-10, electron_maxstep:100, mixing_beta:.3, max_seconds:600,
          ionic_steps:100, etot_conv_thr:1e-5, forc_conv_thr:1e-4,
          species:selected.map(f => ({element:f.element,mass_amu:masses[f.element],starting_magnetization:null})) };
        const prepared = await prepareQeInput(p.batch, state.id, settings, selected);
        expect(prepared.manifest.candidate.atoms).toHaveLength(12); expect(prepared.manifest.scope.calculation_executed).toBe(false);
        const directory = `jobs/${tag}-k${mesh.join("x")}`;
        const execution = save(`${directory}/${prepared.manifest.files.execution.filename}`, prepared.executionInput);
        save(`${directory}/${prepared.manifest.files.initialization.filename}`, prepared.initializationInput);
        const manifest = save(`${directory}/${prepared.filename}`, prepared.json);
        for (const f of selected) save(`${directory}/pseudo/${f.name}`, f.bytes);
        jobs.push({ directory, state_id:state.id, role:state.role, strain_percent:state.strain_percent, mesh,
          composition:state.candidate.composition, execution_input:execution, preparation_manifest:manifest,
          expected_valence_electrons:prepared.manifest.expected_valence_electrons, status:"prepared_not_run", result:null });
      }
    }
    expect(jobs).toHaveLength(36);
    const manifest = { schema_version:"discovery-batch12-prepared-inputs/1.0.0", plan:planPin, studies:p.studies,
      scope:p.scope, protocol:p.protocol, upf_sha256:pins, jobs, files:[...written], calculation_executed:false,
      queueable:false, queue_blocker:"M4 acceptance and explicit per-job/campaign resource bounds remain unassigned." };
    const bundlePin = save("bundle-manifest.json", json(manifest));
    writeFileSync(join(staging,"SHA256SUMS"),written.map(f => `${f.sha256}  ${f.path}`).join("\n")+"\n",{mode:0o600,flag:"wx"});
    renameSync(staging,output);
    const summary = { ...manifest, files:undefined, bundle_manifest_sha256:bundlePin.sha256, private_bundle_path:undefined };
    mkdirSync(dirname(request.public_summary),{recursive:true}); writeFileSync(request.public_summary,json(summary));
    console.log(JSON.stringify({output,studies:3,states:12,jobs:36,manifest_sha256:bundlePin.sha256,executed:false}));
  } catch (error) { rmSync(staging,{recursive:true,force:true}); throw error; }
},120000);
