import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryQeStudyCase } from "@/components/DiscoveryQeStudyCase";
import * as cycle from "@/lib/discovery-research-cycle";
import type { ResearchCase, ResearchReturnInput, ResearchStateInput } from "@/lib/discovery-research-cycle";
import type { QeResultReading } from "@/lib/discovery-qe-result";

const sha = (text: string) => createHash("sha256").update(text).digest("hex");
function native(k: number, width = 0.02): QeResultReading {
  const stem = width === 0.02 ? `tests/fixtures/qe-convergence/k${k}-` : `tests/fixtures/qe-joint-refinement/k${k}-s${width}-`;
  const report = JSON.parse(readFileSync(`${stem}reading.json`, "utf8")), json = JSON.stringify(report, null, 2) + "\n", hash = sha(json);
  return { report, json, sha256: hash, filename: `sclib-qe-output-${hash.slice(0, 16)}.json` };
}
const mesh = () => [2, 4, 6].map(k => native(k));
async function original() {
  const first = native(2).report;
  const state: ResearchStateInput = { formula: "AlB2", host_formula: "MgB2", catalogue_reference: null,
    source_pins: [{ artifact_id: first.source_reference.id, version: String(first.source_reference.source.captured_revision), sha256: first.source_reference.source.file_sha256 }],
    structure: { artifact_id: first.candidate_id, version: "discovery-combined-site-candidates/1.0.0", sha256: first.candidate_cif_sha256 },
    modifications: [{ kind: "substitution", description: "Replace primitive Mg with Al." }, { kind: "strain", description: "Increase lattice lengths by 2%." }],
    conditions: { pressure_gpa: null, temperature_k: null, charge_state: 0, magnetic_state: "nonmagnetic" }, relation_to_catalogue: "source_reference" };
  return cycle.prepareResearchCase(cycle.createResearchCaseInput(state, "high_bandwidth"));
}
function Controlled({ initial, readings, emit }: { initial: ResearchCase; readings: QeResultReading[]; emit: (c: ResearchCase) => void }) {
  const [record, setRecord] = useState(initial);
  useEffect(() => setRecord(initial), [initial]);
  return <DiscoveryQeStudyCase record={record} readings={readings} onCase={next => { emit(next); setRecord(next); }} />;
}
const open = () => fireEvent.click(screen.getByText("Review QE numerical study"));
const prepare = () => fireEvent.click(screen.getByRole("button", { name: /^Prepare (?:follow-up )?study action$/ }));
const evaluate = () => fireEvent.click(screen.getByRole("button", { name: "Evaluate pinned readings" }));
const decide = () => fireEvent.click(screen.getByRole("button", { name: "Record study decision" }));
const count = (emit: ReturnType<typeof vi.fn>, n: number) => waitFor(() => expect(emit).toHaveBeenCalledTimes(n));
const last = (emit: ReturnType<typeof vi.fn>): ResearchCase => emit.mock.calls.at(-1)![0];
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("QE readings linked to a local research decision", () => {
  it("starts collapsed and pins real original readings before separately evaluating the retained AlB2 failure", async () => {
    const initial = await original(), readings = mesh(), emit = vi.fn(), comparison = vi.spyOn(cycle, "prepareQeStudyReturn");
    const ui = render(<Controlled initial={initial} readings={readings} emit={emit} />);
    expect(ui.container.querySelector("details")).not.toHaveAttribute("open");
    expect(ui.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    open(); expect(screen.getByLabelText("Energy tolerance (Hartree/atom)")).toHaveValue("1e-4");
    prepare(); await count(emit, 1);
    const pinned = last(emit);
    expect(comparison).not.toHaveBeenCalled();
    expect(pinned.binding.case_id).not.toBe(initial.binding.case_id);
    expect(pinned.definition.state).toEqual(initial.definition.state);
    expect(pinned.definition.action.input_artifacts).toEqual(readings.map(r => ({ artifact_id: r.filename, version: r.report.version, sha256: sha(r.json) })));
    expect(pinned.definition.action.numerical_protocol).toEqual({ kind: "mesh", tolerance_hartree_per_atom: 1e-4 });
    expect(pinned.definition.action.resources).toEqual({ access: "unconfirmed", cpu_hours: null, gpu_hours: null, memory_gib: null, storage_gib: null, human_hours: null });
    expect(pinned.authority).toMatchObject({ scientific_acceptance: false, rps_score: null, native_state_id: null });
    evaluate(); await count(emit, 2);
    expect(last(emit).returns[0]).toMatchObject({ numerical_assessment: "sampled_window_outside_tolerance", binding: pinned.binding });
    expect(screen.getByText("Sampled energy window exceeds tolerance")).toBeVisible();
    expect(screen.getByLabelText("Energy tolerance (Hartree/atom)")).toBeDisabled();
    expect(last(emit).returns[0].findings).toContain("not execution preregistration");
    decide(); await count(emit, 3);
    expect(last(emit).decision).toMatchObject({ branch_id: "unresolved_window", decision: "redirect", next_direction: "refine_method" });
    expect(last(emit).definition.evidence).toEqual(cycle.unknownResearchEvidence());
    expect(await cycle.importResearchCase((await cycle.exportResearchCase(last(emit))).json)).toEqual(last(emit));
  });

  it.each([
    ["0.02", "sampled_window_within_tolerance", "continue"],
    ["1e-10", "scf_precision_insufficient", "redirect"],
  ] as const)("uses existing readings at tolerance %s without advancing to physical interpretation", async (tolerance, assessment, decision) => {
    const initial = await original(), emit = vi.fn();
    render(<Controlled initial={initial} readings={mesh()} emit={emit} />); open();
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: tolerance } });
    prepare(); await count(emit, 1); evaluate(); await count(emit, 2); decide(); await count(emit, 3);
    expect(last(emit).returns[0].numerical_assessment).toBe(assessment);
    expect(last(emit).decision).toMatchObject({ decision, next_direction: "refine_method" });
  });

  it.each([
    ["full", "sampled_window_outside_tolerance", "redirect", "refine_method"],
    ["missing", "incomplete_grid", "redirect", "refine_method"],
    ["two_by_two", "insufficient_axis_samples", "stop", "pause"],
  ] as const)("preserves the %s joint mesh–smearing outcome", async (sample, assessment, decision, direction) => {
    const values = [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(w => native(k, w)));
    const readings = sample === "missing" ? values.slice(1) : sample === "two_by_two" ? values.filter(r => r.report.settings.mesh[0] !== 6 && r.report.settings.degauss !== 0.01) : values;
    const initial = await original(), emit = vi.fn();
    render(<Controlled initial={initial} readings={readings} emit={emit} />); open();
    fireEvent.change(screen.getByLabelText("Numerical study"), { target: { value: "mesh_smearing" } });
    prepare(); await count(emit, 1); evaluate(); await count(emit, 2); decide(); await count(emit, 3);
    expect(last(emit).returns[0].numerical_assessment).toBe(assessment);
    expect(last(emit).decision).toMatchObject({ decision, next_direction: direction });
  });

  it("creates a linked new case for revised settings and keeps the decided parent unchanged", async () => {
    const initial = await original(), emit = vi.fn();
    render(<Controlled initial={initial} readings={mesh()} emit={emit} />); open();
    prepare(); await count(emit, 1); evaluate(); await count(emit, 2); decide(); await count(emit, 3);
    const parent = last(emit), frozen = JSON.stringify(parent);
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.02" } });
    expect(screen.queryByRole("button", { name: "Evaluate pinned readings" })).not.toBeInTheDocument();
    prepare(); await count(emit, 4);
    const child = last(emit);
    expect(child.parent).toMatchObject({ case_id: parent.binding.case_id, decision_sha256: parent.decision!.decision_sha256, properties_inherited: false });
    expect(child.binding.case_id).not.toBe(parent.binding.case_id);
    expect(child.definition.action.numerical_protocol!.tolerance_hartree_per_atom).toBe(0.02);
    expect(child.returns).toEqual([]); expect(child.decision).toBeNull();
    expect(child.definition.evidence).toEqual(cycle.unknownResearchEvidence());
    expect(JSON.stringify(parent)).toBe(frozen);
  });

  it.each(["coordinates", "charge", "spin", "unknown_charge", "reading_bytes", "duplicate"])("rejects %s before publishing any prepared case", async problem => {
    let initial = await original(); const readings = mesh(), emit = vi.fn();
    const definition = structuredClone(initial.definition);
    if (problem === "coordinates") definition.state.structure!.sha256 = "0".repeat(64);
    if (problem === "charge") definition.state.conditions.charge_state = 1;
    if (problem === "spin") definition.state.conditions.magnetic_state = "spin_polarized";
    if (problem === "unknown_charge") definition.state.conditions.charge_state = null;
    if (problem === "reading_bytes") readings[1].json += " ";
    if (problem === "duplicate") readings[1] = readings[0];
    initial = await cycle.prepareResearchCase(definition);
    render(<Controlled initial={initial} readings={readings} emit={emit} />); open(); prepare();
    await screen.findByRole("alert"); expect(emit).not.toHaveBeenCalled();
  });

  it("leaves fixed-setting mismatches to the existing comparator, without inventing a return", async () => {
    const initial = await original(), emit = vi.fn(), readings = [native(2), native(4, 0.04), native(6)];
    render(<Controlled initial={initial} readings={readings} emit={emit} />); open();
    prepare(); await count(emit, 1); evaluate();
    expect(await screen.findByRole("alert")).toHaveTextContent("More than the selected parameter differs");
    expect(emit).toHaveBeenCalledTimes(1); expect(last(emit).returns).toEqual([]);
    expect(screen.queryByRole("button", { name: "Record study decision" })).not.toBeInTheDocument();
  });

  it("requires new preparation when settings change before evaluation", async () => {
    const initial = await original(), emit = vi.fn(), comparison = vi.spyOn(cycle, "prepareQeStudyReturn");
    render(<Controlled initial={initial} readings={mesh()} emit={emit} />); open();
    prepare(); await count(emit, 1); const old = last(emit);
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.02" } });
    expect(screen.queryByRole("button", { name: "Evaluate pinned readings" })).not.toBeInTheDocument();
    prepare(); await count(emit, 2);
    expect(last(emit).binding.case_id).not.toBe(old.binding.case_id);
    expect(old.definition.action.numerical_protocol!.tolerance_hartree_per_atom).toBe(1e-4);
    expect(comparison).not.toHaveBeenCalled();
  });
});

describe("Obsolete async study callbacks", () => {
  it.each(["case", "readings", "unmount"])("does not publish delayed preparation after %s changes", async change => {
    const initial = await original(), readings = mesh(), emit = vi.fn(), pending = deferred<ResearchCase>();
    const replacement = await cycle.prepareResearchCase({ ...initial.definition, title: "Another research case" });
    vi.spyOn(cycle, "prepareResearchCase").mockReturnValueOnce(pending.promise);
    const ui = render(<Controlled initial={initial} readings={readings} emit={emit} />); open(); prepare();
    await waitFor(() => expect(cycle.prepareResearchCase).toHaveBeenCalled());
    if (change === "unmount") ui.unmount();
    else ui.rerender(<Controlled initial={change === "case" ? replacement : initial} readings={change === "readings" ? [...readings] : readings} emit={emit} />);
    await act(async () => { pending.resolve(initial); await pending.promise; });
    expect(emit).not.toHaveBeenCalled();
  });

  it("discards an in-flight evaluation when the comparison is revised", async () => {
    const initial = await original(), emit = vi.fn(), readings = mesh(), pending = deferred<ResearchReturnInput>();
    render(<Controlled initial={initial} readings={readings} emit={emit} />); open(); prepare(); await count(emit, 1);
    const pinned = last(emit), result = await cycle.prepareQeStudyReturn(pinned, readings, { kind: "mesh", tolerance: 1e-4 }, "Existing native readings evaluated for this case.");
    const comparison = vi.spyOn(cycle, "prepareQeStudyReturn").mockReturnValueOnce(pending.promise);
    evaluate(); await waitFor(() => expect(comparison).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.02" } });
    await act(async () => { pending.resolve(result); await pending.promise; });
    expect(emit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Record study decision" })).not.toBeInTheDocument();
    expect(screen.queryByText("Sampled energy window exceeds tolerance")).not.toBeInTheDocument();
  });
});
