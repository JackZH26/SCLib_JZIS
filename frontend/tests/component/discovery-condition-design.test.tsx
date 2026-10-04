import { webcrypto } from "node:crypto";
import { Blob as NodeBlob } from "node:buffer";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryConditionWorkspace } from "@/components/DiscoveryConditionWorkspace";
import { CONDITION_DESIGN_MAX_BYTES, CONDITION_STAGES, MODIFICATION_KINDS, conditionDesignPublication,
  createConditionDesignPlan, initialConditionDesign, type ConditionDesignInput } from "@/lib/discovery-condition-design";
import { SCIENTIFIC_KEYS, type ScientificReceipt } from "@/lib/discovery-scientific";
import fullWire from "../fixtures/discovery-scientific-full-eight.detail.wire.json";

// Historical, explicitly synthetic SQL-to-HTTP fixture. No real publication or
// scientific approval is performed by these local behavior tests.
const receipt = () => JSON.parse(fullWire) as ScientificReceipt;
function input(): ConditionDesignInput {
  return { ...initialConditionDesign(), hostLabel: "Synthetic host", stateLabel: "Synthetic doped state",
    modifications: [{ kind: "doping", parameters: "Synthetic site A, nominal x = 0.05 per formula unit" }],
    targetPressure: "ambient", temperatureK: "300", hypothesis: "Test whether this modification changes the normal-state bands.",
    nextAction: "Locate and review an exact structure before choosing a calculation." };
}
function fill() {
  openDesign();
  fireEvent.change(screen.getByLabelText("Proposed state label"), { target: { value: "Synthetic modified state" } });
  fireEvent.change(screen.getByLabelText("Modification 1 parameters"), { target: { value: "Synthetic site A, x = 0.05 per formula unit" } });
  fireEvent.change(screen.getByLabelText("Research hypothesis"), { target: { value: "Test a normal-state change, not a Tc prediction." } });
  fireEvent.change(screen.getByLabelText("Proposed next action"), { target: { value: "Inspect an exact source structure." } });
}
function openDesign() {
  const summary = screen.getByText("Outline a local research design");
  if (!summary.closest("details")!.open) fireEvent.click(summary);
}
async function prepareUI() {
  fill(); fireEvent.submit(screen.getByRole("form", { name: "Local condition-design hypothesis" }));
  return screen.findByRole("heading", { name: "Prepared local research plan" });
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("Bounded, reproducible local condition-design contract", () => {
  it("covers exactly the eight native fields without turning a stage into a verdict", () => {
    expect(CONDITION_STAGES.flatMap(s => s.fields).slice().sort()).toEqual(SCIENTIFIC_KEYS.slice().sort());
    expect(new Set(CONDITION_STAGES.flatMap(s => s.fields)).size).toBe(8);
    expect(Object.keys(MODIFICATION_KINDS)).toEqual(["doping", "substitution", "vacancy", "strain", "interface", "layer", "twist", "pressure"]);
  });
  it("reproduces the same plan, changes identity on a proposal edit, and remains a proposal without a source", async () => {
    const a = await createConditionDesignPlan(input()), b = await createConditionDesignPlan(input());
    expect(a.json).toBe(b.json); expect(a.plan.plan_id).toMatch(/^condition-design:[a-f0-9]{64}$/);
    expect(a.plan.source_basis).toBeNull(); expect(a.plan.user_proposal.target_conditions).toEqual({ pressure: { kind: "ambient_target", requested_atm: 1 }, temperature_k: 300, status: "requested_not_realized" });
    expect(a.plan.authority).toEqual({ database_changed: false, calculation_submitted: false, scientific_acceptance: false,
      ml_training_approved: false, genealogy_established: false, modified_state_result_inheritance: false, rps_reassessed: false });
    expect(a.plan).not.toHaveProperty("predicted_tc"); expect(a.plan).not.toHaveProperty("rps_score");
    expect(a.plan.work_plan.every(step => step.execution_status === "proposal_only")).toBe(true);
    expect((await createConditionDesignPlan({ ...input(), nextAction: "Different decision-changing action" })).plan.content_sha256).not.toBe(a.plan.content_sha256);
  });
  it("retains exact selected source/result/state/run/review pins while exporting only whitelisted publication context", async () => {
    const r = receipt(), original = structuredClone(r), row = r.payload.rows[0];
    const p = await createConditionDesignPlan({ ...input(), hostLabel: "Different hypothetical host" }, row, r);
    expect(p.plan.source_basis?.selected_row).toEqual(row);
    expect(p.plan.source_basis?.selected_row.cells.flatMap(c => c.observations).map(o => ({ property: o.property, state: o.state, run: o.run, review: o.review })))
      .toEqual(row.cells.flatMap(c => c.observations).map(o => ({ property: o.property, state: o.state, run: o.run, review: o.review })));
    expect(p.plan.source_basis?.publication).toEqual(conditionDesignPublication(r));
    expect(Object.keys(p.plan.source_basis!.publication!).sort()).toEqual(["package_id", "payload_sha256", "selection_sha256", "publication_sha256", "review_sha256", "release_id", "campaign_id", "campaign_version"].sort());
    expect(p.plan.source_basis).not.toHaveProperty("receipt"); expect(p.plan.source_basis).not.toHaveProperty("payload");
    expect(p.plan.source_basis?.selected_row.assessment.formula).toBe("TEST");
    expect(p.plan.user_proposal.host_label).toBe("Different hypothetical host"); expect(r).toEqual(original);
    expect(new TextEncoder().encode(p.json).length).toBeLessThanOrEqual(CONDITION_DESIGN_MAX_BYTES);
  });
  it("rejects a selected row from a different exact publication context", async () => {
    const r = receipt(), other = structuredClone(r.payload.rows[0]); other.state.row_sha256 = "a".repeat(64);
    await expect(createConditionDesignPlan(input(), other, r)).rejects.toThrow(/does not match this publication/);
  });
  it("rejects a supplied source row without its verified publication context", async () => {
    const r = receipt();
    await expect(createConditionDesignPlan(input(), r.payload.rows[0], null)).rejects.toThrow(/requires its verified publication context/);
  });
  it("hashes and exports the same detached source snapshot despite caller mutation during checksum", async () => {
    let complete!: () => Promise<void>;
    let hashedBytes!: Uint8Array;
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
      hashedBytes = new Uint8Array(bytes);
      return new Promise<ArrayBuffer>(resolve => { complete = async () => resolve(await webcrypto.subtle.digest(algorithm, hashedBytes)); });
    }) } });
    const r = receipt(), originalRow = structuredClone(r.payload.rows[0]), originalPublication = conditionDesignPublication(r);
    const pending = createConditionDesignPlan(input(), r.payload.rows[0], r);
    r.payload.rows[0].cells[0].observations[0].quantity.value = 999;
    r.payload.rows[0].state.row_sha256 = "a".repeat(64);
    r.publication_sha256 = "b".repeat(64);
    await complete();
    const result = await pending;
    expect(result.plan.source_basis?.selected_row).toEqual(originalRow);
    expect(result.plan.source_basis?.publication).toEqual(originalPublication);
    const { plan_id, content_sha256, ...exportedBody } = JSON.parse(result.json);
    expect(exportedBody).toEqual(JSON.parse(new TextDecoder().decode(hashedBytes)));
    const digest = Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", hashedBytes)), v => v.toString(16).padStart(2, "0")).join("");
    expect(content_sha256).toBe(digest); expect(plan_id).toBe(`condition-design:${digest}`);
  });
  it("does not copy source pressure or temperature into an unspecified user target", async () => {
    const r = receipt(), draft = { ...input(), targetPressure: "unspecified" as const, temperatureK: "" };
    const p = await createConditionDesignPlan(draft, r.payload.rows[0], r);
    expect(p.plan.user_proposal.target_conditions).toEqual({ pressure: { kind: "unspecified_target" }, temperature_k: null, status: "requested_not_realized" });
    expect(p.plan.source_basis?.selected_row.state_context.pressure_gpa).toBe(0);
  });
  it("preserves a source's signed zero in both the local digest and downloaded JSON", async () => {
    const r = receipt(); r.payload.rows[0].cells[0].observations[0].quantity.value = -0;
    const negative = await createConditionDesignPlan(input(), r.payload.rows[0], r);
    expect(Object.is(JSON.parse(negative.json).source_basis.selected_row.cells[0].observations[0].quantity.value, -0)).toBe(true);
    r.payload.rows[0].cells[0].observations[0].quantity.value = 0;
    expect((await createConditionDesignPlan(input(), r.payload.rows[0], r)).plan.content_sha256).not.toBe(negative.plan.content_sha256);
  });
  it("keeps EPC assumptions conditional and does not prescribe EPC for an unresolved or correlated route", async () => {
    const epc = await createConditionDesignPlan({ ...input(), pairingRoute: "epc" });
    expect(epc.plan.work_plan.find(s => s.stage === "pairing")?.requirements.join(" ")).toMatch(/α²F.*μ\*/);
    const unknown = await createConditionDesignPlan(input()), correlated = await createConditionDesignPlan({ ...input(), pairingRoute: "correlated" });
    expect(unknown.plan.work_plan.find(s => s.stage === "pairing")?.kind).toBe("source_review");
    expect(correlated.plan.work_plan.find(s => s.stage === "pairing")?.requirements.join(" ")).toMatch(/user hypothesis/);
    expect(correlated.plan.work_plan.find(s => s.stage === "pairing")?.requirements.join(" ")).not.toMatch(/before DFPT/);
  });
  it.each(["-1", "NaN", "Infinity", "0x10", "1e999", "1e-999"])("rejects unsafe target pressure %s without manufacturing zero", async pressureGpa => {
    await expect(createConditionDesignPlan({ ...input(), targetPressure: "specified", pressureGpa })).rejects.toThrow(/Target pressure/);
  });
  it("preserves an explicit zero target and arbitrary representable values without physical caps", async () => {
    const p = await createConditionDesignPlan({ ...input(), targetPressure: "specified", pressureGpa: "0", temperatureK: "1e4" });
    expect(p.plan.user_proposal.target_conditions.pressure).toEqual({ kind: "specified_target", requested_gpa: 0 });
    expect(p.plan.user_proposal.target_conditions.temperature_k).toBe(10000);
  });
  it.each([
    ["blank parameters", { modifications: [{ kind: "doping", parameters: " " }] }],
    ["unsupported modification", { modifications: [{ kind: "magic", parameters: "Unsupported" }] }],
    ["unbounded generation", { modifications: Array.from({ length: 9 }, (_, i) => ({ kind: "doping", parameters: String(i) })) }],
    ["duplicates", { modifications: [input().modifications[0], input().modifications[0]] }],
    ["missing hypothesis", { hypothesis: "" }], ["overlong text", { stateLabel: "x".repeat(201) }],
    ["unsupported solver", { pairingRoute: "universal" }], ["invalid target mode", { targetPressure: "observed" }],
  ])("rejects %s", async (_name, change) => {
    await expect(createConditionDesignPlan({ ...input(), ...change } as ConditionDesignInput)).rejects.toThrow();
  });
  it("fails the actual export bound rather than silently truncating source evidence", async () => {
    const r = receipt(); r.payload.rows[0].assessment.state_summary = "x".repeat(CONDITION_DESIGN_MAX_BYTES);
    await expect(createConditionDesignPlan(input(), r.payload.rows[0], r)).rejects.toThrow(/256 KiB/);
  });
});

describe("Discovery condition-design workspace behavior", () => {
  it("has an honest empty state and labeled native controls without fabricated results", () => {
    render(<DiscoveryConditionWorkspace />);
    expect(screen.getByRole("status")).toHaveTextContent(/No published material state selected/);
    expect(screen.queryByText("No selected record")).not.toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: /research question/ })).toHaveLength(4);
    expect(screen.getByText("Outline a local research design").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByLabelText("Pairing hypothesis")).toHaveValue("unresolved");
    expect(screen.getByLabelText("Target pressure")).toHaveValue("unspecified");
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.queryByText(/7,100/)).not.toBeInTheDocument();
  });
  it("withholds source results when publication context was not supplied", () => {
    const r = receipt(); render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} />);
    expect(screen.getByRole("status")).toHaveTextContent(/Source publication context is missing/);
    expect(screen.queryByText("0 eV · Computed")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Proposed host label")).toHaveValue("");
  });
  it("shows quantities and distinct scientific scopes, preserving the narrow phonon acceptance", () => {
    const r = receipt(); render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />);
    expect(screen.getByText("0 eV · Computed")).toBeInTheDocument();
    expect(screen.getByText("-0.125 THz · Computed")).toBeInTheDocument();
    expect(screen.getAllByText("Scientific result unreviewed")).toHaveLength(7);
    expect(screen.getByText("Accepted review: sampled phonon minimum only")).toBeInTheDocument();
    const scope = screen.getByText("Evidence scope and design-space limits");
    expect(scope.closest("details")).not.toHaveAttribute("open"); fireEvent.click(scope);
    expect(screen.getByText(/do not establish survival at 300 K/)).toBeVisible();
    expect(screen.getByLabelText("Proposed host label")).toHaveValue("TEST");
    expect(screen.getByLabelText("Proposed next action")).toHaveValue("");
  });
  it("distinguishes unknown, not computed, not applicable and conflicted availability without substituting zero", () => {
    const r = receipt();
    ["unknown", "not_computed", "not_applicable", "conflicted"].forEach((status, i) => {
      Object.assign(r.payload.rows[0].cells[i], { availability: status, observations: [], reason_code: "synthetic_declared_status" });
    });
    render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument(); expect(screen.getByText("Not computed (declared)")).toBeInTheDocument();
    expect(screen.getByText("Not applicable (declared)")).toBeInTheDocument(); expect(screen.getByText("Conflicted (declared)")).toBeInTheDocument();
  });
  it("supports form submission, accessible error recovery, focus and source-pin inspection", async () => {
    const r = receipt(); render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />);
    openDesign();
    const host = screen.getByLabelText("Proposed host label"); host.focus(); expect(host).toHaveFocus();
    fireEvent.submit(screen.getByRole("form", { name: "Local condition-design hypothesis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Proposed state label is required");
    const heading = await prepareUI(); await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const disclosure = screen.getByText("Inspect reproducible plan and source pins").closest("summary")!;
    disclosure.focus(); expect(disclosure).toHaveFocus(); fireEvent.click(disclosure);
    const json = screen.getByLabelText("Prepared condition-design JSON");
    expect(json).toHaveAttribute("tabindex", "0");
    expect(JSON.parse(json.textContent!).source_basis.selected_row.state).toEqual(r.payload.rows[0].state);
  });
  it("exports the displayed JSON through a native download and never sends network or storage writes", async () => {
    const r = receipt(), exported: NodeBlob[] = [], NativeURL = URL;
    const revoke = vi.fn();
    vi.stubGlobal("Blob", NodeBlob);
    vi.stubGlobal("URL", class extends NativeURL { static createObjectURL(blob: NodeBlob) { exported.push(blob); return "blob:condition-design"; } static revokeObjectURL = revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const storage = vi.spyOn(window.localStorage, "setItem");
    render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(exported).toHaveLength(1); expect(exported[0].type).toBe("application/json;charset=utf-8");
    const downloaded = await exported[0].text(), shown = screen.getByLabelText("Prepared condition-design JSON").textContent;
    expect(downloaded).toBe(shown); expect(JSON.parse(downloaded).source_basis.selected_row).toEqual(r.payload.rows[0]);
    expect(click).toHaveBeenCalledTimes(1); expect(fetch).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/JSON download requested/);
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:condition-design"), { timeout: 2000 });
  });
  it("keeps a prepared plan available after a browser download failure", async () => {
    const r = receipt(), NativeURL = URL;
    vi.stubGlobal("URL", class extends NativeURL { static createObjectURL() { throw new Error("Unavailable"); } });
    render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/could not start the JSON download/);
    expect(screen.getByRole("heading", { name: "Prepared local research plan" })).toBeInTheDocument();
  });
  it("invalidates prepared exports on any hypothesis edit or exact publication change", async () => {
    const r = receipt(), { rerender } = render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    fireEvent.change(screen.getByLabelText("Target temperature (K, optional)"), { target: { value: "300" } });
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    fireEvent.submit(screen.getByRole("form", { name: "Local condition-design hypothesis" })); await screen.findByRole("button", { name: "Export JSON" });
    const next = structuredClone(r); next.publication_sha256 = "b".repeat(64);
    rerender(<DiscoveryConditionWorkspace row={next.payload.rows[0]} receipt={next} />);
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Proposed state label")).toHaveValue(""); expect(screen.getByLabelText("Research hypothesis")).toHaveValue("");
  });
  it("clears the draft and source on pagehide instead of retaining an exportable stale source", async () => {
    const r = receipt(); render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    act(() => { window.dispatchEvent(new Event("pagehide")); });
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Proposed host label")).toHaveValue("");
    expect(screen.queryByText("0 eV · Computed")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/Source context and local draft cleared/);
  });
  it("clears on document hide and does not restore a source or draft on visibility return", async () => {
    const r = receipt(); render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Research hypothesis")).toHaveValue("");
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(screen.queryByText("0 eV · Computed")).not.toBeInTheDocument();
  });
  it("resets synchronously when the selected state changes within the same material", async () => {
    const r = receipt(), { rerender } = render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />); await prepareUI();
    const next = structuredClone(r); next.payload.rows[0].state.row_id = "00000000-0000-0000-0000-000000000002";
    rerender(<DiscoveryConditionWorkspace row={next.payload.rows[0]} receipt={next} />);
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Proposed state label")).toHaveValue("");
  });
  it("ignores a pending checksum finishing after source removal", async () => {
    let resolve!: (value: ArrayBuffer) => void;
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn(() => new Promise<ArrayBuffer>(yes => { resolve = yes; })) } });
    const r = receipt(), { rerender } = render(<DiscoveryConditionWorkspace row={r.payload.rows[0]} receipt={r} />);
    fill(); fireEvent.submit(screen.getByRole("form", { name: "Local condition-design hypothesis" }));
    expect(screen.getByRole("button", { name: "Preparing local plan…" })).toBeDisabled();
    rerender(<DiscoveryConditionWorkspace />);
    await act(async () => { resolve(new ArrayBuffer(32)); });
    expect(screen.queryByRole("button", { name: "Export JSON" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/No published material state selected/);
  });
  it("bounds the number of local modifications and permits removal without losing control labels", () => {
    render(<DiscoveryConditionWorkspace />);
    openDesign();
    for (let i = 1; i < 8; i++) fireEvent.click(screen.getByRole("button", { name: "Add modification" }));
    expect(screen.getByRole("button", { name: "Add modification" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove modification 2" }));
    expect(screen.getByRole("button", { name: "Add modification" })).toBeEnabled();
    expect(screen.getByLabelText("Modification 7 parameters")).toBeInTheDocument();
  });
});
