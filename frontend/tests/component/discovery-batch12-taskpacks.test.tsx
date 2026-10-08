import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { buildBatch12TaskPacks } from "@/lib/discovery-batch12-taskpacks";
import { prepareCombinedReferenceControl } from "@/lib/discovery-combined-candidates";
import { prepareQeInput, type QeSettings } from "@/lib/discovery-qe-input";
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());
test("factorial cases include the exact parent without increasing candidate or novelty counts", async () => {
  const p = await buildBatch12TaskPacks();
  expect(p.states).toHaveLength(12); expect(p.batch.candidates).toHaveLength(11); expect(p.studies).toHaveLength(3);
  expect(new Set(p.states.map(s => s.id)).size).toBe(12);
  for (const role of ["parent", "al_only", "c_only", "al_c"]) expect(p.states.filter(s => s.role === role).map(s => s.strain_percent)).toEqual([-2, 0, 2]);
  const parent = p.states.find(s => s.role === "parent" && s.strain_percent === 0)!.candidate;
  expect(parent.atoms).toEqual(p.batch.baseline.atoms); expect(parent.cell).toEqual(p.batch.baseline.cell);
  expect(parent.composition).toEqual({ Mg: 4, B: 8 }); expect(parent.nominal_change.changed_sites).toBe(0);
  expect(p.states.find(s => s.role === "al_c")!.candidate.composition).toEqual({ Al: 1, Mg: 3, C: 1, B: 7 });
  expect(p.studies.map(s => s.state_ids.length)).toEqual([6, 6, 12]);
  expect(p.scope.new_material_discovery).toBe(false); expect(p.protocol.auto_enqueue).toBe(false);
});
test("reference controls reject mutated source atoms and foreign identities before preparing decks", async () => {
  const p = await buildBatch12TaskPacks(), reference = await prepareCombinedReferenceControl(p.batch);
  const changed = structuredClone(p.batch); changed.baseline.atoms[0].element = "Li";
  await expect(prepareCombinedReferenceControl(changed)).rejects.toThrow(/reproducible/);
  const settings: QeSettings = { calculation: "scf", ecutwfc: 60, ecutrho: 480, mesh: [4,4,6], shifts: [0,0,0], charge: 0, nspin: 1,
    smearing: "mv", degauss: 0.02, conv_thr: 1e-10, electron_maxstep: 100, mixing_beta: 0.3, max_seconds: 600,
    ionic_steps: 50, etot_conv_thr: 1e-5, forc_conv_thr: 1e-4, species: [{element:"Mg",mass_amu:24.305,starting_magnetization:null},{element:"B",mass_amu:10.81,starting_magnetization:null}] };
  // Header-only fixtures test binding, never solver validity; actual packs use pinned full UPFs.
  const files = [["Mg",10],["B",3]].map(([e,v]) => ({ name: `${e}.UPF`, bytes: new TextEncoder().encode(`<UPF version="2.0.1"><PP_HEADER element="${e}" functional="PBE" relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" z_valence="${v}"/></UPF>`) }));
  const prepared = await prepareQeInput(p.batch, reference.id, settings, files);
  expect(prepared.manifest.candidate).toEqual(reference); expect(prepared.manifest.expected_valence_electrons).toBe(64);
  expect(prepared.manifest.files.execution.sha256).toBe(createHash("sha256").update(prepared.executionInput).digest("hex"));
  await expect(prepareQeInput(p.batch, "reference-control:foreign", settings, files)).rejects.toThrow(/current batch/);
  await expect(prepareQeInput(changed, reference.id, settings, files)).rejects.toThrow(/reproducible/);
});
