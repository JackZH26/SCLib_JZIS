import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PROPERTY_SNAPSHOTS, SOURCE_PROPERTY_REGISTRY, canWithdrawPropertyNote, knownPropertyCapabilities, knownPropertyDetail, knownPropertyImport,
  knownPropertyObservation, knownPropertyPage, knownPropertyReview, loadPropertyImportBytes, propertyDigest, sourcePropertyManifest,
  type PropertyRecovery } from "@/lib/source-properties";
import { access, actorId, copy, detail, importReceipt, noteReceipt, observation, otherId, page, requestNote } from "./source-properties-test-data";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());
describe("finite pending source-property wire", () => {
  it("covers all 49 original entries with distinct 46 expression / 3 unavailable and original unit/window fidelity", () => {
    let unavailable = 0, quantities = 0;
    for (const [batchIndex, batch] of PROPERTY_SNAPSHOTS.entries()) {
      const raw = JSON.parse(readFileSync(`public${batch.path}`, "utf8"));
      expect(sourcePropertyManifest(batch.sha256)).toHaveLength(raw.entries.length);
      for (let index = 0; index < raw.entries.length; index++) {
        const dto = knownPropertyObservation(observation(index, batchIndex))!;
        expect(dto).not.toBeNull(); expect(dto.projection.source_entry).toEqual(raw.entries[index]);
        expect(dto.projection.subject).toEqual(raw.entries[index].source_subject);
        expect(dto.projection.window).toEqual(raw.entries[index].source_window);
        expect(dto.projection.authority.scope).toBe("source_preparation");
        expect(dto.projection.authority.canonical_promotions).toBe(0); expect(dto.projection.authority.scientific_acceptance).toBe(false);
        if (dto.projection.profile === "unavailable") unavailable++;
        quantities += dto.projection.values.quantities.length;
      }
    }
    expect(unavailable).toBe(3); expect(quantities).toBe(91);
    const slope = observation().projection;
    expect(slope.values.quantities[0].quantity.value).toBe(-2.8); expect(slope.values.quantities[0].quantity.unit).toBe("T/K");
    const ambient = observation(5).projection, table = observation(8).projection;
    expect(ambient.values.quantities[0].quantity.raw_value).toBe("4.70(3)"); expect(table.values.quantities[0].quantity.raw_value).toBe("3.000(6)");
    const penetration = observation(9).projection;
    expect(penetration.window.raw_row_label).toContain("T>0"); expect(penetration.values.quantities[0].quantity.unit).toBe("nm");
    const sites = observation(11).projection;
    expect(sites.values.sites).toHaveLength(2); expect(sites.values.quantities[0].quantity.raw_unit).toBeNull(); expect(sites.values.quantities[0].quantity.unit_basis).toBe("cif_fractional_coordinate_field");
    expect(observation(12).projection.values.operations).toHaveLength(24);
  });
  it.each(["subject", "window", "quantity", "role", "pointer", "provenance", "unit", "authority", "private", "entry-hash", "projection-hash"])("rejects altered %s even with otherwise retained source pins", kind => {
    const value = observation(), p = value.projection;
    if (kind === "subject") p.subject.formula = "Nb";
    if (kind === "window") p.window.pressure = 0;
    if (kind === "quantity") p.values.quantities[0].quantity.value = 2.8;
    if (kind === "role") p.values.quantities[0].component_role = "lambda_eph";
    if (kind === "pointer") p.values.quantities[0].json_pointer = "/entries/0/source_subject";
    if (kind === "provenance") p.provenance.sources[0].source_url = "https://example.com/private";
    if (kind === "unit") p.values.quantities[0].quantity.unit = "K";
    if (kind === "authority") p.authority.scope = "runtime_no_database_write";
    if (kind === "private") (p as unknown as Record<string, unknown>).private_notes = "forbidden";
    if (kind === "entry-hash") p.entry_sha256 = "d".repeat(64);
    if (kind === "projection-hash") value.projection_sha256 = "d".repeat(64);
    expect(knownPropertyObservation(value)).toBeNull();
  });
  it("rejects coordinated source and typed-value changes while preserving recursive object key order independence", () => {
    const value = observation(); (value.projection.source_entry.value as Record<string, unknown>).value = 2.8; value.projection.values.quantities[0].quantity.value = 2.8;
    expect(knownPropertyObservation(value)).toBeNull();
    const reorder = (v: unknown): unknown => Array.isArray(v) ? v.map(reorder) : v !== null && typeof v === "object" ? Object.fromEntries(Object.entries(v).reverse().map(([k, item]) => [k, reorder(item)])) : v;
    expect(knownPropertyObservation(reorder(observation()))).not.toBeNull();
  });
  it("bounds list/detail and never treats duplicate rows or new fields as supported", () => {
    expect(knownPropertyPage(page(), 0, 25)).not.toBeNull(); expect(knownPropertyDetail(detail(), detail().id)).not.toBeNull();
    const altered = page(); altered.observations.push(copy(altered.observations[0])); altered.total = 2;
    expect(knownPropertyPage(altered, 0, 25)).toBeNull(); altered.observations[1].id = otherId;
    expect(knownPropertyPage(altered, 0, 25)).toBeNull(); expect(knownPropertyDetail({ ...detail(), private_notes: "not part of this DTO" }, detail().id)).toBeNull();
  });
  it("binds capabilities to the dashboard actor and closed rights without inferring admin access", () => {
    expect(knownPropertyCapabilities(access, actorId)).not.toBeNull(); expect(knownPropertyCapabilities(access, otherId)).toBeNull();
    expect(knownPropertyCapabilities({ ...access, can_import: false })).toBeNull(); expect(knownPropertyCapabilities({ ...access, is_admin: true })).toBeNull();
    expect(knownPropertyCapabilities({ ...access, registry_sha256: "0".repeat(64) })).toBeNull(); expect(access.registry_sha256).toBe(SOURCE_PROPERTY_REGISTRY);
  });
  it("binds exact import preview, manifest, original actor, preview hash and actual ledger-write flag", async () => {
    const value = await importReceipt("test-source-import:one"), ref: PropertyRecovery = { kind: "import", actorId, requestKey: "test-source-import:one", requestSha256: value.request_sha256, previewSha256: value.preview_sha256, sourceSha256: value.source_json_sha256 };
    expect(await knownPropertyImport(value, access, ref, "preview")).not.toBeNull();
    expect(await knownPropertyImport({ ...value, pending_ledger_written: true }, access, ref, "preview")).toBeNull();
    const commit = await importReceipt(ref.requestKey, false); expect(await knownPropertyImport(commit, access, ref, "commit")).not.toBeNull();
    expect(await knownPropertyImport(commit, access, { ...ref, previewSha256: "0".repeat(64) }, "commit")).toBeNull();
    const replay = await importReceipt(ref.requestKey, false, true); expect(await knownPropertyImport(replay, { ...access, session_version: 2, grants: { ...access.grants, curator: otherId } }, ref, "outcome")).not.toBeNull();
    expect(await knownPropertyImport({ ...replay, dry_run: true }, access, ref, "outcome")).toBeNull();
    expect(await knownPropertyImport(replay, { ...access, actor_user_id: otherId }, ref, "outcome")).toBeNull();
    const dirty = copy(value); dirty.observation_manifest[0].source_entry_id = "unknown"; expect(await knownPropertyImport(dirty, access, ref, "preview")).toBeNull();
  });
  it("preserves source-note scope and hash identity, without equating note SHA and appended row SHA", async () => {
    const request = requestNote(), note = await noteReceipt(request), ref: PropertyRecovery = { kind: "review", actorId, requestKey: request.request_key,
      requestSha256: await propertyDigest(request), previewSha256: note.preview_sha256, observationId: request.observation_id, observationSha256: request.observation_sha256 };
    expect(note.source_note_sha256).not.toBe(note.review_sha256); expect(await knownPropertyReview(note, access, ref, request, "preview")).not.toBeNull();
    expect(await knownPropertyReview({ ...note, scientific_acceptance: true }, access, ref, request, "preview")).toBeNull();
    expect(await knownPropertyReview({ ...note, source_note: { ...note.source_note, note: "Changed after preview" } }, access, ref, request, "preview")).toBeNull();
  });
  it("rejects coordinated note/action changes on GET recovery using the original verified note hash, without retaining its body", async () => {
    const request = requestNote(), committed = { ...await noteReceipt(request, false), replayed: true };
    const ref: PropertyRecovery = { kind: "review", actorId, requestKey: request.request_key, requestSha256: committed.request_sha256,
      previewSha256: committed.preview_sha256, observationId: request.observation_id, observationSha256: request.observation_sha256, sourceNoteSha256: committed.source_note_sha256 };
    expect(await knownPropertyReview(committed, access, ref, null, "outcome")).not.toBeNull();
    for (const field of ["action", "note"] as const) {
      const dirty = copy(committed);
      if (field === "action") dirty.source_note.action = "matches_inspected_source";
      else dirty.source_note.note = "Altered source fidelity declaration";
      dirty.source_note_sha256 = await propertyDigest(dirty.source_note);
      expect(await knownPropertyReview(dirty, access, ref, null, "outcome")).toBeNull();
    }
    expect(await knownPropertyReview(committed, access, { ...ref, sourceNoteSha256: undefined }, null, "outcome")).toBeNull();
  });
  it("permits withdrawal only of own preceding nonwithdraw note, while retaining the earlier chain", async () => {
    const value = detail(); expect(canWithdrawPropertyNote(value, access)).toBe(false);
    value.source_notes = [await noteReceipt(requestNote(), false)]; value.source_notes_total = 1;
    expect(canWithdrawPropertyNote(value, access)).toBe(true); expect(canWithdrawPropertyNote(value, { ...access, actor_user_id: otherId })).toBe(false);
    value.source_notes[0].source_note.action = "withdraw_note"; expect(canWithdrawPropertyNote(value, access)).toBe(false);
  });
  it("accepts only the exact downloaded static bytes; a successful HTTP response with altered bytes is refused", async () => {
    const bytes = readFileSync("public/research-pilots/materials-source-observations-2026-10-02.json");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes))); expect(await loadPropertyImportBytes(PROPERTY_SNAPSHOTS[0].sha256)).toBe(bytes.toString("base64"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes.toString().replace("-2.8", "2.8"))));
    await expect(loadPropertyImportBytes(PROPERTY_SNAPSHOTS[0].sha256)).rejects.toThrow("Source snapshot changed");
  });
});
