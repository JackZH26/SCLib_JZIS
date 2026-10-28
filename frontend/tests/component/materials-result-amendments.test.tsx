import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialsAmendmentReview } from "@/components/MaterialsAmendmentReview";
import { materialsProposalAmendment, materialsProposalAmendments } from "@/lib/api";
import { proposalAmendment, type AmendmentDetail, type Body } from "@/lib/materials-proposal-review";
import { syntheticResultAmendments } from "../helpers/materials-result-amendment-test-data";
import type { AmendmentCapture } from "../helpers/materials-amendment-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialsProposalAmendment: vi.fn(), materialsProposalAmendments: vi.fn() }));
const c = syntheticResultAmendments.cases[0], detail = c.pages[0], summary = c.amendments.listing.items[0], dto = c.amendments.details[summary.id];
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const actual: AmendmentCapture | null = process.env.SCLIB_RESULT_AMENDMENT_REPLAY ? JSON.parse(readFileSync(process.env.SCLIB_RESULT_AMENDMENT_REPLAY, "utf8")) : null;
const fixtures = [...syntheticResultAmendments.cases, ...(actual?.cases ?? [])].flatMap(candidate => candidate.amendments.listing.items.flatMap(item =>
  item.selected_result_ids.map(id => ({ id, candidate, summary: item, dto: candidate.amendments.details[item.id],
    detail: candidate.pages.find(p => p.results.some(r => r.local_id === id))!, original: candidate.pages.flatMap(p => p.results).find(r => r.local_id === id)! }))));
const native15 = process.env.SCLIB_NATIVE15_REVIEW_CAPTURE ? JSON.parse(readFileSync(process.env.SCLIB_NATIVE15_REVIEW_CAPTURE, "utf8")) : null;
beforeEach(() => vi.clearAllMocks());

describe("Generic private result amendments", () => {
  it("preserves native /15 definitions and rejects a downgraded semantics wrapper", () => {
    const value = copy(dto);
    value.amendment.graph.schema_version = "materials-ner/15";
    Object.assign(value.amendment.validation, { validator_version: "materials-ner-validation/1.29.0", registry_version: "materials-quantities/4.0.0" });
    for (const row of value.mapping.records) (row.result_semantics as Body).version = "materials-result-semantics/2";
    expect(proposalAmendment(value, detail.run, summary)).not.toBeNull();
    (value.mapping.records[0].result_semantics as Body).version = "materials-result-semantics/1";
    expect(proposalAmendment(value, detail.run, summary)).toBeNull();
  });

  it.skipIf(!native15)("reads and displays the /15 database capture without value or role changes", async () => {
    const parsed = proposalAmendment(native15.dto, native15.detail.run, native15.summary);
    expect(parsed).not.toBeNull();
    const conditions = parsed!.amendment.graph.states[0].conditions as Body[];
    expect(conditions.map(c => [c.kind, c.role])).toEqual([["twist_angle", "sample_geometry"], ["reported_displacement_field", "measurement"]]);
    expect((conditions[0].quantity as Body).value).toBe(-1.27);
    expect((conditions[1].quantity as Body).unit).toBe("V/nm");
    expect((parsed!.amendment.graph.results[0].definition as Body).criterion).toBe("linear_fit_intersection");
    expect(parsed!.mapping.records[0].target_table).toBeNull();
    vi.mocked(materialsProposalAmendments).mockResolvedValue({ ...c.amendments.listing, items: [native15.summary] });
    vi.mocked(materialsProposalAmendment).mockResolvedValue(native15.dto);
    const refusal = vi.fn();
    render(<MaterialsAmendmentReview detail={native15.detail} original={native15.detail.results[0]} onRefusal={refusal} />);
    fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Inspect amendment/ }));
    const reading = within(await screen.findByTestId("amendment-reading"));
    const shownConditions = reading.getByRole("region", { name: "Conditions", exact: true });
    for (const wording of ["twist_angle", "Role: sample geometry", "reported_displacement_field", "Unit: V/nm", "+0.61 V/nm"]) {
      expect(shownConditions.textContent).toContain(wording);
    }
    expect(reading.getByRole("region", { name: "Criterion", exact: true }).textContent).toContain("linear_fit_intersection");
    expect(reading.queryByRole("button", { name: "Find stored candidates" })).toBeNull();
    expect(refusal).not.toHaveBeenCalled();
  });
  it.each(fixtures)("shows native quantity, findings and pending mapping for $id", async f => {
    expect(proposalAmendment(f.dto, f.detail.run, f.summary)).not.toBeNull();
    vi.mocked(materialsProposalAmendments).mockResolvedValue(f.candidate.amendments.listing);
    vi.mocked(materialsProposalAmendment).mockResolvedValue(f.dto);
    const refusal = vi.fn();render(<MaterialsAmendmentReview detail={f.detail} original={f.original} onRefusal={refusal} />);
    fireEvent.click(screen.getByRole("button", { name: "Load source-backed amendments" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Inspect amendment/ }));
    const reading = within(await screen.findByTestId("amendment-reading"));
    expect(reading.getByText(/Canonical quantity mapping is pending/)).toBeVisible();
    const result = f.dto.amendment.graph.results.find(r => r.id === f.id)!;
    expect(reading.getByRole("region", { name: "Quantity kind", exact: true }).textContent).toContain(result.quantity_kind);
    expect(reading.getByRole("region", { name: "Unit", exact: true }).textContent).toContain((result.quantity as Body).unit);
    const findings = reading.getByRole("region", { name: "Source findings pending reassessment" });
    expect(within(findings).getAllByRole("listitem")).toHaveLength(f.dto.amendment.source_review!.findings.length);
    expect(within(findings).getAllByRole("heading", { name: "Missing from draft" })).toHaveLength(f.dto.amendment.source_review!.findings.filter(x => x.kind === "source_completeness").length);
    expect(reading.queryByRole("button", { name: "Find stored candidates" })).toBeNull();
    expect(reading.queryByRole("button", { name: /approve|publish|promote/i })).toBeNull();
    expect(refusal).not.toHaveBeenCalled();
  });

  it.each([
    (d: AmendmentDetail) => { d.amendment.graph.schema_version = "materials-ner/15"; },
    (d: AmendmentDetail) => { d.amendment.graph.schema_version = "materials-ner/14"; (d.amendment.validation as Body).registry_version = "materials-quantities/2.0.0"; },
    (d: AmendmentDetail) => { d.amendment.graph.schema_version = "materials-ner/14"; (d.amendment.validation as Body).validator_version = "materials-ner-validation/1.24.0"; },
    (d: AmendmentDetail) => { d.mapping.records[0].quantity_kind = "tc"; },
    (d: AmendmentDetail) => { (d.mapping.records[0].source_quantity as Body).unit = "K"; },
    (d: AmendmentDetail) => { d.mapping.records[0].dependencies = [{ result_id: "other", relation: "derived_from" }]; },
    (d: AmendmentDetail) => { d.mapping.records[0].normalized = { invented: 123 }; },
    (d: AmendmentDetail) => { d.mapping.records[0].target_table = "material_claims"; },
    (d: AmendmentDetail) => { d.mapping.records[0].target_id = "invented"; },
    (d: AmendmentDetail) => { d.mapping.records[0].result_pointer = "/graph/results/1"; },
    (d: AmendmentDetail) => { d.mapping.records[0].holds = []; },
    (d: AmendmentDetail) => { (d.amendment.source_review as unknown as Body).independent_review = true; },
    (d: AmendmentDetail) => { d.amendment.source_review!.findings[0].anchors[0].start_char += 1; },
    (d: AmendmentDetail) => { d.amendment.source_review!.findings[0].path = "/states/99"; },
    (d: AmendmentDetail) => { d.amendment.source_review!.findings[1].path = "/states/0"; },
  ])("refuses quantity coercion, misplaced evidence and asserted authority %#", mutate => {
    const changed = copy(dto);mutate(changed);
    expect(proposalAmendment(changed, detail.run, summary)).toBeNull();
  });
});
