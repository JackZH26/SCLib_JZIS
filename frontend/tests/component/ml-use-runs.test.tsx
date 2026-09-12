import { webcrypto } from "node:crypto";
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlRunsWorkbench } from "@/components/MlRunsWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import * as runs from "@/lib/ml-use-runs";
import { changed, http, recoveryFor, syntheticReply } from "../helpers/ml-run-wire";

vi.mock("@/lib/ml-use-runs", async original => ({ ...await original<typeof runs>(), getRunAccess: vi.fn(), inspectRunContext: vi.fn(),
  inspectRunPlan: vi.fn(), previewRun: vi.fn(), commitRun: vi.fn(), recoverRun: vi.fn(), checkRun: vi.fn() }));
const foreign = "00000000-0000-4000-8000-999999999999", originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
let account: "owner" | "reviewer" | "foreign";
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name, exact: true }));
const fill = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); account = "owner";
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(JSON.parse(http.plan_committed).result.plan.created_at));
  vi.mocked(runs.getRunAccess).mockImplementation(async kind => {
    if (account === "reviewer" && kind === "decision") return http.approver_access;
    if (account === "owner" && kind === "plan") return http.requester_access;
    if (account === "foreign" && kind === "plan") return changed(http.requester_access, v => { v.actor_user_id = foreign; });
    throw new ApiError(403, null, "PRIVATE_CANARY");
  });
  vi.mocked(runs.inspectRunContext).mockResolvedValue(http.context); vi.mocked(runs.inspectRunPlan).mockResolvedValue(http.unreviewed);
  vi.mocked(runs.previewRun).mockImplementation(async (kind, input) => syntheticReply(kind, input, false));
  vi.mocked(runs.commitRun).mockImplementation(async (kind, input) => syntheticReply(kind, input, true));
  vi.mocked(runs.recoverRun).mockImplementation(async ref => ref.kind === "plan" ? http.plan_outcome : http.approve_outcome);
  vi.mocked(runs.checkRun).mockResolvedValue(http.readiness_unreviewed);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll); else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
async function mount(kind: runs.RunKind = "plan", strict = false) {
  if (kind === "decision") account = "reviewer";
  render(strict ? <StrictMode><MlRunsWorkbench /></StrictMode> : <MlRunsWorkbench />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh workflow access" })).toBeEnabled());
  if (kind === "decision") fireEvent.change(screen.getByRole("combobox", { name: "Workflow role" }), { target: { value: "decision" } });
  await waitFor(() => expect(screen.getByLabelText(kind === "plan" ? "Submission UUID" : "Run plan UUID")).toBeEnabled());
}
async function loadOwner() {
  fill("Submission UUID", http.submission_query.submission_id); fill("Submission record SHA-256", http.submission_query.submission_sha256);
  fill("Inventory SHA-256", http.submission_query.inventory_sha256); click("Load run context");
  const heading = await screen.findByRole("heading", { name: "Review exact run inputs" }); await waitFor(() => expect(heading).toHaveFocus());
}
async function loadReview() {
  fill("Run plan UUID", http.plan_query.plan_id); fill("Run plan record SHA-256", http.plan_query.plan_sha256); click("Inspect exact run plan");
  const heading = await screen.findByRole("heading", { name: "Review independent run contract" }); await waitFor(() => expect(heading).toHaveFocus());
}
function budgets() { fill(/CPU budget \(seconds\)/, String(http.plan_input.cpu_seconds)); fill(/Wall-time budget/, String(http.plan_input.wall_seconds)); fill(/Memory budget/, String(http.plan_input.memory_mib)); }
function decision(name: "approve" | "deny" | "revoke" = "approve") {
  fireEvent.change(screen.getByRole("combobox", { name: "Review decision", exact: true }), { target: { value: name } });
  fill(/Review reason code/, http.approve_input.reason_code);
  if (name === "approve") { fill(/Review evidence SHA-256/, http.approve_input.evidence_sha256); fill(/Approval expiry/, String(http.approve_input.expires_epoch)); }
}
async function preview(kind: runs.RunKind = "plan") {
  if (kind === "plan") { await loadOwner(); budgets(); } else { await loadReview(); decision(); }
  fireEvent.click(screen.getByRole("checkbox")); click(kind === "plan" ? "Preview run plan" : "Preview run decision");
  await screen.findByRole("button", { name: "Commit exact run preview" });
}
async function unknown(kind: runs.RunKind = "plan") {
  vi.mocked(runs.commitRun).mockRejectedValueOnce(new ApiError(0, null, "PRIVATE_CANARY"));
  await mount(kind); await preview(kind); click("Commit exact run preview"); await screen.findByText(/Commit outcome is unknown/);
}

describe("owner and independent approver workbench", () => {
  it("requires explicit budgets and confirmation; records only an exact preview, never auto-checks or trains", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem"); await mount(); await loadOwner();
    expect(screen.getByLabelText(/CPU budget \(seconds\)/)).toHaveValue(""); expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(runs.previewRun).not.toHaveBeenCalled(); expect(runs.commitRun).not.toHaveBeenCalled(); budgets();
    expect(screen.getByRole("button", { name: "Preview run plan" })).toBeDisabled(); fireEvent.click(screen.getByRole("checkbox")); click("Preview run plan");
    await screen.findByRole("button", { name: "Commit exact run preview" }); expect(runs.commitRun).not.toHaveBeenCalled();
    const input = vi.mocked(runs.previewRun).mock.calls[0][1]; expect(input).toEqual({ ...http.plan_input, request_key: input.request_key });
    click("Commit exact run preview"); await screen.findByRole("heading", { name: "Historical run receipt" });
    expect(runs.commitRun).toHaveBeenCalledWith("plan", input, expect.stringMatching(/^[0-9a-f]{64}$/), expect.any(AbortSignal));
    expect(runs.checkRun).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled(); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
  });
  it.each(["CPU budget", "Wall-time budget", "Memory budget", "Submission UUID", "Run plan UUID"])("invalidates prepared consent and commit on %s edit", async label => {
    await mount(); await preview(); fill(new RegExp("^" + label), label.includes("UUID") ? foreign : "100");
    expect(screen.queryByRole("button", { name: "Commit exact run preview" })).not.toBeInTheDocument();
    const checkbox = screen.queryByRole("checkbox"); if (checkbox) expect(checkbox).not.toBeChecked(); expect(runs.commitRun).not.toHaveBeenCalled();
  });
  it.each(["0", "01", "1e2", "-1", "1.5", "1801"])("does not preview invalid CPU budget %s", async value => {
    await mount(); await loadOwner(); budgets(); fill(/CPU budget \(seconds\)/, value);
    expect(screen.getByRole("checkbox")).toBeDisabled(); expect(runs.previewRun).not.toHaveBeenCalled();
  });
  it.each(["approve", "deny", "revoke"] as const)("requires an independent account and explicit %s with exact predecessor", async name => {
    if (name === "revoke") vi.mocked(runs.inspectRunPlan).mockResolvedValue(http.approve_inspection);
    await mount("decision"); await loadReview(); expect(screen.getByRole("combobox", { name: "Review decision", exact: true })).toHaveValue("");
    expect(runs.inspectRunContext).not.toHaveBeenCalled(); expect(runs.checkRun).not.toHaveBeenCalled(); decision(name);
    fireEvent.click(screen.getByRole("checkbox")); click("Preview run decision"); await screen.findByRole("button", { name: "Commit exact run preview" });
    const i = vi.mocked(runs.previewRun).mock.calls[0][1] as runs.RunDecisionInput;
    expect(i.decision).toBe(name); expect(i.supersedes_id).toBe(name === "revoke" ? JSON.parse(http.approve_committed).result.decision.id : null);
    expect(i.expires_epoch).toBe(name === "approve" ? http.approve_input.expires_epoch : null);
    click("Commit exact run preview"); await screen.findByRole("heading", { name: "Historical run receipt" }); expect(runs.commitRun).toHaveBeenCalledTimes(1);
  });
  it("does not offer revocation without an approval head or default to approval; expiry must be explicit and retained", async () => {
    await mount("decision"); await loadReview(); expect(screen.getByRole("option", { name: "Revoke exact approval" })).toBeDisabled();
    decision(); fill(/Approval expiry/, ""); expect(screen.getByRole("checkbox")).toBeDisabled();
    fill(/Approval expiry/, String(Math.floor(Date.now() / 1000))); expect(screen.getByRole("checkbox")).toBeDisabled();
    fill(/Approval expiry/, String(http.approve_input.expires_epoch + 100000)); expect(screen.getByRole("checkbox")).toBeDisabled();
  });
  it.each(["Review reason code", "Review evidence SHA-256", "Approval expiry"])("invalidates approval preview on %s edit", async label => {
    await mount("decision"); await preview("decision"); fill(new RegExp(label), "changed");
    expect(screen.queryByRole("button", { name: "Commit exact run preview" })).not.toBeInTheDocument(); expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
  it("checks current conditions only on request and separates approval from missing rights and execution gates", async () => {
    vi.mocked(runs.checkRun).mockResolvedValue(http.readiness_approve); await mount();
    fill("Run plan UUID", http.plan_query.plan_id); fill("Run plan record SHA-256", http.plan_query.plan_sha256); expect(runs.checkRun).not.toHaveBeenCalled();
    click("Check current run readiness"); const region = await screen.findByRole("region", { name: "Current run readiness" });
    expect(within(region).getByText("Conditional approval recorded")).toBeInTheDocument(); expect(within(region).getByText("Not satisfied")).toBeInTheDocument();
    expect(within(region).getByText("guarded execution consumer unavailable")).toBeInTheDocument(); expect(runs.commitRun).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /execute|start model|train/i })).not.toBeInTheDocument();
  });
  it.each(["plan", "decision"] as const)("recovers an uncertain %s by original key; a 404 stays locked and sends no extra write", async kind => {
    await unknown(kind); const [lane, input] = vi.mocked(runs.commitRun).mock.calls[0];
    vi.mocked(runs.recoverRun).mockRejectedValueOnce(new ApiError(404, null, "PRIVATE_CANARY")); click("Check original run outcome");
    await screen.findByText(/No outcome was observed/); expect(screen.getByRole("combobox", { name: "Workflow role" })).toBeDisabled();
    vi.mocked(runs.recoverRun).mockResolvedValueOnce(syntheticReply(lane, input, true, true)); click("Check original run outcome");
    await screen.findByRole("heading", { name: "Historical run receipt" }); expect(runs.commitRun).toHaveBeenCalledTimes(1);
    expect(vi.mocked(runs.recoverRun).mock.calls[0][0]).toEqual(vi.mocked(runs.recoverRun).mock.calls[1][0]);
    expect(screen.getByRole("combobox", { name: "Workflow role" })).toBeEnabled();
  });
  it("retries only the identical original body and digest after explicit action", async () => {
    await unknown(); const first = vi.mocked(runs.commitRun).mock.calls[0]; click("Retry identical original run write");
    await screen.findByRole("heading", { name: "Historical run receipt" });
    expect(vi.mocked(runs.commitRun).mock.calls[1].slice(0, 3)).toEqual(first.slice(0, 3)); expect(runs.commitRun).toHaveBeenCalledTimes(2);
  });
  it.each(["plan", "decision"] as const)("supports read-only manual recovery of an earlier %s under its original account", async kind => {
    await mount(kind); const ref = recoveryFor(kind === "plan" ? "plan" : "approve"); fill("Recovery request key", ref.requestKey); fill("Recovery intent SHA-256", ref.intentSha256);
    click("Recover historical run record"); await screen.findByRole("heading", { name: "Historical run receipt" });
    expect(runs.recoverRun).toHaveBeenCalledWith(ref, expect.any(AbortSignal)); expect(runs.commitRun).not.toHaveBeenCalled(); expect(runs.previewRun).not.toHaveBeenCalled();
  });
  it("clears private drafts on auth change, hides foreign recovery metadata and discards the retry body", async () => {
    await unknown(); const [kind, input] = vi.mocked(runs.commitRun).mock.calls[0];
    act(() => notifyAuthChange()); account = "foreign"; click("Refresh workflow access"); await screen.findByText(/belongs to another account/);
    expect(screen.queryByRole("region", { name: "Unresolved run operation" })).not.toBeInTheDocument(); expect(screen.getByLabelText("Submission UUID")).toHaveValue("");
    account = "owner"; act(() => notifyAuthChange()); click("Refresh workflow access"); await screen.findByRole("button", { name: "Check original run outcome" });
    expect(screen.queryByRole("button", { name: "Retry identical original run write" })).not.toBeInTheDocument();
    vi.mocked(runs.recoverRun).mockResolvedValue(syntheticReply(kind, input, true, true)); click("Check original run outcome");
    await screen.findByRole("heading", { name: "Historical run receipt" }); expect(runs.commitRun).toHaveBeenCalledTimes(1);
  });
  it("ignores late context after an identity change and aborts its request", async () => {
    const late = deferred<string>(); vi.mocked(runs.inspectRunContext).mockReturnValue(late.promise); await mount();
    fill("Submission UUID", http.submission_query.submission_id); fill("Submission record SHA-256", http.submission_query.submission_sha256); fill("Inventory SHA-256", http.submission_query.inventory_sha256);
    click("Load run context"); await waitFor(() => expect(runs.inspectRunContext).toHaveBeenCalled()); act(() => notifyAuthChange());
    await act(async () => late.resolve(http.context)); expect(screen.queryByRole("heading", { name: "Review exact run inputs" })).not.toBeInTheDocument();
    expect(vi.mocked(runs.inspectRunContext).mock.calls[0][1]!.aborted).toBe(true); expect(screen.getByLabelText("Submission UUID")).toHaveValue("");
  });
  it("ignores a late commit after session change while retaining only original recovery references", async () => {
    const late = deferred<string>(); vi.mocked(runs.commitRun).mockReturnValue(late.promise); await mount(); await preview(); click("Commit exact run preview");
    const [kind, input] = vi.mocked(runs.commitRun).mock.calls[0]; act(() => notifyAuthChange()); await act(async () => late.resolve(syntheticReply(kind, input, true)));
    expect(screen.queryByRole("heading", { name: "Historical run receipt" })).not.toBeInTheDocument(); click("Refresh workflow access");
    await screen.findByRole("button", { name: "Check original run outcome" }); expect(screen.queryByRole("button", { name: "Retry identical original run write" })).not.toBeInTheDocument();
  });
  it("survives StrictMode replay and synchronously refuses a double commit", async () => {
    await mount("plan", true); await preview(); const late = deferred<string>(); vi.mocked(runs.commitRun).mockReturnValue(late.promise);
    const button = screen.getByRole("button", { name: "Commit exact run preview" }); act(() => { fireEvent.click(button); fireEvent.click(button); });
    expect(runs.commitRun).toHaveBeenCalledTimes(1); const [kind, input] = vi.mocked(runs.commitRun).mock.calls[0];
    await act(async () => late.resolve(syntheticReply(kind, input, true))); await screen.findByRole("heading", { name: "Historical run receipt" });
  });
  it("refuses changed role grants before preview and clears data after denied refresh", async () => {
    await mount(); await loadOwner(); budgets(); fireEvent.click(screen.getByRole("checkbox"));
    vi.mocked(runs.getRunAccess).mockResolvedValueOnce(changed(http.requester_access, v => { v.requester_grant_id = foreign; })); click("Preview run plan");
    await screen.findByText(/response could not be verified/); expect(runs.previewRun).not.toHaveBeenCalled();
    vi.mocked(runs.getRunAccess).mockRejectedValueOnce(new ApiError(403, null, "PRIVATE_CANARY")); click("Refresh workflow access");
    await screen.findByText(/Access changed/); expect(screen.getByLabelText("Submission UUID")).toHaveValue(""); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
  });
});
