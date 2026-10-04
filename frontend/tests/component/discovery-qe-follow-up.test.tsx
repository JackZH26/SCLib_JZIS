import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateCombinedCandidates } from "@/lib/discovery-combined-candidates";
import { prepareQeInput, type PreparedQe, type QeFile } from "@/lib/discovery-qe-input";
import { inspectQeResultContext, inspectQeResult, type QeResultContext } from "@/lib/discovery-qe-result";
import { canPrepareQeFollowUp, prepareQeFollowUp } from "@/lib/discovery-qe-follow-up";
import { DiscoveryQeInput } from "@/components/DiscoveryQeInput";

const source = (extension: string) => readFileSync(`tests/fixtures/qe-output/scf.${extension}`, "utf8");
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const file = (name: string, text: string): QeFile => ({ name, bytes: new TextEncoder().encode(text) });
// Header-only UPFs and changed native prefixes test the data flow, not physical execution.
async function inputs() {
  const old = JSON.parse(source("json")) as PreparedQe["manifest"];
  const pseudos = old.pseudopotentials.map(item => file(item.filename, `<UPF version="2.0.1"><PP_HEADER element="${item.element}" functional="PBE" relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" z_valence="${item.valence_electrons}"/></UPF>`));
  const batch = await generateCombinedCandidates(old.construction_request);
  const prepared = await prepareQeInput(batch, old.candidate.id, old.settings, pseudos);
  const prefix = (id: string) => `sclib_${id.split(":")[1].slice(0, 16)}`;
  return { manifest: file(prepared.filename, prepared.json), input: file(prepared.manifest.files.execution.filename, prepared.executionInput),
    xml: file("data-file-schema.xml", source("xml").replaceAll(prefix(old.id), prefix(prepared.manifest.id))), stdout: file("pw.out", source("out")), pseudos };
}
const context = async () => inspectQeResultContext(await inputs());
const resign = (v: QeResultContext) => { v.reading.json = JSON.stringify(v.reading.report, null, 2) + "\n"; v.reading.sha256 = sha(v.reading.json); };
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Reading to explicit next preparation", () => {
  it("preserves the original reading API and keeps binary files out of both exports", async () => {
    const files = await inputs(), restored = await inspectQeResultContext(files);
    expect(restored.reading).toEqual(await inspectQeResult(files));
    const next = await prepareQeFollowUp(restored, { ...restored.reading.report.settings, mesh: [8, 8, 8] }, "Check mesh sensitivity.");
    expect(next.prepared.manifest.candidate).toEqual(restored.preparation.prepared.manifest.candidate);
    expect(next.prepared.manifest.pseudopotentials).toEqual(restored.reading.report.pseudopotentials);
    expect(next.prepared.executionInput).toContain("K_POINTS automatic\n8 8 8 0 0 0");
    expect(next.lineage.record.settings_changes).toEqual([{ field: "mesh", before: [4, 4, 4], after: [8, 8, 8] }]);
    expect(next.lineage.record.previous_reading.report).toEqual(restored.reading.report);
    expect(next.lineage.record.next_preparation.sha256).toBe(sha(next.prepared.json));
    expect(next.lineage.sha256).toBe(sha(next.lineage.json));
    expect(next.lineage.record.scope).toMatchObject({ next_run_executed: false, wavefunction_restart: false, previous_results_inherited: false, cross_run_comparability_established: false, database_write: false });
    expect(next.lineage.json).not.toContain("<UPF"); expect(next.lineage.json).not.toContain('"pseudos"');
  });
  it("records charge, magnetic model, species and calculation changes without calling runs comparable", async () => {
    const prior = await context(), settings = structuredClone(prior.reading.report.settings);
    settings.calculation = "relax"; settings.charge = 1; settings.nspin = 2;
    settings.species.forEach(item => { item.starting_magnetization = 0.1; });
    const next = await prepareQeFollowUp(prior, settings, "Test another electronic state.");
    expect(next.lineage.record.settings_changes.map(change => change.field).sort()).toEqual(["calculation", "charge", "nspin", "species"]);
    expect(next.prepared.manifest.expected_valence_electrons).toBe(8);
    expect(next.lineage.record.scope.cross_run_comparability_established).toBe(false);
  });
  it("keeps an intentional repeat distinct from changed settings", async () => {
    const prior = await context(), next = await prepareQeFollowUp(prior, prior.reading.report.settings, " Repeat to inspect reproducibility. ");
    expect(next.lineage.record.relation).toBe("repeat_preparation"); expect(next.lineage.record.settings_changes).toEqual([]);
    expect(next.prepared).toEqual(prior.preparation.prepared);
    expect(next.lineage.record.researcher_rationale).toBe("Repeat to inspect reproducibility.");
  });
  it.each(["", " ", "x".repeat(2001), "invalid\u0000note"])("requires a bounded explicit reason", async note => {
    const prior = await context(); await expect(prepareQeFollowUp(prior, prior.reading.report.settings, note)).rejects.toThrow(/Describe why/);
  });
  it("does not silently discard relaxed coordinates or promote initialization output", async () => {
    for (const edit of [(v: QeResultContext) => { v.reading.report.settings.calculation = "relax"; }, (v: QeResultContext) => { v.reading.report.input_kind = "initialization"; }]) {
      const prior = await context(); edit(prior); expect(canPrepareQeFollowUp(prior)).toBe(false);
      await expect(prepareQeFollowUp(prior, prior.reading.report.settings, "Next")).rejects.toThrow(/original fixed-geometry/);
    }
  });
  it("can prepare a corrective run after electronic nonconvergence", async () => {
    const files = await inputs(); files.xml.bytes = new TextEncoder().encode(new TextDecoder().decode(files.xml.bytes).replace('<convergence_achieved>true', '<convergence_achieved>false'));
    const prior = await inspectQeResultContext(files); expect(prior.reading.report.status).toBe("scf_not_converged");
    const next = await prepareQeFollowUp(prior, { ...prior.reading.report.settings, electron_maxstep: 150 }, "Allow more iterations after examining the failure.");
    expect(next.lineage.record.previous_reading.report.status).toBe("scf_not_converged");
  });
  it("rejects stale or mismatched original settings, candidate geometry, file pins and UPF bytes", async () => {
    const changes = [
      (v: QeResultContext) => { v.reading.json += " "; },
      (v: QeResultContext) => { v.reading.report.candidate_id = "other"; resign(v); },
      (v: QeResultContext) => { v.reading.report.settings.mesh = [6, 6, 6]; resign(v); },
      (v: QeResultContext) => { v.reading.report.files[0].sha256 = "0".repeat(64); resign(v); },
      (v: QeResultContext) => { v.preparation.prepared.manifest.candidate.atoms[0].fractional[0] += 0.1; },
      (v: QeResultContext) => { v.preparation.pseudos[0].bytes[0] = 0; },
    ];
    for (const change of changes) { const prior = await context(); change(prior); await expect(prepareQeFollowUp(prior, prior.reading.report.settings, "Next")).rejects.toThrow(); }
  });
  it("freezes the entire prior context and requested settings before asynchronous checks", async () => {
    const prior = await context(), settings = structuredClone(prior.reading.report.settings);
    let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
    const original = crypto.subtle.digest.bind(crypto.subtle);
    vi.spyOn(crypto.subtle, "digest").mockImplementationOnce(async (...args) => { await gate; return original(...args); });
    const pending = prepareQeFollowUp(prior, settings, "Repeat");
    prior.preparation.pseudos[0].bytes.fill(0); prior.reading.report.candidate_id = "changed"; settings.charge = 7;
    release(); const result = await pending; expect(result.prepared.manifest.settings.charge).toBe(0);
    expect(result.lineage.record.previous_reading.report.candidate_id).not.toBe("changed");
  });
});

describe("Follow-up input interface", () => {
  it("restores exact controls and original files, records differences and clears a stale export on edit", async () => {
    const prior = await context();
    const create = vi.fn(() => "blob:followup"); Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<DiscoveryQeInput batch={prior.preparation.batch} candidateId={prior.reading.report.candidate_id} followUp={prior} />);
    expect(screen.getByLabelText("K-point mesh a")).toHaveValue(4);
    expect(screen.getByLabelText("Wavefunction cutoff (Ry)")).toHaveValue("60");
    expect(screen.getByLabelText("Al atomic mass (u)")).toHaveValue("26.9815385");
    expect(screen.queryByLabelText("UPF files")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare QE inputs", hidden: true })).toBeDisabled();
    fireEvent.click(screen.getByText("Prepare a follow-up calculation"));
    fireEvent.change(screen.getByLabelText("Reason for this follow-up"), { target: { value: "Check the next mesh." } });
    for (const axis of ["a", "b", "c"]) fireEvent.change(screen.getByLabelText(`K-point mesh ${axis}`), { target: { value: "8" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Prepare QE inputs" })));
    expect(await screen.findByText("[4,4,4] → [8,8,8]")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download follow-up record" })); expect(create).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Reason for this follow-up"), { target: { value: "Revised question" } });
    expect(screen.queryByRole("button", { name: "Download follow-up record" })).not.toBeInTheDocument();
  });
});
