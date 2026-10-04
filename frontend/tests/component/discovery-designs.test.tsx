import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryDesignWorkbench } from "@/components/DiscoveryDesignWorkbench";
import { ApiError, discoveryDesignCapabilities, discoveryDesignCommit, discoveryDesignContext, discoveryDesignDetail, discoveryDesignOutcome, discoveryDesignPage, discoveryDesignPreview } from "@/lib/api";
import { knownDesignCapabilities, knownDesignContext, knownDesignDetail, knownDesignPage, knownDesignReceipt, knownDesignRequest, emptyResearchDesign } from "@/lib/discovery-designs";
import wire from "../fixtures/discovery-designs-native.synthetic.json";
import { notifyAuthChange } from "@/lib/auth-session";
import { expressionCanonical, expressionSha } from "@/lib/source-expressions";
import type { DesignRequest } from "@/lib/discovery-designs";

vi.mock("@/components/dashboard/user-context", () => ({ useDashboardUser: () => ({ user: { id: wire.capabilities.actor_user_id } }) }));
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), discoveryDesignCapabilities: vi.fn(), discoveryDesignContext: vi.fn(), discoveryDesignPreview: vi.fn(), discoveryDesignCommit: vi.fn(), discoveryDesignOutcome: vi.fn(), discoveryDesignPage: vi.fn(), discoveryDesignDetail: vi.fn(), discoveryConditionBatchCapabilities: vi.fn().mockRejectedValue(new Error("Batch capability unavailable in existing design tests")) }));
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const capability = () => knownDesignCapabilities(wire.capabilities, wire.capabilities.actor_user_id)!;
const clone = <T,>(value: T): T => structuredClone(value);
function defaults() {
  vi.mocked(discoveryDesignCapabilities).mockResolvedValue(clone(wire.capabilities));
  vi.mocked(discoveryDesignContext).mockResolvedValue(clone(wire.context));
  vi.mocked(discoveryDesignPage).mockResolvedValue(clone(wire.page));
  vi.mocked(discoveryDesignDetail).mockResolvedValue(clone(wire.detail));
}
// Reuse the native receipt envelope for UI transport-failure tests. These
// transformed mock receipts are not represented as native SQL executions.
async function mockPreview(request: DesignRequest) {
  const result = clone(wire.preview), body = JSON.parse(result.receipt_canonical_json);
  const requestText = expressionCanonical(request), requestSha = await expressionSha(requestText);
  body.request_key = request.request_key; body.request_json = requestText; body.request_sha256 = requestSha;
  body.payload = request.payload; body.operation = request.operation;
  if (request.operation !== "withdraw") { body.baseline = request.payload.baseline; body.design = request.payload.design; body.parent = request.payload.parent; }
  const preview = JSON.parse(body.preview_json); preview.request_sha256 = requestSha;
  body.preview_json = expressionCanonical(preview); body.preview_sha256 = await expressionSha(body.preview_json);
  result.request_key = request.request_key; result.request_sha256 = requestSha; result.request_canonical_json = requestText;
  result.preview_canonical_json = body.preview_json; result.preview_sha256 = body.preview_sha256;
  result.receipt_canonical_json = expressionCanonical(body); result.receipt_sha256 = await expressionSha(result.receipt_canonical_json);
  return result;
}
async function fillValidProposal() {
  fireEvent.click(await screen.findByRole("button", { name: "Load exact baseline" }));
  await screen.findByRole("region", { name: "Baseline reference" });
  for (const [label, value] of [["Host label", "Synthetic research host"], ["Proposed state label", "Synthetic modified state"], ["Parameters 1", "Define site A and nominal x = 0.05 per formula unit"], ["Research hypothesis", "Inspect whether the site model has supporting evidence"], ["Question this action tests", "Does the source resolve the site?"], ["Prerequisites (one per line)", "Inspect the exact source and supplement"], ["Observable outcome 1", "The source supplies a resolved site"], ["Observable outcome 2", "The source leaves the site unresolved"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
it("replays actual synthetic SQL/HTTP capabilities, context, receipt, page and history", async () => {
  const cap = capability(); expect(cap).not.toBeNull();
  const b = wire.context.baseline;
  expect(await knownDesignContext(wire.context, cap, { kind: "native_property", material_id: b.material_id, record_index: null, property_id: b.property_id })).not.toBeNull();
  expect(knownDesignRequest(wire.request)).toBe(true);
  const ref = { actorId: cap.actor_user_id, requestKey: wire.request.request_key, requestSha: wire.preview.request_sha256, previewSha: wire.preview.preview_sha256, receiptSha: wire.preview.receipt_sha256, receiptId: wire.preview.receipt_id };
  expect(await knownDesignReceipt(wire.preview, cap, ref, "preview")).not.toBeNull();
  expect(await knownDesignReceipt(wire.commit, cap, ref, "commit")).not.toBeNull();
  expect(await knownDesignReceipt(wire.outcome, cap, ref, "outcome")).not.toBeNull();
  expect(await knownDesignPage(wire.page, cap, 0)).not.toBeNull();
  expect(await knownDesignDetail(wire.detail, cap, wire.commit.design_id)).not.toBeNull();
});
it("rejects a dry-run preview disguised as a saved replay", async () => {
  expect(await knownDesignReceipt({ ...wire.preview, replayed: true }, capability(), undefined, "preview")).toBeNull();
});
it.each(["context", "receipt", "page", "detail"] as const)("detaches %s values and actor pins before asynchronous proof checks", async kind => {
  let release!: () => Promise<void>, first = true;
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn((algorithm: string, bytes: Uint8Array) => {
    const captured = new Uint8Array(bytes);
    if (!first) return webcrypto.subtle.digest(algorithm, captured);
    first = false;
    return new Promise<ArrayBuffer>(resolve => { release = async () => resolve(await webcrypto.subtle.digest(algorithm, captured)); });
  }) } });
  const cap = clone(capability()), expected = { kind: "native_property" as const, material_id: wire.context.baseline.material_id, record_index: null, property_id: wire.context.baseline.property_id };
  const value = clone(kind === "context" ? wire.context : kind === "receipt" ? wire.commit : kind === "page" ? wire.page : wire.detail);
  const original = clone(value);
  const pending = kind === "context" ? knownDesignContext(value, cap, expected) : kind === "receipt" ? knownDesignReceipt(value, cap) : kind === "page" ? knownDesignPage(value, cap, 0) : knownDesignDetail(value, cap, wire.commit.design_id);
  value.scientific_acceptance = true as never;
  cap.actor_user_id = "00000000-0000-0000-0000-000000000000";
  expected.material_id = "Changed during proof verification";
  await release();
  expect(await pending).toEqual(original);
});
it("rejects false authority, private source extensions and corrupted immutable receipts", async () => {
  expect(knownDesignCapabilities({ ...wire.capabilities, scientific_acceptance: true }, wire.capabilities.actor_user_id)).toBeNull();
  expect(await knownDesignReceipt({ ...wire.commit, context_json: "PRIVATE SOURCE" }, capability())).toBeNull();
  expect(await knownDesignReceipt({ ...wire.commit, receipt_sha256: "a".repeat(64) }, capability())).toBeNull();
  expect(await knownDesignReceipt({ ...wire.commit, request_canonical_json: wire.commit.request_canonical_json.replace("Synthetic", "Modified") }, capability())).toBeNull();
  const changed = clone(wire.detail); changed.entries[0].design.hypothesis = "Changed outside immutable proof";
  expect(await knownDesignDetail(changed, capability(), wire.commit.design_id)).toBeNull();
});
it("rejects wrong actor, selector, session, head and recovery request pins", async () => {
  const wrong = { ...capability(), session_version: capability().session_version + 1 };
  expect(await knownDesignPage(wire.page, wrong, 0)).toBeNull();
  expect(await knownDesignContext(wire.context, capability(), { kind: "unanchored", material_id: null, record_index: null, property_id: null })).toBeNull();
  expect(await knownDesignReceipt(wire.commit, { ...capability(), actor_user_id: "00000000-0000-0000-0000-000000000000" })).toBeNull();
  const changed = clone(wire.detail); changed.entries[0].is_head = false;
  expect(await knownDesignDetail(changed, capability(), wire.commit.design_id)).toBeNull();
  expect(await knownDesignReceipt(wire.outcome, capability(), { actorId: capability().actor_user_id, requestKey: wire.request.request_key, requestSha: "b".repeat(64), previewSha: wire.preview.preview_sha256, receiptSha: wire.preview.receipt_sha256, receiptId: wire.preview.receipt_id }, "outcome")).toBeNull();
});
it("rejects outer projection tampering while immutable record hashes remain unchanged", async () => {
  const detail = clone(wire.detail); detail.entries[0].projection!.values[0].value = 300;
  expect(await knownDesignDetail(detail, capability(), wire.commit.design_id)).toBeNull();
  const page = clone(wire.page); page.entries[0].projection!.formula = "Different formula";
  expect(await knownDesignPage(page, capability(), 0)).toBeNull();
  const context = clone(wire.context); context.projection!.pressure_gpa = 250 as never;
  expect(await knownDesignContext(context, capability(), { kind: "native_property", material_id: wire.context.baseline.material_id, record_index: null, property_id: wire.context.baseline.property_id })).toBeNull();
});
it("requires decision-changing outcomes and keeps unknown resources distinct from explicit zero", () => {
  const req = clone(wire.request); req.payload.design.next_action.outcomes[1].decision = req.payload.design.next_action.outcomes[0].decision;
  expect(knownDesignRequest(req)).toBe(false);
  const single = clone(wire.request); single.payload.design.next_action.outcomes.pop(); expect(knownDesignRequest(single)).toBe(false);
  const budget = clone(wire.request); budget.payload.design.next_action.budget[0].raw_upper = "0" as never; expect(knownDesignRequest(budget)).toBe(false);
  const explicit = clone(wire.request); explicit.payload.design.next_action.budget[0].status = "estimated"; explicit.payload.design.next_action.budget[0].raw_upper = "0" as never; expect(knownDesignRequest(explicit)).toBe(true);
  expect(emptyResearchDesign().next_action.budget.every(b => b.status === "unknown" && b.raw_upper === null)).toBe(true);
});
it("loads saved history with explicit source scope and no automatic write", async () => {
  defaults(); render(<DiscoveryDesignWorkbench />);
  const load = await screen.findByRole("button", { name: "Load saved designs" });
  fireEvent.click(load); fireEvent.click(await screen.findByRole("button", { name: "Inspect history" }));
  expect(await screen.findByRole("region", { name: "Research design history" })).toHaveTextContent("band gap: 0 eV");
  expect(screen.getByText(/Latest 1 of 1 immutable revisions/)).toBeInTheDocument();
  expect(discoveryDesignPreview).not.toHaveBeenCalled(); expect(discoveryDesignCommit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Start linked proposal" }));
  expect(screen.getByLabelText("Host label")).toHaveValue(wire.request.payload.design.host_label);
  expect(screen.getByRole("button", { name: "Preview private proposal" })).toBeDisabled();
  expect(screen.getByText(/This link does not establish material genealogy/)).toBeInTheDocument();
});
it("turns an explicitly selected condition scenario into a linked proposal only after fresh baseline loading", async () => {
  defaults(); vi.mocked(discoveryDesignPreview).mockImplementation(request => mockPreview(request));
  render(<DiscoveryDesignWorkbench />);
  fireEvent.click(await screen.findByRole("button", { name: "Load saved designs" }));
  fireEvent.click(await screen.findByRole("button", { name: "Inspect history" }));
  fireEvent.click(await screen.findByText("Plan a bounded condition sweep"));
  fireEvent.change(screen.getByLabelText("Pressure choices (GPa, one per line)"), { target: { value: "10\n20" } });
  fireEvent.change(screen.getByLabelText("Temperature choices (K, one per line)"), { target: { value: "300" } });
  fireEvent.click(screen.getByRole("button", { name: "Estimate combinations" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate scenarios" }));
  fireEvent.click(await screen.findByRole("button", { name: "Use 20 GPa target · 300 K target" }));
  expect(screen.getByLabelText("Requested pressure (GPa)")).toHaveValue("20");
  expect(screen.getByLabelText("Requested temperature (K, optional)")).toHaveValue("300");
  expect(screen.getByRole("button", { name: "Preview private proposal" })).toBeDisabled();
  expect(discoveryDesignPreview).not.toHaveBeenCalled(); expect(discoveryDesignCommit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Load exact baseline" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Preview private proposal" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Preview private proposal" }));
  await screen.findByRole("region", { name: "Exact design preview" });
  const request = vi.mocked(discoveryDesignPreview).mock.calls[0][0];
  expect(request.operation).toBe("propose");
  expect(request.payload).toMatchObject({ parent: { design_id: wire.commit.design_id, revision_id: wire.commit.receipt_id, record_sha256: wire.commit.receipt_sha256 }, design: { target_conditions: { pressure: { kind: "specified", raw_gpa: "20" }, temperature_k: "300" } } });
  expect(discoveryDesignCommit).not.toHaveBeenCalled();
});
it("clears private source values, history, selector and draft on pagehide and ignores late reads", async () => {
  defaults(); let resolve!: (value: unknown) => void;
  vi.mocked(discoveryDesignPage).mockImplementation(() => new Promise(done => { resolve = done; }));
  render(<DiscoveryDesignWorkbench initialMaterialId={wire.context.baseline.material_id} initialPropertyId={wire.context.baseline.property_id} />);
  fireEvent.click(await screen.findByRole("button", { name: "Load exact baseline" }));
  expect(await screen.findByRole("region", { name: "Baseline reference" })).toHaveTextContent("band gap: 0 eV");
  fireEvent.change(screen.getByLabelText("Host label"), { target: { value: "PRIVATE DRAFT" } });
  fireEvent.click(screen.getByRole("button", { name: "Load saved designs" }));
  act(() => { window.dispatchEvent(new Event("pagehide")); });
  await act(async () => { resolve(clone(wire.page)); });
  expect(document.body.textContent).not.toContain("PRIVATE DRAFT");
  expect(screen.queryByRole("region", { name: "Baseline reference" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Saved research designs" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Exact material ID")).not.toBeInTheDocument();
  expect(discoveryDesignCommit).not.toHaveBeenCalled();
});
it("shows default-disabled or unavailable interface without granting access from account flags", async () => {
  vi.mocked(discoveryDesignCapabilities).mockRejectedValue(new ApiError(404, {}, "Unavailable"));
  render(<DiscoveryDesignWorkbench />);
  expect(await screen.findByText(/This research-design interface or exact record is unavailable/)).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Persistent research design" })).not.toBeInTheDocument();
});
it("clears the previous private selector and draft on authentication changes", async () => {
  defaults(); render(<DiscoveryDesignWorkbench initialMaterialId={wire.context.baseline.material_id} initialPropertyId={wire.context.baseline.property_id} />);
  expect(await screen.findByLabelText("Exact material ID")).toHaveValue(wire.context.baseline.material_id);
  fireEvent.change(screen.getByLabelText("Host label"), { target: { value: "Previous private draft" } });
  act(() => notifyAuthChange());
  fireEvent.click(screen.getByRole("button", { name: "Refresh access" }));
  expect(await screen.findByLabelText("Baseline type")).toHaveValue("unanchored");
  expect(screen.getByLabelText("Host label")).toHaveValue("");
  expect(screen.queryByLabelText("Exact property ID")).not.toBeInTheDocument();
});
it.each([false, true])("recovers an unknown save by the original GET without retrying a write (hide=%s)", async hide => {
  defaults(); let preview!: typeof wire.preview;
  vi.mocked(discoveryDesignPreview).mockImplementation(async request => { preview = await mockPreview(request); return preview; });
  vi.mocked(discoveryDesignCommit).mockRejectedValue(new ApiError(503, {}, "Synthetic unknown submission outcome"));
  vi.mocked(discoveryDesignOutcome).mockImplementation(async () => ({ ...preview, dry_run: false, pending_ledger_written: true, replayed: true }));
  render(<DiscoveryDesignWorkbench initialMaterialId={wire.context.baseline.material_id} initialPropertyId={wire.context.baseline.property_id} />);
  await fillValidProposal();
  fireEvent.submit(screen.getByRole("form", { name: "Persistent research design" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save private proposal" }));
  await screen.findByRole("button", { name: "Check original request" });
  if (hide) { act(() => { window.dispatchEvent(new Event("pagehide")); }); fireEvent.click(screen.getByRole("button", { name: "Refresh access" })); }
  fireEvent.click(await screen.findByRole("button", { name: "Check original request" }));
  expect(await screen.findByRole("region", { name: "Saved design receipt" })).toHaveTextContent("Revision 1 · proposed");
  expect(discoveryDesignPreview).toHaveBeenCalledTimes(1); expect(discoveryDesignCommit).toHaveBeenCalledTimes(1); expect(discoveryDesignOutcome).toHaveBeenCalledTimes(1);
  expect(vi.mocked(discoveryDesignOutcome).mock.calls[0].slice(0, 2)).toEqual([preview.request_key, preview.request_sha256]);
});
it("invalidates an exact preview when a proposal field changes", async () => {
  defaults(); vi.mocked(discoveryDesignPreview).mockImplementation(mockPreview);
  render(<DiscoveryDesignWorkbench initialMaterialId={wire.context.baseline.material_id} initialPropertyId={wire.context.baseline.property_id} />);
  await fillValidProposal(); fireEvent.submit(screen.getByRole("form", { name: "Persistent research design" }));
  await screen.findByRole("button", { name: "Save private proposal" });
  fireEvent.change(screen.getByLabelText("Requested temperature (K, optional)"), { target: { value: "300" } });
  expect(screen.queryByRole("button", { name: "Save private proposal" })).not.toBeInTheDocument();
  expect(discoveryDesignCommit).not.toHaveBeenCalled();
});
