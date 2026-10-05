import { webcrypto } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { compileLiteralPackage } from "@/lib/material-literal-fields";
import { compileTablePackage, knownTableCaseCapabilities, knownTableSourceCapabilities, knownTableSourceRevision, knownTableCaseContext, knownTableCaseDetail, tableExpressionRecovery, knownTableExpressionReceipt, tableStoredSourceIdentity, knownTableStoredOutcome, readTableRecovery, storeTableRecovery, clearTableRecovery } from "@/lib/material-table-fields";
import { tableOracle, tablePackage, tableSourceCap, tableCaseCap, tableActor, tableMaterial, tableContext, tableDetail, tableRevision, tableSourceReceipt, tableCaseReceipt, tableFlags } from "../helpers/material-table-field-test-data";
import type { TableCaseRequest } from "@/lib/material-table-fields";
import { expressionCanonical } from "@/lib/source-expressions";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });

describe("original table proof contract", () => {
  it("reconstructs all four Python/SQL projections from original bytes", async () => {
    const actual = await compileTablePackage(tableOracle.package);
    expect(actual.packageSha).toBe(tableOracle.packageSha);
    expect(actual.projections).toEqual(tableOracle.projections);
    expect(actual.projections.map(p => p.value.raw_value)).toEqual(["3.16", "492", "3.07", "501"]);
    expect(actual.projections.every(p => p.value.quantity === null && p.value.raw_uncertainty === null && p.scientific_acceptance === false)).toBe(true);
    await expect(compileLiteralPackage(tableOracle.package)).rejects.toThrow();
  });

  it.each(["column", "unit", "value", "ragged", "order", "caption", "locator", "authority", "fraction_index"])("rejects altered %s instead of treating a rehash as evidence", async change => {
    const p = await tablePackage(), e = p.expressions[0], g = e.table_binding;
    if (change === "column") e.subject.formula_spans = [g.header_spans[2]];
    else if (change === "unit") e.unit_spans = p.expressions[1].unit_spans;
    else if (change === "value") e.value_spans = [g.rows[1][2]];
    else if (change === "ragged") g.rows[0].pop();
    else if (change === "order") g.header_spans.reverse();
    else if (change === "caption") g.caption_spans[0].sha256 = "0".repeat(64);
    else if (change === "locator") e.locator.row = 1;
    else if (change === "fraction_index") g.row_index = 1.5;
    else Object.assign(e, { scientific_acceptance: true });
    await expect(compileTablePackage(p)).rejects.toThrow();
  });

  it("requires an explicit two-field profile and verifies source/target receipt closure", async () => {
    expect(knownTableCaseCapabilities(tableCaseCap, tableActor)).toEqual(tableCaseCap);
    expect(knownTableSourceCapabilities(tableSourceCap, tableActor)).toEqual(tableSourceCap);
    expect(knownTableCaseCapabilities({ ...tableCaseCap, version: "material-field-case/1.1.0" }, tableActor)).toBeNull();
    const context = await tableContext();
    expect(await knownTableCaseContext(context, tableCaseCap, tableMaterial, "retained_result", 0, null)).toEqual(context);
    const detail = await tableDetail();
    expect(await knownTableCaseDetail(detail, tableCaseCap)).toEqual(detail);
    const revision = await tableRevision();
    expect(await knownTableSourceRevision(revision, revision.id)).toEqual(revision);
    revision.projection.table_binding.raw_row_label = "invented unit";
    expect(await knownTableSourceRevision(revision, revision.id)).toBeNull();
  });

  it("pins preview, commit and GET recovery without storing source text", async () => {
    const p = await compileTablePackage(await tablePackage()), key = "table-test:source", ref = tableExpressionRecovery(p, tableSourceCap, key);
    const preview = await tableSourceReceipt(p, key);
    expect(await knownTableExpressionReceipt(preview, tableSourceCap, ref, "preview", p)).toEqual(preview);
    const pinned = { ...ref, previewSha: preview.preview_sha256, receiptId: preview.receipt_id, receiptSha: preview.receipt_sha256, captureId: preview.capture_id, manifestCanonical: expressionCanonical(preview.expression_manifest) };
    const identity = await tableStoredSourceIdentity(pinned);
    expect(storeTableRecovery(identity)).toBe(true);
    expect(storeTableRecovery(identity)).toBe(false);
    expect(JSON.stringify(identity)).not.toContain("Mo5P");
    const saved = await tableSourceReceipt(p, key, false);
    expect(await knownTableExpressionReceipt(saved, tableSourceCap, pinned, "commit", p)).toEqual(saved);
    expect(await knownTableStoredOutcome(saved, tableActor, identity)).toBeNull();
    saved.replayed = true;
    expect(await knownTableStoredOutcome(saved, tableActor, identity)).not.toBeNull();
    expect(clearTableRecovery(identity)).toBe(true);
    expect(readTableRecovery(tableActor)).toEqual({ status: "empty" });
  });

  it("verifies a pending association through its exact target and original table cell", async () => {
    const detail = await tableDetail(), context = await tableContext();
    const field = "electronic_specific_heat_coefficient_source_value";
    const expression = await tableRevision(field, "synthetic:source", false);
    const request: TableCaseRequest = {
      version: "material-field-case-operation/1.2.0", request_key: "synthetic:table-association", operation: "association",
      payload: { target_id: detail.target.id, target_sha256: detail.target.record_sha256,
        expression_revision_id: expression.id, expression_record_sha256: expression.record_sha256,
        source_identity: { paper_id: context.closure.paper_id, work_id: context.closure.work_id },
        action: "propose", predecessor: null },
    };
    const receipt = await tableCaseReceipt(request, false, field, context, expression);
    detail.associations = [{ id: receipt.receipt_id, record_sha256: receipt.receipt_sha256,
      record_canonical_json: receipt.receipt_canonical_json, operation: "association", payload: request.payload,
      context_canonical_json: null, context_sha256: context.context_sha256, created_at: "2026-10-02T00:00:00Z",
      eligibility: { eligible: true, reason_codes: [] }, is_head: true, expression, source_identity_status: "proposed", ...tableFlags }];
    detail.association_total = detail.association_returned = 1;
    expect(await knownTableCaseDetail(detail, tableCaseCap)).toEqual(detail);
    expression.projection.value.raw_unit = "K";
    expect(await knownTableCaseDetail(detail, tableCaseCap)).toBeNull();
  });
});
