import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardUserProvider } from "@/components/dashboard/user-context";
import { SourceExpressionWorkbench } from "@/components/SourceExpressionWorkbench";
import { ApiError, sourceExpressionCapabilities, sourceExpressionCaptureDetail, sourceExpressionCaptures, sourceExpressionCommit, sourceExpressionDetail,
  sourceExpressionList, sourceExpressionOutcome, sourceExpressionPreview, type User } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { expressionCanonical, expressionSha, prepareExpressionPackage } from "@/lib/source-expressions";
import { emptyCapturePage, emptyExpressionPage, expressionActor, expressionCap, syntheticPackage, syntheticReceipt, syntheticRevision } from "../helpers/source-expression-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), sourceExpressionCapabilities: vi.fn(), sourceExpressionCaptureDetail: vi.fn(),
  sourceExpressionCaptures: vi.fn(), sourceExpressionCommit: vi.fn(), sourceExpressionDetail: vi.fn(), sourceExpressionList: vi.fn(), sourceExpressionOutcome: vi.fn(), sourceExpressionPreview: vi.fn() }));
const user = { id: expressionActor, name: "Synthetic source operator", email: "source@example.invalid", is_admin: false, is_reviewer: false } as User;
const otherId = "00000000-0000-4000-8000-000000000120";
function view(id = expressionActor) { return <DashboardUserProvider value={{ user: { ...user, id }, setUser: vi.fn() }}><SourceExpressionWorkbench /></DashboardUserProvider>; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function mount() { const result = render(view()); await screen.findByText("No retained expressions in this bounded view."); return result; }
async function selectFile(raw = "94.5 ± 0.3", unit = "K") {
  const pkg = await syntheticPackage(raw, unit), bytes = new TextEncoder().encode(JSON.stringify(pkg)), file = new File([bytes], "prepared-source-package.json", { type: "application/json" });
  Object.defineProperty(file, "arrayBuffer", { value: async () => bytes.buffer });
  fireEvent.change(screen.getByLabelText("Source-package JSON file"), { target: { files: [file] } });
  await screen.findByRole("button", { name: "Preview pending package" }); return pkg;
}
async function prepare() { await selectFile(); fireEvent.click(screen.getByRole("button", { name: "Preview pending package" })); await screen.findByRole("button", { name: "Save pending source expressions" }); }
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto); vi.mocked(sourceExpressionCapabilities).mockResolvedValue(structuredClone(expressionCap));
  vi.mocked(sourceExpressionList).mockImplementation(async offset => ({ ...emptyExpressionPage(), offset: offset ?? 0 }));
  vi.mocked(sourceExpressionCaptures).mockImplementation(async offset => ({ ...emptyCapturePage(), offset: offset ?? 0 }));
  vi.mocked(sourceExpressionPreview).mockImplementation(async body => syntheticReceipt(await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(body.package))), body.request_key));
  vi.mocked(sourceExpressionCommit).mockImplementation(async body => syntheticReceipt(await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(body.package))), body.request_key, false));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Private new-source intake workbench", () => {
  it("waits for exact authenticated capabilities and refuses foreign actors before any private read", async () => {
    const cap = deferred<unknown>(); vi.mocked(sourceExpressionCapabilities).mockReturnValue(cap.promise); render(view());
    expect(sourceExpressionList).not.toHaveBeenCalled(); expect(screen.queryByLabelText("Source-package JSON file")).not.toBeInTheDocument();
    await act(async () => cap.resolve({ ...expressionCap, actor_user_id: otherId })); await screen.findByText(/response could not be verified/); expect(sourceExpressionList).not.toHaveBeenCalled();
  });
  it("keeps default-disabled and read-only capability states explicit without adding auth or grants", async () => {
    vi.mocked(sourceExpressionCapabilities).mockRejectedValueOnce(new ApiError(404, null, "disabled")); render(view());
    await screen.findByText(/interface or record is unavailable/); expect(screen.queryByLabelText("Source-package JSON file")).not.toBeInTheDocument();
    vi.mocked(sourceExpressionCapabilities).mockResolvedValue({ ...expressionCap, can_import: false, curator_grant_id: null });
    fireEvent.click(screen.getByRole("button", { name: "Refresh access and records" })); await screen.findByText("Read access"); await screen.findByText("No retained expressions in this bounded view.");
    expect(screen.queryByLabelText("Source-package JSON file")).not.toBeInTheDocument(); expect(sourceExpressionPreview).not.toHaveBeenCalled();
  });
  it("keeps file selection local and preserves raw source values, computed origin and ambient window", async () => {
    await mount(); await selectFile("−2.8 ± 0.2", "K"); expect(sourceExpressionPreview).not.toHaveBeenCalled(); expect(sourceExpressionCommit).not.toHaveBeenCalled();
    expect(screen.getByText("−2.8 ± 0.2 K")).toBeInTheDocument(); expect(screen.getByText(/Source reported · Computed · ambient/)).toBeInTheDocument();
    expect(screen.getByText(/Window|Source window/, { selector: "p" })).toBeTruthy(); expect(screen.queryByText("0 GPa")).not.toBeInTheDocument();
  });
  it("explicitly previews and saves the identical package plus original preview digest", async () => {
    await mount(); await prepare(); expect(sourceExpressionCommit).not.toHaveBeenCalled(); const request = vi.mocked(sourceExpressionPreview).mock.calls[0][0];
    const prepared = await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(request.package))), preview = await syntheticReceipt(prepared, request.request_key);
    fireEvent.click(screen.getByRole("button", { name: "Save pending source expressions" })); await screen.findByRole("heading", { name: "Saved pending history" });
    expect(sourceExpressionCommit).toHaveBeenCalledOnce(); expect(vi.mocked(sourceExpressionCommit).mock.calls[0].slice(0, 2)).toEqual([request, preview.preview_sha256]);
    expect(screen.queryByRole("button", { name: "Save pending source expressions" })).not.toBeInTheDocument();
  });
  it("invalidates a checked preview when a different file is selected", async () => {
    await mount(); await prepare(); await selectFile("75", "mK"); expect(screen.queryByRole("button", { name: "Save pending source expressions" })).not.toBeInTheDocument();
    expect(screen.getByText("75 mK")).toBeInTheDocument(); expect(sourceExpressionCommit).not.toHaveBeenCalled();
  });
  it("rejects oversized and invalid JSON locally without rendering unknown private context or uploading", async () => {
    await mount(); const file = new File(["{\"private_notes\":\"confidential test string\"}"], "unsupported.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode('{"private_notes":"confidential test string"}').buffer });
    fireEvent.change(screen.getByLabelText("Source-package JSON file"), { target: { files: [file] } }); await screen.findByText(/does not match/);
    expect(screen.queryByText(/confidential test string/)).not.toBeInTheDocument(); expect(sourceExpressionPreview).not.toHaveBeenCalled();
    Object.defineProperty(file, "size", { value: 1024 * 1024 + 1 }); fireEvent.change(screen.getByLabelText("Source-package JSON file"), { target: { files: [file] } }); await screen.findByText(/Choose a source-package/);
  });
  it("keeps filter controls and applied query consistent after refresh", async () => {
    await mount(); fireEvent.change(screen.getByLabelText("Field"), { target: { value: "tc_kelvin" } }); fireEvent.change(screen.getByLabelText("Source identity"), { target: { value: "test-conference" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" })); await waitFor(() => expect(vi.mocked(sourceExpressionList).mock.calls.at(-1)?.[2]).toEqual({ field: "tc_kelvin", sourceId: "test-conference", currentness: undefined }));
    await screen.findByText("No retained expressions in this bounded view."); fireEvent.click(screen.getByRole("button", { name: "Refresh access and records" })); await screen.findByText("No retained expressions in this bounded view.");
    expect(screen.getByLabelText("Field")).toHaveValue(""); expect(screen.getByLabelText("Source identity")).toHaveValue(""); expect(vi.mocked(sourceExpressionList).mock.calls.at(-1)?.[2]).toEqual({});
  });
  it("checks a 503 only with original GET identity, preserves uncertainty on 404, then reads saved replay", async () => {
    await mount(); await prepare(); const request = vi.mocked(sourceExpressionPreview).mock.calls[0][0], prepared = await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(request.package)));
    const saved = await syntheticReceipt(prepared, request.request_key, false); saved.replayed = true;
    vi.mocked(sourceExpressionCommit).mockRejectedValue(new ApiError(503, null, "unknown")); vi.mocked(sourceExpressionOutcome).mockRejectedValueOnce(new ApiError(404, null, "not found")).mockResolvedValueOnce(saved);
    fireEvent.click(screen.getByRole("button", { name: "Save pending source expressions" })); await screen.findByText(/Save outcome is unknown/); expect(screen.queryByLabelText("Source-package JSON file")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check original request" })); await screen.findByText(/original outcome remains unverified/);
    fireEvent.click(screen.getByRole("button", { name: "Check original request" })); await screen.findByRole("heading", { name: "Saved pending history" });
    expect(sourceExpressionCommit).toHaveBeenCalledOnce(); expect(vi.mocked(sourceExpressionOutcome).mock.calls[0].slice(0, 2)).toEqual([request.request_key, prepared.requestSha]); expect(sourceExpressionPreview).toHaveBeenCalledOnce();
  });
  it("does not display a coordinated-tampered outcome with unchanged original operation identity", async () => {
    await mount(); await prepare(); const request = vi.mocked(sourceExpressionPreview).mock.calls[0][0], prepared = await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(request.package)));
    const changed = await syntheticReceipt(prepared, request.request_key, false); changed.replayed = true; changed.expression_manifest[0].projection_sha256 = "f".repeat(64);
    const preview = JSON.parse(changed.preview_canonical_json); preview.manifest = changed.expression_manifest; changed.preview_canonical_json = expressionCanonical(preview); changed.preview_sha256 = await expressionSha(changed.preview_canonical_json);
    const body = JSON.parse(changed.receipt_canonical_json); body.preview_sha256 = changed.preview_sha256; body.expression_manifest = changed.expression_manifest; changed.receipt_canonical_json = expressionCanonical(body); changed.receipt_sha256 = await expressionSha(changed.receipt_canonical_json);
    vi.mocked(sourceExpressionCommit).mockRejectedValue(new ApiError(503, null, "unknown")); vi.mocked(sourceExpressionOutcome).mockResolvedValue(changed);
    fireEvent.click(screen.getByRole("button", { name: "Save pending source expressions" })); await screen.findByText(/Save outcome is unknown/); fireEvent.click(screen.getByRole("button", { name: "Check original request" }));
    await screen.findByText(/original outcome remains unverified/); expect(screen.queryByRole("heading", { name: "Saved pending history" })).not.toBeInTheDocument(); expect(sourceExpressionCommit).toHaveBeenCalledOnce();
  });
  it("clears source data on auth change and ignores an in-flight file read", async () => {
    await mount(); const delayed = deferred<ArrayBuffer>(), file = new File(["{}"], "late-source.json"); Object.defineProperty(file, "arrayBuffer", { value: () => delayed.promise });
    fireEvent.change(screen.getByLabelText("Source-package JSON file"), { target: { files: [file] } }); act(() => notifyAuthChange());
    const pkg = await syntheticPackage(); await act(async () => delayed.resolve(new TextEncoder().encode(JSON.stringify(pkg)).buffer));
    expect(screen.queryByText(/LaH10/)).not.toBeInTheDocument(); expect(screen.queryByLabelText("Source-package JSON file")).not.toBeInTheDocument(); expect(sourceExpressionPreview).not.toHaveBeenCalled();
  });
  it("never exposes a prior actor's unknown operation after account switching", async () => {
    const mounted = await mount(); await prepare(); vi.mocked(sourceExpressionCommit).mockRejectedValue(new ApiError(503, null, "unknown"));
    fireEvent.click(screen.getByRole("button", { name: "Save pending source expressions" })); await screen.findByText(/Save outcome is unknown/);
    vi.mocked(sourceExpressionCapabilities).mockResolvedValue({ ...expressionCap, actor_user_id: otherId }); mounted.rerender(view(otherId)); await screen.findByText("No retained expressions in this bounded view.");
    expect(screen.queryByRole("button", { name: "Check original request" })).not.toBeInTheDocument(); expect(sourceExpressionOutcome).not.toHaveBeenCalled();
  });
  it("rejects a coordinated changed capture declaration under unchanged original record and fragment identities", async () => {
    const original = (await syntheticRevision()).capture, changed = structuredClone(original); changed.source.url = "https://example.com/changed-capture.pdf";
    changed.source.currentness = "declared_current"; changed.source_metadata_canonical_json = expressionCanonical(changed.source); changed.metadata_sha256 = await expressionSha(changed.source_metadata_canonical_json);
    vi.mocked(sourceExpressionCaptures).mockResolvedValue({ ...emptyCapturePage(), total: 1, captures: [original] });
    vi.mocked(sourceExpressionCaptureDetail).mockResolvedValue({ version: expressionCap.version, ...changed }); await mount();
    fireEvent.click(screen.getByText("Retained captures (1)")); fireEvent.click(screen.getByRole("button", { name: "Inspect capture scope" })); await screen.findByText(/response could not be verified/);
    expect(screen.queryByRole("region", { name: "Retained capture scope" })).not.toBeInTheDocument(); expect(screen.queryByRole("link", { name: "Open declared source link" })).not.toBeInTheDocument();
  });
  it("shows raw uncertainty/roles and honest publication declarations in exact detail, ignoring stale account responses", async () => {
    const revision = await syntheticRevision(), { version: _version, ...item } = revision; item.import_receipt = null;
    vi.mocked(sourceExpressionList).mockResolvedValue({ ...emptyExpressionPage(), total: 1, expressions: [item] }); vi.mocked(sourceExpressionDetail).mockResolvedValue(revision);
    const mounted = render(view()); await screen.findByRole("button", { name: "Inspect expression" }); fireEvent.click(screen.getByRole("button", { name: "Inspect expression" }));
    const section = await screen.findByRole("region", { name: "Exact source expression revision" }); expect(within(section).getByText("94.5 ± 0.3 K")).toBeInTheDocument();
    expect(within(section).getByText("Source reported · Computed")).toBeInTheDocument(); expect(within(section).getByText("ambient", { selector: "dd" })).toBeInTheDocument();
    expect(within(section).getByText(/Publication currentness remains unverified/)).toBeInTheDocument(); expect(within(section).getByText("Declared parent-file SHA256, unverified")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "Open declared source link" })).toHaveAttribute("href", "https://example.com/source.pdf");
    const late = deferred<unknown>(); vi.mocked(sourceExpressionDetail).mockReturnValue(late.promise); fireEvent.click(screen.getByRole("button", { name: "Inspect expression" }));
    vi.mocked(sourceExpressionList).mockResolvedValue(emptyExpressionPage()); vi.mocked(sourceExpressionCapabilities).mockResolvedValue({ ...expressionCap, actor_user_id: otherId }); mounted.rerender(view(otherId));
    await act(async () => late.resolve(revision)); await screen.findByText("No retained expressions in this bounded view."); expect(screen.queryByRole("region", { name: "Exact source expression revision" })).not.toBeInTheDocument(); expect(screen.queryByText("94.5 ± 0.3 K")).not.toBeInTheDocument();
  });
});
