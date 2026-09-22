import { webcrypto } from "node:crypto";
import { File as NodeFile } from "node:buffer";
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlPilotParticipationWorkbench } from "@/components/MlPilotParticipationWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import * as pilot from "@/lib/ml-pilot-participation";
import { changed, http, recoveryFor, syntheticReply } from "../helpers/ml-pilot-wire";

vi.mock("@/lib/ml-pilot-participation", async original => ({ ...await original<typeof pilot>(), getPilotAccess: vi.fn(), inspectPilot: vi.fn(),
  previewPilotDecision: vi.fn(), commitPilotDecision: vi.fn(), recoverPilotDecision: vi.fn() }));
const foreign = "00000000-0000-4000-8000-999999999999", scroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name, exact: true }));
const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
let account: "self" | "owner" | "foreign";
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); account = "self";
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.mocked(pilot.getPilotAccess).mockImplementation(async () => account === "self" ? http.access : account === "owner" ? http.owner_access : changed(http.access, v => { v.actor_user_id = foreign; }));
  vi.mocked(pilot.inspectPilot).mockResolvedValue(http.initial);
  vi.mocked(pilot.previewPilotDecision).mockImplementation(async input => syntheticReply(input, false));
  vi.mocked(pilot.commitPilotDecision).mockImplementation(async input => syntheticReply(input, true));
  vi.mocked(pilot.recoverPilotDecision).mockResolvedValue(http.accept_historical);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (scroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", scroll); else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
async function mount(strict = false) {
  render(strict ? <StrictMode><MlPilotParticipationWorkbench /></StrictMode> : <MlPilotParticipationWorkbench />);
  await waitFor(() => expect(screen.getByLabelText("Registration UUID")).toBeEnabled());
}
async function load() {
  fill("Registration UUID", http.query.registration_id); fill("Registration record SHA-256", http.query.registration_sha256); click("Inspect invitation");
  const heading = await screen.findByRole("heading", { name: "Current account participation" }); await waitFor(() => expect(heading).toHaveFocus());
}
function decide(choice: pilot.PilotChoice = "decline") {
  fireEvent.change(screen.getByRole("combobox", { name: "Participation decision" }), { target: { value: choice } });
  fireEvent.change(screen.getByLabelText(/^Reason code/), { target: { value: "synthetic_protocol_participation" } });
  if (choice === "accept") {
    fireEvent.change(screen.getByLabelText("Original selection file"), { target: { files: [new NodeFile([Buffer.from(http.selection_base64, "base64")], "selection.json")] } });
    fireEvent.change(screen.getByLabelText("Original protocol file"), { target: { files: [new NodeFile([Buffer.from(http.protocol_base64, "base64")], "protocol.json")] } });
  }
}
async function preview(choice: pilot.PilotChoice = "decline") {
  await load(); decide(choice); fireEvent.click(screen.getByRole("checkbox")); click("Preview participation decision");
  await screen.findByRole("button", { name: "Commit exact participation preview" });
}
describe("participant-only English workbench", () => {
  it.each(["accept", "decline", "withdraw"] as const)("requires explicit %s consent and commits the exact preview", async choice => {
    if (choice === "withdraw") vi.mocked(pilot.inspectPilot).mockResolvedValue(http.revoked_inspection);
    const storage = vi.spyOn(Storage.prototype, "setItem"); await mount(); await load();
    expect(screen.getByRole("combobox")).toHaveValue(""); expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(pilot.previewPilotDecision).not.toHaveBeenCalled(); decide(choice);
    expect(screen.getByRole("button", { name: "Preview participation decision" })).toBeDisabled(); fireEvent.click(screen.getByRole("checkbox")); click("Preview participation decision");
    await screen.findByRole("button", { name: "Commit exact participation preview" }); expect(pilot.commitPilotDecision).not.toHaveBeenCalled();
    expect(pilot.inspectPilot).toHaveBeenCalledTimes(2); const [input, actor, files] = vi.mocked(pilot.previewPilotDecision).mock.calls[0];
    expect(input.decision).toBe(choice); expect(actor).toBe(http.participant_id); expect(input.supersedes_id).toBe(choice === "withdraw" ? JSON.parse(http.accept_committed).result.decision.id : null);
    if (choice === "accept") expect(files).toMatchObject({ selection_base64: http.selection_base64, protocol_base64: http.protocol_base64 }); else expect(files).toBeNull();
    click("Commit exact participation preview"); await screen.findByRole("heading", { name: "Historical participation receipt" });
    expect(pilot.commitPilotDecision).toHaveBeenCalledWith(input, actor, files, expect.stringMatching(/^[0-9a-f]{64}$/), expect.any(AbortSignal));
    expect(screen.queryByRole("region", { name: "Current pilot participation" })).not.toBeInTheDocument(); expect(storage).not.toHaveBeenCalled();
  });
  it("never offers a registrar an action on someone else's binding", async () => {
    account = "owner"; vi.mocked(pilot.inspectPilot).mockResolvedValue(http.owner_initial); await mount(); await load();
    expect(screen.getByText(/Registrar view: all bound accounts/)).toBeInTheDocument(); expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(pilot.previewPilotDecision).not.toHaveBeenCalled();
  });
  it("disables new acceptance under revoked roles but leaves protective decisions available", async () => {
    vi.mocked(pilot.inspectPilot).mockResolvedValue(http.revoked_inspection); await mount(); await load();
    expect(screen.getByRole("option", { name: "Accept exact protocol" })).toBeDisabled(); expect(screen.getByRole("option", { name: "Withdraw current acceptance" })).toBeEnabled();
    expect(screen.getByText("Not ready")).toBeInTheDocument(); expect(screen.queryByLabelText("Original selection file")).not.toBeInTheDocument();
  });
  it("does not turn a historical document policy into current readiness or acceptance", async () => {
    vi.mocked(pilot.inspectPilot).mockResolvedValue(changed(http.initial, v => { v.current_registration_document_policy = false; v.registration_document_check_version = "ml08-registration-documents/1.0.0"; }));
    await mount(); await load(); expect(screen.getByRole("option", { name: "Accept exact protocol" })).toBeDisabled(); expect(screen.getByRole("option", { name: "Decline participation" })).toBeEnabled();
  });
  it("clears consent when the predecessor changed since inspection instead of silently accepting a new head", async () => {
    await mount(); await load(); decide(); fireEvent.click(screen.getByRole("checkbox")); vi.mocked(pilot.inspectPilot).mockResolvedValue(http.accept_inspection);
    click("Preview participation decision"); await screen.findByText(/current participation or role state changed/);
    expect(screen.getByRole("combobox")).toHaveValue(""); expect(pilot.previewPilotDecision).not.toHaveBeenCalled(); expect(pilot.commitPilotDecision).not.toHaveBeenCalled();
  });
  it("rejects mismatched original files locally with no preview or document upload", async () => {
    await mount(); await load(); decide("accept"); fireEvent.change(screen.getByLabelText("Original protocol file"), { target: { files: [new NodeFile(["PRIVATE_CANARY"], "wrong.json")] } });
    fireEvent.click(screen.getByRole("checkbox")); click("Preview participation decision"); await screen.findByText(/documents or current state could not be verified/);
    expect(pilot.previewPilotDecision).not.toHaveBeenCalled(); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument(); expect(screen.queryByLabelText("Original protocol file")).not.toBeInTheDocument();
  });
  it.each(["reason", "choice", "invitation", "files", "confirmation"])("invalidates a preview on %s change", async field => {
    await mount(); await preview("accept");
    if (field === "reason") fireEvent.change(screen.getByLabelText(/^Reason code/), { target: { value: "changed" } });
    if (field === "choice") decide("decline");
    if (field === "invitation") fill("Registration UUID", foreign);
    if (field === "files") fireEvent.change(screen.getByLabelText("Original selection file"), { target: { files: [] } });
    if (field === "confirmation") fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.queryByRole("button", { name: "Commit exact participation preview" })).not.toBeInTheDocument(); expect(pilot.commitPilotDecision).not.toHaveBeenCalled();
  });
  it("recovers an unknown commit using only its original key and hash; 404 does not unlock a new write", async () => {
    vi.mocked(pilot.commitPilotDecision).mockRejectedValueOnce(new ApiError(503, null, "PRIVATE_CANARY")); await mount(); await preview("accept"); click("Commit exact participation preview");
    await screen.findByText(/Commit outcome is unknown/); const input = vi.mocked(pilot.commitPilotDecision).mock.calls[0][0];
    expect(screen.queryByLabelText("Original selection file")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
    vi.mocked(pilot.recoverPilotDecision).mockRejectedValueOnce(new ApiError(404, null, "PRIVATE_CANARY")); click("Check original outcome"); await screen.findByText(/No outcome was observed/);
    expect(screen.getByLabelText("Registration UUID")).toBeDisabled(); vi.mocked(pilot.recoverPilotDecision).mockResolvedValueOnce(syntheticReply(input, true, true)); click("Check original outcome");
    await screen.findByRole("heading", { name: "Historical participation receipt" }); expect(pilot.commitPilotDecision).toHaveBeenCalledTimes(1);
    expect(vi.mocked(pilot.recoverPilotDecision).mock.calls[0][0]).toEqual(vi.mocked(pilot.recoverPilotDecision).mock.calls[1][0]); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
  });
  it("clears an unresolved operation on account switch and exposes recovery only to the original account", async () => {
    vi.mocked(pilot.commitPilotDecision).mockRejectedValueOnce(new ApiError(503, null, "PRIVATE_CANARY")); await mount(); await preview(); click("Commit exact participation preview"); await screen.findByText(/Commit outcome is unknown/);
    account = "foreign"; act(() => notifyAuthChange()); expect(screen.queryByRole("region", { name: "Unresolved participation operation" })).not.toBeInTheDocument();
    click("Refresh account access"); await screen.findByText(/unresolved operation belongs to another account/); expect(screen.getByLabelText("Registration UUID")).toBeDisabled();
    account = "self"; act(() => notifyAuthChange()); click("Refresh account access"); await screen.findByRole("button", { name: "Check original outcome" });
    expect(pilot.commitPilotDecision).toHaveBeenCalledTimes(1); expect(pilot.recoverPilotDecision).not.toHaveBeenCalled();
  });
  it("supports manual historical recovery without an invitation, documents or reviewer grant", async () => {
    await mount(); const ref = recoveryFor("accept"); fill("Recovery request key", ref.requestKey); fill("Recovery intent SHA-256", ref.intentSha256); click("Recover historical participation");
    const region = await screen.findByRole("region", { name: "Historical participation receipt" }); expect(within(region).getByText(/not current readiness/)).toBeInTheDocument();
    expect(pilot.inspectPilot).not.toHaveBeenCalled(); expect(pilot.commitPilotDecision).not.toHaveBeenCalled();
  });
  it("rechecks account identity immediately before commit", async () => {
    await mount(); await preview(); account = "foreign"; click("Commit exact participation preview"); await screen.findByText(/Account access changed/);
    expect(pilot.commitPilotDecision).not.toHaveBeenCalled(); expect(screen.getByLabelText("Registration UUID")).toHaveValue("");
  });
  it("discards a late inspection after an auth change", async () => {
    const pending = deferred<string>(); vi.mocked(pilot.inspectPilot).mockReturnValueOnce(pending.promise); await mount();
    fill("Registration UUID", http.query.registration_id); fill("Registration record SHA-256", http.query.registration_sha256); click("Inspect invitation");
    await waitFor(() => expect(pilot.inspectPilot).toHaveBeenCalled()); act(() => notifyAuthChange()); await act(async () => pending.resolve(http.initial));
    expect(screen.queryByRole("region", { name: "Current pilot participation" })).not.toBeInTheDocument(); expect(screen.getByLabelText("Registration UUID")).toHaveValue("");
  });
  it("guards double-click commits synchronously and ignores a late reply after auth revocation", async () => {
    const pending = deferred<string>(); vi.mocked(pilot.commitPilotDecision).mockReturnValueOnce(pending.promise); await mount(); await preview();
    click("Commit exact participation preview"); click("Commit exact participation preview"); await waitFor(() => expect(pilot.commitPilotDecision).toHaveBeenCalledTimes(1));
    const input = vi.mocked(pilot.commitPilotDecision).mock.calls[0][0]; act(() => notifyAuthChange()); await act(async () => pending.resolve(syntheticReply(input, true)));
    expect(screen.queryByRole("region", { name: "Historical participation receipt" })).not.toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Unresolved participation operation" })).not.toBeInTheDocument();
  });
  it("refresh clears private invitation, uploaded files, consent and prepared preview", async () => {
    await mount(); await preview("accept"); click("Refresh account access"); await waitFor(() => expect(screen.getByLabelText("Registration UUID")).toBeEnabled());
    expect(screen.getByLabelText("Registration UUID")).toHaveValue(""); expect(screen.queryByRole("button", { name: "Commit exact participation preview" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Original selection file")).not.toBeInTheDocument();
  });
  it("survives StrictMode admission replay without automatic writes", async () => { await mount(true); await load(); expect(pilot.previewPilotDecision).not.toHaveBeenCalled(); expect(pilot.commitPilotDecision).not.toHaveBeenCalled(); });
});
