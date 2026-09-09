import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { getSelectionAccess, getSelectionContext, getSelectionOutcome, inventoryCell, parsePreparedSelection, parseRegistrationReceipt,
  parseSelectionAccess, parseSelectionContext, prepareSelection, recoveryFor, registerSelection, selectedInventory, selectionSourceFromFile } from "@/lib/discovery-selection";
import { parsePreparedScientificPayload, SCIENTIFIC_KEYS } from "@/lib/discovery-scientific";
import provenance from "../fixtures/discovery-selection/provenance.json";
import { hash, requestFixture, verifiedFixture, wires } from "./helpers/discovery-selection-fixtures";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
const mutated = (raw: string, change: (v: any) => void) => { const v = JSON.parse(raw); change(v); return JSON.stringify(v); };
const resealContext = (change: (v: any) => void) => mutated(wires.contextWire, v => {
  const c = JSON.parse(v.context_json); change(c); v.context_json = JSON.stringify(c); v.context_sha256 = hash(v.context_json);
});

describe("actual Discovery selection wire contract", () => {
  it("verifies retained wire and backend provenance hashes without float reserialization", () => {
    for (const file of provenance.files) {
      const raw = JSON.parse(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-selection", file.file), "utf8")) as string;
      expect(hash(raw), file.file).toBe(file.sha256); expect(Buffer.byteLength(raw)).toBe(file.size_bytes);
    }
    // Portable copy differs from the original external writer only by the
    // final blank line. Keep both actual byte pins, never rewrite provenance.
    expect(hash(readFileSync(resolve(process.cwd(), "tests/fixtures/capture-discovery-selection.py"), "utf8"))).toBe("77330867abefb9cb44534174b463c1ffc4ca0e4661b5c7bd0c4f9617c92e76c8");
    for (const [file, sha] of Object.entries(provenance.source_pins)) expect(hash(readFileSync(resolve(process.cwd(), "..", file), "utf8")), file).toBe(sha);
  });
  it("accepts all eight actual private fields with zero scientific acceptance and unedited commands", async () => {
    const { prepared, context } = await verifiedFixture();
    expect(prepared.payload.rows[0].cells.map(c => c.property_key)).toEqual(SCIENTIFIC_KEYS);
    const observations = prepared.payload.rows.flatMap(r => r.cells.flatMap(c => c.observations));
    expect(observations).toHaveLength(8); expect(observations.every(o => !o.scientific_scope_accepted)).toBe(true);
    expect(observations.find(o => o.property.property_key === "band_gap")?.quantity.value).toBe(0);
    expect(observations.find(o => o.property.property_key === "phonon_min_frequency")?.quantity.value).toBe(-0.125);
    expect(prepared.payload_sha256).toBe(provenance.pins.payload_sha256);
    expect(hash(prepared.preview_json)).toBe(provenance.pins.preview_sha256);
    expect(hash(prepared.commit_json)).toBe(provenance.pins.commit_sha256);
    expect(context.context_sha256).toBe(provenance.pins.context_sha256);
  });
  it("separates explicit no-structure selection from the registered structure and keeps unknown distinct", async () => {
    const { context, request } = await verifiedFixture(), m = context.context.materials[0];
    expect(selectedInventory(m, request.choices[0].assessment_id, null).results).toHaveLength(0);
    expect(selectedInventory(m, request.choices[0].assessment_id, request.choices[0].structure_id).results).toHaveLength(8);
    expect(inventoryCell("band_gap", [])).toMatchObject({ availability: "unknown", reason_code: "no_matching_registered_result" });
    expect(() => selectedInventory(m, "unknown", null)).toThrow();
    expect(() => selectedInventory(m, request.choices[0].assessment_id, "")).toThrow();
  });
  it("accepts exact private payload independently without pretending it is a public receipt", async () => {
    const p = JSON.parse(wires.preparedWire);
    expect((await parsePreparedScientificPayload(p.payload_json, p.payload_sha256, p.selection_sha256)).payload.rows).toHaveLength(1);
  });
  it.each([
    ["extra key", (v: any) => { v.debug = "PRIVATE_CANARY"; }],
    ["scientific approval", (v: any) => { v.scientific_acceptance = true; }],
    ["false admission", (v: any) => { v.can_prepare_selection = false; }],
    ["bad grant", (v: any) => { v.actor_grant_id = "not-an-id"; }],
  ])("rejects access %s", (_, change) => expect(() => parseSelectionAccess(mutated(wires.accessWire, change as (v: any) => void))).toThrow());
  it.each([
    ["foreign actor", (v: any) => { v.actor_user_id = "00000000-0000-0000-0000-000000000000"; }],
    ["false quantity basis", (v: any) => { v.quantity_basis = "scientifically_accepted"; }],
    ["native material mismatch", (v: any) => { v.materials[0].material.table = "material_states"; }],
    ["missing null structure", (v: any) => { v.materials[0].structures.shift(); }],
    ["unknown native state", (v: any) => { v.materials[0].results[0].state_id = "00000000-0000-0000-0000-000000000000"; }],
    ["wrong unit", (v: any) => { v.materials[0].results[0].quantity.unit = "K"; }],
    ["invented current review", (v: any) => { v.materials[0].results[0].scientific_scope_accepted = true; }],
    ["inapplicable evidence context", (v: any) => { v.materials[0].declaration_evidence[0].structure_id = "00000000-0000-0000-0000-000000000000"; }],
    ["duplicate material", (v: any) => { v.materials.push(v.materials[0]); }],
  ])("rejects resealed context %s", async (_, change) => {
    await expect(parseSelectionContext(resealContext(change as (v: any) => void), parseSelectionAccess(wires.accessWire), requestFixture().source)).rejects.toThrow();
  });
  it.each([
    ["stale payload", (v: any) => { v.payload_sha256 = "0".repeat(64); }],
    ["wrong actor", (v: any) => { v.actor_user_id = "00000000-0000-0000-0000-000000000000"; }],
    ["wrong key", (v: any) => { v.request_key = "another"; }],
    ["claimed registration", (v: any) => { v.registration_performed = true; }],
    ["stale command bytes", (v: any) => { v.preview_json += " "; }],
    ["reversed dry run", (v: any) => { v.preview_json = v.commit_json; v.preview_sha256 = v.commit_sha256; }],
  ])("rejects prepared %s", async (_, change) => {
    const f = await verifiedFixture();
    await expect(parsePreparedSelection(mutated(wires.preparedWire, change as (v: any) => void), f.access, f.context, f.request)).rejects.toThrow();
  });
  it("rejects resealed equivalent scalar escapes that would poison original-outcome recovery", async () => {
    const f = await verifiedFixture(), response = JSON.parse(wires.preparedWire);
    const original = JSON.parse(response.commit_json).expected_inventory_sha256 as string;
    const escaped = `"\\u${original.charCodeAt(0).toString(16).padStart(4, "0")}${original.slice(1)}"`;
    for (const kind of ["preview", "commit"]) {
      response[`${kind}_json`] = response[`${kind}_json`].replace(JSON.stringify(original), escaped);
      response[`${kind}_sha256`] = hash(response[`${kind}_json`]);
    }
    // This is the previously accepted erroneous request hash, derived from the
    // resealed raw scalar, not the backend canonical semantic request.
    const command = JSON.parse(response.commit_json), expected = { distribution_package_id: command.distribution_package_id,
      expected_distribution_record_sha256: command.expected_distribution_record_sha256, expected_inventory_sha256: command.expected_inventory_sha256,
      expected_selection_sha256: command.expected_selection_sha256, operation: "register", public_bundle: command.public_bundle,
      selection: command.selection, version: "discovery-projection-governance/1.0.0" };
    // Use actual original raw spans to preserve Python float spelling.
    const { parsePrivateDiscoveryJSON } = await import("@/lib/discovery-scientific");
    const spans = parsePrivateDiscoveryJSON(response.commit_json, 20 * 1024 * 1024, Object.keys(command)).spans;
    response.request_sha256 = hash(`{${Object.keys(expected).sort().map(k => `${JSON.stringify(k)}:${k === "operation" ? '"register"' : k === "version" ? '"discovery-projection-governance/1.0.0"' : spans.get(k)}`).join(",")}}`);
    expect(response.request_sha256).not.toBe(f.prepared.request_sha256);
    await expect(parsePreparedSelection(JSON.stringify(response), f.access, f.context, f.request)).rejects.toThrow();
  });
  it("rejects a response to changed choices and does not mutate caller-owned data", async () => {
    const f = await verifiedFixture(); f.request.choices[0].structure_id = null;
    await expect(parsePreparedSelection(wires.preparedWire, f.access, f.context, f.request)).rejects.toThrow();
    expect(f.request.choices[0].structure_id).toBeNull();
  });
  it("rejects a resealed structure-kind relabel with unchanged native ID and row pin", async () => {
    const f = await verifiedFixture(), response = JSON.parse(wires.preparedWire), oldHash = response.payload_sha256;
    expect(response.payload_json).toContain('"structure_kind":"coordinates"');
    response.payload_json = response.payload_json.replaceAll('"structure_kind":"coordinates"', '"structure_kind":"prototype"');
    response.payload_sha256 = hash(response.payload_json);
    for (const kind of ["preview", "commit"]) {
      response[`${kind}_json`] = response[`${kind}_json`].replace(oldHash, response.payload_sha256);
      response[`${kind}_sha256`] = hash(response[`${kind}_json`]);
    }
    await expect(parsePreparedSelection(JSON.stringify(response), f.access, f.context, f.request)).rejects.toThrow();
  });
  it("binds receipts by request/payload/selection, not provisional UUID; requires outer durability", async () => {
    const f = await verifiedFixture(), ref = recoveryFor(f.prepared);
    const rehearsal = parseRegistrationReceipt(wires.previewWire, ref, false), committed = parseRegistrationReceipt(wires.commitWire, ref, true);
    expect(rehearsal.id).not.toBe(committed.id);
    expect(parseRegistrationReceipt(wires.outcomeWire, ref, true, true).replayed).toBe(true);
    expect(() => parseRegistrationReceipt(wires.previewWire, ref, true)).toThrow();
    expect(() => parseRegistrationReceipt(wires.commitWire, ref, true, true)).toThrow();
    expect(() => parseRegistrationReceipt(mutated(wires.commitWire, v => { v.result.committed = true; }), ref, true)).toThrow();
    expect(() => parseRegistrationReceipt(wires.commitWire, { ...ref, selectionSha256: "0".repeat(64) }, true)).toThrow();
  });
  it.each(["{\"x\":1,\"x\":2}", "{\"x\":NaN}", "{\"x\":\"\\ud800\"}", "\ufeff{}", "{} trailing"])("rejects malformed local file %s", async raw => {
    const file = { size: Buffer.byteLength(raw), arrayBuffer: async () => new TextEncoder().encode(raw).buffer } as File;
    await expect(selectionSourceFromFile(file, requestFixture().source.distribution_package_id)).rejects.toThrow();
  });
  it("bounds local file bytes and retains canonical source exactly", async () => {
    const file = { size: Buffer.byteLength(wires.sourceWire), arrayBuffer: async () => new TextEncoder().encode(wires.sourceWire).buffer } as File;
    expect(await selectionSourceFromFile(file, requestFixture().source.distribution_package_id)).toEqual(requestFixture().source);
    await expect(selectionSourceFromFile({ ...file, size: 17 * 1024 * 1024 } as File, requestFixture().source.distribution_package_id)).rejects.toThrow();
  });
});

describe("bounded same-session selection transport", () => {
  it("uses the fixed private paths and raw commands with no redirects or automatic retries", async () => {
    const f = await verifiedFixture(), fetcher = vi.fn(async () => new Response(wires.accessWire, { headers: { "content-type": "application/json" } })); vi.stubGlobal("fetch", fetcher);
    await getSelectionAccess(); await getSelectionContext(f.request.source); await prepareSelection(f.request); await registerSelection(f.prepared.commit_json); await getSelectionOutcome(recoveryFor(f.prepared));
    expect(fetcher).toHaveBeenCalledTimes(5);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls[3][1]).toMatchObject({ body: f.prepared.commit_json, method: "POST", credentials: "include", cache: "no-store", redirect: "error" });
    expect(calls[4][0]).toContain(`/outcome?operation=register&request_key=`); expect(calls[4][1].method).toBe("GET");
  });
  it("does not dispatch an already-cancelled write", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher); const c = new AbortController(); c.abort();
    await expect(registerSelection("{}", c.signal)).rejects.toBeInstanceOf(ApiError); expect(fetcher).not.toHaveBeenCalled();
  });
  it("cancels an uncooperative response and never reads private error text", async () => {
    const cancel = vi.fn(), fetcher = vi.fn(async () => new Response(new ReadableStream({ cancel }), { status: 403 })); vi.stubGlobal("fetch", fetcher);
    await expect(getSelectionAccess()).rejects.toMatchObject({ status: 403 }); expect(cancel).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([
    ["wrong content type", () => new Response("{}", { headers: { "content-type": "text/html" } })],
    ["oversized advertised body", () => new Response("{}", { headers: { "content-type": "application/json", "content-length": "9999999" } })],
    ["oversized streamed body", () => new Response("x".repeat(4097), { headers: { "content-type": "application/json" } })],
    ["invalid UTF-8", () => new Response(new Uint8Array([0xff]), { headers: { "content-type": "application/json" } })],
  ])("rejects %s", async (_, response) => {
    vi.stubGlobal("fetch", vi.fn(async () => (response as () => Response)())); await expect(getSelectionAccess()).rejects.toMatchObject({ status: 0 });
  });
  it("enforces a deadline even when fetch ignores its signal", async () => {
    vi.useFakeTimers(); const fetcher = vi.fn(() => new Promise<Response>(() => {})); vi.stubGlobal("fetch", fetcher);
    const pending = getSelectionAccess(), assertion = expect(pending).rejects.toMatchObject({ status: 0 });
    await vi.advanceTimersByTimeAsync(35_001); await assertion; expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("aborts a stalled body read", async () => {
    const cancel = vi.fn(); vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream({ cancel }), { headers: { "content-type": "application/json" } })));
    const c = new AbortController(), pending = getSelectionAccess(c.signal), assertion = expect(pending).rejects.toMatchObject({ status: 0 });
    await Promise.resolve(); await Promise.resolve(); c.abort(); await assertion; expect(cancel).toHaveBeenCalled();
  });
});
