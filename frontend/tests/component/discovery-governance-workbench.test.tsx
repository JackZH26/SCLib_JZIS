import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryGovernanceWorkbench } from "@/components/DiscoveryGovernanceWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import * as governance from "@/lib/discovery-governance";
import { governanceFixture, governanceHash, governanceWire, historyWire, operationRequest, packageId, type Phase } from "./helpers/discovery-governance-fixtures";

vi.mock("@/lib/discovery-governance", async importOriginal => {
  const original = await importOriginal<typeof governance>();
  return { ...original, getOperatorAccess: vi.fn(), getGovernanceHeader: vi.fn(), getReviewPage: vi.fn(), getCurrentInspection: vi.fn(),
    postGovernance: vi.fn(), getGovernanceOutcome: vi.fn(), parseCurrentInspection: vi.fn(original.parseCurrentInspection),
    prepareGovernanceDraft: vi.fn(original.prepareGovernanceDraft), readProjectionRights: vi.fn(original.readProjectionRights) };
});
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
function setup(phase: Phase = "initial", actor: "reviewer" | "publisher" = "reviewer") {
  vi.mocked(governance.getOperatorAccess).mockResolvedValue(governanceWire(`${actor}-access.response.wire.json`));
  vi.mocked(governance.getGovernanceHeader).mockResolvedValue(historyWire(phase, "governance", actor));
  vi.mocked(governance.getReviewPage).mockResolvedValue(historyWire(phase, "reviews", actor));
}
beforeEach(async () => {
  vi.stubGlobal("crypto", webcrypto); vi.clearAllMocks();
  const original = await vi.importActual<typeof governance>("@/lib/discovery-governance");
  vi.mocked(governance.parseCurrentInspection).mockImplementation(original.parseCurrentInspection);
  vi.mocked(governance.prepareGovernanceDraft).mockImplementation(original.prepareGovernanceDraft);
  vi.mocked(governance.readProjectionRights).mockImplementation(original.readProjectionRights);
  setup(); vi.mocked(governance.getCurrentInspection).mockResolvedValue(governanceWire("current-inspection.response.wire.json"));
  vi.mocked(governance.postGovernance).mockImplementation(async (draft, commit) => {
    const stem = ["approve", "reject"].includes(draft.decision) ? `review-${draft.decision}` : draft.decision;
    return governanceWire(`${stem}-${commit ? "commit" : "preview"}.response.wire.json`);
  });
  vi.mocked(governance.getGovernanceOutcome).mockResolvedValue(governanceWire("review-reject-outcome.response.wire.json"));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
async function start() {
  render(<DiscoveryGovernanceWorkbench />); await screen.findByText(/Current explicit roles:/);
  await waitFor(() => expect(screen.getByLabelText("Projection package ID")).toBeEnabled());
}
async function inspect() {
  await start(); fireEvent.change(screen.getByLabelText("Projection package ID"), { target: { value: packageId } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect governance history" }));
  await screen.findByRole("region", { name: "Recorded governance history" });
  await waitFor(() => expect(screen.getByLabelText("Operation")).toBeEnabled());
}
async function current() {
  fireEvent.click(screen.getByRole("button", { name: "Inspect current scientific content" }));
  await screen.findByRole("region", { name: "Current scientific inspection" });
  await waitFor(() => expect(screen.getByLabelText("Operation")).toBeEnabled());
}
function choose(decision: governance.GovernanceDraft["decision"]) {
  fireEvent.change(screen.getByLabelText("Operation"), { target: { value: decision } });
  fireEvent.change(screen.getByLabelText("Decision reason code"), { target: { value: operationRequest(decision).reason_code } });
  if (decision === "publish" || decision === "withdraw") fireEvent.change(screen.getByLabelText("Exact approved review"), { target: { value: operationRequest(decision).review_id } });
}
function chooseRights(change?: (rows: any[]) => void) {
  const rows = operationRequest("approve").rights; change?.(rows); const raw = JSON.stringify(rows);
  const file = new File([raw], "synthetic-explicit-rights.json", { type: "application/json" });
  Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode(raw).buffer });
  fireEvent.change(screen.getByLabelText("Complete rights JSON file"), { target: { files: [file] } });
}
async function checkRights() {
  fireEvent.click(screen.getByRole("button", { name: "Check complete rights file locally" }));
  await waitFor(() => expect(screen.getByLabelText("I approve this exact representative selection.")).toBeEnabled());
}
function consent() {
  fireEvent.click(screen.getByLabelText("I approve this exact representative selection."));
  fireEvent.click(screen.getByLabelText("I approve disclosure under the complete new-scope rights assertions."));
}
async function rehearse() {
  fireEvent.click(screen.getByRole("button", { name: "Run decision rehearsal" }));
  await screen.findByRole("region", { name: "Native governance rehearsal" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Commit exact decision" })).toBeEnabled());
}
async function rejection() { setup("held"); await inspect(); choose("reject"); await rehearse(); }
async function unknownCommit() {
  await rejection(); vi.mocked(governance.postGovernance).mockRejectedValueOnce(new ApiError(0, null, "PRIVATE_CANARY"));
  fireEvent.click(screen.getByRole("button", { name: "Commit exact decision" })); await screen.findByText(/Operation outcome is unknown/);
}

describe("independent Discovery governance workbench", () => {
  it("loads only explicit metadata, keeps operation unset and never infers legacy admin or publication authority", async () => {
    await start(); expect(governance.getGovernanceHeader).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Projection package ID"), { target: { value: packageId } });
    expect(governance.getGovernanceHeader).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Inspect governance history" }));
    await screen.findByText("Complete recorded history verified for this snapshot.");
    expect(screen.getByLabelText("Operation")).toHaveValue(""); expect(screen.getByLabelText("Decision reason code")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    expect(governance.getCurrentInspection).not.toHaveBeenCalled(); expect(governance.postGovernance).not.toHaveBeenCalled();
    expect(screen.getByText(/a later approval does not override it/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Publish using an exact approved review" })).toBeDisabled();
    expect(screen.getByText(/Legacy admin flags do not grant/)).toBeInTheDocument();
  });
  it("requires current science, all new-scope rights, and two explicit confirmations before approval", async () => {
    await inspect(); choose("approve"); expect(screen.getByLabelText("Complete rights JSON file")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    await current(); expect(screen.getByLabelText("Operation")).toHaveValue(""); choose("approve");
    chooseRights(); expect(governance.readProjectionRights).not.toHaveBeenCalled(); expect(governance.postGovernance).not.toHaveBeenCalled();
    await checkRights(); const checkboxes = screen.getAllByRole("checkbox"); checkboxes.forEach(c => expect(c).not.toBeChecked());
    expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled(); consent(); await rehearse();
    const call = vi.mocked(governance.postGovernance).mock.calls[0];
    expect(JSON.parse(call[0].previewJSON)).toEqual({ ...operationRequest("approve"), dry_run: true, request_key: call[0].recovery.requestKey });
    expect(call[1]).toBe(false); expect(call[0].recovery.requestSha256).toBe(JSON.parse(governanceWire("review-approve-preview.response.wire.json")).result.request_sha256);
    expect(screen.getByRole("heading", { name: /Native rehearsal verified/ })).toHaveFocus();
  });
  it("invalidates exact consent when replacing or rechecking rights, and never inherits file A approval for file B", async () => {
    await inspect(); await current(); choose("approve"); chooseRights(); await checkRights(); consent();
    expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeEnabled();
    chooseRights(rows => { rows[0].basis_code = "different_explicit_basis"; });
    screen.getAllByRole("checkbox").forEach(c => expect(c).not.toBeChecked());
    await checkRights(); expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    consent(); expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeEnabled();
    await checkRights(); screen.getAllByRole("checkbox").forEach(c => expect(c).not.toBeChecked());
    expect(governance.postGovernance).not.toHaveBeenCalled();
  });
  it("preserves native quantities and the full scientific details while separating current read from governance", async () => {
    await inspect(); await current(); const region = screen.getByRole("region", { name: "Current scientific inspection" });
    const trigger = within(region).getByRole("button", { name: /^Inspect / }); fireEvent.click(trigger);
    expect(screen.getByRole("region", { name: /scientific details$/ })).toBeInTheDocument();
    expect(screen.getAllByText(/-0.125 THz/).length).toBeGreaterThan(0);
    expect(screen.getByText(/same frozen campaign, budget, policy, release/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close details" })); expect(trigger).toHaveFocus();
  });
  it.each(["reject", "withdraw"] as const)("permits protective %s after current science is held, without scientific fallback", async decision => {
    setup(decision === "reject" ? "held" : "rejected", decision === "reject" ? "reviewer" : "publisher");
    await inspect(); vi.mocked(governance.getCurrentInspection).mockRejectedValueOnce(new ApiError(400, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Inspect current scientific content" }));
    await screen.findByText(/Current scientific inspection is unavailable/);
    expect(screen.getByRole("region", { name: "Recorded governance history" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Current scientific inspection" })).not.toBeInTheDocument();
    choose(decision); await rehearse(); const draft = vi.mocked(governance.postGovernance).mock.calls[0][0];
    expect(JSON.parse(draft.previewJSON)).toEqual({ ...operationRequest(decision), dry_run: true, request_key: draft.recovery.requestKey });
    expect(screen.queryByText(/PRIVATE_CANARY/)).not.toBeInTheDocument();
  });
  it("requires the publisher to select an exact independent approval and current science, then preserves command pins", async () => {
    setup("approved", "publisher"); await inspect(); await current();
    fireEvent.change(screen.getByLabelText("Operation"), { target: { value: "publish" } });
    fireEvent.change(screen.getByLabelText("Decision reason code"), { target: { value: operationRequest("publish").reason_code } });
    expect(screen.getByLabelText("Exact approved review")).toHaveValue(""); expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Exact approved review"), { target: { value: operationRequest("publish").review_id } });
    await rehearse(); expect(vi.mocked(governance.postGovernance).mock.calls[0][0].recovery.operation).toBe("publish");
    expect(screen.getByRole("option", { name: "Approve selection and disclosure" })).toBeDisabled();
  });
  it.each(["rejected", "withdrawn"] as const)("never permits publishing a %s history", async phase => {
    setup(phase, "publisher"); await inspect(); await current(); choose("publish");
    expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    expect(screen.getByText(/This recorded rejection or withdrawal prevents publication/)).toBeInTheDocument();
    expect(governance.postGovernance).not.toHaveBeenCalled();
  });
  it("double-clicks commit once, verifies outer durability, and clears all input decisions", async () => {
    const scroll = vi.fn(); Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: scroll, configurable: true });
    await rejection(); const button = screen.getByRole("button", { name: "Commit exact decision" });
    await waitFor(() => expect(scroll).toHaveBeenCalledWith({ block: "start" }));
    act(() => { fireEvent.click(button); fireEvent.click(button); });
    await screen.findByRole("region", { name: "Verified governance receipt" });
    expect(governance.postGovernance).toHaveBeenCalledTimes(2);
    expect(vi.mocked(governance.postGovernance).mock.calls[1][1]).toBe(true);
    expect(vi.mocked(governance.postGovernance).mock.calls[1][0]).toEqual(vi.mocked(governance.postGovernance).mock.calls[0][0]);
    expect(screen.queryByRole("region", { name: "Explicit governance decision" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Exact operation receipt" })).toHaveFocus());
    expect(governance.getGovernanceOutcome).not.toHaveBeenCalled();
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(2));
  });
  it("invalidates a rehearsal on edits and clears decision choices on package changes", async () => {
    await rejection(); fireEvent.change(screen.getByLabelText("Decision reason code"), { target: { value: "revised_reason" } });
    expect(screen.queryByRole("region", { name: "Native governance rehearsal" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Projection package ID"), { target: { value: "" } });
    expect(screen.queryByRole("region", { name: "Recorded governance history" })).not.toBeInTheDocument();
  });
  it.each(["commit", "current"] as const)("clears stale history before %s, without dispatching the protected operation", async mode => {
    await rejection(); vi.mocked(governance.getGovernanceHeader).mockResolvedValueOnce(historyWire("rejected", "governance"));
    fireEvent.click(screen.getByRole("button", { name: mode === "commit" ? "Commit exact decision" : "Inspect current scientific content" }));
    await screen.findByText(governance.GOVERNANCE_FAILURE);
    expect(screen.queryByRole("region", { name: "Recorded governance history" })).not.toBeInTheDocument();
    expect(governance.postGovernance).toHaveBeenCalledTimes(1); expect(governance.getCurrentInspection).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Original governance recovery" })).not.toBeInTheDocument();
  });
  it("does not infer unknown-write state from pre-submit role denial", async () => {
    await rejection(); vi.mocked(governance.getOperatorAccess).mockRejectedValueOnce(new ApiError(403, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact decision" })); await screen.findByText(/Operator access changed/);
    expect(governance.postGovernance).toHaveBeenCalledTimes(1); expect(screen.queryByRole("region", { name: "Original governance recovery" })).not.toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_CANARY/)).not.toBeInTheDocument();
  });
  it("keeps an uncertain write locked through 404 and recovers only the original GET request", async () => {
    await unknownCommit(); expect(screen.getByLabelText("Projection package ID")).toHaveValue(""); expect(screen.getByLabelText("Projection package ID")).toBeDisabled();
    expect(screen.queryByRole("region", { name: "Recorded governance history" })).not.toBeInTheDocument();
    vi.mocked(governance.getGovernanceOutcome).mockRejectedValueOnce(new ApiError(404, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByText(/No original outcome was visible/);
    expect(screen.getByLabelText("Projection package ID")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("region", { name: "Verified governance receipt" });
    expect(governance.postGovernance).toHaveBeenCalledTimes(2); expect(governance.getGovernanceOutcome).toHaveBeenCalledTimes(2);
    expect(vi.mocked(governance.getGovernanceOutcome).mock.calls[0][0]).toEqual(vi.mocked(governance.getGovernanceOutcome).mock.calls[1][0]);
    expect(screen.queryByText(/PRIVATE_CANARY/)).not.toBeInTheDocument();
  });
  it("hides the locator on session change, refuses a foreign actor, and allows same-account regrant recovery", async () => {
    await unknownCommit(); const original = vi.mocked(governance.postGovernance).mock.calls[1][0].recovery;
    act(() => notifyAuthChange()); expect(screen.queryByText(new RegExp(original.requestKey))).not.toBeInTheDocument();
    const access = JSON.parse(governanceWire("reviewer-access.response.wire.json"));
    vi.mocked(governance.getOperatorAccess).mockResolvedValue(JSON.stringify({ ...access, actor_user_id: "00000000-0000-0000-0000-000000000000" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh operator access" })); await screen.findByText(/belongs to another account/);
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument(); expect(screen.getByLabelText("Projection package ID")).toBeDisabled();
    access.grants[0].id = "00000000-0000-0000-0000-000000000001";
    vi.mocked(governance.getOperatorAccess).mockResolvedValue(JSON.stringify(access)); act(() => notifyAuthChange());
    fireEvent.click(screen.getByRole("button", { name: "Refresh operator access" })); await screen.findByRole("button", { name: "Check original outcome" });
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("region", { name: "Verified governance receipt" });
    expect(governance.getGovernanceOutcome).toHaveBeenCalledWith(original, expect.any(AbortSignal)); expect(governance.postGovernance).toHaveBeenCalledTimes(2);
  });
  it("treats a malformed acknowledgement as unknown rather than success", async () => {
    await rejection(); vi.mocked(governance.postGovernance).mockResolvedValueOnce(governanceWire("review-reject-preview.response.wire.json"));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact decision" })); await screen.findByText(/Operation outcome is unknown/);
    expect(screen.queryByRole("region", { name: "Verified governance receipt" })).not.toBeInTheDocument();
  });
  it("loads pages explicitly, binds each to the complete snapshot, and refuses a changed page without partial approval", async () => {
    // Deliberately constructed client pagination case, not an actual-wire capture.
    const f = await governanceFixture(), reviews = Array.from({ length: 27 }, (_, i) => ({ ...f.page.reviews[0],
      id: `00000000-0000-0000-0000-${String(i + 1).padStart(12, "0")}`, created_at: `2026-09-09T00:00:${String(i).padStart(2, "0")}.000000Z` }));
    const header = { ...f.header, review_count: reviews.length, history_sha256: governanceHash(governance.governanceCanonical({ version: governance.HISTORY_VERSION,
      package: f.header.package, reviews, actions: [] })) };
    vi.mocked(governance.getGovernanceHeader).mockResolvedValue(JSON.stringify(header));
    vi.mocked(governance.getReviewPage).mockResolvedValueOnce(JSON.stringify({ ...header, reviews: reviews.slice(0, 25), after: null, next_after: reviews[24].id,
      page_size: 25, returned_count: 25, history_order: "created_at_then_id_ascending" }));
    await inspect(); expect(screen.getByText(/History is partial/)).toBeInTheDocument(); expect(governance.getReviewPage).toHaveBeenCalledTimes(1);
    await current(); choose("approve"); chooseRights(); await checkRights(); consent(); expect(screen.getByRole("button", { name: "Run decision rehearsal" })).toBeDisabled();
    vi.mocked(governance.getReviewPage).mockRejectedValueOnce(new ApiError(409, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Load next review page" })); await screen.findByText(governance.GOVERNANCE_FAILURE);
    expect(governance.getReviewPage).toHaveBeenLastCalledWith(header, reviews[24].id, expect.any(AbortSignal));
    expect(screen.queryByRole("region", { name: "Recorded governance history" })).not.toBeInTheDocument(); expect(governance.postGovernance).not.toHaveBeenCalled();
  });
  it.each(["auth", "pagehide", "unmount"] as const)("discards late scientific content after %s", async mode => {
    await inspect(); const late = deferred<governance.CurrentInspection>();
    const original = await vi.importActual<typeof governance>("@/lib/discovery-governance"), f = await governanceFixture();
    const value = await original.parseCurrentInspection(governanceWire("current-inspection.response.wire.json"), f.header);
    vi.mocked(governance.parseCurrentInspection).mockImplementationOnce(() => late.promise);
    fireEvent.click(screen.getByRole("button", { name: "Inspect current scientific content" })); await waitFor(() => expect(governance.parseCurrentInspection).toHaveBeenCalled());
    if (mode === "auth") act(() => notifyAuthChange()); else if (mode === "pagehide") act(() => window.dispatchEvent(new Event("pagehide")));
    else { const { cleanup } = await import("@testing-library/react"); cleanup(); }
    await act(async () => { late.resolve(value); }); expect(screen.queryByRole("region", { name: "Current scientific inspection" })).not.toBeInTheDocument();
    expect(governance.postGovernance).not.toHaveBeenCalled();
  });
  it("bounds a stalled local draft hash, releases busy state and ignores late success", async () => {
    setup("held"); await inspect(); choose("reject"); const late = deferred<governance.GovernanceDraft>();
    vi.mocked(governance.prepareGovernanceDraft).mockImplementationOnce(() => late.promise); vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Run decision rehearsal" })); });
    expect(screen.getByRole("button", { name: "Refresh operator access" })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(55_001); });
    expect(screen.getByRole("button", { name: "Refresh operator access" })).toBeEnabled(); expect(screen.getByRole("alert")).toHaveTextContent(governance.GOVERNANCE_FAILURE);
    await act(async () => { late.resolve({} as governance.GovernanceDraft); }); expect(governance.postGovernance).not.toHaveBeenCalled();
  });
});
