import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialsProposalReview } from "@/components/MaterialsProposalReview";
import { ApiError, materialsProposalCapabilities, materialsProposalDetail, materialsProposalEvidence, materialsProposalExport, materialsProposalExportFile, materialsProposalRuns } from "@/lib/api";
import { proposalAccess, proposalDetail, proposalEvidence, proposalExport, proposalQueue } from "@/lib/materials-proposal-review";
import { access, detail, evidence, exportDescriptor, queue, quote, run, heldSource } from "../helpers/materials-proposal-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialsProposalCapabilities: vi.fn(), materialsProposalDetail: vi.fn(), materialsProposalEvidence: vi.fn(), materialsProposalExport: vi.fn(), materialsProposalExportFile: vi.fn(), materialsProposalRuns: vi.fn() }));
function copy<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
async function select() {
  fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
  fireEvent.click(await screen.findByRole("button", { name: "I1 · tc" }));
  await screen.findByRole("heading", { name: "Captured source passages" });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(materialsProposalCapabilities).mockResolvedValue(copy(access));
  vi.mocked(materialsProposalRuns).mockResolvedValue(copy(queue));
  vi.mocked(materialsProposalDetail).mockResolvedValue(copy(detail));
  vi.mocked(materialsProposalEvidence).mockResolvedValue(copy(evidence));
  vi.mocked(materialsProposalExport).mockResolvedValue(copy(exportDescriptor));
  vi.mocked(materialsProposalExportFile).mockResolvedValue(new Uint8Array([80, 75, 3, 4]));
});

describe("Materials source review", () => {
  it("accepts versioned device-condition exports without granting authority", () => {
    const value = copy(exportDescriptor); value.version = "materials-proposal-export/5";
    value.run = { ...run, extraction_version: "materials-ner/15" };
    expect(proposalExport(value, value.run)).toEqual(value);
    value.authority.ml_training_eligible = true as false;
    expect(proposalExport(value, value.run)).toBeNull();
  });
  it("shows qualitative ambient pressure without a numeric zero and retains operation purpose", async () => {
    const source = copy(detail), current = copy(queue);
    source.run.extraction_version = current.items[0].extraction_version = "materials-ner/13";
    source.entities.states[0].payload.pressure = { availability: "reported", regime: "explicit_ambient", condition_id: null, basis_raw: "ambient pressure" };
    source.entities.states[0].payload.conditions = [{ id: "operation", kind: "temperature", role: "unknown", quantity: { status: "reported", raw: "10 K" }, basis_raw: "pressure was changed at 10 K" }];
    vi.mocked(materialsProposalRuns).mockResolvedValue(current); vi.mocked(materialsProposalDetail).mockResolvedValue(source);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText(/The source explicitly reports ambient pressure/)).toBeVisible();
    expect(screen.getByText(/No numeric pressure is reported for this declaration/)).toBeVisible();
    expect(screen.getByText("Pressure wording", { exact: true })).toBeVisible();
    expect(screen.getByText("pressure was changed at 10 K", { exact: true })).toBeVisible();
    expect(screen.queryByText(/Measurement pressure is unavailable/)).toBeNull();
    expect(screen.queryByText("0 GPa", { exact: true })).toBeNull();
    const descriptor = { ...copy(exportDescriptor), version: "materials-proposal-export/2", run: source.run };
    expect(proposalExport(descriptor, source.run)).not.toBeNull();
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
  });

  it.each([
    ["tc_pressure_slope", -1.1, "K GPa−1", "≈ −1.1(1) K GPa−1"],
    ["electrical_resistivity", 300, "µΩ·cm", "(300 ± 30) µΩ·cm"],
  ] as const)("reads %s in its source units and retains review boundaries", async (kind, value, unit, raw) => {
    const source = copy(detail), current = copy(queue); source.run.extraction_version = "materials-ner/12"; current.items[0].extraction_version = "materials-ner/12";
    source.results[0].payload.quantity_kind = kind;
    source.results[0].payload.quantity = { status: "reported", raw, value, unit, approximate: kind === "tc_pressure_slope", relation: "exact", uncertainty: { kind: "reported_unspecified", minus: kind === "tc_pressure_slope" ? .1 : 30, plus: kind === "tc_pressure_slope" ? .1 : 30 } };
    source.results[0].payload.definition = { criterion: "onset", criterion_raw: "onset", parameters: [] };
    vi.mocked(materialsProposalRuns).mockResolvedValue(current); vi.mocked(materialsProposalDetail).mockResolvedValue(source);
    render(<MaterialsProposalReview />);
    fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
    fireEvent.click(await screen.findByRole("button", { name: `I1 · ${kind}` }));
    const reading = within(await screen.findByRole("article", { name: `Reported result · ${kind}` }));
    expect(reading.getByText(raw, { exact: true })).toBeVisible();
    expect(screen.getByText(unit, { exact: true })).toBeVisible();
    expect(screen.getByText(String(value), { exact: true })).toBeVisible();
    expect(screen.getByText("Uncertainty", { exact: true })).toBeVisible();
    if (kind === "tc_pressure_slope") {
      expect(screen.getByText("Transition criterion", { exact: true })).toBeVisible();
      expect(screen.getByText(/not an independent input for predicting Tc/)).toBeVisible();
    } else expect(screen.getByText(/normalization reference does not establish/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
  });
  it.each(["materials-ner/10", "materials-ner/11", "materials-ner/12", "materials-ner/13", "materials-ner/14", "materials-ner/15"])("reads supported multi-digit extraction version %s without changing review authority", async version => {
    const currentQueue = copy(queue), currentDetail = copy(detail), currentExport = copy(exportDescriptor);
    for (const header of [currentQueue.items[0], currentDetail.run, currentExport.run]) header.extraction_version = version;
    const expected = currentQueue.items[0];
    expect(proposalQueue(currentQueue)).not.toBeNull();
    expect(proposalDetail(currentDetail, expected)).not.toBeNull();
    expect(proposalExport(currentExport, expected)).not.toBeNull();
    vi.mocked(materialsProposalRuns).mockResolvedValue(currentQueue);
    vi.mocked(materialsProposalDetail).mockResolvedValue(currentDetail);
    vi.mocked(materialsProposalExport).mockResolvedValue(currentExport);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText(quote)).toBeVisible();
    expect(screen.getByRole("button", { name: "Download complete run (ZIP)" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
  });
  it.each(["materials-ner/0", "materials-ner/01", "materials-ner/16", "materials-ner/13-extra"])("rejects unsupported or malformed extraction version %s", version => {
    const currentQueue = copy(queue), currentDetail = copy(detail), currentExport = copy(exportDescriptor);
    for (const header of [currentQueue.items[0], currentDetail.run, currentExport.run]) header.extraction_version = version;
    const expected = currentQueue.items[0];
    expect(proposalQueue(currentQueue)).toBeNull();
    expect(proposalDetail(currentDetail, expected)).toBeNull();
    expect(proposalExport(currentExport, expected)).toBeNull();
  });
  it("preserves the reported magnetic field basis without implying a resolved convention", async () => {
    const source = copy(detail);
    source.entities.states[0].payload.conditions = [{ id: "field", kind: "reported_magnetic_field", role: "measurement",
      quantity: { status: "reported", raw: "26.42 T" }, basis_raw: "$H$", orientation_raw: "$\\perp$ $c$" }];
    vi.mocked(materialsProposalDetail).mockResolvedValue(source);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText("Reported magnetic field", { exact: true })).toBeVisible();
    expect(screen.getByText("Reported basis", { exact: true })).toBeVisible();
    expect(screen.getByText("$H$", { exact: true })).toBeVisible();
    expect(screen.getByText("26.42 T", { exact: true })).toBeVisible();
    expect(screen.getByText("$\\perp$ $c$", { exact: true })).toBeVisible();
    expect(screen.getByText("Field convention unresolved. Source units are preserved; no B/H conversion is applied.")).toBeVisible();
    expect(screen.getByText(/Ambient pressure is not inferred/)).toBeVisible();
  });
  it("shows the original quantity symbol and component without translating scientific notation", async () => {
    const source = copy(detail);
    source.results[0].payload.quantity_name_raw = "T_{c}";
    source.results[0].payload.component_raw = "$H$ $\\parallel $ $c$";
    vi.mocked(materialsProposalDetail).mockResolvedValue(source);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText("Source quantity name", { exact: true })).toBeVisible();
    expect(screen.getByText("T_{c}", { exact: true })).toBeVisible();
    expect(screen.getByText("Component / direction", { exact: true })).toBeVisible();
    expect(screen.getByText("$H$ $\\parallel $ $c$", { exact: true })).toBeVisible();
  });
  it("keeps held and missing original items visible without presenting the old candidate as a current result", async () => {
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByRole("heading", { name: "Source item accounting" })).toBeVisible();
    expect(screen.getByText("Held for review", { exact: true })).toBeVisible();
    expect(screen.getByText("No result retained", { exact: true })).toBeVisible();
    expect(screen.queryByRole("button", { name: "I2 · hc2" })).toBeNull();
    fireEvent.click(screen.getByText("I2 · original candidate and source"));
    expect(screen.getByText(heldSource)).toBeVisible();
    expect(screen.getByText(/not an accepted scientific exclusion or a negative measurement/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
  });
  it("does not treat absent accounting from an older version as complete extraction", async () => {
    const older = copy(detail); delete older.coverage.source_item_accounting;
    vi.mocked(materialsProposalDetail).mockResolvedValue(older);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText(/Source item accounting is unavailable/)).toBeVisible();
  });
  it("admits exact source-owned DTOs and rejects asserted authority or mismatched ownership", () => {
    expect(proposalAccess(access)).toBe(true); expect(proposalQueue(queue)).not.toBeNull();
    expect(proposalDetail(detail, run)).not.toBeNull(); expect(proposalEvidence(evidence, run, "I1")).not.toBeNull();
    expect(proposalAccess({ ...access, authority: { ...access.authority, scientific_acceptance: true } })).toBe(false);
    const wrong = copy(detail); wrong.results[0].payload.state_id = "unrelated";
    expect(proposalDetail(wrong, run)).toBeNull();
    expect(proposalEvidence({ ...evidence, packet_sha256: "0".repeat(64) }, run, "I1")).toBeNull();
    expect(proposalEvidence({ ...evidence, items: [{ ...evidence.items[0], end_char: 10000 }] }, run, "I1")).toBeNull();
    expect(proposalExport(exportDescriptor, run)).not.toBeNull();
    expect(proposalExport({ ...exportDescriptor, scope: "visible_pages" }, run)).toBeNull();
    expect(proposalExport({ ...exportDescriptor, counts: { ...exportDescriptor.counts, results: 0 } }, run)).toBeNull();
    expect(proposalExport({ ...exportDescriptor, filename: "../unsafe.zip" }, run)).toBeNull();
  });
  it("shows independent formula and identity missingness, exact escaped source and no inferred ambient pressure", async () => {
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByRole("heading", { name: "Reported result · tc" })).toBeVisible();
    expect(screen.getByText("Formula availability")).toBeVisible(); expect(screen.getByText("ambiguous")).toBeVisible();
    expect(screen.getByText("Sample identity")).toBeVisible();
    expect(screen.getByText(/Ambient pressure is not inferred/)).toBeVisible();
    expect(screen.getByText(quote)).toBeVisible(); expect(document.querySelector("img")).toBeNull();
    expect(screen.getByRole("button", { name: "Next evidence page" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
    expect(screen.getByText(/not a full-paper or training dataset export/)).toBeVisible();
  });
  it.each([401, 403, 404, 409, 503])("clears retained data when authorization or integrity fails (%i)", async status => {
    render(<MaterialsProposalReview />); await select();
    vi.mocked(materialsProposalEvidence).mockRejectedValue(new ApiError(status, { detail: "SECRET_SOURCE" }, "SECRET_SOURCE"));
    fireEvent.click(screen.getByRole("button", { name: "I1 · tc" }));
    await screen.findByRole("alert"); expect(screen.queryByText(quote)).toBeNull();
    expect(screen.queryByText(/SECRET_SOURCE/)).toBeNull(); expect(screen.queryByRole("heading", { name: "Results by sample and state" })).toBeNull();
  });
  it("retains failed empty runs without claiming no scientific results", async () => {
    vi.mocked(materialsProposalDetail).mockResolvedValue({ ...copy(detail), results: [], run: { ...run, result_count: 0, extraction_version: null } });
    render(<MaterialsProposalReview />);
    fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
    expect(await screen.findByText(/attempt retained no result rows/)).toBeVisible();
    expect(screen.getByText("Source coverage, versions and run failures")).toBeVisible();
  });
  it("keeps core missingness visible without filling the reading view with empty optional fields", async () => {
    const sparse = copy(detail);
    sparse.entities.states[0].payload.conditions = [{ kind: "magnetic_flux_density", role: "measurement", quantity: { status: "reported", raw: "9 T" } }];
    vi.mocked(materialsProposalDetail).mockResolvedValue(sparse);
    render(<MaterialsProposalReview />); await select();
    expect(screen.getByText(/Measurement pressure is unavailable/)).toBeVisible();
    expect(screen.getByText("9 T")).toBeVisible();
    expect(screen.getByText("Transition criterion")).toBeVisible();
    for (const empty of ["Lower bound", "Upper bound", "Uncertainty", "Approximate", "Substrate", "Procedure details", "Criterion parameters", "Orientation"]) {
      expect(screen.queryByText(empty, { exact: true })).toBeNull();
    }
    expect(screen.getByText("Complete result fields and normalization")).toBeVisible();
  });
  it("does not reveal an evidence response that arrives after a new query", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(materialsProposalEvidence).mockImplementation(() => new Promise(r => { resolve = r; }));
    render(<MaterialsProposalReview />);
    fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
    fireEvent.click(await screen.findByRole("button", { name: "I1 · tc" }));
    // Submit is guarded in the UI; an external auth change or programmatic submit also invalidates pending evidence.
    fireEvent.submit(screen.getByRole("button", { name: "Refresh access and search" }).closest("form")!);
    await act(async () => resolve(copy(evidence)));
    expect(screen.queryByText(quote)).toBeNull();
  });
  it("requires fresh authorized reads before an English review-page download", async () => {
    const create = vi.fn(() => "blob:review-test"), revoke = vi.fn();
    vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      render(<MaterialsProposalReview />); await select();
      fireEvent.click(screen.getByRole("button", { name: "Download visible review (JSON)" }));
      await waitFor(() => expect(create).toHaveBeenCalledOnce());
      expect(materialsProposalDetail).toHaveBeenCalledTimes(2); expect(materialsProposalEvidence).toHaveBeenCalledTimes(2);
      expect(click).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith("blob:review-test");
    } finally { click.mockRestore(); vi.unstubAllGlobals(); }
  });
  it("downloads the complete retained run only after a checked descriptor and byte request", async () => {
    const create = vi.fn(() => "blob:complete-review"), revoke = vi.fn();
    vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      render(<MaterialsProposalReview />); await select();
      fireEvent.click(screen.getByRole("button", { name: "Download complete run (ZIP)" }));
      await waitFor(() => expect(click).toHaveBeenCalledOnce());
      expect(materialsProposalExport).toHaveBeenCalledOnce();
      expect(materialsProposalExportFile).toHaveBeenCalledWith(run.run_id, exportDescriptor.sha256, 4, expect.any(AbortSignal));
      expect(create).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith("blob:complete-review");
    } finally { click.mockRestore(); vi.unstubAllGlobals(); }
  });
  it("clears private data when access or checksum verification fails during full export", async () => {
    vi.mocked(materialsProposalExportFile).mockRejectedValue(new ApiError(409, null, "PRIVATE_ERROR"));
    render(<MaterialsProposalReview />); await select();
    fireEvent.click(screen.getByRole("button", { name: "Download complete run (ZIP)" }));
    await screen.findByRole("alert"); expect(screen.queryByText(quote)).toBeNull();
    expect(screen.queryByText("PRIVATE_ERROR")).toBeNull();
  });
});
