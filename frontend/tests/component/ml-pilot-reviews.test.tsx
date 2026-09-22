import { webcrypto } from "node:crypto";
import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlPilotReviewWorkbench } from "@/components/MlPilotReviewWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import * as review from "@/lib/ml-pilot-reviews";
import * as quality from "@/lib/ml-pilot-quality";
import { changed, coverageReply, documents, native, own, recoveryFor, reference, syntheticReply } from "../helpers/ml-review-wire";
import { evidenceDocuments, evidenceNative, evidenceParts } from "../helpers/ml-evidence-wire";

vi.mock("@/lib/ml-pilot-reviews", async original => ({ ...await original<typeof review>(), getReviewWording: vi.fn(), inspectReview: vi.fn(), checkReviewDocuments: vi.fn(),
  checkReviewCoverage: vi.fn(), sendReviewEvidence: vi.fn(), previewReview: vi.fn(), commitReview: vi.fn(), recoverReview: vi.fn() }));
const foreign = "00000000-0000-4000-8000-999999999999", scroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
let account: "self" | "foreign", currentInspection: string;
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name, exact: true }));
const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); account = "self"; currentInspection = own.initial;
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.mocked(review.getReviewWording).mockImplementation(async () => account === "self" ? own.declaration_wording : changed(own.declaration_wording, v => { v.actor_user_id = foreign; }));
  vi.mocked(review.inspectReview).mockImplementation(async () => currentInspection);
  vi.mocked(review.checkReviewDocuments).mockResolvedValue(own.preflight);
  vi.mocked(review.checkReviewCoverage).mockResolvedValue(coverageReply());
  vi.mocked(review.previewReview).mockImplementation(async (a, c) => syntheticReply(c, a, false));
  vi.mocked(review.commitReview).mockImplementation(async (a, c) => syntheticReply(c, a, true));
  vi.mocked(review.recoverReview).mockResolvedValue(own.recovered);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (scroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", scroll); else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
async function mount(strict = false) {
  render(strict ? <StrictMode><MlPilotReviewWorkbench /></StrictMode> : <MlPilotReviewWorkbench />);
  await waitFor(() => expect(screen.getByLabelText("Participant UUID")).toBeEnabled());
}
async function load(ref = reference()) {
  fill("Participant UUID", ref.participant_id); fill("Participant record SHA-256", ref.participant_sha256); fill("Registration record SHA-256", ref.registration_sha256);
  click("Inspect own declaration history"); const h = await screen.findByRole("heading", { name: "Your declaration history" }); await waitFor(() => expect(h).toHaveFocus());
}
function choose(a: review.ReviewAction) {
  fireEvent.change(screen.getByRole("combobox", { name: "Review action" }), { target: { value: a } });
  fireEvent.change(screen.getByLabelText(/^Reason code/), { target: { value: "synthetic_review" } });
}
async function scope(upload: review.ReviewDocuments = documents()) {
  for (const [name, label] of [["selection", "Original selection file"], ["protocol", "Original protocol file"], ["reviews", "Original review log"], ["conclusion", "Original conclusion file"]] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { files: [new NodeFile([Buffer.from(upload[`${name}_base64`], "base64")], name)] } });
  }
  click("Check original review documents"); await screen.findByText(/Original documents checked for your account/);
}
async function preview(a: review.ReviewAction = "attest") {
  await load(); choose(a); if (a === "attest") await scope();
  fireEvent.click(screen.getByRole("checkbox", { name: /^I have/ })); click("Preview review declaration");
  const h = await screen.findByRole("heading", { name: "Exact preview — not yet committed" }); await waitFor(() => expect(h).toHaveFocus());
}
const confirm = () => fireEvent.click(screen.getByRole("checkbox", { name: "I confirm this exact preview and want to record this action." }));
async function verifiedBytes() {
  vi.stubGlobal("Blob", NodeBlob);
  vi.mocked(review.getReviewWording).mockResolvedValue(evidenceNative.wording);
  vi.mocked(review.inspectReview).mockResolvedValue(evidenceNative.history);
  vi.mocked(review.checkReviewDocuments).mockResolvedValue(evidenceNative.preflight);
  vi.mocked(review.sendReviewEvidence).mockResolvedValue(evidenceNative.complete);
  await mount(); await load(evidenceNative.reference); choose("attest"); await scope(evidenceDocuments);
  expect(screen.queryByRole("button", { name: "Show verified field report" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Exact canary bundle", { exact: false }), { target: { files: [new NodeFile([evidenceParts().files.canary], "canary.json")] } });
  click("Verify canary and context bytes"); await screen.findByRole("status", { name: "Byte integrity snapshot" });
}
describe("English own-review declaration workbench", () => {
  it.each(["source", "original", "account", "failed_recheck"])("shows byte replay without science approval, then clears it after %s", async change => {
    vi.stubGlobal("Blob", NodeBlob);
    vi.mocked(review.getReviewWording).mockResolvedValue(evidenceNative.wording);
    vi.mocked(review.inspectReview).mockResolvedValue(evidenceNative.history);
    vi.mocked(review.checkReviewDocuments).mockResolvedValue(evidenceNative.preflight);
    vi.mocked(review.sendReviewEvidence).mockResolvedValue(evidenceNative.complete);
    await mount(); await load(evidenceNative.reference); choose("attest"); await scope(evidenceDocuments);
    expect(review.sendReviewEvidence).not.toHaveBeenCalled(); expect(screen.getByRole("button", { name: "Verify canary and context bytes" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Exact canary bundle", { exact: false }), { target: { files: [new NodeFile([evidenceParts().files.canary], "canary.json")] } });
    click("Verify canary and context bytes");
    const result = await screen.findByRole("status", { name: "Byte integrity snapshot" });
    expect(within(result).getByText("Exact canary replay verified")).toBeInTheDocument();
    expect(within(result).getByText(/No context files were required/)).toBeInTheDocument();
    expect(within(result).getByText(/does not verify source permissions/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked();
    const body = vi.mocked(review.sendReviewEvidence).mock.calls[0][1]; expect(Buffer.from(await body.arrayBuffer())).toEqual(evidenceParts().raw);
    click("Show verified field report");
    const report = await screen.findByRole("region", { name: "Verified private field report" });
    await waitFor(() => expect(within(report).getByRole("heading", { name: "Pilot field recovery and curation effort" })).toHaveFocus());
    expect(within(report).getByText(/No atomic results were recovered/)).toBeInTheDocument();
    expect(review.sendReviewEvidence).toHaveBeenCalledTimes(1); expect(review.checkReviewDocuments).toHaveBeenCalledTimes(1);
    expect(review.checkReviewCoverage).not.toHaveBeenCalled(); expect(review.previewReview).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked();
    if (change === "source") fireEvent.change(screen.getByLabelText("Exact context files", { exact: false }), { target: { files: [] } });
    if (change === "original") {
      await scope(evidenceDocuments);
      expect(screen.getByRole("button", { name: "Verify canary and context bytes" })).toBeDisabled();
      expect(screen.getByLabelText("Exact canary bundle", { exact: false })).toHaveValue("");
    }
    if (change === "account") act(() => notifyAuthChange());
    if (change === "failed_recheck") {
      vi.mocked(review.sendReviewEvidence).mockRejectedValueOnce(new ApiError(409, null, "PRIVATE_CANARY"));
      click("Verify canary and context bytes"); await screen.findByText(/exact documents, response or current state could not be verified/);
    }
    expect(screen.queryByRole("status", { name: "Byte integrity snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Joint declaration snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Verified private field report" })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it.each([401, 403])("clears byte proof and private report when access refresh returns %s before reading files", async status => {
    await verifiedBytes(); const reader = vi.spyOn(quality, "preparePilotQualityReport");
    vi.mocked(review.getReviewWording).mockRejectedValueOnce(new ApiError(status, null, "PRIVATE_CANARY"));
    click("Show verified field report"); await screen.findByText(/Account access changed/);
    expect(reader).not.toHaveBeenCalled(); expect(screen.queryByRole("region", { name: "Verified private field report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Byte integrity snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("discards a completed local report after an in-flight authenticated account change", async () => {
    await verifiedBytes(); const real = quality.preparePilotQualityReport; let finish!: (value: quality.PilotQualityReport) => void;
    const reader = vi.spyOn(quality, "preparePilotQualityReport").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    click("Show verified field report"); await waitFor(() => expect(reader).toHaveBeenCalledTimes(1));
    const [canary, conclusion, basis, proof] = reader.mock.calls[0];
    act(() => notifyAuthChange()); const value = await real(canary, conclusion, basis, proof);
    await act(async () => finish(value));
    expect(screen.queryByRole("region", { name: "Verified private field report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Byte integrity snapshot" })).not.toBeInTheDocument();
    expect(review.sendReviewEvidence).toHaveBeenCalledTimes(1); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("checks joint snapshot coverage without consent, automatic calls or declarations", async () => {
    await mount(); await load(); choose("attest"); await scope();
    expect(review.checkReviewCoverage).not.toHaveBeenCalled(); click("Check joint declaration coverage");
    const result = await screen.findByRole("status", { name: "Joint declaration snapshot" });
    expect(within(result).getByText("Account declarations complete for this snapshot")).toBeInTheDocument();
    expect(within(result).getByText(/not collective scientific signoff/)).toBeInTheDocument();
    expect(review.checkReviewCoverage).toHaveBeenCalledWith(reference(), documents(), expect.any(AbortSignal));
    expect(review.previewReview).not.toHaveBeenCalled(); expect(review.commitReview).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked();
  });
  it.each(["initial", "withdrawn"] as const)("shows the original %s incomplete snapshot without claiming signoff", async phase => {
    vi.mocked(review.checkReviewCoverage).mockResolvedValue(coverageReply(phase));
    await mount(); await load(); choose("attest"); await scope(); click("Check joint declaration coverage");
    const result = await screen.findByRole("status", { name: "Joint declaration snapshot" });
    expect(within(result).getByText("Account declarations incomplete for this snapshot")).toBeInTheDocument();
    expect(within(result).getByText(phase === "initial" ? "missing" : "withdrawn")).toBeInTheDocument();
  });
  it.each(["source", "account", "failed_recheck"])("removes an old joint snapshot after %s changes", async change => {
    await mount(); await load(); choose("attest"); await scope(); click("Check joint declaration coverage");
    await screen.findByRole("status", { name: "Joint declaration snapshot" });
    if (change === "source") fireEvent.change(screen.getByLabelText("Original review log"), { target: { files: [] } });
    if (change === "account") act(() => notifyAuthChange());
    if (change === "failed_recheck") {
      vi.mocked(review.checkReviewCoverage).mockRejectedValueOnce(new ApiError(409, null, "PRIVATE_CANARY"));
      click("Check joint declaration coverage"); await screen.findByText(/exact documents, response or current state could not be verified/);
    }
    expect(screen.queryByRole("status", { name: "Joint declaration snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("discards in-flight joint coverage when the authenticated account changes", async () => {
    let finish!: (value: string) => void;
    vi.mocked(review.checkReviewCoverage).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await mount(); await load(); choose("attest"); await scope(); click("Check joint declaration coverage");
    await waitFor(() => expect(review.checkReviewCoverage).toHaveBeenCalled());
    act(() => notifyAuthChange()); await act(async () => finish(coverageReply()));
    expect(screen.queryByRole("status", { name: "Joint declaration snapshot" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Participant UUID")).toHaveValue("");
  });
  it.each(["attest", "withdraw"] as const)("requires two unselected explicit confirmations and exact %s commit", async action => {
    if (action === "withdraw") currentInspection = own.attested_inspection;
    const storage = vi.spyOn(Storage.prototype, "setItem"); await mount(); await load();
    expect(screen.getByRole("combobox")).toHaveValue(""); expect(review.previewReview).not.toHaveBeenCalled(); choose(action);
    if (action === "attest") await scope();
    expect(screen.getByRole("checkbox", { name: /^I have/ })).not.toBeChecked(); expect(screen.getByRole("button", { name: "Preview review declaration" })).toBeDisabled();
    expect(screen.getByText(JSON.parse(own.declaration_wording).declaration_text)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /^I have/ })); click("Preview review declaration");
    await screen.findByRole("heading", { name: "Exact preview — not yet committed" }); expect(review.commitReview).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Commit exact review declaration" })).toBeDisabled(); confirm(); click("Commit exact review declaration");
    await screen.findByRole("heading", { name: "Historical review declaration receipt" });
    const [a, c, d] = vi.mocked(review.previewReview).mock.calls[0]; expect(a).toBe(action); expect(c.declaration_acknowledged).toBe(true);
    expect(review.commitReview).toHaveBeenCalledWith(action, c, d, expect.stringMatching(/^[a-f0-9]{64}$/), expect.any(AbortSignal));
    if (action === "attest") expect(d).toEqual(documents()); else { expect(d).toBeNull(); expect(review.checkReviewDocuments).not.toHaveBeenCalled(); }
    expect(storage).not.toHaveBeenCalled(); expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
  it("separates complete record counts, own contribution and conclusion authorship", async () => {
    await mount(); await load(); choose("attest"); await scope();
    const region = screen.getByRole("region", { name: "Review declaration consent" });
    expect(within(region).getByText("Complete log records, including revisions")).toBeInTheDocument();
    expect(within(region).getByText("61")).toBeInTheDocument(); expect(within(region).getByText("No")).toBeInTheDocument();
    expect(within(region).getByText(/not endorsement as the conclusion author/)).toBeInTheDocument();
    expect(review.previewReview).not.toHaveBeenCalled();
  });
  it("shows the zero-review conclusion author's distinct scope without inventing own reviews", async () => {
    const author = native.participants.find(p => JSON.parse(p.preflight).conclusion_author_is_current_account)!;
    vi.mocked(review.getReviewWording).mockResolvedValue(author.declaration_wording); vi.mocked(review.inspectReview).mockResolvedValue(author.attested_inspection);
    await mount(); const ref = reference(author); fill("Participant UUID", ref.participant_id); fill("Participant record SHA-256", ref.participant_sha256); fill("Registration record SHA-256", ref.registration_sha256);
    click("Inspect own declaration history"); await screen.findByRole("heading", { name: "Your declaration history" });
    expect(screen.getByText("0")).toBeInTheDocument(); expect(screen.getByText(/also covers the exact conclusion/)).toBeInTheDocument();
  });
  it.each(["files", "reason", "action", "reference", "consent"])("invalidates an old preview when %s changes", async kind => {
    await mount(); await preview(); confirm();
    if (kind === "files") fireEvent.change(screen.getByLabelText("Original review log"), { target: { files: [] } });
    if (kind === "reason") fireEvent.change(screen.getByLabelText(/^Reason code/), { target: { value: "changed" } });
    if (kind === "action") fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    if (kind === "reference") fill("Participant UUID", foreign);
    if (kind === "consent") fireEvent.click(screen.getByRole("checkbox", { name: /^I have/ }));
    expect(screen.queryByRole("button", { name: "Commit exact review declaration" })).not.toBeInTheDocument(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("rechecks the predecessor and clears consent instead of silently rebasing", async () => {
    await mount(); await load(); choose("attest"); await scope(); fireEvent.click(screen.getByRole("checkbox", { name: /^I have/ }));
    currentInspection = own.attested_inspection; click("Preview review declaration"); await screen.findByText(/Your declaration history changed/);
    expect(review.previewReview).not.toHaveBeenCalled(); expect(screen.getByRole("combobox")).toHaveValue("");
  });
  it("does not record a declaration from mismatched preflight evidence", async () => {
    vi.mocked(review.checkReviewDocuments).mockResolvedValue(changed(own.preflight, v => { v.input_pins.reviews_file_sha256 = "f".repeat(64); }));
    await mount(); await load(); choose("attest");
    for (const [name, label] of [["selection", "Original selection file"], ["protocol", "Original protocol file"], ["reviews", "Original review log"], ["conclusion", "Original conclusion file"]] as const)
      fireEvent.change(screen.getByLabelText(label), { target: { files: [new NodeFile([Buffer.from(own.upload[`${name}_base64`], "base64")], name)] } });
    click("Check original review documents"); await screen.findByText(/exact documents, response or current state could not be verified/);
    expect(review.previewReview).not.toHaveBeenCalled(); expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
  it("locks an uncertain commit to read-only original-key recovery, including missing receipts", async () => {
    vi.mocked(review.commitReview).mockRejectedValueOnce(new ApiError(503, null, "PRIVATE_CANARY")); await mount(); await preview(); confirm(); click("Commit exact review declaration");
    await screen.findByText(/Commit outcome is unknown/); expect(screen.queryByLabelText("Original review log")).not.toBeInTheDocument();
    vi.mocked(review.recoverReview).mockRejectedValueOnce(new ApiError(404, null, "PRIVATE_CANARY")); click("Check original review outcome"); await screen.findByText(/No outcome was observed/);
    expect(screen.getByLabelText("Participant UUID")).toBeDisabled(); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
    const [a, c] = vi.mocked(review.commitReview).mock.calls[0]; vi.mocked(review.recoverReview).mockResolvedValueOnce(syntheticReply(c, a, true, true));
    click("Check original review outcome"); await screen.findByRole("heading", { name: "Historical review declaration receipt" });
    expect(review.commitReview).toHaveBeenCalledTimes(1); expect(vi.mocked(review.recoverReview).mock.calls[0][0]).toEqual(vi.mocked(review.recoverReview).mock.calls[1][0]);
  });
  it("hides unresolved private references on account switch and restores them only for the original account", async () => {
    vi.mocked(review.commitReview).mockRejectedValueOnce(new ApiError(503, null, "PRIVATE_CANARY")); await mount(); await preview(); confirm(); click("Commit exact review declaration"); await screen.findByText(/Commit outcome is unknown/);
    account = "foreign"; act(() => notifyAuthChange()); expect(screen.queryByRole("region", { name: "Unresolved review operation" })).not.toBeInTheDocument();
    click("Refresh review access"); await screen.findByText(/unresolved operation belongs to another account/); expect(screen.getByLabelText("Participant UUID")).toBeDisabled();
    account = "self"; act(() => notifyAuthChange()); click("Refresh review access"); await screen.findByRole("button", { name: "Check original review outcome" });
    expect(review.commitReview).toHaveBeenCalledTimes(1); expect(review.recoverReview).not.toHaveBeenCalled();
  });
  it("rechecks account identity immediately before a commit", async () => {
    await mount(); await preview(); confirm(); account = "foreign"; click("Commit exact review declaration"); await screen.findByText(/Account access changed/);
    expect(review.commitReview).not.toHaveBeenCalled(); expect(screen.queryByText(JSON.parse(own.declaration_wording).declaration_text)).not.toBeInTheDocument();
  });
  it("performs manual historical recovery without invitation or source documents", async () => {
    await mount(); const r = recoveryFor(); fill("Recovery request key", r.requestKey); fill("Recovery intent SHA-256", r.intentSha256); click("Recover historical review declaration");
    await screen.findByRole("heading", { name: "Historical review declaration receipt" }); expect(review.inspectReview).not.toHaveBeenCalled();
    expect(review.checkReviewDocuments).not.toHaveBeenCalled(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("discards an old in-flight preview after an auth notification", async () => {
    let resolve!: (v: string) => void; vi.mocked(review.previewReview).mockImplementationOnce(() => new Promise(yes => { resolve = yes; }));
    await mount(); await load(); choose("attest"); await scope(); fireEvent.click(screen.getByRole("checkbox", { name: /^I have/ })); click("Preview review declaration");
    await waitFor(() => expect(review.previewReview).toHaveBeenCalled()); const [a, c] = vi.mocked(review.previewReview).mock.calls[0];
    act(() => notifyAuthChange()); await act(async () => resolve(syntheticReply(c, a, false)));
    expect(screen.queryByRole("heading", { name: "Exact preview — not yet committed" })).not.toBeInTheDocument(); expect(review.commitReview).not.toHaveBeenCalled();
  });
  it("does not perform automatic writes under StrictMode or on page mount", async () => {
    await mount(true); expect(review.previewReview).not.toHaveBeenCalled(); expect(review.commitReview).not.toHaveBeenCalled(); expect(review.checkReviewDocuments).not.toHaveBeenCalled();
  });
  it("keeps the private feature unavailable on 404 without claiming an empty history", async () => {
    vi.mocked(review.getReviewWording).mockRejectedValue(new ApiError(404, null, "PRIVATE_CANARY")); render(<MlPilotReviewWorkbench />);
    await screen.findByText(/exact account binding or private feature is unavailable/); expect(screen.getByLabelText("Participant UUID")).toBeDisabled();
    expect(screen.queryByText(/Latest recorded action/)).not.toBeInTheDocument(); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
  });
});
