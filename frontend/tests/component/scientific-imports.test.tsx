/** Local byte validation over actual synthetic SQL-to-HTTP wire; no program runs. */
import { webcrypto } from "node:crypto";

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScientificImportsPage from "@/app/dashboard/research/imports/page";
import { ApiError, scientificImportAccess, scientificImportBinding, scientificImportOutcome, scientificImportSubmit } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { IMPORT_LIMITS, importBytesHash, importCanonical, importDigest, importHash, importLogicalName,
  importMaterialId, knownImportAccess, knownImportBinding, knownImportManifest, knownImportReceipt,
  prepareImportRequest, readImportManifest } from "@/lib/scientific-imports";
import http from "../fixtures/scientific-import-recovery-http.json";
import outcomes from "../fixtures/scientific-import-outcomes-http.json";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(),
  scientificImportAccess: vi.fn(), scientificImportBinding: vi.fn(), scientificImportSubmit: vi.fn(), scientificImportOutcome: vi.fn() }));

type Obj = Record<string, unknown>;
const object = (value: unknown) => value as Obj;
const copy = <T,>(value: T): T => structuredClone(value);
const bytes = (value: string) => new TextEncoder().encode(value);
const unbase64 = (value: string) => new Uint8Array(Buffer.from(value, "base64"));
const manifest = knownImportManifest(http.request.manifest)!;
const binding = knownImportBinding(http.material_binding, http.material_binding.material_id)!;
const access = knownImportAccess(http.capabilities)!;
const pin = http.preview.result.request_sha256;
const foreign = "00000000-0000-4000-8000-111111111111";
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");

/** jsdom File has no arrayBuffer; each explicit test file supplies its own read. */
function localFile(data: Uint8Array, name = "arbitrary-local-name.bin") {
  const file = new File([data as Uint8Array<ArrayBuffer>], name);
  const read = vi.fn(async () => data.slice().buffer);
  Object.defineProperty(file, "arrayBuffer", { value: read });
  return { file, read };
}
function sourceFiles() {
  return Object.fromEntries(manifest.files.map(entry => [entry.logical_name,
    localFile(unbase64(http.request.artifact_bytes_base64[entry.sha256 as keyof typeof http.request.artifact_bytes_base64])).file]));
}
function options() {
  return { manifest: copy(manifest), manifestSha256: http.request.expected_manifest_sha256, binding: copy(binding),
    files: sourceFiles(), forceFile: localFile(unbase64(http.request.force_constants_bytes_base64)).file,
    forceName: http.request.context.force_constants.logical_name, forceSha256: http.request.context.force_constants.sha256,
    compilerSha256: access.compiler_sha256, requestKey: http.request.request_key };
}
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto); vi.resetAllMocks();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.mocked(scientificImportAccess).mockResolvedValue(copy(http.capabilities));
  vi.mocked(scientificImportBinding).mockResolvedValue(copy(http.material_binding));
  vi.mocked(scientificImportSubmit).mockImplementation(async body => copy(body.dry_run ? http.preview : http.committed));
  vi.mocked(scientificImportOutcome).mockResolvedValue(copy(http.outcome));
});
afterEach(() => {
  // Unmount/flush effects while the test's browser methods still exist. Vitest
  // can run this hook before RTL's automatic cleanup; restoring them first
  // races the receipt-focus effect and removes jsdom's scrollIntoView shim.
  cleanup();
  vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

describe("scientific import exact native wire", () => {
  it("matches the actual Python canonical manifest and complete augmented package pin", async () => {
    expect(access).not.toBeNull(); expect(binding).not.toBeNull(); expect(manifest).not.toBeNull();
    expect(await importDigest(manifest)).toBe(http.request.expected_manifest_sha256);
    const selected = localFile(bytes(importCanonical(manifest)), "anything.json");
    expect(await readImportManifest(selected.file, http.request.expected_manifest_sha256)).toEqual(manifest);
    const prepared = await prepareImportRequest(options());
    expect(prepared).toEqual({ ...http.request, dry_run: true, expected_request_sha256: pin });
    expect({ ...prepared, dry_run: false }).toEqual(http.commit_request);
    expect(selected.read).toHaveBeenCalledOnce();
    expect(knownImportReceipt(http.preview, { requestSha256: pin, mode: "preview", grantId: access.actor_grant_id })?.status).toBe("success_pending");
    expect(knownImportReceipt(http.committed, { requestSha256: pin, mode: "commit" })?.status).toBe("success_pending");
    expect(knownImportReceipt(http.outcome, { requestSha256: pin, mode: "outcome" })?.replayed).toBe(true);
    expect(knownImportReceipt(http.outcome_unknown, { requestSha256: pin, mode: "outcome" })?.status).toBe("outcome_unknown");
  });
  it("projects only bounded display metadata, not native spectrum/source text or a recomputed report hash", () => {
    const result = knownImportReceipt(http.committed, { requestSha256: pin, mode: "commit" })!;
    expect(Object.keys(result).sort()).toEqual(["actorGrantId", "attemptId", "costs", "outcomeId", "packageId", "reasons", "replayed", "reportSha256", "requestSha256", "rowIds", "status"].sort());
    expect(result.reportSha256).toBe(http.committed.result.report_sha256);
    expect(JSON.stringify(result)).not.toMatch(/raw_text|cell_angstrom|calculation_cpu_seconds|preflight/);
    result.rowIds!.property = foreign;
    expect(http.committed.result.row_ids.property).not.toBe(foreign);
  });
  it("preserves historical grants during current same-actor outcome recovery", () => {
    const old = copy(http.outcome); old.actor_grant_id = foreign;
    expect(knownImportReceipt(old, { requestSha256: pin, mode: "outcome" })).not.toBeNull();
    expect(knownImportReceipt(old, { requestSha256: pin, mode: "outcome", grantId: access.actor_grant_id })).toBeNull();
  });
  it.each(["success_pending", "quarantined", "failed", "outcome_unknown"] as const)("admits independently captured actual %s without inventing terminal IDs", status => {
    const raw = outcomes[status].outcome;
    const parsed = knownImportReceipt(raw, { mode: "outcome", requestSha256: raw.request_sha256 });
    expect(parsed?.status).toBe(status);
    expect(parsed?.rowIds === null).toBe(status !== "success_pending");
    if (status === "outcome_unknown") expect(parsed?.outcomeId).toBeNull();
    if (status === "failed") expect(parsed?.costs).toEqual({ import_wall_ms: null, import_cpu_ms: null });
  });
  it.each(["version", "actor", "grant", "compiler", "boolean", "authority", "extra"])("rejects capability %s", kind => {
    const value = object(copy(http.capabilities));
    if (kind === "version") value.version = "scientific-import-capabilities/99";
    if (kind === "actor") value.actor_user_id = "../actor";
    if (kind === "grant") value.actor_grant_id = null;
    if (kind === "compiler") value.compiler_sha256 = "A".repeat(64);
    if (kind === "boolean") value.can_import = 1;
    if (kind === "authority") object(value.authority).scientific_accepted = true;
    if (kind === "extra") value.source_text = "PRIVATE_NOT_RENDERED";
    expect(knownImportAccess(value)).toBeNull();
  });
  it.each(["material", "hash", "formula", "extra"])("rejects material binding %s", kind => {
    const value = object(copy(http.material_binding));
    if (kind === "material") value.material_id = "another-material";
    if (kind === "hash") value.material_row_sha256 = "bad";
    if (kind === "formula") value.material_formula = "\ud800";
    if (kind === "extra") value.reviewed = true;
    expect(knownImportBinding(value, binding.material_id)).toBeNull();
  });
  it.each(["version", "wrapper", "commit_flag", "pin", "actor_grant", "authority", "extra", "status", "outcome_id", "report_hash", "report_status", "report_pin", "report_authority", "report_extra", "reason", "cost_zero", "cost_boolean", "rows", "row_extra", "approval_coverage"])("rejects receipt %s", kind => {
    const value = object(copy(http.committed)), result = object(value.result), report = object(result.report);
    if (kind === "version") value.version = "scientific-import-operation/99";
    if (kind === "wrapper") value.dry_run = true;
    if (kind === "commit_flag") value.committed = false;
    if (kind === "pin") result.request_sha256 = "b".repeat(64);
    if (kind === "actor_grant") result.actor_grant_id = "not-a-uuid";
    if (kind === "authority") object(result.authority).execution_attested = true;
    if (kind === "extra") result.source_bytes = "private";
    if (kind === "status") result.status = "scientifically_accepted";
    if (kind === "outcome_id") result.outcome_id = null;
    if (kind === "report_hash") result.report_sha256 = "A".repeat(64);
    if (kind === "report_status") report.status = "quarantined";
    if (kind === "report_pin") report.request_sha256 = "c".repeat(64);
    if (kind === "report_authority") object(report.authority).ml_training_approved = true;
    if (kind === "report_extra") report.made_up = true;
    if (kind === "reason") report.reason_codes = ["approval_for_everything"];
    if (kind === "cost_zero") object(result.costs).calculation_cpu_seconds = 0;
    if (kind === "cost_boolean") object(result.costs).import_wall_ms = true;
    if (kind === "rows") result.row_ids = null;
    if (kind === "row_extra") object(result.row_ids).material = foreign;
    if (kind === "approval_coverage") object(report.coverage).ml_admitted_properties = 1;
    expect(knownImportReceipt(value, { requestSha256: pin, mode: "commit" })).toBeNull();
  });
  it.each(["outcome_id", "report_sha256", "report", "row_ids", "costs"])("unknown cannot carry terminal %s", field => {
    const value = object(copy(http.outcome_unknown)); value[field] = object(http.outcome)[field];
    expect(knownImportReceipt(value, { requestSha256: value.request_sha256 as string, mode: "outcome" })).toBeNull();
  });
  it("distinguishes valid zero worker timing from unknown calculation costs", () => {
    const value = copy(http.committed); value.result.costs.import_wall_ms = 0; value.result.costs.import_cpu_ms = 0;
    expect(knownImportReceipt(value, { requestSha256: pin, mode: "commit" })?.costs).toEqual({ import_wall_ms: 0, import_cpu_ms: 0 });
  });
  it.each(["coordinate_missing", "coordinate_mismatch", "force_missing", "force_quarantined", "preflight_quarantined", "preflight_authority", "preflight_extra", "coverage_empty", "coverage_extra", "outcome_not_replayed"])("rejects contradictory success %s", kind => {
    const value = object(copy(http.outcome)), report = object(value.report), preflight = object(report.preflight);
    if (kind === "coordinate_missing") report.coordinate_sha256 = null;
    if (kind === "coordinate_mismatch") object(report.force_constants).coordinate_sha256 = "e".repeat(64);
    if (kind === "force_missing") report.force_constants = null;
    if (kind === "force_quarantined") object(report.force_constants).status = "quarantined";
    if (kind === "preflight_quarantined") preflight.status = "quarantined";
    if (kind === "preflight_authority") object(preflight.authority).material_binding_verified = true;
    if (kind === "preflight_extra") preflight.verified_globally = true;
    if (kind === "coverage_empty") object(report.coverage).parsed_candidates = 0;
    if (kind === "coverage_extra") object(report.coverage).independent_support_count = 1;
    if (kind === "outcome_not_replayed") value.replayed = false;
    expect(knownImportReceipt(value, { requestSha256: pin, mode: "outcome" })).toBeNull();
  });
});

describe("strict local scientific package files", () => {
  it.each(["extra", "version", "adapter", "approval", "attestation", "role", "duplicate_name", "traversal", "bad_hash", "size_boolean", "size_fraction", "size_unsafe", "file_count", "geometry", "context_extra", "credentials_url", "unicode", "hash_size_conflict"])("rejects manifest %s", kind => {
    const value = object(copy(manifest)), files = value.files as Obj[], context = object(value.context);
    if (kind === "extra") value.source_text = "private";
    if (kind === "version") value.version = "scientific-program-package/99";
    if (kind === "adapter") value.adapter_id = "exec-shell";
    if (kind === "approval") object(value.declarations).ml_training_approved = true;
    if (kind === "attestation") object(value.declarations).execution_attested = true;
    if (kind === "role") files[0].role = "command";
    if (kind === "duplicate_name") files[1].logical_name = files[0].logical_name;
    if (kind === "traversal") files[0].logical_name = "../input";
    if (kind === "bad_hash") files[0].sha256 = "A".repeat(64);
    if (kind === "size_boolean") files[0].size_bytes = true;
    if (kind === "size_fraction") files[0].size_bytes = 1.2;
    if (kind === "size_unsafe") files[0].size_bytes = Number.MAX_SAFE_INTEGER + 1;
    if (kind === "file_count") value.files = Array(17).fill(files[0]);
    if (kind === "geometry") context.geometry_scope = "assume_3d";
    if (kind === "context_extra") context.pressure_gpa = 0;
    if (kind === "credentials_url") context.source_url = "https://user:secret@example.org/";
    if (kind === "unicode") context.material_formula = "\ud800";
    if (kind === "hash_size_conflict") files[1].sha256 = files[0].sha256;
    expect(knownImportManifest(value)).toBeNull();
  });
  it.each(["newline", "BOM", "indent", "duplicate_key", "invalid_utf8", "wrong_hash"])("does not repair %s manifest bytes", async kind => {
    const canonical = importCanonical(manifest);
    let raw = bytes(canonical);
    if (kind === "newline") raw = bytes(canonical + "\n");
    if (kind === "BOM") raw = bytes("\ufeff" + canonical);
    if (kind === "indent") raw = bytes(JSON.stringify(manifest, null, 2));
    if (kind === "duplicate_key") raw = bytes(canonical.replace('{"adapter_id":', '{"adapter_id":"qe-matdyn-flfrq","adapter_id":'));
    if (kind === "invalid_utf8") raw = new Uint8Array([0xc3, 0x28]);
    await expect(readImportManifest(localFile(raw).file, kind === "wrong_hash" ? "e".repeat(64) : await importBytesHash(raw))).rejects.toThrow();
  });
  it.each([0, IMPORT_LIMITS.manifest + 1])("rejects manifest metadata size %i before file read", async size => {
    const selected = localFile(bytes("{}")); Object.defineProperty(selected.file, "size", { value: size });
    await expect(readImportManifest(selected.file, "a".repeat(64))).rejects.toThrow();
    expect(selected.read).not.toHaveBeenCalled();
  });
  it("rejects an oversized total declared inventory before reading any source", async () => {
    const value = copy(manifest); value.files[0].size_bytes = IMPORT_LIMITS.file; value.files[1].size_bytes = IMPORT_LIMITS.file;
    await expect(readImportManifest(localFile(bytes(importCanonical(value))).file, await importDigest(value))).rejects.toThrow(/8 MiB/);
  });
  it("permits shared bytes across distinct logical entries without fabricating extra blobs", async () => {
    const opts = options(), first = opts.manifest.files[0];
    opts.manifest.files.push({ ...first, role: "provenance", logical_name: "same-bytes.txt" });
    opts.files["same-bytes.txt"] = opts.files[first.logical_name]; opts.manifestSha256 = await importDigest(opts.manifest);
    const value = await prepareImportRequest(opts);
    expect(Object.keys(value.artifact_bytes_base64)).toHaveLength(2);
    expect(value.manifest.files).toHaveLength(3);
  });
  it("allows an explicitly absent force-constant sidecar, without inventing bytes", async () => {
    const opts = options(); const value = await prepareImportRequest({ ...opts, forceFile: null, forceName: "", forceSha256: "" });
    expect(value.context.force_constants).toBeNull(); expect(value.force_constants_bytes_base64).toBeNull(); expect(value.expected_request_sha256).not.toBe(pin);
  });
  it.each(["missing", "extra", "size", "source_hash", "force_hash", "force_missing_name", "force_unpaired", "force_oversized", "material_pin", "manifest_pin", "compiler", "request_key"])("rejects prepared file/context %s", async kind => {
    const opts = options(), first = manifest.files[0];
    if (kind === "missing") delete opts.files[first.logical_name];
    if (kind === "extra") opts.files["not-declared.txt"] = opts.files[first.logical_name];
    if (kind === "size") opts.files[first.logical_name] = localFile(bytes("short")).file;
    if (kind === "source_hash") opts.files[first.logical_name] = localFile(new Uint8Array(first.size_bytes)).file;
    if (kind === "force_hash") opts.forceSha256 = "f".repeat(64);
    if (kind === "force_missing_name") opts.forceName = "";
    if (kind === "force_unpaired") Object.assign(opts, { forceFile: null });
    if (kind === "force_oversized") Object.defineProperty(opts.forceFile, "size", { value: IMPORT_LIMITS.force + 1 });
    if (kind === "material_pin") opts.binding.material_row_sha256 = "bad";
    if (kind === "manifest_pin") opts.manifestSha256 = "a".repeat(64);
    if (kind === "compiler") opts.compilerSha256 = "bad";
    if (kind === "request_key") opts.requestKey = "white space";
    await expect(prepareImportRequest(opts)).rejects.toThrow();
    if (["missing", "extra", "size", "force_oversized"].includes(kind)) {
      for (const file of Object.values(opts.files)) expect(file.arrayBuffer).not.toHaveBeenCalled();
    }
  });
  it("rejects a read whose returned length differs from the selected file", async () => {
    const opts = options(), file = opts.files[manifest.files[0].logical_name];
    vi.mocked(file.arrayBuffer).mockResolvedValue(new ArrayBuffer(1));
    await expect(prepareImportRequest(opts)).rejects.toThrow(/bytes changed/);
  });
  it("snapshots caller metadata and file map before asynchronous reads", async () => {
    const opts = options(), first = manifest.files[0], file = opts.files[first.logical_name], pending = deferred<ArrayBuffer>();
    vi.mocked(file.arrayBuffer).mockReturnValueOnce(pending.promise);
    const preparing = prepareImportRequest(opts);
    await waitFor(() => expect(file.arrayBuffer).toHaveBeenCalledOnce());
    opts.manifest.context.material_formula = "Nb"; opts.binding.material_id = "other-material";
    opts.compilerSha256 = "c".repeat(64); opts.forceName = "replacement.fc"; opts.requestKey = "replacement-key";
    opts.files[manifest.files[1].logical_name] = localFile(bytes("replaced source")).file;
    pending.resolve(unbase64(http.request.artifact_bytes_base64[first.sha256 as keyof typeof http.request.artifact_bytes_base64]).buffer);
    expect(await preparing).toEqual({ ...http.request, dry_run: true, expected_request_sha256: pin });
  });
  it("preserves exact binary bytes and never fetches a documentary source URL", async () => {
    const opts = options(), payload = new Uint8Array([0, 255, 128, 10, 13]);
    const sha = await importBytesHash(payload); opts.manifest.files.push({ role: "provenance", logical_name: "binary.dat", sha256: sha, size_bytes: payload.length });
    opts.files["binary.dat"] = localFile(payload).file; opts.manifest.context.source_url = "https://example.org/not-fetched";
    opts.manifestSha256 = await importDigest(opts.manifest); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const value = await prepareImportRequest(opts);
    expect(unbase64(value.artifact_bytes_base64[sha])).toEqual(payload); expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([NaN, Infinity, -Infinity, 1.5, undefined, "\ud800"])("rejects unsupported canonical scalar %s", value => {
    expect(() => importCanonical({ value })).toThrow();
  });
  it("validates safe names without normalizing identifiers or granting authority", () => {
    expect(importMaterialId(binding.material_id)).toBe(true);
    for (const value of [" x", "x ", "x\nx", "x".repeat(101), "\ud800"]) expect(importMaterialId(value)).toBe(false);
    for (const value of ["../x", "/x", "a..b", "x/y", ""]) expect(importLogicalName(value)).toBe(false);
    expect(importHash("a".repeat(64))).toBe(true); expect(importHash("A".repeat(64))).toBe(false);
  });
  it("does not depend on an ES2024 String prototype method", () => {
    const descriptor = Object.getOwnPropertyDescriptor(String.prototype, "isWellFormed");
    Object.defineProperty(String.prototype, "isWellFormed", { configurable: true, value: undefined });
    try {
      expect(importMaterialId("valid-material")).toBe(true);
      expect(importMaterialId("\ud800")).toBe(false);
      expect(importCanonical({ formula: "MgB₂" })).toBe('{"formula":"MgB₂"}');
    } finally { if (descriptor) Object.defineProperty(String.prototype, "isWellFormed", descriptor); }
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function mount() {
  render(<ScientificImportsPage />);
  await waitFor(() => expect(screen.getByLabelText("Material ID")).toBeEnabled());
}
async function inspectMaterial() {
  fireEvent.change(screen.getByLabelText("Material ID"), { target: { value: binding.material_id } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect material" }));
  await screen.findByText(/Current formula: AlAs/);
}
async function selectPackage() {
  fireEvent.change(screen.getByLabelText("Canonical manifest file"), { target: { files: [localFile(bytes(importCanonical(manifest)), "manifest.json").file] } });
  fireEvent.change(screen.getByLabelText("Independent manifest SHA-256"), { target: { value: http.request.expected_manifest_sha256 } });
  fireEvent.click(screen.getByRole("button", { name: "Load local manifest" }));
  await screen.findByLabelText("Source file: " + manifest.files[0].logical_name);
  for (const [name, file] of Object.entries(sourceFiles())) fireEvent.change(screen.getByLabelText("Source file: " + name), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText("Force-constant file (optional)"), { target: { files: [localFile(unbase64(http.request.force_constants_bytes_base64)).file] } });
  fireEvent.change(screen.getByLabelText("Force-constant logical name"), { target: { value: http.request.context.force_constants.logical_name } });
  fireEvent.change(screen.getByLabelText("Independent force-constant SHA-256"), { target: { value: http.request.context.force_constants.sha256 } });
}
async function prepare() {
  await mount(); await inspectMaterial(); await selectPackage();
  fireEvent.click(screen.getByRole("button", { name: "Preview pending import" }));
  return screen.findByRole("heading", { name: "Review before importing" });
}
async function enterUnknown() {
  await prepare();
  vi.mocked(scientificImportSubmit).mockRejectedValueOnce(new ApiError(503, { detail: "PRIVATE_SOURCE_DIAGNOSTIC" }, "Private error"));
  fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
  await screen.findByText(/Import outcome is unknown/);
  return vi.mocked(scientificImportSubmit).mock.calls[1][0];
}

describe("explicit private scientific import workflow", () => {
  it("auto-loads only capability GET and keeps source selection local until explicit preview", async () => {
    await mount();
    expect(scientificImportAccess).toHaveBeenCalledOnce();
    expect(scientificImportBinding).not.toHaveBeenCalled(); expect(scientificImportSubmit).not.toHaveBeenCalled();
    await inspectMaterial(); await selectPackage();
    expect(scientificImportSubmit).not.toHaveBeenCalled(); expect(scientificImportOutcome).not.toHaveBeenCalled();
    expect(screen.getByText(/This does not run a calculation, approve science or admit ML training data/)).toBeVisible();
  });
  it("previews actual bytes then commits the exact pin and body only after a separate click", async () => {
    const heading = await prepare(); expect(heading).toHaveFocus();
    expect(scientificImportSubmit).toHaveBeenCalledOnce();
    const body = vi.mocked(scientificImportSubmit).mock.calls[0][0];
    expect(body).toEqual({ ...http.request, request_key: body.request_key, dry_run: true, expected_request_sha256: pin });
    expect(body.request_key).toMatch(/^browser-import:/);
    expect(screen.queryByText(http.preview.result.row_ids.property)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open scientific evidence workbench" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    const receipt = await screen.findByRole("heading", { name: "Durable import receipt" }); expect(receipt).toHaveFocus();
    expect(vi.mocked(scientificImportSubmit).mock.calls[1][0]).toEqual({ ...body, dry_run: false });
    expect(screen.getByText(http.committed.result.row_ids.property)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open scientific evidence workbench" })).toHaveAttribute("href", "/dashboard/research/review");
    expect(screen.getByText(/Calculation wall time, CPU time and monetary cost: not reported, not zero/)).toBeVisible();
    expect(screen.queryByText(/raw_text|cell_angstrom/)).not.toBeInTheDocument();
  });
  it.each(["Material ID", "Independent manifest SHA-256", "Force-constant logical name", "Independent force-constant SHA-256"])("editing %s invalidates the preview", async label => {
    await prepare(); fireEvent.change(screen.getByLabelText(label), { target: { value: "changed" } });
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(scientificImportSubmit).toHaveBeenCalledOnce();
  });
  it.each(["Canonical manifest file", "Source file: synthetic.in", "Force-constant file (optional)"])("replacing %s invalidates the preview", async label => {
    await prepare(); fireEvent.change(screen.getByLabelText(label), { target: { files: [localFile(bytes("changed")).file] } });
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(scientificImportSubmit).toHaveBeenCalledOnce();
  });
  it("rejects a locally mismatched source without uploading or showing raw diagnostics", async () => {
    await mount(); await inspectMaterial(); await selectPackage();
    fireEvent.change(screen.getByLabelText("Source file: synthetic.in"), { target: { files: [localFile(new Uint8Array(manifest.files[0].size_bytes)).file] } });
    fireEvent.click(screen.getByRole("button", { name: "Preview pending import" }));
    await screen.findByText(/source file does not match its manifest SHA-256/);
    expect(scientificImportSubmit).not.toHaveBeenCalled();
  });
  it("checks compiler identity again and refuses changed-parser commit before POST", async () => {
    await prepare(); vi.mocked(scientificImportAccess).mockResolvedValue({ ...http.capabilities, compiler_sha256: "c".repeat(64) });
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByText(/server parser version changed/); expect(scientificImportSubmit).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
  });
  it("blocks double commit and keeps every input locked while the original submission is pending", async () => {
    await prepare(); const pending = deferred<unknown>(); vi.mocked(scientificImportSubmit).mockReturnValueOnce(pending.promise);
    const button = screen.getByRole("button", { name: "Commit exact preview" });
    fireEvent.click(button); fireEvent.click(button);
    await waitFor(() => expect(scientificImportSubmit).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Material ID")).toBeDisabled(); expect(screen.getByLabelText("Canonical manifest file")).toBeDisabled();
    await act(async () => pending.resolve(copy(http.committed)));
    await screen.findByRole("heading", { name: "Durable import receipt" });
  });
  it("404 recovery stays unknown and uses only the original actor/key/pin GET", async () => {
    const submitted = await enterUnknown();
    expect(screen.getByLabelText("Material ID")).toHaveValue("");
    expect(screen.queryByText(/Current formula:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Material row SHA-256:/)).not.toBeInTheDocument();
    vi.mocked(scientificImportOutcome).mockRejectedValueOnce(new ApiError(404, http.absent, "Not found"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByText(/No attempt was observed in this snapshot/);
    expect(scientificImportOutcome).toHaveBeenCalledWith({ actorId: access.actor_user_id, requestKey: submitted.request_key, requestSha256: pin }, expect.any(AbortSignal));
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2); expect(screen.getByLabelText("Material ID")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_SOURCE_DIAGNOSTIC")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Durable import receipt" });
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2); expect(scientificImportOutcome).toHaveBeenCalledTimes(2);
  });
  it("distinguishes a durable start from terminal success and permits another explicit read", async () => {
    await enterUnknown(); vi.mocked(scientificImportOutcome).mockResolvedValueOnce(copy(http.outcome_unknown));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByText(/A durable start exists, but its terminal outcome is unknown/);
    expect(screen.getByLabelText("Material ID")).toBeDisabled(); expect(screen.getByRole("button", { name: "Check original outcome" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Open scientific evidence workbench" })).not.toBeInTheDocument();
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2);
  });
  it("treats a mismatched commit acknowledgement as unknown, not saved success", async () => {
    await prepare(); const value = copy(http.committed); value.result.request_sha256 = "f".repeat(64);
    vi.mocked(scientificImportSubmit).mockResolvedValueOnce(value);
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByText(/Import outcome is unknown/);
    expect(screen.queryByText(http.committed.result.row_ids.property)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check original outcome" })).toBeEnabled();
  });
  it("clears all local files and pins on refreshed denial without revealing backend details", async () => {
    await prepare(); vi.mocked(scientificImportAccess).mockRejectedValueOnce(new ApiError(403, { detail: "PRIVATE_SOURCE_DIAGNOSTIC" }, "Private error"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    await screen.findByText(/Curator access or session changed/);
    expect(screen.getByLabelText("Material ID")).toHaveValue(""); expect(screen.getByLabelText("Independent manifest SHA-256")).toHaveValue("");
    expect(screen.queryByLabelText("Source file: synthetic.in")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_SOURCE_DIAGNOSTIC")).not.toBeInTheDocument();
  });
  it("ignores a late material response after the authentication generation changes", async () => {
    await mount(); const pending = deferred<unknown>(); vi.mocked(scientificImportBinding).mockReturnValueOnce(pending.promise);
    fireEvent.change(screen.getByLabelText("Material ID"), { target: { value: binding.material_id } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect material" }));
    await waitFor(() => expect(scientificImportBinding).toHaveBeenCalledOnce());
    act(() => notifyAuthChange()); await act(async () => pending.resolve(copy(http.material_binding)));
    expect(screen.queryByText(/Current formula: AlAs/)).not.toBeInTheDocument(); expect(screen.getByLabelText("Material ID")).toHaveValue("");
    expect(vi.mocked(scientificImportBinding).mock.calls[0][1]?.aborted).toBe(true);
  });
  it("ignores late local file decoding after logout and performs no upload", async () => {
    await mount(); const selected = localFile(bytes(importCanonical(manifest))), pending = deferred<ArrayBuffer>();
    selected.read.mockReturnValueOnce(pending.promise);
    fireEvent.change(screen.getByLabelText("Canonical manifest file"), { target: { files: [selected.file] } });
    fireEvent.change(screen.getByLabelText("Independent manifest SHA-256"), { target: { value: http.request.expected_manifest_sha256 } });
    fireEvent.click(screen.getByRole("button", { name: "Load local manifest" }));
    await waitFor(() => expect(selected.read).toHaveBeenCalledOnce()); act(() => notifyAuthChange());
    await act(async () => pending.resolve(bytes(importCanonical(manifest)).buffer));
    expect(screen.queryByLabelText("Source file: synthetic.in")).not.toBeInTheDocument(); expect(scientificImportSubmit).not.toHaveBeenCalled();
  });
  it("discards a late preview response after logout", async () => {
    await mount(); await inspectMaterial(); await selectPackage(); const pending = deferred<unknown>(); vi.mocked(scientificImportSubmit).mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole("button", { name: "Preview pending import" }));
    await waitFor(() => expect(scientificImportSubmit).toHaveBeenCalledOnce()); act(() => notifyAuthChange());
    await act(async () => pending.resolve(copy(http.preview)));
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Independent manifest SHA-256")).toHaveValue("");
  });
  it("preserves only original recovery references after submission logout and rejects a different account", async () => {
    await prepare(); const pending = deferred<unknown>(); vi.mocked(scientificImportSubmit).mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" })); await waitFor(() => expect(scientificImportSubmit).toHaveBeenCalledTimes(2));
    act(() => notifyAuthChange()); await act(async () => pending.resolve(copy(http.committed)));
    expect(screen.queryByText(http.committed.result.row_ids.property)).not.toBeInTheDocument();
    expect(screen.queryByText(access.actor_user_id)).not.toBeInTheDocument(); expect(screen.queryByText(pin)).not.toBeInTheDocument();
    vi.mocked(scientificImportAccess).mockResolvedValue({ ...http.capabilities, actor_user_id: foreign });
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" })); await screen.findByText(/belongs to another account/);
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument(); expect(screen.getByLabelText("Material ID")).toBeDisabled();
    vi.mocked(scientificImportAccess).mockResolvedValue(copy(http.capabilities));
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    await screen.findByRole("button", { name: "Check original outcome" });
    expect(screen.queryByLabelText("Source file: synthetic.in")).not.toBeInTheDocument();
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2);
  });
  it("warns before leaving unresolved memory-only recovery without storing private data", async () => {
    const local = vi.spyOn(window.localStorage, "setItem"), session = vi.spyOn(Storage.prototype, "setItem");
    await enterUnknown(); const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true); expect(local).not.toHaveBeenCalled(); expect(session).not.toHaveBeenCalled();
  });
  it("recovers an old grant receipt after a new current grant for the same original account", async () => {
    await enterUnknown(); act(() => notifyAuthChange());
    vi.mocked(scientificImportAccess).mockResolvedValue({ ...http.capabilities, actor_grant_id: foreign });
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    fireEvent.click(await screen.findByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Durable import receipt" });
    expect(screen.getByText(http.committed.result.row_ids.property)).toBeVisible();
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2);
  });
  it("fetch abort after the 55-second deadline retains same-key unknown recovery", async () => {
    await prepare(); vi.useFakeTimers();
    vi.mocked(scientificImportSubmit).mockImplementationOnce((_body, signal) => new Promise((_resolve, reject) => {
      signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await act(async () => { await Promise.resolve(); await vi.advanceTimersByTimeAsync(55_001); });
    expect(screen.getByText(/Import outcome is unknown/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Check original outcome" })).toBeEnabled();
    expect(scientificImportSubmit).toHaveBeenCalledTimes(2);
  });
});
