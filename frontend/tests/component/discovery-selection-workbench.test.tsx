import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverySelectionWorkbench } from "@/components/DiscoverySelectionWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { SCIENTIFIC_DISCLAIMER } from "@/lib/discovery-scientific";
import * as selection from "@/lib/discovery-selection";
import { verifiedFixture, wires as historicalWires } from "./helpers/discovery-selection-fixtures";
import { barrierRequest, syntheticV2Prepared, syntheticV2Registration } from "./helpers/discovery-main-barrier-fixtures";

vi.mock("@/lib/discovery-selection", async importOriginal => {
  const original = await importOriginal<typeof import("@/lib/discovery-selection")>();
  return { ...original, getSelectionAccess: vi.fn(), getSelectionContext: vi.fn(), prepareSelectionV2: vi.fn(),
    registerSelection: vi.fn(), getSelectionOutcome: vi.fn(),
    parseSelectionContext: vi.fn(original.parseSelectionContext), parsePreparedSelection: vi.fn(original.parsePreparedSelection),
    selectionSourceFromFile: vi.fn(original.selectionSourceFromFile) };
});
const request = barrierRequest(), chosen = request.choices[0];
const wires = { ...historicalWires, previewWire: syntheticV2Registration(historicalWires.previewWire),
  commitWire: syntheticV2Registration(historicalWires.commitWire), outcomeWire: syntheticV2Registration(historicalWires.outcomeWire) };
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function sourceFile() {
  const file = new File([wires.sourceWire], "canonical.json", { type: "application/json" });
  Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode(wires.sourceWire).buffer });
  return file;
}
beforeEach(async () => {
  vi.stubGlobal("crypto", webcrypto); vi.clearAllMocks();
  const original = await vi.importActual<typeof selection>("@/lib/discovery-selection");
  vi.mocked(selection.parseSelectionContext).mockImplementation(original.parseSelectionContext);
  vi.mocked(selection.parsePreparedSelection).mockImplementation(original.parsePreparedSelection);
  vi.mocked(selection.selectionSourceFromFile).mockImplementation(original.selectionSourceFromFile);
  vi.mocked(selection.getSelectionAccess).mockResolvedValue(wires.accessWire);
  vi.mocked(selection.getSelectionContext).mockResolvedValue(wires.contextWire);
  vi.mocked(selection.prepareSelectionV2).mockImplementation(async req => {
    expect(req.source).toEqual(request.source); expect(req.choices).toEqual(request.choices);
    return syntheticV2Prepared(req.request_key);
  });
  vi.mocked(selection.registerSelection).mockImplementation(async raw => JSON.parse(raw).dry_run ? wires.previewWire : wires.commitWire);
  vi.mocked(selection.getSelectionOutcome).mockResolvedValue(wires.outcomeWire);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
async function start() {
  render(<DiscoverySelectionWorkbench />);
  await screen.findByText(/Current curator access verified/);
}
function chooseFile() {
  fireEvent.change(screen.getByLabelText("Distribution package ID"), { target: { value: request.source.distribution_package_id } });
  fireEvent.change(screen.getByLabelText("Original public-bundle JSON file"), { target: { files: [sourceFile()] } });
}
async function inspect() {
  await start(); chooseFile(); fireEvent.click(screen.getByRole("button", { name: "Inspect frozen distribution" }));
  await screen.findByRole("region", { name: "Explicit representative choices" });
  await waitFor(() => expect(screen.getByLabelText("State and action assessment")).toBeEnabled());
}
function chooseRepresentative() {
  fireEvent.change(screen.getByLabelText("State and action assessment"), { target: { value: chosen.assessment_id } });
  fireEvent.change(screen.getByLabelText("Structure binding"), { target: { value: chosen.structure_id } });
  fireEvent.change(screen.getByLabelText("Selection rationale"), { target: { value: chosen.rationale } });
  fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "not_declared" } });
}
async function compile() {
  await inspect(); chooseRepresentative(); fireEvent.click(screen.getByRole("button", { name: "Compile scientific preview" }));
  await screen.findByRole("region", { name: "Compiled scientific preview" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Run registration rehearsal" })).toBeEnabled());
}
async function rehearse() {
  await compile(); fireEvent.click(screen.getByRole("button", { name: "Run registration rehearsal" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Register exact preview" })).toBeEnabled());
}
async function unknownCommit() {
  await rehearse(); vi.mocked(selection.registerSelection).mockRejectedValueOnce(new ApiError(0, null, "PRIVATE_CANARY"));
  fireEvent.click(screen.getByRole("button", { name: "Register exact preview" }));
  await screen.findByText(/Registration outcome is unknown/);
}

describe("curator Discovery selection workbench", () => {
  it("requires an explicit barrier choice and never preselects a category or basis", async () => {
    await inspect(); chooseRepresentative();
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "declared" } });
    expect(screen.getByLabelText("Main-barrier category")).toHaveValue("");
    expect(screen.getByLabelText("Main-barrier statement")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Main-barrier category"), { target: { value: "scientific_hypothesis" } });
    fireEvent.change(screen.getByLabelText("Main-barrier statement"), { target: { value: "A testable research hypothesis." } });
    fireEvent.change(screen.getByLabelText("Main-barrier rationale"), { target: { value: "Exact retained values require further interpretation." } });
    const basis = screen.getByRole("group", { name: "Exact main-barrier basis (choose 1–8)" });
    for (const checkbox of within(basis).getAllByRole("checkbox")) expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
    fireEvent.click(within(basis).getByRole("checkbox", { name: /Band gap \(band_gap\)/ }));
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeEnabled();
    expect(selection.prepareSelectionV2).not.toHaveBeenCalled(); expect(selection.registerSelection).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Main-barrier category"), { target: { value: "execution_constraint" } });
    expect(screen.getByLabelText("Main-barrier statement")).toHaveValue(""); expect(screen.getByLabelText("Main-barrier rationale")).toHaveValue("");
    for (const checkbox of within(screen.getByRole("group", { name: "Exact main-barrier basis (choose 1–8)" })).queryAllByRole("checkbox")) expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
  });
  it("invalidates declared statement, rationale and basis edits, and resets the barrier on context or cell changes", async () => {
    await inspect(); chooseRepresentative(); let preparedRaw = "";
    vi.mocked(selection.prepareSelectionV2).mockImplementation(async req => {
      preparedRaw = syntheticV2Prepared(req.request_key, req.choices[0].main_barrier); return preparedRaw;
    });
    vi.mocked(selection.registerSelection).mockImplementation(async raw => syntheticV2Registration(JSON.parse(raw).dry_run ? historicalWires.previewWire : historicalWires.commitWire, preparedRaw));
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "declared" } });
    fireEvent.change(screen.getByLabelText("Main-barrier category"), { target: { value: "scientific_hypothesis" } });
    fireEvent.change(screen.getByLabelText("Main-barrier statement"), { target: { value: "A testable research hypothesis." } });
    fireEvent.change(screen.getByLabelText("Main-barrier rationale"), { target: { value: "Exact retained values require further interpretation." } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Band gap \(band_gap\)/ }));
    async function previewAndRehearse() {
      fireEvent.click(screen.getByRole("button", { name: "Compile scientific preview" }));
      await screen.findByRole("region", { name: "Compiled scientific preview" });
      await waitFor(() => expect(screen.getByRole("button", { name: "Run registration rehearsal" })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: "Run registration rehearsal" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "Register exact preview" })).toBeEnabled());
    }
    await previewAndRehearse();
    expect(within(screen.getByRole("region", { name: "Compiled scientific preview" })).getByText("A testable research hypothesis.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Main-barrier statement"), { target: { value: "An edited statement." } });
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    await previewAndRehearse();
    fireEvent.change(screen.getByLabelText("Main-barrier rationale"), { target: { value: "An edited rationale." } });
    expect(screen.queryByRole("button", { name: "Register exact preview" })).not.toBeInTheDocument();
    await previewAndRehearse();
    fireEvent.click(screen.getByRole("checkbox", { name: /DOS at Fermi level \(dos_at_fermi\)/ }));
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Superfluid stiffness availability declaration"), { target: { value: "not_computed" } });
    expect(screen.getByLabelText("Main-barrier declaration")).toHaveValue("");
    expect(screen.queryByLabelText("Main-barrier statement")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "not_declared" } });
    fireEvent.change(screen.getByLabelText("State and action assessment"), { target: { value: "" } });
    expect(screen.queryByLabelText("Main-barrier declaration")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("State and action assessment"), { target: { value: chosen.assessment_id } });
    expect(screen.getByLabelText("Main-barrier declaration")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "not_declared" } });
    fireEvent.change(screen.getByLabelText("Structure binding"), { target: { value: "none" } });
    expect(screen.getByLabelText("Main-barrier declaration")).toHaveValue("");
  });
  it("does not upload on file choice, select a default assessment or conflate unset with explicit null", async () => {
    await start(); chooseFile(); expect(selection.getSelectionContext).not.toHaveBeenCalled(); expect(selection.prepareSelectionV2).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Inspect frozen distribution" }));
    await screen.findByLabelText("State and action assessment");
    expect(screen.getByLabelText("State and action assessment")).toHaveValue(""); expect(screen.getByLabelText("Structure binding")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("State and action assessment"), { target: { value: chosen.assessment_id } });
    expect(screen.getByLabelText("Selection rationale")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Structure binding"), { target: { value: "none" } });
    expect(screen.getByText(/0 matching results/)).toBeInTheDocument();
    expect(screen.getByLabelText("Selection rationale")).toBeEnabled();
    expect(selection.registerSelection).not.toHaveBeenCalled();
  });
  it("shows all eight native fields, all-unreviewed private preview and scope disclaimer; preserves zero and negative values", async () => {
    await compile();
    expect(screen.getByText(SCIENTIFIC_DISCLAIMER)).toBeInTheDocument();
    expect(screen.getByText(/same frozen campaign, budget, policy and release/)).toBeInTheDocument();
    const preview = screen.getByRole("region", { name: "Compiled scientific preview" });
    expect(within(preview).getByText("8 recorded; 0 scope accepted")).toBeInTheDocument();
    const expand = within(preview).getByRole("button", { name: /^Inspect / }); fireEvent.click(expand);
    expect(screen.getByRole("region", { name: /scientific details$/ })).toBeInTheDocument();
    expect(screen.getAllByText(/0 eV/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/-0.125 THz/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Unreviewed scientific result/).length).toBeGreaterThan(0);
    expect(screen.getByText(/The prepared representative is explicit/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close details" })); expect(expand).toHaveFocus();
    expect(screen.getByRole("button", { name: "Register exact preview" })).toBeDisabled();
    expect(selection.registerSelection).not.toHaveBeenCalled();
  });
  it("posts the byte-exact prepared commands only after a separate native rehearsal, and double clicks commit once", async () => {
    await rehearse(); const key = vi.mocked(selection.prepareSelectionV2).mock.calls[0][0].request_key;
    const expected = JSON.parse(syntheticV2Prepared(key));
    expect(selection.registerSelection).toHaveBeenNthCalledWith(1, expected.preview_json, expect.any(AbortSignal));
    const submit = screen.getByRole("button", { name: "Register exact preview" });
    act(() => { fireEvent.click(submit); fireEvent.click(submit); });
    await screen.findByRole("region", { name: "Verified registration receipt" });
    expect(selection.registerSelection).toHaveBeenCalledTimes(2);
    expect(selection.registerSelection).toHaveBeenNthCalledWith(2, expected.commit_json, expect.any(AbortSignal));
    expect(screen.getByLabelText("Distribution package ID")).toHaveValue("");
    expect(screen.queryByRole("region", { name: "Explicit representative choices" })).not.toBeInTheDocument();
    expect(selection.getSelectionOutcome).not.toHaveBeenCalled();
  });
  it("invalidates preview and rehearsal on edits and clears declarations and rationale when structure changes", async () => {
    await rehearse();
    fireEvent.change(screen.getByLabelText("Selection rationale"), { target: { value: "Updated choice" } });
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    const availability = screen.getByLabelText("Superfluid stiffness availability declaration");
    fireEvent.change(availability, { target: { value: "not_computed" } });
    fireEvent.change(screen.getByLabelText("Superfluid stiffness reason code"), { target: { value: "explicit_no_computation" } });
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeDisabled();
    const checks = screen.getAllByRole("checkbox", { hidden: true }); fireEvent.click(checks[0]);
    expect(screen.getByLabelText("Main-barrier declaration")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Main-barrier declaration"), { target: { value: "not_declared" } });
    expect(screen.getByRole("button", { name: "Compile scientific preview" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Structure binding"), { target: { value: "none" } });
    expect(screen.getByLabelText("Selection rationale")).toHaveValue("");
    expect(screen.queryByLabelText("Superfluid stiffness reason code")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Superfluid stiffness availability declaration")).toHaveValue("inventory");
  });
  it("does not turn a failed pre-submit access check into an unknown write", async () => {
    await rehearse(); vi.mocked(selection.getSelectionAccess).mockRejectedValueOnce(new ApiError(403, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Register exact preview" }));
    await screen.findByText(/Curator access changed/); expect(selection.registerSelection).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Original registration recovery" })).not.toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_CANARY/)).not.toBeInTheDocument();
  });
  it("clears private material content after an uncertain write and keeps 404 locked without retry", async () => {
    await unknownCommit();
    expect(screen.queryByRole("region", { name: "Explicit representative choices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Distribution package ID")).toHaveValue(""); expect(screen.getByLabelText("Distribution package ID")).toBeDisabled();
    expect(screen.getByLabelText("Original public-bundle JSON file")).toHaveValue("");
    expect(screen.queryByText(/PRIVATE_CANARY/)).not.toBeInTheDocument();
    vi.mocked(selection.getSelectionOutcome).mockRejectedValueOnce(new ApiError(404, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByText(/No original outcome was visible/);
    expect(screen.getByLabelText("Distribution package ID")).toBeDisabled(); expect(selection.registerSelection).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("region", { name: "Verified registration receipt" });
    expect(selection.registerSelection).toHaveBeenCalledTimes(2); expect(selection.getSelectionOutcome).toHaveBeenCalledTimes(2);
    expect(vi.mocked(selection.getSelectionOutcome).mock.calls[0][0]).toEqual(vi.mocked(selection.getSelectionOutcome).mock.calls[1][0]);
  });
  it("hides the locator on auth change, refuses another actor, and recovers under a new grant for the original actor", async () => {
    await unknownCommit(); const originalKey = vi.mocked(selection.prepareSelectionV2).mock.calls[0][0].request_key;
    act(() => notifyAuthChange()); expect(screen.queryByText(new RegExp(originalKey))).not.toBeInTheDocument();
    const access = JSON.parse(wires.accessWire), foreign = { ...access, actor_user_id: "00000000-0000-0000-0000-000000000000" };
    vi.mocked(selection.getSelectionAccess).mockResolvedValue(JSON.stringify(foreign));
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    await screen.findByText(/belongs to another account/);
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Distribution package ID")).toBeDisabled();
    vi.mocked(selection.getSelectionAccess).mockResolvedValue(JSON.stringify({ ...access, actor_grant_id: "00000000-0000-0000-0000-000000000001" }));
    act(() => notifyAuthChange()); fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    await screen.findByRole("button", { name: "Check original outcome" });
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("region", { name: "Verified registration receipt" });
    expect(selection.getSelectionOutcome).toHaveBeenCalledWith(expect.objectContaining({ actorId: access.actor_user_id, requestKey: originalKey }), expect.any(AbortSignal));
    expect(selection.registerSelection).toHaveBeenCalledTimes(2);
  });
  it("treats a malformed commit acknowledgement as unknown, not success", async () => {
    await rehearse(); vi.mocked(selection.registerSelection).mockResolvedValueOnce(wires.previewWire);
    fireEvent.click(screen.getByRole("button", { name: "Register exact preview" }));
    await screen.findByText(/Registration outcome is unknown/);
    expect(screen.queryByRole("region", { name: "Verified registration receipt" })).not.toBeInTheDocument();
  });
  it("abandons late prepared verification after session change", async () => {
    await inspect(); chooseRepresentative(); const late = deferred<selection.PreparedSelection>();
    vi.mocked(selection.parsePreparedSelection).mockImplementationOnce(() => late.promise);
    fireEvent.click(screen.getByRole("button", { name: "Compile scientific preview" }));
    await waitFor(() => expect(selection.parsePreparedSelection).toHaveBeenCalled());
    act(() => notifyAuthChange());
    await act(async () => { late.resolve((await verifiedFixture()).prepared); });
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Distribution package ID")).toHaveValue("");
  });
  it("clears page-hidden private content and does not recover or re-upload automatically", async () => {
    await rehearse(); act(() => window.dispatchEvent(new Event("pagehide")));
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Distribution package ID")).toHaveValue("");
    expect(selection.getSelectionOutcome).not.toHaveBeenCalled(); expect(selection.prepareSelectionV2).toHaveBeenCalledTimes(1);
  });
  it.each(["context", "prepared"] as const)("times out stalled %s verification, releases busy state and discards late resolution", async mode => {
    const f = await verifiedFixture(); await (mode === "context" ? start() : inspect());
    if (mode === "context") chooseFile(); else chooseRepresentative();
    const late = deferred<any>();
    if (mode === "context") {
      vi.mocked(selection.selectionSourceFromFile).mockResolvedValueOnce(request.source);
      vi.mocked(selection.parseSelectionContext).mockImplementationOnce(() => late.promise);
    } else vi.mocked(selection.parsePreparedSelection).mockImplementationOnce(() => late.promise);
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: mode === "context" ? "Inspect frozen distribution" : "Compile scientific preview" })); });
    expect(screen.getByRole("button", { name: "Refresh curator access" })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(55_001); });
    expect(screen.getByRole("button", { name: "Refresh curator access" })).toBeEnabled();
    expect(screen.getByRole("alert")).toHaveTextContent(selection.SELECTION_FAILURE);
    await act(async () => { late.resolve(mode === "context" ? f.context : f.prepared); });
    expect(screen.queryByRole("region", { name: "Compiled scientific preview" })).not.toBeInTheDocument();
    if (mode === "context") expect(screen.queryByRole("region", { name: "Explicit representative choices" })).not.toBeInTheDocument();
  });
});
