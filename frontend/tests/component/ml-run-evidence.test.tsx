import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlRunEvidencePanel } from "@/components/MlRunEvidencePanel";
import { notifyAuthChange } from "@/lib/auth-session";
import * as runs from "@/lib/ml-use-runs";
import { canonical, changed, http, sha, syntheticReply } from "../helpers/ml-run-wire";

vi.mock("@/lib/ml-use-runs", async original => ({ ...await original<typeof runs>(), readRunEvidence: vi.fn(), purgeRunEvidence: vi.fn() }));
const text = 'SYNTHETIC review only.\nΔTc / 数据 / 🧪 <script>alert("never")</script>\n';
const input = { ...http.approve_input, evidence_sha256: sha(text), evidence_text: text } as runs.RunDecisionInput;
const decision = JSON.parse(syntheticReply("decision", input, true)).result.decision;
const ref = { decision_id: decision.id, decision_sha256: decision.record_sha256 };
const boundary = { scope: "private_run_review_text_not_scientific_acceptance_or_execution_authority", scientific_acceptance: false,
  source_permission_granted: false, run_authorization_granted: false, ml_training_approved: false, training_execution: "disabled" };
const document = canonical({ version: runs.RUN_EVIDENCE_VERSION, ...ref, decision, plan_id: decision.plan_id, plan_sha256: decision.plan_sha256,
  content_sha256: sha(text), content_type: "text/plain; charset=utf-8", text, size_bytes: new TextEncoder().encode(text).length,
  access_expires_at: JSON.parse(http.context).input_access_expires_at, ...boundary });
const purged = canonical({ version: runs.RUN_EVIDENCE_VERSION, committed: true, result: { version: runs.RUN_EVIDENCE_VERSION,
  ...ref, evidence_state: "purged", replayed: false, purge: { reason: "reviewer_request", created_at: decision.created_at }, ...boundary } });

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); vi.mocked(runs.readRunEvidence).mockResolvedValue(document); vi.mocked(runs.purgeRunEvidence).mockResolvedValue(purged); });
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name, exact: true }));
function opened() {
  render(<MlRunEvidencePanel />); expect(runs.readRunEvidence).not.toHaveBeenCalled(); click("Manage private review evidence");
  fireEvent.change(screen.getByLabelText("Evidence decision UUID"), { target: { value: ref.decision_id } });
  fireEvent.change(screen.getByLabelText("Evidence decision record SHA-256"), { target: { value: ref.decision_sha256 } });
}

describe("private evidence exact-byte contract", () => {
  it("binds literal UTF-8 text to its immutable decision, not just a self-supplied content hash", async () => {
    const result = await runs.parseRunEvidence(document, ref); expect(result.text).toBe(text); expect(result.decision).toEqual(decision);
    expect(runs.runIntent("decision", input, decision.actor_user_id)).not.toHaveProperty("evidence_text");
    expect(await runs.runEvidenceDigest(text)).toBe(sha(text));
    expect(runs.validRunEvidenceText("é".repeat(4096))).toBe(true);
    for (const value of ["", " \t\n", "é".repeat(4097), "\u0000", "\ud800"]) expect(runs.validRunEvidenceText(value)).toBe(false);
  });
  it.each(["text", "resealed_text", "decision", "plan", "size", "expiry", "authority", "extra"])("refuses mutated evidence %s", async name => {
    const raw = changed(document, v => {
      if (name === "text") v.text += "changed";
      if (name === "resealed_text") { v.text += "changed"; v.content_sha256 = sha(v.text); v.size_bytes = new TextEncoder().encode(v.text).length; }
      if (name === "decision") v.decision.record_sha256 = "f".repeat(64);
      if (name === "plan") v.plan_sha256 = "f".repeat(64);
      if (name === "size") v.size_bytes++;
      if (name === "expiry") v.access_expires_at = "not a date";
      if (name === "authority") v.scientific_acceptance = true;
      if (name === "extra") v.source_bytes = "unrequested";
    });
    await expect(runs.parseRunEvidence(raw, ref)).rejects.toThrow();
  });
  it.each(["record", "committed", "state", "reason", "authority"])("refuses inconsistent purge receipt %s", name => {
    const raw = changed(purged, v => {
      if (name === "record") v.result.decision_sha256 = "f".repeat(64);
      if (name === "committed") v.committed = false;
      if (name === "state") v.result.evidence_state = "retained";
      if (name === "reason") v.result.purge.reason = "inferred";
      if (name === "authority") v.result.run_authorization_granted = true;
    });
    expect(() => runs.parseRunEvidencePurge(raw, ref)).toThrow();
  });
});

describe("private evidence interactions", () => {
  it("loads only explicitly, renders source strings inertly and clears without browser storage", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem"); opened(); click("Read exact private review");
    await screen.findByText(/Content SHA-256:/); expect(documentBody().querySelector("pre")?.textContent).toBe(text);
    expect(documentBody().querySelector("script")).toBeNull(); expect(storage).not.toHaveBeenCalled();
    expect(runs.readRunEvidence).toHaveBeenCalledWith(ref, expect.any(AbortSignal));
    click("Clear displayed text"); expect(documentBody().querySelector("pre")).toBeNull();
  });
  it("requires explicit purge confirmation, then clears retained display and reports preserved history", async () => {
    opened(); expect(screen.getByRole("button", { name: "Purge exact private review" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox")); click("Purge exact private review");
    await screen.findByText(/Private text purge verified/); expect(runs.purgeRunEvidence).toHaveBeenCalledTimes(1);
    expect(runs.purgeRunEvidence).toHaveBeenCalledWith(ref, expect.any(AbortSignal)); expect(documentBody().querySelector("pre")).toBeNull();
  });
  it("keeps an uncertain purge locked and retries only identical references on explicit request", async () => {
    vi.mocked(runs.purgeRunEvidence).mockRejectedValueOnce(new Error("PRIVATE_CANARY")); opened();
    fireEvent.click(screen.getByRole("checkbox")); click("Purge exact private review"); await screen.findByText(/Purge outcome is unknown/);
    expect(screen.getByLabelText("Evidence decision UUID")).toBeDisabled(); expect(runs.purgeRunEvidence).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument(); click("Retry identical evidence purge");
    await screen.findByText(/Private text purge verified/); expect(vi.mocked(runs.purgeRunEvidence).mock.calls[1][0]).toEqual(ref);
  });
  it("invalidates a stale read on auth change before it can restore private text", async () => {
    let resolve!: (raw: string) => void;
    vi.mocked(runs.readRunEvidence).mockImplementationOnce(() => new Promise(done => { resolve = done; })); opened(); click("Read exact private review");
    act(() => { notifyAuthChange(); }); await act(async () => { resolve(document); });
    expect(documentBody().querySelector("pre")).toBeNull(); expect(screen.queryByLabelText("Evidence decision UUID")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Manage private review evidence" })).toBeEnabled());
  });
});
function documentBody() { return window.document.body; }
