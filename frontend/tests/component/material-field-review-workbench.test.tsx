import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardUserProvider } from "@/components/dashboard/user-context";
import { MaterialFieldReviewWorkbench } from "@/components/MaterialFieldReviewWorkbench";
import { ApiError, materialFieldReviewCapabilities, materialFieldReviewCommit, materialFieldReviewContext, materialFieldReviewEffective, materialFieldReviewOutcome, materialFieldReviewPreview, type User } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import { FIELD_REVIEW_CHECKS, fieldReviewCheckLabel } from "@/lib/material-field-review";
import { reviewActor, reviewCap, reviewExpression, reviewTarget, syntheticReviewCanonical, syntheticReviewContext, syntheticReviewEffective, syntheticReviewReceipt } from "../helpers/material-field-review-test-data";
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialFieldReviewCapabilities: vi.fn(), materialFieldReviewContext: vi.fn(), materialFieldReviewPreview: vi.fn(), materialFieldReviewCommit: vi.fn(), materialFieldReviewOutcome: vi.fn(), materialFieldReviewEffective: vi.fn() }));
const user = { id: reviewActor, name: "Synthetic independent reviewer", email: "reviewer@example.invalid", is_admin: false, is_reviewer: true } as User;
function view(actor = reviewActor) { return <DashboardUserProvider value={{ user: { ...user, id: actor }, setUser: vi.fn() }}><MaterialFieldReviewWorkbench initialTargetId={reviewTarget} initialExpressionId={reviewExpression} /></DashboardUserProvider>; }
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) }; }
async function mount() { const rendered = render(view()); await screen.findByText("Reviewer access available"); return rendered; }
async function inspect() { fireEvent.click(screen.getByRole("button", { name: "Load current review context" })); return screen.findByRole("region", { name: "Original result and proposed field" }); }
async function prepare() { await inspect(); fireEvent.change(screen.getByLabelText("Review rationale"), { target: { value: "Original source inspected; this window still needs clarification." } }); fireEvent.click(screen.getByRole("button", { name: "Preview field decision" })); return screen.findByRole("button", { name: "Save this field decision" }); }
beforeEach(() => { sessionStorage.clear(); vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); vi.mocked(materialFieldReviewCapabilities).mockResolvedValue(structuredClone(reviewCap)); vi.mocked(materialFieldReviewContext).mockImplementation(async selector => syntheticReviewContext(selector.fieldId)); vi.mocked(materialFieldReviewEffective).mockImplementation(async () => syntheticReviewEffective()); vi.mocked(materialFieldReviewPreview).mockImplementation(async request => syntheticReviewReceipt(request)); vi.mocked(materialFieldReviewCommit).mockImplementation(async request => syntheticReviewReceipt(request, false)); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("Private independent field review", () => {
  it("withholds a context paired with a different effective review head", async () => {
    vi.mocked(materialFieldReviewEffective).mockResolvedValue(await syntheticReviewEffective(true));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Load current review context" }));
    await screen.findByText(/response could not be verified/);
    expect(screen.queryByRole("region", { name: "Reviewer field decision" })).not.toBeInTheDocument();
    expect(materialFieldReviewPreview).not.toHaveBeenCalled();
  });
  it("uses hashed target and association authorship when offering source-fidelity acceptance", async () => {
    const context = await syntheticReviewContext();
    context.subject.target_user_id = reviewActor;
    context.subject_canonical_json = syntheticReviewCanonical(context.subject);
    context.subject_sha256 = await expressionSha(context.subject_canonical_json);
    context.item_template.expected_subject_sha256 = context.subject_sha256;
    vi.mocked(materialFieldReviewContext).mockResolvedValue(context);
    await mount(); await inspect();
    expect(screen.getByRole("option", { name: "Accept source fidelity for this field" })).toBeDisabled();
    expect(screen.getByText(/independent of the target/)).toBeInTheDocument();
  });
  it("recovers the original unknown save after remount using minimal GET-only pins", async () => {
    const first = await mount(); await prepare();
    const request = vi.mocked(materialFieldReviewPreview).mock.calls[0][0], receipt = await syntheticReviewReceipt(request, false); receipt.replayed = true;
    vi.mocked(materialFieldReviewCommit).mockRejectedValueOnce(new ApiError(503, null, "unknown"));
    fireEvent.click(screen.getByRole("button", { name: "Save this field decision" }));
    await screen.findByRole("region", { name: "Original review outcome recovery" }); first.unmount();
    await mount(); await screen.findByRole("region", { name: "Original review outcome recovery" });
    expect(screen.getByLabelText("Retained-result target ID")).toBeDisabled();
    expect(document.body.textContent).not.toContain("resistive onset");
    vi.mocked(materialFieldReviewOutcome).mockResolvedValueOnce(receipt);
    fireEvent.click(screen.getByRole("button", { name: "Check original save outcome" }));
    await screen.findByRole("region", { name: "Verified field review receipt" });
    expect(materialFieldReviewCommit).toHaveBeenCalledOnce();
    expect(materialFieldReviewOutcome).toHaveBeenCalledOnce();
    expect(sessionStorage.length).toBe(0);
  });
  it("preserves an actor's original save through an A to B to A session switch", async () => {
    const first = await mount(); await prepare();
    vi.mocked(materialFieldReviewCommit).mockRejectedValueOnce(new ApiError(503, null, "unknown"));
    fireEvent.click(screen.getByRole("button", { name: "Save this field decision" }));
    await screen.findByRole("region", { name: "Original review outcome recovery" });
    const b = "00000000-0000-4000-8000-000000000999";
    vi.mocked(materialFieldReviewCapabilities).mockResolvedValue({ ...reviewCap, actor_user_id: b }); first.rerender(view(b));
    await screen.findByText("Reviewer access available");
    expect(screen.queryByRole("region", { name: "Original review outcome recovery" })).not.toBeInTheDocument();
    vi.mocked(materialFieldReviewCapabilities).mockResolvedValue(reviewCap); first.rerender(view());
    await screen.findByRole("region", { name: "Original review outcome recovery" });
    expect(materialFieldReviewOutcome).not.toHaveBeenCalled();
    expect(materialFieldReviewCommit).toHaveBeenCalledOnce();
  });
  it("attempts no write when the original identity cannot be retained", async () => {
    await mount(); await prepare();
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => { throw new Error("Unavailable storage"); });
    fireEvent.click(screen.getByRole("button", { name: "Save this field decision" }));
    await screen.findByText(/No write was attempted/);
    expect(materialFieldReviewCommit).not.toHaveBeenCalled();
  });
  it("waits for matching authenticated capabilities and an explicit target read before doing any private or write operation", async () => { const pending = deferred<unknown>(); vi.mocked(materialFieldReviewCapabilities).mockReturnValue(pending.promise); render(view()); expect(materialFieldReviewContext).not.toHaveBeenCalled(); await act(async () => pending.resolve(reviewCap)); await screen.findByText("Reviewer access available"); expect(materialFieldReviewContext).not.toHaveBeenCalled(); await inspect(); expect(materialFieldReviewPreview).not.toHaveBeenCalled(); expect(materialFieldReviewCommit).not.toHaveBeenCalled(); const original = screen.getByRole("region", { name: "Original result and proposed field" }); expect(within(original).getByText("23 K")).toBeInTheDocument(); expect(within(original).getByText("resistive onset")).toBeInTheDocument(); });
  it("rejects foreign or default-disabled capabilities without showing private selectors", async () => { vi.mocked(materialFieldReviewCapabilities).mockResolvedValue({ ...reviewCap, actor_user_id: reviewTarget }); render(view()); await screen.findByText(/response could not be verified/); expect(screen.queryByLabelText("Retained-result target ID")).not.toBeInTheDocument(); vi.mocked(materialFieldReviewCapabilities).mockRejectedValueOnce(new ApiError(404, null, "disabled")); fireEvent.click(screen.getByRole("button", { name: "Refresh review access" })); await screen.findByText(/exact record is unavailable/); expect(materialFieldReviewContext).not.toHaveBeenCalled(); });
  it("requires a rationale and all explicit inspection checks before acceptance can be previewed", async () => { await mount(); await inspect(); fireEvent.click(screen.getByRole("button", { name: "Preview field decision" })); await screen.findByText(/Supply a review rationale/); expect(materialFieldReviewPreview).not.toHaveBeenCalled(); fireEvent.change(screen.getByLabelText("Review rationale"), { target: { value: "I checked publication, source boundaries, sample and this result window." } }); fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "accept" } }); fireEvent.click(screen.getByRole("button", { name: "Preview field decision" })); expect(materialFieldReviewPreview).not.toHaveBeenCalled(); for (const check of FIELD_REVIEW_CHECKS) fireEvent.change(screen.getByLabelText(fieldReviewCheckLabel(check)), { target: { value: "satisfied" } }); fireEvent.click(screen.getByLabelText(/I inspected the original source/)); fireEvent.click(screen.getByRole("button", { name: "Preview field decision" })); await screen.findByRole("button", { name: "Save this field decision" }); const request = vi.mocked(materialFieldReviewPreview).mock.calls[0][0]; expect(request.items[0].source_inspection_attested).toBe(true); expect(request.items[0].decision).toBe("accept"); expect(materialFieldReviewCommit).not.toHaveBeenCalled(); });
  it("saves only the exact validated preview and clears it when selector or rationale changes", async () => { await mount(); await prepare(); fireEvent.change(screen.getByLabelText("Review rationale"), { target: { value: "Changed source review rationale; another exact preview is required." } }); expect(screen.queryByRole("button", { name: "Save this field decision" })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Preview field decision" })); await screen.findByRole("button", { name: "Save this field decision" }); const request = vi.mocked(materialFieldReviewPreview).mock.calls[1][0], expected = await syntheticReviewReceipt(request); fireEvent.click(screen.getByRole("button", { name: "Save this field decision" })); await screen.findByRole("region", { name: "Verified field review receipt" }); expect(vi.mocked(materialFieldReviewCommit).mock.calls[0].slice(0, 2)).toEqual([request, expected.preview_sha256]); expect(materialFieldReviewCommit).toHaveBeenCalledOnce(); expect(screen.queryByRole("region", { name: "Original result and proposed field" })).not.toBeInTheDocument(); });
  it("locks an uncertain save and recovers only with the original GET identity, including a 404 that does not prove failure", async () => { await mount(); await prepare(); const request = vi.mocked(materialFieldReviewPreview).mock.calls[0][0], saved = await syntheticReviewReceipt(request, false); saved.replayed = true; vi.mocked(materialFieldReviewCommit).mockRejectedValueOnce(new ApiError(503, null, "unknown")); vi.mocked(materialFieldReviewOutcome).mockRejectedValueOnce(new ApiError(404, null, "not proof")).mockResolvedValueOnce(saved); fireEvent.click(screen.getByRole("button", { name: "Save this field decision" })); await screen.findByRole("region", { name: "Original review outcome recovery" }); expect(screen.getByLabelText("Retained-result target ID")).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "Check original save outcome" })); await screen.findByText(/original outcome remains unresolved/); fireEvent.click(screen.getByRole("button", { name: "Check original save outcome" })); await screen.findByRole("region", { name: "Verified field review receipt" }); expect(materialFieldReviewCommit).toHaveBeenCalledOnce(); expect(vi.mocked(materialFieldReviewOutcome).mock.calls[0].slice(0, 2)).toEqual([request.request_key, await expressionSha(expressionCanonical(request))]); });
  it("shows a genuine effective field but withholds its value after a late source hold", async () => { const accepted = await syntheticReviewEffective(true), heldValue = await syntheticReviewEffective(true, true); const context = await syntheticReviewContext(); context.item_template.predecessor = { id: accepted.decision!.id, record_sha256: accepted.decision!.record_sha256 }; vi.mocked(materialFieldReviewContext).mockResolvedValue(context); vi.mocked(materialFieldReviewEffective).mockResolvedValueOnce(accepted).mockResolvedValueOnce(heldValue); await mount(); await inspect(); const first = screen.getByRole("region", { name: "Current field decision" }); expect(within(first).getByText("Source fidelity accepted for this field")).toBeInTheDocument(); expect(within(first).getByText("resistive onset")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Load current review context" })); await waitFor(() => expect(materialFieldReviewEffective).toHaveBeenCalledTimes(2)); const held = await screen.findByRole("region", { name: "Current field decision" }); expect(within(held).queryByText("resistive onset")).not.toBeInTheDocument(); expect(within(held).getByText(/source expression held/)).toBeInTheDocument(); });
  it("permits read-only current field inspection while hiding the review write form", async () => { vi.mocked(materialFieldReviewCapabilities).mockResolvedValue({ ...reviewCap, can_write: false, reviewer_grant_id: null }); render(view()); await screen.findByText("Read-only research access"); await inspect(); expect(screen.queryByRole("region", { name: "Reviewer field decision" })).not.toBeInTheDocument(); expect(materialFieldReviewPreview).not.toHaveBeenCalled(); });
  it("clears source and value state on auth change and ignores an old private response", async () => { const late = deferred<unknown>(); vi.mocked(materialFieldReviewContext).mockReturnValue(late.promise); await mount(); fireEvent.click(screen.getByRole("button", { name: "Load current review context" })); act(() => notifyAuthChange()); await act(async () => late.resolve(await syntheticReviewContext())); expect(screen.queryByRole("region", { name: "Original result and proposed field" })).not.toBeInTheDocument(); expect(screen.queryByLabelText("Retained-result target ID")).not.toBeInTheDocument(); expect(materialFieldReviewEffective).not.toHaveBeenCalled(); });
  it("does not carry an uncertain operation to a different authenticated actor", async () => { const rendered = await mount(); await prepare(); vi.mocked(materialFieldReviewCommit).mockRejectedValueOnce(new ApiError(503, null, "unknown")); fireEvent.click(screen.getByRole("button", { name: "Save this field decision" })); await screen.findByRole("region", { name: "Original review outcome recovery" }); const actor = "00000000-0000-4000-8000-000000000999"; vi.mocked(materialFieldReviewCapabilities).mockResolvedValue({ ...reviewCap, actor_user_id: actor }); rendered.rerender(view(actor)); await screen.findByText("Reviewer access available"); expect(screen.queryByRole("region", { name: "Original review outcome recovery" })).not.toBeInTheDocument(); expect(materialFieldReviewOutcome).not.toHaveBeenCalled(); });
});
