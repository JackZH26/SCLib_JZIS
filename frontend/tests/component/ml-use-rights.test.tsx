import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlRightsWorkbench } from "@/components/MlRightsWorkbench";
import { ApiError } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { importCanonical, importDigest } from "@/lib/scientific-imports";
import * as rights from "@/lib/ml-use-rights";
import http from "../fixtures/ml-use-rights-native.delivery20260921r9.wire.json";

vi.mock("@/lib/ml-use-rights", async original => ({ ...await original<typeof import("@/lib/ml-use-rights")>(),
  getMlRightsAccess: vi.fn(), inspectMlRights: vi.fn(), previewMlRights: vi.fn(), commitMlRights: vi.fn(), recoverMlRights: vi.fn() }));
const actor = rights.parseMlRightsAccess(http.access), query = http.query;
const foreign = "00000000-0000-4000-8000-999999999999", otherHash = "f".repeat(64);
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
const reference = (kind: "allow" | "revoke" | "deny"): rights.MlRightsRecovery => ({ actorId: actor.actor_user_id,
  requestKey: http[kind + "_input" as "allow_input"].request_key, intentSha256: JSON.parse(http[kind + "_preview" as "allow_preview"]).result.intent_sha256 });
const changed = (raw: string, modify: (v: any) => void) => { const v = JSON.parse(raw); modify(v); return JSON.stringify(v); };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }

// Browser-only resealed transport fixtures: the UI chooses its own random key.
// These are not fresh SQL responses or additional permission evidence.
async function transport(input: rights.MlRightsInput, committed: boolean, replayed = false) {
  const kind = input.decision, v = JSON.parse(http[(kind + (committed ? "_committed" : "_preview")) as "allow_preview"]);
  v.result.intent = rights.mlRightsIntent(input, actor.actor_user_id); v.result.intent_sha256 = await importDigest(v.result.intent); v.result.replayed = replayed;
  if (committed) {
    const d = v.result.decision; Object.assign(d, input, { actor_user_id: actor.actor_user_id, intent_sha256: v.result.intent_sha256 });
    const { created_at: _created, record_sha256: _hash, ...body } = d; d.record_sha256 = await importDigest(body);
  }
  return importCanonical(v);
}
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(JSON.parse(http.allow_committed).result.decision.created_at));
  vi.mocked(rights.getMlRightsAccess).mockResolvedValue(http.access);
  vi.mocked(rights.inspectMlRights).mockImplementation(async q => q.after ? http.next_page : http.unreviewed);
  vi.mocked(rights.previewMlRights).mockImplementation(input => transport(input, false));
  vi.mocked(rights.commitMlRights).mockImplementation(input => transport(input, true));
  vi.mocked(rights.recoverMlRights).mockResolvedValue(http.allow_outcome);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll); else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });

describe("actual native ML rights protocol", () => {
  it("pins the exact native archive and all 598 backend/harness/schema source files", () => {
    const hash = (b: Buffer) => createHash("sha256").update(b).digest("hex");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.delivery20260921r9.wire.json")))).toBe("f084cb5b026d9b507a98746b272cfa19829dbc88973a9cb10c0334d49ccb8c2a");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch75.wire.json")))).toBe("325260f84981f4f663e249da71e542ade0f7c2cd52115e9bcd38138247c67689");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch72.wire.json")))).toBe("776c9bdf006b09f1ab9fd1818b891be26741f21d7b0081357ec347069ab2c86b");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch73.wire.json")))).toBe("f8e7ac8010645f46c926a7e3459954566e419e4dc8fa9446ffca9c7694345a96");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch74.wire.json")))).toBe("d87f6e34db0c2f09f7b810cf55ce62a9a3e9c8368b69250178ad4e63bedda751");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch71.wire.json")))).toBe("d1f0d859d01baafaf32ccfe888d23331002da5e708c072aa21cc4b7123a4e0fc");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch70.wire.json")))).toBe("d9774a7e9e11c2f3e568f3361dccbe14d1a91393b4e1c5bd385276e4889aa40b");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch69.wire.json")))).toBe("efefe4aef7b5112d21359128f17e662198a5e8531ca90a20a0bad007014d3222");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch68.wire.json")))).toBe("14885ab44024bc09ee55d2cf53c37c5a76e4cf8dfbf22d6d1acf6faf22bd5809");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch67-final.wire.json")))).toBe("d4d6c5d119b35eab2a1d05a474b00dc1fb77403d041ad4fe0fb34b473c45c4de");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch67.wire.json")))).toBe("4372be2a47ff30fab7990a58ac3d2db193d722602d6c18886b0d56b38d0f3059");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch66.wire.json")))).toBe("9ae1256d36e916f065b6cbb2737bdd829e1eb2d43183b912b3262ba66bb81193");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch65.wire.json")))).toBe("c6431f457ed7de687a48fe9bef413452e57d243310ffdf75dfeef06daae697aa");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.wire.json")))).toBe("35ac35963bf7108560492d3a9b91af69cb62e0ce70748e8be1151be4eac668fb");
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/ml-use-rights-native.batch60.wire.json")))).toBe("79ad4248be9d5b75d9655a62064b5a4a8a9ab599e3887225cf6e745924e19f21");
    expect(http.source_pins).toHaveLength(598); expect(new Set(http.source_pins.map(p => p.path)).size).toBe(598);
    expect(http.source_pins.some(p => p.path === "api/tests/test_ml_pilot_participant_wire.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "api/services/ml08_pilot.schema.json")).toBe(true);
    expect(http.source_pins.some(p => p.path === "scripts/migration_pilot_registration.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "scripts/probe_ml_pilot_registration_install.py")).toBe(true);
    expect(http.source_pins.some(p => p.path === "api/tests/test_ml_pilot_registration_reliability.py")).toBe(true);
    for (const p of http.source_pins) { expect(p.path).toMatch(/^(?:(api|scripts)\/[A-Za-z0-9_./-]+\.py|api\/services\/[A-Za-z0-9_-]+\.schema\.json)$/); expect(p.path.split("/")).not.toContain("..");
      expect(hash(readFileSync(resolve(process.cwd(), "..", p.path))), p.path).toBe(p.sha256); }
  });
  it("verifies actual access, two pages, three decisions, record hashes and historical outcomes", async () => {
    const first = await rights.parseMlRightsPage(http.unreviewed, actor, query);
    const next = await rights.parseMlRightsPage(http.next_page, actor, { ...query, after: first.next_after }, first);
    expect(first.resource_count).toBe(285); expect(next.resources.length).toBe(25);
    expect(first.resources.some(r => r.kind === "row")).toBe(true); expect(first.resources.some(r => r.kind === "artifact")).toBe(true);
    for (const kind of ["allow", "revoke", "deny"] as const) {
      const input = http[(kind + "_input") as "allow_input"] as rights.MlRightsInput;
      const preview = await rights.parseMlRightsResult(http[(kind + "_preview") as "allow_preview"], reference(kind), false, input);
      const saved = await rights.parseMlRightsResult(http[(kind + "_committed") as "allow_committed"], reference(kind), true, input);
      const recovered = await rights.parseMlRightsResult(http[(kind + "_outcome") as "allow_outcome"], reference(kind), true);
      const page = await rights.parseMlRightsPage(http[(kind + "_page") as "allow_page"], actor, query);
      expect(preview.decision).toBeNull(); expect(saved.decision).toEqual(recovered.decision); expect(page.resources[0].head).toEqual(saved.decision);
      expect(saved.intent.decision).toBe(kind); expect(recovered.replayed).toBe(true);
    }
  });
  it.each(["version", "actor_user_id", "reviewer_grant_id", "curator_grant_id", "can_review_rights", "extra", "scientific_acceptance", "public_release", "ml_training_approved",
    "reviewer_authority_authenticated", "live_source_rights_checked", "external_dependency_completeness_proven", "source_permission_granted", "run_authorization_granted", "data_access_granted",
    "current_source_validity_checked", "legal_evidence_independently_verified", "training_execution"])("rejects invalid access %s", key => {
    const raw = changed(http.access, v => { v[key] = key.endsWith("_id") ? "invalid" : key === "version" ? "unknown" : key === "can_review_rights" ? 1 : true; });
    expect(() => rights.parseMlRightsAccess(raw)).toThrow();
  });
  it.each(["actor", "grant", "submission", "inventory", "count", "duplicate", "order", "cursor", "short_cursor", "entry_extra", "entry_hash", "size", "status", "extra", "authority", "head", "expiry"])("rejects mismatched page %s", kind => {
    const raw = changed(http.unreviewed, v => {
      if (kind === "actor") v.actor_user_id = foreign; if (kind === "grant") v.reviewer_grant_id = foreign;
      if (kind === "submission") v.submission_sha256 = otherHash; if (kind === "inventory") v.inventory_sha256 = otherHash;
      if (kind === "count") v.resource_count = true; if (kind === "duplicate") v.resources[1] = v.resources[0];
      if (kind === "order") v.resources.reverse(); if (kind === "cursor") v.next_after = otherHash;
      if (kind === "short_cursor") { v.resources = v.resources.slice(0, 1); v.next_after = v.resources[0].resource_id; }
      if (kind === "entry_extra") v.resources[0].entry.raw_source = "PRIVATE_CANARY";
      if (kind === "entry_hash") v.resources[0].resource_id = "0".repeat(64);
      if (kind === "size") v.resources[0].entry.uploaded_size_bytes = Number.MAX_SAFE_INTEGER + 1;
      if (kind === "status") v.resources[0].recorded_permission_status = "allow_recorded";
      if (kind === "extra") v.source_text = "PRIVATE_CANARY";
      if (kind === "authority") v.ml_training_approved = true;
      if (kind === "head") v.resources[0].head = JSON.parse(http.allow_committed).result.decision;
      if (kind === "expiry") v.input_access_expires_at = "invalid";
    });
    return expect(rights.parseMlRightsPage(raw, actor, query)).rejects.toThrow();
  });
  it.each(["encoding", "container", "origins", "duplicate_representation", "unknown_field"])("rejects even resealed unsupported representation %s", async kind => {
    const v = JSON.parse(http.unreviewed), row = v.resources.find((r: any) => r.kind === "row"), r = row.entry.representations[0];
    if (kind === "encoding") r.encoding = "assumed_row_hash";
    if (kind === "container") r.container_sha256 = r.container_sha256 ? null : otherHash;
    if (kind === "origins") r.origins.push(r.origins[0]);
    if (kind === "duplicate_representation") row.entry.representations.push(row.entry.representations[0]);
    if (kind === "unknown_field") r.raw_source = "PRIVATE_CANARY";
    row.resource_id = await importDigest({ kind: row.kind, entry: row.entry });
    v.resources.sort((a: any, b: any) => a.resource_id.localeCompare(b.resource_id)); v.next_after = v.resources.at(-1).resource_id;
    await expect(rights.parseMlRightsPage(JSON.stringify(v), actor, query)).rejects.toThrow();
  });
  it.each(["actor", "input", "hash", "record", "authority", "extra", "dry_run", "committed", "decision_null", "scope", "unsafe_expiry"])("refuses invalid commit %s", async kind => {
    const v = JSON.parse(http.allow_committed), ref = reference("allow");
    if (kind === "actor") ref.actorId = foreign; if (kind === "hash") ref.intentSha256 = otherHash;
    if (kind === "input") v.result.intent.resource_id = otherHash;
    if (kind === "record") v.result.decision.evidence_sha256 = otherHash;
    if (kind === "authority") v.result.source_permission_granted = true;
    if (kind === "extra") v.result.private_source = "PRIVATE_CANARY";
    if (kind === "dry_run") v.result.dry_run = true; if (kind === "committed") v.committed = false;
    if (kind === "decision_null") v.result.decision = null; if (kind === "scope") v.result.scope = "current_run_authority";
    if (kind === "unsafe_expiry") v.result.intent.expires_epoch = 9007199254740992;
    await expect(rights.parseMlRightsResult(JSON.stringify(v), ref, true)).rejects.toThrow();
  });
  it.each(["duplicate", "nested_duplicate", "BOM", "surrogate", "trailing", "oversize"])("refuses ambiguous raw JSON %s", kind => {
    let raw = http.access;
    if (kind === "duplicate") raw = raw.replace('{', '{"version":"bad",');
    if (kind === "nested_duplicate") raw = raw.replace('{', '{"extra":{"a":1,"a":2},');
    if (kind === "BOM") raw = "\ufeff" + raw;
    if (kind === "surrogate") raw = raw.replace(actor.actor_user_id, "\\ud800");
    if (kind === "trailing") raw += "{}"; if (kind === "oversize") raw += " ".repeat(4096);
    expect(() => rights.parseMlRightsAccess(raw)).toThrow();
  });
  it("rejects page changes across cursor reads and changed original preview fields", async () => {
    const first = await rights.parseMlRightsPage(http.unreviewed, actor, query);
    await expect(rights.parseMlRightsPage(changed(http.next_page, v => v.resource_count++), actor, { ...query, after: first.next_after }, first)).rejects.toThrow();
    await expect(rights.parseMlRightsResult(http.allow_preview, reference("allow"), false, { ...http.allow_input, evidence_sha256: otherHash } as rights.MlRightsInput)).rejects.toThrow();
  });
  it.each(["285.0", "285e0", "285.0000000000000000001"])("refuses noninteger wire tokens even if JS rounds them to integers: %s", async value => {
    await expect(rights.parseMlRightsPage(http.unreviewed.replace('"resource_count":285', '"resource_count":' + value), actor, query)).rejects.toThrow();
  });
});

async function mount() { render(<MlRightsWorkbench />); await waitFor(() => expect(screen.getByLabelText("Submission UUID")).toBeEnabled()); }
async function inspect() {
  for (const [label, value] of [["Submission UUID", query.submission_id], ["Submission record SHA-256", query.submission_sha256], ["Inventory SHA-256", query.inventory_sha256]])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect inventory" }));
  fireEvent.click(await screen.findByRole("button", { name: "Review resource 1", exact: true }));
  await screen.findByRole("heading", { name: "Review exact resource" });
}
function choose(kind: "allow" | "deny" | "revoke" = "allow") {
  fireEvent.change(screen.getByLabelText("Decision", { exact: true }), { target: { value: kind } });
  fireEvent.change(screen.getByLabelText("Documented basis"), { target: { value: kind === "allow" ? "documented_permission" : "withdrawn" } });
  if (kind === "allow") {
    fireEvent.change(screen.getByLabelText("Evidence document SHA-256", { exact: true }), { target: { value: http.allow_input.evidence_sha256 } });
    fireEvent.change(screen.getByLabelText(/Allow expiry/), { target: { value: String(http.allow_input.expires_epoch) } });
  }
  fireEvent.click(screen.getByRole("checkbox"));
}
async function preview(kind: "allow" | "deny" | "revoke" = "allow") { await inspect(); choose(kind);
  fireEvent.click(screen.getByRole("button", { name: "Preview ML rights decision" })); await screen.findByRole("heading", { name: "Review before committing" }); }
async function unknown() {
  vi.mocked(rights.commitMlRights).mockRejectedValue(new ApiError(503, null, "PRIVATE_CANARY"));
  await mount(); await preview(); fireEvent.click(screen.getByRole("button", { name: "Commit exact ML preview" }));
  await screen.findByText(/Commit outcome is unknown/);
}
describe("independent rights workbench", () => {
  it("rechecks admission after Strict Mode mount-effect replay without retaining the old busy guard", async () => {
    render(<StrictMode><MlRightsWorkbench /></StrictMode>);
    await waitFor(() => expect(screen.getByLabelText("Submission UUID")).toBeEnabled());
    expect(rights.getMlRightsAccess).toHaveBeenCalledTimes(2); expect(rights.commitMlRights).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it.each([401, 403, 404])("does not inspect or write without admitted access: %s", async status => {
    vi.mocked(rights.getMlRightsAccess).mockRejectedValue(new ApiError(status, null, "PRIVATE_CANARY")); render(<MlRightsWorkbench />);
    await screen.findByRole("alert"); expect(screen.getByLabelText("Submission UUID")).toBeDisabled();
    expect(rights.inspectMlRights).not.toHaveBeenCalled(); expect(rights.commitMlRights).not.toHaveBeenCalled(); expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
  });
  it("requires reviewed evidence and an explicit bounded expiry before preview; edits invalidate it", async () => {
    await mount(); await inspect(); expect(screen.getByRole("button", { name: "Preview ML rights decision" })).toBeDisabled();
    choose(); fireEvent.change(screen.getByLabelText(/Allow expiry/), { target: { value: "9999999999999999" } });
    expect(screen.getByRole("checkbox")).toBeDisabled(); expect(screen.getByRole("button", { name: "Preview ML rights decision" })).toBeDisabled();
    choose(); fireEvent.click(screen.getByRole("button", { name: "Preview ML rights decision" })); await screen.findByRole("heading", { name: "Review before committing" });
    expect(rights.commitMlRights).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Evidence document SHA-256", { exact: true }), { target: { value: otherHash } });
    expect(screen.queryByRole("button", { name: "Commit exact ML preview" })).not.toBeInTheDocument(); expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
  it.each(["allow", "deny", "revoke"] as const)("previews and commits only the exact explicit %s decision", async kind => {
    if (kind === "revoke") vi.mocked(rights.inspectMlRights).mockResolvedValue(http.allow_page);
    await mount(); await preview(kind); fireEvent.click(screen.getByRole("button", { name: "Commit exact ML preview" }));
    await screen.findByRole("heading", { name: "Historical decision receipt" });
    const input = vi.mocked(rights.previewMlRights).mock.calls[0][0];
    expect(rights.commitMlRights).toHaveBeenCalledTimes(1); expect(vi.mocked(rights.commitMlRights).mock.calls[0][0]).toEqual(input);
    expect(input.purpose).toBe(rights.ML_RIGHTS_PURPOSE); expect(input.decision).toBe(kind);
    expect(input.expires_epoch).toBe(kind === "allow" ? http.allow_input.expires_epoch : null);
    expect(screen.getByText(/This receipt is not current permission/)).toBeInTheDocument();
  });
  it("pins pagination and never interprets selecting a resource as a write", async () => {
    await mount(); await inspect(); fireEvent.click(screen.getByRole("button", { name: "Next resources" }));
    await waitFor(() => expect(rights.inspectMlRights).toHaveBeenCalledTimes(2));
    expect(vi.mocked(rights.inspectMlRights).mock.calls[1][0]).toEqual({ ...query, after: JSON.parse(http.unreviewed).next_after });
    expect(rights.previewMlRights).not.toHaveBeenCalled(); expect(rights.commitMlRights).not.toHaveBeenCalled();
  });
  it("keeps unknown commits locked, rejects missing outcomes, then retries only identical input", async () => {
    await unknown(); expect(screen.getByRole("button", { name: "Inspect inventory" })).toBeDisabled();
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
    vi.mocked(rights.recoverMlRights).mockRejectedValue(new ApiError(404, null, "PRIVATE_CANARY"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByText(/No outcome was observed/);
    expect(rights.commitMlRights).toHaveBeenCalledTimes(1);
    vi.mocked(rights.commitMlRights).mockImplementation(input => transport(input, true, true));
    fireEvent.click(screen.getByRole("button", { name: "Retry exact original commit" })); await screen.findByRole("heading", { name: "Historical decision receipt" });
    expect(vi.mocked(rights.commitMlRights).mock.calls[1].slice(0, 2)).toEqual(vi.mocked(rights.commitMlRights).mock.calls[0].slice(0, 2));
  });
  it("clears source/review state on auth change, isolates foreign recovery, and ignores late responses", async () => {
    const d = deferred<string>(); vi.mocked(rights.commitMlRights).mockReturnValue(d.promise);
    await mount(); await preview(); fireEvent.click(screen.getByRole("button", { name: "Commit exact ML preview" }));
    const input = vi.mocked(rights.commitMlRights).mock.calls[0][0];
    act(() => notifyAuthChange()); expect(screen.queryByLabelText("ML rights preview")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Unresolved ML rights operation")).not.toBeInTheDocument(); expect(screen.getByLabelText("Submission UUID")).toHaveValue("");
    vi.mocked(rights.getMlRightsAccess).mockResolvedValue(changed(http.access, v => v.actor_user_id = foreign));
    fireEvent.click(screen.getByRole("button", { name: "Refresh reviewer access" })); await screen.findByText(/An unresolved operation belongs/);
    await act(async () => d.resolve(await transport(input, true))); expect(screen.queryByRole("heading", { name: "Historical decision receipt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect inventory" })).toBeDisabled();
  });
  it("recovers an earlier operation from manually retained references without a write", async () => {
    await mount(); const ref = reference("allow");
    fireEvent.change(screen.getByLabelText("Recovery request key"), { target: { value: ref.requestKey } });
    fireEvent.change(screen.getByLabelText("Recovery intent SHA-256"), { target: { value: ref.intentSha256 } });
    fireEvent.click(screen.getByRole("button", { name: "Recover historical decision" })); await screen.findByRole("heading", { name: "Historical decision receipt" });
    expect(rights.recoverMlRights).toHaveBeenCalledWith(ref, expect.any(AbortSignal)); expect(rights.commitMlRights).not.toHaveBeenCalled();
  });
  it("blocks duplicate clicks synchronously while a commit is in flight", async () => {
    const d = deferred<string>(); vi.mocked(rights.commitMlRights).mockReturnValue(d.promise); await mount(); await preview();
    const b = screen.getByRole("button", { name: "Commit exact ML preview" }); fireEvent.click(b); fireEvent.click(b);
    expect(rights.commitMlRights).toHaveBeenCalledTimes(1); await act(async () => d.resolve(await transport(vi.mocked(rights.commitMlRights).mock.calls[0][0], true)));
    expect(within(await screen.findByLabelText("Historical ML rights receipt")).getByText(/Decision: allow/)).toBeInTheDocument();
  });
});

describe("bounded session transport", () => {
  it("uses fixed private paths, cookies, no-store, redirect refusal, and POST-only opaque recovery references", async () => {
    const real = await vi.importActual<typeof rights>("@/lib/ml-use-rights"); const fetcher = vi.fn().mockResolvedValue(new Response(http.allow_outcome, { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); const ref = reference("allow"); expect(await real.recoverMlRights(ref)).toBe(http.allow_outcome);
    expect(fetcher.mock.calls[0][0]).toMatch(/\/ml\/use\/rights\/outcome$/);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include", cache: "no-store", redirect: "error", body: JSON.stringify({ request_key: ref.requestKey, expected_intent_sha256: ref.intentSha256 }) });
  });
  it.each(["non_json", "too_large", "utf8", "too_many_parts", "status"])("rejects bounded transport failure %s without raw errors", async kind => {
    const real = await vi.importActual<typeof rights>("@/lib/ml-use-rights"); let response: Response;
    if (kind === "too_many_parts") response = new Response(new ReadableStream({ start(c) { for (let i = 0; i < 4097; i++) c.enqueue(new Uint8Array([32])); c.close(); } }), { headers: { "Content-Type": "application/json" } });
    else if (kind === "utf8") response = new Response(new Uint8Array([255]), { headers: { "Content-Type": "application/json" } });
    else response = new Response("PRIVATE_CANARY", { status: kind === "status" ? 403 : 200,
      headers: { "Content-Type": kind === "non_json" ? "text/html" : "application/json", ...(kind === "too_large" ? { "Content-Length": "999999999" } : {}) } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response)); await expect(real.getMlRightsAccess()).rejects.not.toThrow("PRIVATE_CANARY");
  });
  it("bounds hung fetches and honors already-aborted calls without retry", async () => {
    vi.useFakeTimers(); const real = await vi.importActual<typeof rights>("@/lib/ml-use-rights"), fetcher = vi.fn().mockReturnValue(new Promise(() => {}));
    vi.stubGlobal("fetch", fetcher); const pending = real.getMlRightsAccess(); const rejected = expect(pending).rejects.toBeInstanceOf(ApiError);
    await vi.advanceTimersByTimeAsync(30001); await rejected; expect(fetcher).toHaveBeenCalledTimes(1);
    const controller = new AbortController(); controller.abort(); await expect(real.getMlRightsAccess(controller.signal)).rejects.toThrow(); expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
