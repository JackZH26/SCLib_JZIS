import { webcrypto } from "node:crypto";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DistributionRightsWorkbench } from "@/components/DistributionRightsWorkbench";
import { ApiError, distributionRightsAccess, distributionRightsContext, distributionRightsOutcome,
  distributionRightsPage, distributionRightsPrepare } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { knownRightsAccess, knownRightsContext, knownRightsPage, knownRightsResult, rightsDigest,
  type RightsInput, type RightsRecovery } from "@/lib/distribution-rights";
import http from "../fixtures/distribution-rights-http.json";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(),
  distributionRightsAccess: vi.fn(), distributionRightsPage: vi.fn(), distributionRightsContext: vi.fn(),
  distributionRightsPrepare: vi.fn(), distributionRightsOutcome: vi.fn() }));

type Obj = Record<string, any>;
const copy = <T,>(value: T): T => structuredClone(value);
const foreign = "00000000-0000-4000-8000-999999999999";
const otherHash = "f".repeat(64);
const access = knownRightsAccess(http.capabilities)!;
const packageId = http.selected.package_id;
const dependencyId = http.selected.dependency.dependency_id;
const page = knownRightsPage(http.listing, access, packageId)!;
const selected = page.dependencies.find(row => row.dependency_id === dependencyId)!;
const originalInput = http.request as RightsInput;
const recovery: RightsRecovery = { actorId: access.actor_user_id, packageId, dependencyId,
  requestKey: originalInput.request_key, intentSha256: http.preview.result.intent_sha256 };
const binding = (committed: boolean) => ({ ...recovery, committed, request: originalInput,
  grantId: access.actor_grant_id, publicBundleSha256: http.selected.public_bundle_sha256 });

/** Preserve the actual SQL/HTTP synthetic scientific metadata. Only a browser
 * request key and its canonical intent digest are remapped by this transport.
 */
async function transport(input: RightsInput, committed: boolean) {
  const value = copy(committed ? http.committed : http.preview);
  value.result.intent.request_key = input.request_key;
  value.result.intent_sha256 = await rightsDigest(value.result.intent);
  return value;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { resolve, promise };
}
async function mount() {
  render(<DistributionRightsWorkbench />);
  await waitFor(() => expect(screen.getByLabelText("Package UUID")).toBeEnabled());
}
async function inspect() {
  fireEvent.change(screen.getByLabelText("Package UUID"), { target: { value: packageId } });
  fireEvent.click(screen.getByRole("button", { name: "Load dependencies", exact: true }));
  fireEvent.click((await screen.findAllByRole("button", { name: "Inspect dependency", exact: true }))[0]);
  return screen.findByRole("heading", { name: "Exact dependency" });
}
function setDecision() {
  fireEvent.change(screen.getByLabelText("Decision", { exact: true }), { target: { value: "allow" } });
  fireEvent.change(screen.getByLabelText("License or permission basis"), { target: { value: originalInput.license_code } });
  fireEvent.change(screen.getByLabelText("Basis code"), { target: { value: originalInput.basis_code } });
  fireEvent.change(screen.getByLabelText("Reason code"), { target: { value: originalInput.reason_code } });
}
async function prepare() {
  await inspect(); setDecision();
  fireEvent.click(screen.getByRole("button", { name: "Preview rights decision" }));
  return screen.findByRole("heading", { name: "Review before committing" });
}
function commitCalls() { return vi.mocked(distributionRightsPrepare).mock.calls.filter(([, , body]) => body.dry_run === false); }
async function unknown() {
  vi.mocked(distributionRightsPrepare).mockImplementation(async (_package, _dependency, body) => {
    if (body.dry_run === false) throw new ApiError(503, null, "PRIVATE_FAILURE_MUST_NOT_RENDER");
    return transport(body, false);
  });
  await mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
  return screen.findByText(/Commit outcome is unknown/);
}

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto); vi.resetAllMocks();
  vi.mocked(distributionRightsAccess).mockResolvedValue(copy(http.capabilities));
  vi.mocked(distributionRightsPage).mockResolvedValue(copy(http.listing));
  vi.mocked(distributionRightsContext).mockResolvedValue(copy(http.selected));
  vi.mocked(distributionRightsPrepare).mockImplementation(async (_package, _dependency, body) => transport(body, body.dry_run === false));
  vi.mocked(distributionRightsOutcome).mockImplementation(async ref => {
    const result = await transport({ ...originalInput, request_key: ref.requestKey }, true);
    result.result.replayed = true; return result;
  });
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("closed RPS rights wire from actual disposable SQL and HTTP", () => {
  it("matches the actual capability, page, context, preview, commit and historical outcome", async () => {
    expect(access).not.toBeNull(); expect(page).not.toBeNull(); expect(selected).toBeDefined();
    expect(knownRightsContext(http.selected, access, page, selected)).not.toBeNull();
    expect(await rightsDigest(http.preview.result.intent)).toBe(http.preview.result.intent_sha256);
    expect(await rightsDigest(http.preview.result.rights_document)).toBe(http.preview.result.rights_bytes_sha256);
    expect(await knownRightsResult(http.preview, binding(false))).not.toBeNull();
    expect(await knownRightsResult(http.committed, binding(true))).not.toBeNull();
    expect(await knownRightsResult(http.outcome, { ...recovery, committed: true })).not.toBeNull();
  });
  it.each(["version", "scope", "actor", "grant", "can_read", "can_prepare", "extra",
    "scientific_acceptance", "ml_training_approved", "current_authorization_checked"])("rejects access %s", field => {
    const value = copy(http.capabilities) as Obj;
    if (field === "actor") value.actor_user_id = "not-a-uuid";
    else if (field === "grant") value.actor_grant_id = null;
    else if (field === "extra") value.raw_source = "PRIVATE_MUST_NOT_RENDER";
    else if (field === "version" || field === "scope") value[field] = "unsupported";
    else value[field] = field.startsWith("can_") ? 1 : true;
    expect(knownRightsAccess(value)).toBeNull();
  });
  it.each(["actor", "grant", "package", "inventory", "boolean_count", "too_many", "duplicate", "order",
    "cursor", "cursor_short", "row_extra", "row_control", "row_hash", "extra", "approval"])("rejects page %s", failure => {
    const value = copy(http.listing) as Obj;
    if (failure === "actor") value.actor_user_id = foreign;
    if (failure === "grant") value.actor_grant_id = foreign;
    if (failure === "package") value.package_id = foreign;
    if (failure === "inventory") value.inventory_sha256 = otherHash;
    if (failure === "boolean_count") value.dependency_count = true;
    if (failure === "too_many") value.dependency_count = 20001;
    if (failure === "duplicate") value.dependencies[1] = copy(value.dependencies[0]);
    if (failure === "order") value.dependencies.reverse();
    if (failure === "cursor") value.next_after = otherHash;
    if (failure === "cursor_short") { value.dependencies = value.dependencies.slice(0, 1); value.next_after = value.dependencies[0].dependency_id; }
    if (failure === "row_extra") value.dependencies[0].projection = { private: true };
    if (failure === "row_control") value.dependencies[0].row_id = "private\ntext";
    if (failure === "row_hash") value.dependencies[0].row_sha256 = "A".repeat(64);
    if (failure === "extra") value.full_inventory = [];
    if (failure === "approval") value.ml_training_approved = true;
    expect(knownRightsPage(value, access, packageId, null, page.inventory_sha256)).toBeNull();
  });
  it("binds the cursor and page inventory and returns detached metadata", () => {
    expect(knownRightsPage(http.listing, access, packageId, dependencyId, page.inventory_sha256)).toBeNull();
    const raw = copy(http.listing), parsed = knownRightsPage(raw, access, packageId)!;
    parsed.dependencies[0].row_id = "edited";
    expect(raw.dependencies[0].row_id).not.toBe("edited");
  });
  it.each(["actor", "grant", "package", "inventory", "package_hash", "selected", "extra",
    "source_hash", "head_hash", "head_decision", "approval"])("rejects exact detail %s", failure => {
    const value = copy(http.selected) as Obj;
    if (failure === "actor") value.actor_user_id = foreign;
    if (failure === "grant") value.actor_grant_id = foreign;
    if (failure === "package") value.package_id = foreign;
    if (failure === "inventory") value.inventory_sha256 = otherHash;
    if (failure === "package_hash") value.package_record_sha256 = otherHash;
    if (failure === "selected") value.dependency.row_id = foreign;
    if (failure === "extra") value.source_text = "PRIVATE_MUST_NOT_RENDER";
    if (failure === "source_hash") value.dependency.bytes_sha256 = "bad";
    if (failure.startsWith("head_")) value.head = { id: foreign, record_sha256: failure === "head_hash" ? "bad" : otherHash,
      decision: failure === "head_decision" ? "accept" : "allow", license_code: "CC0-1.0", basis_code: "recorded", reason_code: "recorded" };
    if (failure === "approval") value.scientific_acceptance = true;
    expect(knownRightsContext(value, access, page, selected)).toBeNull();
  });
  it.each(["outer_extra", "outer_commit", "inner_commit", "inner_extra", "actor", "grant", "request_key",
    "package", "dependency", "head_pair", "intent_hash", "document_hash", "document_extra", "document_scope",
    "document_approval", "intent_approval", "result_approval", "document_binding", "artifact_hash", "missing_receipt"])("rejects receipt %s", async failure => {
    const value = copy(http.committed) as Obj, r = value.result, i = r.intent, d = r.rights_document;
    if (failure === "outer_extra") value.raw = {};
    if (failure === "outer_commit") value.committed = false;
    if (failure === "inner_commit") r.committed = true;
    if (failure === "inner_extra") r.artifact_bytes = "private";
    if (failure === "actor") i.actor_user_id = foreign;
    if (failure === "grant") i.actor_grant_id = foreign;
    if (failure === "request_key") i.request_key = "different";
    if (failure === "package") i.package_id = foreign;
    if (failure === "dependency") i.dependency_id = otherHash;
    if (failure === "head_pair") i.expected_head_id = foreign;
    if (failure === "intent_hash") r.intent_sha256 = otherHash;
    if (failure === "document_hash") r.rights_bytes_sha256 = otherHash;
    if (failure === "document_extra") d.source_text = "private";
    if (failure === "document_scope") d.scope = "ml_training";
    if (failure === "document_approval") d.scientific_acceptance = true;
    if (failure === "intent_approval") i.ml_training_approved = true;
    if (failure === "result_approval") r.current_authorization_checked = true;
    if (failure === "document_binding") d.inventory_sha256 = otherHash;
    if (failure === "artifact_hash") r.artifact.bytes_sha256 = otherHash;
    if (failure === "missing_receipt") r.permission = null;
    expect(await knownRightsResult(value, binding(true))).toBeNull();
  });
  it("rejects a fully rehashed replacement of the independently selected public bundle", async () => {
    const value = copy(http.preview);
    value.result.intent.public_bundle_sha256 = otherHash; value.result.rights_document.public_bundle_sha256 = otherHash;
    value.result.rights_bytes_sha256 = await rightsDigest(value.result.rights_document);
    value.result.intent.rights_bytes_sha256 = value.result.rights_bytes_sha256;
    value.result.intent_sha256 = await rightsDigest(value.result.intent);
    expect(await knownRightsResult(value, { ...binding(false), intentSha256: "" })).toBeNull();
  });
  it("uses the historical grant only for exact actor/key/hash recovery", async () => {
    const value = copy(http.outcome); value.result.intent.actor_grant_id = foreign;
    value.result.intent_sha256 = await rightsDigest(value.result.intent);
    const ref = { ...recovery, intentSha256: value.result.intent_sha256, committed: true };
    expect(await knownRightsResult(value, ref)).not.toBeNull();
    expect(await knownRightsResult(value, { ...ref, grantId: access.actor_grant_id })).toBeNull();
    expect(await knownRightsResult(value, { ...ref, actorId: foreign })).toBeNull();
  });
  it("preserves inherited allow-document basis on an explicit protective revoke", async () => {
    const value = copy(http.preview) as Obj, i = value.result.intent;
    i.decision = "revoke"; i.basis_code = "rights_withdrawn";
    i.expected_head_id = http.committed.result.permission.id;
    i.expected_head_sha256 = http.committed.result.permission.record_sha256;
    value.result.intent_sha256 = await rightsDigest(i);
    const request: RightsInput = { ...originalInput, decision: "revoke", basis_code: i.basis_code,
      expected_head_id: i.expected_head_id, expected_head_sha256: i.expected_head_sha256 };
    expect(await knownRightsResult(value, { ...binding(false), request, intentSha256: value.result.intent_sha256 })).not.toBeNull();
    expect(value.result.rights_document.distribution_permitted).toBe(true);
    expect(value.result.rights_document.basis_code).toBe(originalInput.basis_code);
  });
});

describe("private rights preparation workbench", () => {
  it("loads capabilities only, never preselects favorable intent, and keeps English scope limits", async () => {
    const delayed = deferred<unknown>(); vi.mocked(distributionRightsAccess).mockReturnValueOnce(delayed.promise);
    render(<DistributionRightsWorkbench />);
    expect(distributionRightsPage).not.toHaveBeenCalled(); expect(distributionRightsPrepare).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Package UUID")).toBeDisabled();
    await act(async () => delayed.resolve(http.capabilities)); await inspect();
    expect(screen.getByLabelText("Decision", { exact: true })).toHaveValue("");
    expect(screen.getByLabelText("License or permission basis")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Preview rights decision" })).toBeDisabled();
    expect(screen.getByText(/A rights statement is not legal verification/)).toHaveTextContent(/scientific acceptance or ML training approval/);
    expect(screen.getByText(/Do not paste source text, credentials/)).toBeVisible();
    expect(distributionRightsPrepare).not.toHaveBeenCalled();
  });
  it("requires explicit preview then exact commit and stores no private browser data", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    await mount(); await prepare(); expect(commitCalls()).toHaveLength(0);
    const request = vi.mocked(distributionRightsPrepare).mock.calls[0][2];
    expect(request).toEqual({ ...originalInput, request_key: request.request_key, dry_run: true });
    expect(distributionRightsContext).toHaveBeenCalledWith(packageId, dependencyId, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(commitCalls()).toHaveLength(1);
    expect(commitCalls()[0][2]).toEqual({ ...request, dry_run: false,
      expected_intent_sha256: (await transport(request, false)).result.intent_sha256 });
    expect(screen.getByText(/live artifact can later change/)).toBeVisible();
    expect(screen.getByText(/does not establish current publication eligibility/)).toBeVisible();
    expect(local).not.toHaveBeenCalled(); local.mockRestore();
  });
  it("moves keyboard focus to the loaded exact decision without granting or sending a write", async () => {
    await mount(); const heading = await inspect();
    // The heading's DOM insertion can precede the passive focus effect. Wait
    // for the actual accessibility outcome, not only for the heading to exist.
    await waitFor(() => expect(heading).toHaveFocus());
    expect(distributionRightsPrepare).not.toHaveBeenCalled();
  });
  it.each(["Decision", "License or permission basis", "Basis code", "Reason code", "Package UUID"])("invalidates the exact preview on %s edit", async label => {
    await mount(); await prepare();
    const value = label === "Decision" ? "" : label === "License or permission basis" ? "CC0-1.0" : label === "Package UUID" ? foreign : "changed_code";
    fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(commitCalls()).toHaveLength(0);
  });
  it("keeps the same unknown key across GET 404 and recovers without another POST", async () => {
    await unknown(); const original = commitCalls()[0][2];
    expect(screen.getByText(original.request_key)).toBeVisible();
    expect(screen.getByLabelText("Package UUID")).toBeDisabled();
    expect(screen.queryByText("PRIVATE_FAILURE_MUST_NOT_RENDER")).not.toBeInTheDocument();
    vi.mocked(distributionRightsOutcome).mockRejectedValueOnce(new ApiError(404, null, "private not found"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByText(/original commit may still be in flight; no rollback is inferred/);
    expect(commitCalls()).toHaveLength(1); expect(screen.getByText(original.request_key)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(distributionRightsOutcome).toHaveBeenLastCalledWith({ actorId: access.actor_user_id, packageId, dependencyId,
      requestKey: original.request_key, intentSha256: original.expected_intent_sha256 }, expect.any(AbortSignal));
    expect(commitCalls()).toHaveLength(1); expect(screen.getByText(/Recovered existing record/)).toBeVisible();
  });
  it("only explicit retry resends the byte-identical original key and pin, with double-click protection", async () => {
    await unknown(); const original = copy(commitCalls()[0][2]), delayed = deferred<unknown>();
    vi.mocked(distributionRightsPrepare).mockReturnValueOnce(delayed.promise);
    const retry = screen.getByRole("button", { name: "Retry exact original commit" });
    expect(screen.getByText(/explicit retry may perform the original write/)).toBeVisible();
    fireEvent.click(retry); fireEvent.click(retry);
    expect(commitCalls()).toHaveLength(2); expect(commitCalls()[1][2]).toEqual(original);
    expect(JSON.stringify(commitCalls()[1][2])).toBe(JSON.stringify(original));
    await act(async () => delayed.resolve(await transport(original, true)));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(distributionRightsOutcome).not.toHaveBeenCalled();
  });
  it("blocks double initial commit while the actual response is pending", async () => {
    await mount(); await prepare(); const delayed = deferred<unknown>();
    vi.mocked(distributionRightsPrepare).mockReturnValueOnce(delayed.promise);
    const button = screen.getByRole("button", { name: "Commit exact preview" });
    fireEvent.click(button); fireEvent.click(button); expect(commitCalls()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Refresh reviewer access" })).toBeDisabled();
    await act(async () => delayed.resolve(await transport(commitCalls()[0][2], true)));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
  });
  it("treats a malformed successful commit response as unknown, not a second permission", async () => {
    await mount(); await prepare();
    vi.mocked(distributionRightsPrepare).mockImplementationOnce(async (_p, _d, request) => {
      const value = await transport(request, true); value.result.ml_training_approved = true; return value;
    });
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByText(/Commit outcome is unknown/);
    expect(screen.queryByRole("heading", { name: "Committed historical receipt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(commitCalls()).toHaveLength(1);
  });
  it("clears private evidence and ignores a late selected dependency after auth changes", async () => {
    const delayed = deferred<unknown>(); vi.mocked(distributionRightsContext).mockReturnValueOnce(delayed.promise);
    await mount(); fireEvent.change(screen.getByLabelText("Package UUID"), { target: { value: packageId } });
    fireEvent.click(screen.getByRole("button", { name: "Load dependencies" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Inspect dependency" }))[0]);
    await waitFor(() => expect(distributionRightsContext).toHaveBeenCalled());
    act(() => notifyAuthChange());
    expect(vi.mocked(distributionRightsContext).mock.calls[0][2]?.aborted).toBe(true);
    await act(async () => delayed.resolve(http.selected));
    expect(screen.queryByRole("heading", { name: "Exact dependency" })).not.toBeInTheDocument();
    expect(screen.queryByText(http.selected.inventory_sha256)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Package UUID")).toHaveValue("");
    expect(distributionRightsPrepare).not.toHaveBeenCalled();
  });
  it.each([401, 403, 503])("clears evidence after refresh HTTP %s without exposing server text", async status => {
    await mount(); await prepare();
    vi.mocked(distributionRightsAccess).mockRejectedValueOnce(new ApiError(status, null, "PRIVATE_REVIEW_DETAIL"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh reviewer access" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("heading", { name: "Exact dependency" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_REVIEW_DETAIL")).not.toBeInTheDocument();
  });
  it("retains only opaque recovery across auth changes and never exposes it to another actor", async () => {
    await unknown(); const original = commitCalls()[0][2];
    act(() => notifyAuthChange());
    expect(screen.queryByText(original.request_key)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry exact original commit" })).not.toBeInTheDocument();
    vi.mocked(distributionRightsAccess).mockResolvedValue({ ...http.capabilities, actor_user_id: foreign });
    fireEvent.click(screen.getByRole("button", { name: "Refresh reviewer access" }));
    await screen.findByText(/unresolved operation belongs to another account/);
    expect(screen.queryByText(original.request_key)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
    act(() => notifyAuthChange()); vi.mocked(distributionRightsAccess).mockResolvedValue(copy(http.capabilities));
    fireEvent.click(screen.getByRole("button", { name: "Refresh reviewer access" }));
    await screen.findByRole("button", { name: "Check original outcome" });
    expect(screen.getByText(original.request_key)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Retry exact original commit" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(commitCalls()).toHaveLength(1);
  });
  it("aborts pending work on unmount and never renders the late response", async () => {
    const delayed = deferred<unknown>(); vi.mocked(distributionRightsAccess).mockReturnValueOnce(delayed.promise);
    const mounted = render(<DistributionRightsWorkbench />); mounted.unmount();
    expect(vi.mocked(distributionRightsAccess).mock.calls[0][0]?.aborted).toBe(true);
    await act(async () => delayed.resolve(http.capabilities));
    expect(distributionRightsPage).not.toHaveBeenCalled(); expect(distributionRightsPrepare).not.toHaveBeenCalled();
  });
  it("turns the commit deadline into unknown and keeps the original locator after a GET deadline", async () => {
    await mount(); await prepare(); vi.useFakeTimers();
    vi.mocked(distributionRightsPrepare).mockImplementationOnce((_package, _dependency, _body, signal) => new Promise((_resolve, reject) => {
      signal!.addEventListener("abort", () => reject(new ApiError(0, null, "PRIVATE_TIMEOUT")), { once: true });
    }));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    const original = commitCalls()[0][2];
    await act(async () => { await vi.advanceTimersByTimeAsync(30_001); });
    expect(screen.getByText(/Commit outcome is unknown/)).toBeVisible();
    expect(screen.getByText(original.request_key)).toBeVisible();
    vi.mocked(distributionRightsOutcome).mockImplementationOnce((_ref, signal) => new Promise((_resolve, reject) => {
      signal!.addEventListener("abort", () => reject(new ApiError(0, null, "PRIVATE_TIMEOUT")), { once: true });
    }));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_001); });
    expect(screen.getByText(/Outcome remains unknown/)).toBeVisible();
    expect(screen.getByText(original.request_key)).toBeVisible();
    expect(screen.queryByText("PRIVATE_TIMEOUT")).not.toBeInTheDocument(); expect(commitCalls()).toHaveLength(1);
  });
  it("discards a late commit receipt after auth change while preserving original-account GET recovery", async () => {
    await mount(); await prepare(); const delayed = deferred<unknown>();
    vi.mocked(distributionRightsPrepare).mockReturnValueOnce(delayed.promise);
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    const original = commitCalls()[0][2]; act(() => notifyAuthChange());
    expect(commitCalls()[0][3]?.aborted).toBe(true);
    await act(async () => delayed.resolve(await transport(original, true)));
    expect(screen.queryByRole("heading", { name: "Committed historical receipt" })).not.toBeInTheDocument();
    expect(screen.queryByText(original.request_key)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh reviewer access" }));
    await screen.findByRole("button", { name: "Check original outcome" });
    expect(screen.queryByRole("button", { name: "Retry exact original commit" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" }); expect(commitCalls()).toHaveLength(1);
  });
});
