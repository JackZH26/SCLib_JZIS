import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardUserProvider } from "@/components/dashboard/user-context";
import { SourcePropertyWorkbench } from "@/components/SourcePropertyWorkbench";
import { ApiError, sourcePropertyCapabilities, sourcePropertyDetail, sourcePropertyDownload, sourcePropertyImportCommit,
  sourcePropertyImportOutcome, sourcePropertyImportPreview, sourcePropertyList, sourcePropertyReviewCommit, sourcePropertyReviewOutcome, sourcePropertyReviewPreview, type User } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { PROPERTY_SNAPSHOTS, type PropertyReviewRequest } from "@/lib/source-properties";
import { access, actorId, copy, detail, importReceipt, noteReceipt, otherId, page, requestNote } from "./source-properties-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), sourcePropertyCapabilities: vi.fn(), sourcePropertyDetail: vi.fn(), sourcePropertyDownload: vi.fn(),
  sourcePropertyImportCommit: vi.fn(), sourcePropertyImportOutcome: vi.fn(), sourcePropertyImportPreview: vi.fn(), sourcePropertyList: vi.fn(), sourcePropertyReviewCommit: vi.fn(), sourcePropertyReviewOutcome: vi.fn(), sourcePropertyReviewPreview: vi.fn() }));
const user = { id: actorId, name: "Synthetic test actor", email: "test@example.invalid", is_admin: false, is_reviewer: false } as User;
function view(id = actorId) { return <DashboardUserProvider value={{ user: { ...user, id }, setUser: vi.fn() }}><SourcePropertyWorkbench /></DashboardUserProvider>; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function mount() { const rendered = render(view()); await screen.findByText(/Current access verified/); await screen.findByRole("button", { name: "Inspect dHc₂/dT" }); return rendered; }
async function inspect() { fireEvent.click(screen.getByRole("button", { name: "Inspect dHc₂/dT" })); await screen.findByRole("button", { name: "Download private record" }); }
async function prepareImport() { fireEvent.click(screen.getByRole("button", { name: "Preview pending import" })); return screen.findByRole("button", { name: "Save pending import" }); }
async function prepareNote() {
  await inspect(); fireEvent.click(screen.getByLabelText("Source value or statement")); fireEvent.change(screen.getByLabelText("Inspection note"), { target: { value: "Test-only source expression inspection." } });
  fireEvent.click(screen.getByLabelText(/I inspected the cited source/)); fireEvent.click(screen.getByRole("button", { name: "Preview source note" })); return screen.findByRole("button", { name: "Save source note" });
}
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto);
  vi.mocked(sourcePropertyCapabilities).mockResolvedValue(copy(access)); vi.mocked(sourcePropertyList).mockResolvedValue(page());
  vi.mocked(sourcePropertyDetail).mockResolvedValue(detail()); vi.mocked(sourcePropertyDownload).mockResolvedValue(detail());
  vi.mocked(sourcePropertyImportPreview).mockImplementation(body => importReceipt(body.request_key)); vi.mocked(sourcePropertyImportCommit).mockImplementation(body => importReceipt(body.request_key, false));
  vi.mocked(sourcePropertyReviewPreview).mockImplementation(request => noteReceipt(request)); vi.mocked(sourcePropertyReviewCommit).mockImplementation(request => noteReceipt(request, false));
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => new Response(readFileSync(`public${url}`))));
  Object.defineProperty(URL, "createObjectURL", { value: vi.fn().mockReturnValue("blob:private-test"), configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true }); vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("private pending source workbench", () => {
  it("waits for authenticated capabilities before private reads or writes and refuses foreign actor responses", async () => {
    const pending = deferred<unknown>(); vi.mocked(sourcePropertyCapabilities).mockReturnValue(pending.promise); render(view());
    expect(sourcePropertyList).not.toHaveBeenCalled(); expect(screen.queryByRole("button", { name: "Preview pending import" })).not.toBeInTheDocument();
    await act(async () => pending.resolve({ ...access, actor_user_id: otherId })); await screen.findByText(/response could not be verified/);
    expect(sourcePropertyList).not.toHaveBeenCalled(); expect(sourcePropertyImportPreview).not.toHaveBeenCalled();
  });
  it("keeps unavailable interface explicit and offers no implicit grant or public approval", async () => {
    vi.mocked(sourcePropertyCapabilities).mockRejectedValue(new ApiError(404, null, "unavailable")); render(view()); await screen.findByText(/pending source interface or record is unavailable/);
    expect(sourcePropertyList).not.toHaveBeenCalled(); expect(screen.getByText(/does not approve science/)).toBeInTheDocument();
  });
  it("shows signed source values and conditions, without promoting context or overwriting scientific roles", async () => {
    await mount(); await inspect(); expect(screen.getByText("-2.8 T/K")).toBeInTheDocument(); expect(screen.getByText("source curve derived slope")).toBeInTheDocument();
    expect(screen.getByText(/50% resistive transition/)).toBeInTheDocument(); expect(screen.getByText(/association unestablished/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source 1" })).toHaveAttribute("href", expect.stringContaining("arxiv.org")); expect(screen.queryByRole("option", { name: "Withdraw my preceding note" })).not.toBeInTheDocument();
  });
  it("does not write on selection or preview; explicit commit uses the exact displayed request and preview", async () => {
    await mount(); expect(sourcePropertyImportPreview).not.toHaveBeenCalled(); await prepareImport(); expect(sourcePropertyImportCommit).not.toHaveBeenCalled();
    expect(screen.getByText(/15 source records · 15 source expressions/)).toBeInTheDocument(); const request = vi.mocked(sourcePropertyImportPreview).mock.calls[0][0], p = await importReceipt(request.request_key);
    fireEvent.click(screen.getByRole("button", { name: "Save pending import" })); await screen.findByRole("heading", { name: "Saved pending receipt" }); expect(sourcePropertyImportCommit).toHaveBeenCalledOnce();
    expect(vi.mocked(sourcePropertyImportCommit).mock.calls[0][0]).toEqual(request); expect(vi.mocked(sourcePropertyImportCommit).mock.calls[0][1]).toBe(p.preview_sha256); expect(screen.getByText(/Saved to private pending history/)).toBeInTheDocument();
  });
  it("invalidates the import preview on snapshot change rather than committing previous bytes", async () => {
    await mount(); await prepareImport(); fireEvent.change(screen.getByLabelText("Source snapshot"), { target: { value: PROPERTY_SNAPSHOTS[1].sha256 } });
    expect(screen.queryByRole("button", { name: "Save pending import" })).not.toBeInTheDocument(); expect(sourcePropertyImportCommit).not.toHaveBeenCalled();
  });
  it("keeps the type selector consistent with the All types query after refreshing access", async () => {
    await mount(); fireEvent.change(screen.getByLabelText("Record type"), { target: { value: "quantity" } });
    await waitFor(() => expect(vi.mocked(sourcePropertyList).mock.calls.at(-1)?.[2]).toBe("quantity"));
    await screen.findByRole("button", { name: "Inspect dHc₂/dT" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh access" })); await screen.findByRole("button", { name: "Inspect dHc₂/dT" });
    expect(screen.getByLabelText("Record type")).toHaveValue(""); expect(vi.mocked(sourcePropertyList).mock.calls.at(-1)?.[2]).toBeUndefined();
  });
  it("requires deliberate checks, note and attestation; edits invalidate a note preview", async () => {
    await mount(); await inspect(); expect(screen.getByRole("button", { name: "Preview source note" })).toBeDisabled(); fireEvent.click(screen.getByLabelText("Source value or statement"));
    fireEvent.change(screen.getByLabelText("Inspection note"), { target: { value: "Test-only inspection" } }); expect(screen.getByRole("button", { name: "Preview source note" })).toBeDisabled(); expect(sourcePropertyReviewPreview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(/I inspected the cited source/)); fireEvent.click(screen.getByRole("button", { name: "Preview source note" })); await screen.findByRole("button", { name: "Save source note" });
    expect(sourcePropertyReviewCommit).not.toHaveBeenCalled(); fireEvent.change(screen.getByLabelText("Inspection note"), { target: { value: "Changed after preview" } }); expect(screen.queryByRole("button", { name: "Save source note" })).not.toBeInTheDocument();
  });
  it("commits a fidelity note against the exact observation/head rather than material or Tc approval", async () => {
    await mount(); await prepareNote(); const request = vi.mocked(sourcePropertyReviewPreview).mock.calls[0][0]; expect(request.scope).toBe("source_expression_fidelity_note");
    expect(request.expected_previous_review_id).toBeNull(); expect(request.observation_sha256).toBe(detail().record_sha256); fireEvent.click(screen.getByRole("button", { name: "Save source note" }));
    await screen.findByRole("heading", { name: "Saved pending receipt" }); expect(vi.mocked(sourcePropertyReviewCommit).mock.calls[0][0]).toEqual(request); expect(sourcePropertyImportCommit).not.toHaveBeenCalled();
  });
  it("recovers 503 only by original GET key/hash, retains uncertainty on 404 and never retries POST", async () => {
    await mount(); await prepareImport(); const request = vi.mocked(sourcePropertyImportPreview).mock.calls[0][0], previous = await importReceipt(request.request_key, false, true);
    vi.mocked(sourcePropertyImportCommit).mockRejectedValue(new ApiError(503, null, "unknown")); vi.mocked(sourcePropertyImportOutcome).mockRejectedValueOnce(new ApiError(404, null, "not found"));
    fireEvent.click(screen.getByRole("button", { name: "Save pending import" })); await screen.findByText(/Submission outcome is unknown/); expect(screen.queryByRole("button", { name: "Preview pending import" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByText(/original outcome remains unverified/); vi.mocked(sourcePropertyImportOutcome).mockResolvedValue(previous);
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("heading", { name: "Saved pending receipt" }); expect(sourcePropertyImportCommit).toHaveBeenCalledOnce();
    expect(vi.mocked(sourcePropertyImportOutcome).mock.calls[0].slice(0, 2)).toEqual([request.request_key, previous.request_sha256]);
  });
  it("keeps note-commit recovery separate and checks its original request/hash", async () => {
    await mount(); await prepareNote(); const request = vi.mocked(sourcePropertyReviewPreview).mock.calls[0][0]; vi.mocked(sourcePropertyReviewCommit).mockRejectedValue(new ApiError(503, null, "unknown"));
    const recovered = { ...await noteReceipt(request, false), replayed: true }; vi.mocked(sourcePropertyReviewOutcome).mockResolvedValue(recovered); fireEvent.click(screen.getByRole("button", { name: "Save source note" }));
    await screen.findByText(/Submission outcome is unknown/); fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("heading", { name: "Saved pending receipt" });
    expect(sourcePropertyReviewCommit).toHaveBeenCalledOnce(); expect(sourcePropertyImportOutcome).not.toHaveBeenCalled(); expect(vi.mocked(sourcePropertyReviewOutcome).mock.calls[0].slice(0, 2)).toEqual([request.request_key, recovered.request_sha256]);
  });
  it("clears all private response state on auth notification and ignores a late detail", async () => {
    await mount(); const delayed = deferred<unknown>(); vi.mocked(sourcePropertyDetail).mockReturnValue(delayed.promise); fireEvent.click(screen.getByRole("button", { name: "Inspect dHc₂/dT" }));
    act(() => notifyAuthChange()); await act(async () => delayed.resolve(detail())); expect(screen.queryByRole("button", { name: "Download private record" })).not.toBeInTheDocument();
    expect(screen.queryByText("-2.8 T/K")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Preview pending import" })).not.toBeInTheDocument();
  });
  it("prevents switched-account private downloads while current verified downloads produce a Blob", async () => {
    const rendered = await mount(); await inspect(); fireEvent.click(screen.getByRole("button", { name: "Download private record" })); await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledOnce());
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob)); const delayed = deferred<unknown>(); vi.mocked(sourcePropertyDownload).mockReturnValue(delayed.promise); fireEvent.click(screen.getByRole("button", { name: "Download private record" }));
    vi.mocked(sourcePropertyCapabilities).mockResolvedValue({ ...access, actor_user_id: otherId }); rendered.rerender(view(otherId)); await act(async () => delayed.resolve(detail()));
    expect(URL.createObjectURL).toHaveBeenCalledOnce(); expect(screen.queryByText("-2.8 T/K")).not.toBeInTheDocument();
  });
  it("does not expose or recover a preceding actor's unknown request after an account switch", async () => {
    const rendered = await mount(); await prepareImport(); vi.mocked(sourcePropertyImportCommit).mockRejectedValue(new ApiError(503, null, "unknown")); fireEvent.click(screen.getByRole("button", { name: "Save pending import" }));
    await screen.findByText(/Submission outcome is unknown/); vi.mocked(sourcePropertyCapabilities).mockResolvedValue({ ...access, actor_user_id: otherId }); rendered.rerender(view(otherId));
    await screen.findByRole("button", { name: "Preview pending import" }); expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument(); expect(sourcePropertyImportOutcome).not.toHaveBeenCalled();
  });
  it("allows own preceding-note withdrawal and treats a concurrent head change as a conflict", async () => {
    const current = detail(); current.source_notes = [await noteReceipt(requestNote(), false)]; current.source_notes_total = 1; vi.mocked(sourcePropertyDetail).mockResolvedValue(current);
    await mount(); await inspect(); expect(screen.getByRole("option", { name: "Withdraw my preceding note" })).toBeInTheDocument(); fireEvent.change(screen.getByLabelText("Finding"), { target: { value: "withdraw_note" } });
    fireEvent.click(screen.getByLabelText("Source locator")); fireEvent.change(screen.getByLabelText("Inspection note"), { target: { value: "Withdraw my prior test-only note." } }); fireEvent.click(screen.getByLabelText(/I inspected the cited source/));
    vi.mocked(sourcePropertyReviewPreview).mockImplementation(async (request: PropertyReviewRequest) => noteReceipt(request, true, access, 2)); fireEvent.click(screen.getByRole("button", { name: "Preview source note" })); await screen.findByRole("button", { name: "Save source note" });
    const request = vi.mocked(sourcePropertyReviewPreview).mock.calls[0][0]; expect(request.expected_previous_review_id).toBe(current.source_notes[0].review_id); expect(request.expected_previous_review_sha256).toBe(current.source_notes[0].review_sha256);
    vi.mocked(sourcePropertyReviewCommit).mockRejectedValue(new ApiError(409, null, "head changed")); fireEvent.click(screen.getByRole("button", { name: "Save source note" })); await screen.findByText(/note head changed/);
    expect(screen.queryByRole("button", { name: "Save source note" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
  });
});
