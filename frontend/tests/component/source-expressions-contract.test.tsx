import { webcrypto } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";
import { MAX_PACKAGE_BYTES, expressionCanonical, expressionRecovery, expressionSha, knownCapturePage, knownExpressionCapabilities, knownExpressionPage,
  knownExpressionReceipt, knownSourceCapture, knownSourceRevision, parseExpressionJson, prepareExpressionPackage, sourceValueLabel } from "@/lib/source-expressions";
import { emptyCapturePage, emptyExpressionPage, expressionActor, expressionCap, preparedSynthetic, syntheticPackage, syntheticReceipt, syntheticRevision } from "../helpers/source-expression-test-data";

beforeAll(() => { Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true }); });
const encoded = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));
describe("Private source-expression input and exact canonical lineage", () => {
  it("keeps signed source values, uncertainty and a separate ambient window without inventing pressure", async () => {
    const data = await preparedSynthetic("−2.8 ± 0.2", "K");
    expect(data.localExpressions[0].rawValue).toBe("−2.8 ± 0.2"); expect(data.localExpressions[0].window).toBe("ambient");
    expect(data.localExpressions[0].conditions).toEqual([{ field: "window_statement", role: "fit_window", rawValue: "ambient", rawUnit: null }]);
    expect(data.localExpressions[0].origin).toBe("Computed"); expect(data.package.source.source_id).toBe("test-conference");
  });
  it("verifies non-BMP offsets by codepoint, and rejects a UTF-16 span with otherwise retained bytes", async () => {
    const pkg = await syntheticPackage(); expect(pkg.expressions[0].subject.formula_spans[0].start).toBe(2);
    pkg.expressions[0].subject.formula_spans[0].start++; pkg.expressions[0].subject.formula_spans[0].end++;
    await expect(prepareExpressionPackage(encoded(pkg))).rejects.toThrow("source span");
  });
  it("preserves missing units and an exact arbitrary raw unit without applying registry defaults", async () => {
    const missing = await preparedSynthetic("94.5", ""), unknown = await preparedSynthetic("94.5", "source unit");
    expect(missing.localExpressions[0].rawUnit).toBeNull(); expect(unknown.localExpressions[0].rawUnit).toBe("source unit");
  });
  it("does not accept duplicate keys, nonfinite numbers, excessive nesting or private unknown context", async () => {
    expect(() => parseExpressionJson('{"version":1,"version":2}')).toThrow("Duplicate");
    expect(() => parseExpressionJson('{"start":1e999}')).toThrow("finite");
    expect(() => parseExpressionJson("[".repeat(22) + "0" + "]".repeat(22))).toThrow("bounds");
    const pkg = await syntheticPackage(); await expect(prepareExpressionPackage(encoded({ ...pkg, private_notes: "not uploaded" }))).rejects.toThrow("format");
    (pkg.expressions[0].origin_basis as unknown as Record<string, unknown>).private_notes = "nested";
    await expect(prepareExpressionPackage(encoded(pkg))).rejects.toThrow("format");
  });
  it("rejects an array that would otherwise coerce to a valid registry field name", async () => {
    const pkg = await syntheticPackage(); (pkg.expressions[0] as unknown as Record<string, unknown>).field_id = ["tc_kelvin"];
    await expect(prepareExpressionPackage(encoded(pkg))).rejects.toThrow("format");
    const revision = await syntheticRevision(); (revision.projection as unknown as Record<string, unknown>).field_id = ["tc_kelvin"];
    expect(await knownSourceRevision(revision, revision.id)).toBeNull();
  });
  it("does not silently convert floating-point metadata tokens to Python integer span offsets", async () => {
    const pkg = await syntheticPackage(), original = JSON.stringify(pkg); expect(original).toContain('"start":2');
    await expect(prepareExpressionPackage(new TextEncoder().encode(original.replace('"start":2', '"start":2.0')))).rejects.toThrow("integers");
    await expect(prepareExpressionPackage(new TextEncoder().encode(original.replace('"start":2', '"start":2e0')))).rejects.toThrow("integers");
    expect(parseExpressionJson('{"value":2.0,"uncertainty":3e-1}', false)).toEqual({ value: 2, uncertainty: 0.3 });
  });
  it("enforces file and decoded fragment limits before any upload or source inspection", async () => {
    await expect(prepareExpressionPackage(new Uint8Array(MAX_PACKAGE_BYTES + 1))).rejects.toThrow("1 MiB");
    const pkg = await syntheticPackage(); pkg.source_text_base64 = btoa("A".repeat(131073)); await expect(prepareExpressionPackage(encoded(pkg))).rejects.toThrow();
  });
  it("rejects reordered/overlapping spans and discontiguous scalar selection", async () => {
    const pkg = await syntheticPackage(); pkg.expressions[0].value_spans.push({ ...pkg.expressions[0].value_spans[0] }); await expect(prepareExpressionPackage(encoded(pkg))).rejects.toThrow();
    const formula = await syntheticPackage(); formula.expressions[0].subject.formula_spans.push({ ...formula.expressions[0].subject.formula_spans[0] }); await expect(prepareExpressionPackage(encoded(formula))).rejects.toThrow();
  });
  it("changes only local file fingerprint for pretty formatting, with source and package digests preserved", async () => {
    const pkg = await syntheticPackage(), a = await prepareExpressionPackage(encoded(pkg)), b = await prepareExpressionPackage(new TextEncoder().encode(JSON.stringify(pkg, null, 2)));
    expect(a.fileSha).not.toBe(b.fileSha); expect(a.packageSha).toBe(b.packageSha); expect(a.package.source_content_sha256).toBe(b.package.source_content_sha256);
    expect(expressionCanonical(JSON.parse(expressionCanonical(pkg)))).toBe(expressionCanonical(pkg));
  });
  it("requires active actor-bound finite capabilities, with disabled read-only access remaining usable", () => {
    expect(knownExpressionCapabilities(expressionCap, expressionActor)).not.toBeNull();
    expect(knownExpressionCapabilities(expressionCap, "00000000-0000-4000-8000-000000000111")).toBeNull();
    expect(knownExpressionCapabilities({ ...expressionCap, can_import: false, curator_grant_id: null }, expressionActor)).not.toBeNull();
    expect(knownExpressionCapabilities({ ...expressionCap, scientific_acceptance: true }, expressionActor)).toBeNull();
    expect(knownExpressionCapabilities({ ...expressionCap, private_notes: {} }, expressionActor)).toBeNull();
  });
  it("binds preview to the exact original package, entry IDs and current grant/session", async () => {
    const prepared = await preparedSynthetic(), ref = expressionRecovery(prepared, expressionCap, "test-intake:preview"), receipt = await syntheticReceipt(prepared, ref.requestKey);
    expect(await knownExpressionReceipt(receipt, expressionCap, ref, "preview", prepared)).not.toBeNull();
    expect(await knownExpressionReceipt(receipt, { ...expressionCap, session_version: 3 }, ref, "preview", prepared)).toBeNull();
    receipt.expression_manifest[0].entry_sha256 = "f".repeat(64); expect(await knownExpressionReceipt(receipt, expressionCap, ref, "preview", prepared)).toBeNull();
  });
  it("refuses a coordinated changed manifest and rehashed preview while preserving original outcome pins", async () => {
    const prepared = await preparedSynthetic(), baseRef = expressionRecovery(prepared, expressionCap, "test-intake:unknown"), original = await syntheticReceipt(prepared, baseRef.requestKey);
    const ref = { ...baseRef, previewSha: original.preview_sha256, manifestCanonical: expressionCanonical(original.expression_manifest) };
    const changed = await syntheticReceipt(prepared, baseRef.requestKey, false); changed.replayed = true; changed.expression_manifest[0].projection_sha256 = "f".repeat(64);
    const preview = JSON.parse(changed.preview_canonical_json); preview.manifest = changed.expression_manifest; changed.preview_canonical_json = expressionCanonical(preview); changed.preview_sha256 = await expressionSha(changed.preview_canonical_json);
    const body = JSON.parse(changed.receipt_canonical_json); body.expression_manifest = changed.expression_manifest; body.preview_sha256 = changed.preview_sha256; changed.receipt_canonical_json = expressionCanonical(body); changed.receipt_sha256 = await expressionSha(changed.receipt_canonical_json);
    expect(await knownExpressionReceipt(changed, expressionCap, ref, "outcome")).toBeNull();
  });
  it("accepts original same-actor committed replay with a later session, without rewriting historical authorization", async () => {
    const prepared = await preparedSynthetic(), baseRef = expressionRecovery(prepared, expressionCap, "test-intake:replay"), receipt = await syntheticReceipt(prepared, baseRef.requestKey, false); receipt.replayed = true;
    const ref = { ...baseRef, previewSha: receipt.preview_sha256, manifestCanonical: expressionCanonical(receipt.expression_manifest) };
    const result = await knownExpressionReceipt(receipt, { ...expressionCap, session_version: 9, curator_grant_id: "00000000-0000-4000-8000-000000000109" }, ref, "outcome");
    expect(result?.actor_session_version).toBe(2); expect(result?.pending_ledger_written).toBe(true);
    expect(await knownExpressionReceipt(receipt, expressionCap, { ...ref, actorId: "00000000-0000-4000-8000-000000000110" }, "outcome")).toBeNull();
  });
  it("verifies source detail by exact canonical record, original package entry and quantity provenance", async () => {
    const revision = await syntheticRevision(); expect(await knownSourceRevision(revision, revision.id, revision.record_sha256)).not.toBeNull();
    expect(revision.projection.value.raw_value).toBe("94.5 ± 0.3"); expect(revision.projection.window.raw_label).toBe("ambient");
    expect(sourceValueLabel(revision.projection.value)).toBe("94.5 ± 0.3 K");
    revision.source_entry.locator.slide = 7; expect(await knownSourceRevision(revision, revision.id)).toBeNull();
  });
  it("rejects normalized quantity tampering even if projection hash is recomputed, while old record SHA stays fixed", async () => {
    const revision = await syntheticRevision(); if (!("value" in revision.projection.value)) throw new Error("quantity expected");
    revision.projection.value.value = 150; revision.projection_canonical_json = JSON.stringify(revision.projection); revision.projection_sha256 = await expressionSha(revision.projection_canonical_json);
    expect(await knownSourceRevision(revision, revision.id)).toBeNull();
  });
  it("rejects changed declared source metadata rehashed under an original capture record/content pin", async () => {
    const original = (await syntheticRevision()).capture, changed = structuredClone(original);
    changed.source.url = "https://example.com/changed-source.pdf"; changed.source.currentness = "declared_current"; changed.source.rights_status = "restricted";
    changed.source_metadata_canonical_json = expressionCanonical(changed.source); changed.metadata_sha256 = await expressionSha(changed.source_metadata_canonical_json);
    expect(await knownSourceCapture({ version: "source-expression-intake/2.0.0", ...changed }, original.id, original)).toBeNull();
    expect(await knownSourceCapture({ version: "source-expression-intake/2.0.0", ...original, latest_retained_capture_for_source: false }, original.id, original)).not.toBeNull();
  });
  it("pins an exact revision to its original immutable receipt SHA despite coordinated metadata and package rehashing", async () => {
    const revision = await syntheticRevision(), receipt = revision.import_receipt!;
    revision.capture.source.url = "https://example.com/changed.pdf"; revision.capture.source.currentness = "declared_current";
    revision.capture.source_metadata_canonical_json = expressionCanonical(revision.capture.source); revision.capture.metadata_sha256 = await expressionSha(revision.capture.source_metadata_canonical_json);
    const pkg = JSON.parse(receipt.package_canonical_json); pkg.source = revision.capture.source;
    receipt.package_canonical_json = expressionCanonical(pkg); receipt.package_sha256 = await expressionSha(receipt.package_canonical_json);
    receipt.request_canonical_json = expressionCanonical({ version: receipt.version, package_sha256: receipt.package_sha256 }); receipt.request_sha256 = await expressionSha(receipt.request_canonical_json);
    const preview = JSON.parse(receipt.preview_canonical_json); preview.request_sha256 = receipt.request_sha256; receipt.preview_canonical_json = expressionCanonical(preview); receipt.preview_sha256 = await expressionSha(receipt.preview_canonical_json);
    const body = JSON.parse(receipt.receipt_canonical_json); Object.assign(body, { package_json: receipt.package_canonical_json, package_sha256: receipt.package_sha256, request_sha256: receipt.request_sha256, preview_sha256: receipt.preview_sha256 });
    receipt.receipt_canonical_json = expressionCanonical(body); receipt.receipt_sha256 = await expressionSha(receipt.receipt_canonical_json);
    expect(await knownSourceRevision(revision, revision.id, revision.record_sha256)).toBeNull();
  });
  it("uses retained canonical float tokens rather than integer-only reserialization", async () => {
    const revision = await syntheticRevision(); revision.projection_canonical_json = revision.projection_canonical_json.replace('"uncertainty":0.3', '"uncertainty":3e-1'); revision.projection_sha256 = await expressionSha(revision.projection_canonical_json);
    const body = JSON.parse(revision.revision_canonical_json); body.projection_json = revision.projection_canonical_json; body.projection_sha256 = revision.projection_sha256;
    revision.revision_canonical_json = expressionCanonical(body); revision.record_sha256 = await expressionSha(revision.revision_canonical_json);
    // Compact lists do not carry the receipt. They still bind exact retained float strings to this record.
    const { version: _version, ...listItem } = revision; listItem.import_receipt = null;
    expect(await knownSourceRevision(listItem)).not.toBeNull();
  });
  it("does not treat current capture, valid CIF/source metadata or a bounded empty window as scientific approval", async () => {
    expect(await knownExpressionPage(emptyExpressionPage(), 0, 8)).not.toBeNull(); expect(await knownCapturePage(emptyCapturePage(), 0, 25)).not.toBeNull();
    const revision = await syntheticRevision(), { version: _version, ...item } = revision; item.import_receipt = null;
    const page = { ...emptyExpressionPage(), total: 1, expressions: [item] };
    expect(await knownExpressionPage(page, 0, 8)).not.toBeNull(); expect(await knownExpressionPage(page, 0, 8, { field: "lambda_eph" })).toBeNull();
    item.capture.publication_revision_verified = true as false; expect(await knownExpressionPage(page, 0, 8)).toBeNull();
  });
});
