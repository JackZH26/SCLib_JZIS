import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import rawBatch from "@/public/research-pilots/materials-pressure-table-sources-2026-10-02.json";
import { loadPressureTableBatch, loadPressureTableSubject, pressureTableSourceHref, pressureTableSubjectEntries, pressureTableSubjectPath } from "@/lib/material-pressure-table-sources";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const batch = loadPressureTableBatch()!;
describe("Pressure and table source metadata boundaries", () => {
  it("pins the finite 18-expression resource, sidecar and independent source subjects", () => {
    const file = readFileSync(resolve(process.cwd(), "public/research-pilots/materials-pressure-table-sources-2026-10-02.json"));
    const sha = createHash("sha256").update(file).digest("hex");
    expect(sha).toBe("788144f67d439d0a5051e3b5144c988311e5423ccfa56402beb5566744ebe284");
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots/materials-pressure-table-sources-2026-10-02.json.sha256"), "utf8")).toBe(`${sha}  materials-pressure-table-sources-2026-10-02.json\n`);
    expect(batch.entries).toHaveLength(18);
    expect(batch.sources).toHaveLength(2);
    expect(["bitecl", "mo_nominal_column_2", "mo_nominal_column_3"].map(subject => pressureTableSubjectEntries(batch, subject).length)).toEqual([6, 6, 6]);
    expect(new Set(batch.entries.map(entry => entry.expression_key)).size).toBe(18);
    expect(batch.sources.map(source => source.id)).toEqual(["private-primary:arxiv:1501.06203:pdf-raw:20261002-r1", "private-primary:arxiv:1603.02892:pdf-raw:20261002-r1"]);
    expect(batch.entries.every(entry => entry.source_id === batch.sources[entry.source_subject_id === "bitecl" ? 0 : 1].id)).toBe(true);
    expect(rawBatch).toMatchObject({ scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false, counts_are_independent_experiments: false, selected_result_association: "unestablished" });
    expect(rawBatch.entries.every(entry => entry.status === "pending" && entry.scientific_acceptance === false && entry.sample_identity_established === false && entry.phase_identity_established === false)).toBe(true);
  });
  it("keeps the main BiTc window separate from both caption criteria and the unresolved inset label", () => {
    const entries = pressureTableSubjectEntries(batch, "bitecl");
    expect(entries[0]).toMatchObject({ field_id: "tc_kelvin", window: { id: "tc:highest:15gpa" }, value: { value: 7, raw_value: "7", raw_unit: "K" } });
    expect(entries[0].conditions.map(condition => condition.field_id)).toEqual(["pressure_gpa"]);
    expect(entries[1].value).toMatchObject({ raw_value: "15", raw_unit: "GPa", value: null, unit: null, status: "unit_requires_review" });
    const captions = entries.slice(4);
    expect(captions.map(entry => entry.window.id)).toEqual(["figure2-caption:criterion:24.1gpa", "figure2-caption:criterion:50.8gpa"]);
    expect(captions.map(entry => entry.conditions.find(condition => condition.field_id === "pressure_gpa")!.value.raw_value)).toEqual(["24.1", "50.8"]);
    expect(captions.every(entry => entry.conditions[0].value.raw_value === "90% resistivity transition")).toBe(true);
    expect(rawBatch.source_label_conflict).toMatchObject({ caption_and_main_text_pressure_raw: "50.8 GPa", inset_legend_pressure_raw: "50.1 GPa", resolved: false, common_physical_pressure_established: false });
    expect(rawBatch.source_label_conflict.caption_pressure_span).not.toEqual(rawBatch.source_label_conflict.inset_legend_span);
    expect(rawBatch.sources[0]).toMatchObject({ pdf_internal_date_raw: "July 7, 2018", official_arxiv_v1_submission_date: "2015-01-25", revision_correspondence: "unresolved", current_url_is_capture_version_pinned: false });
  });
  it("preserves both nominal columns, every parenthetical value and decomposed source unit", () => {
    const columns = [pressureTableSubjectEntries(batch, "mo_nominal_column_2"), pressureTableSubjectEntries(batch, "mo_nominal_column_3")];
    expect(columns.map(entries => entries[0].subject.sample_label)).toEqual(["Mo5P0.9B2.1", "Mo5PB2"]);
    expect(columns.every(entries => entries.every(entry => entry.subject.formula === "Mo5P1.07(4)B1.93(4)"))).toBe(true);
    expect(columns.map(entries => entries.slice(0, 4).map(entry => entry.value.raw_value))).toEqual([
      ["8.7(1)", "8.9(1)", "5.9726(1)", "11.074(3)"], ["8.8(2)", "8.7(2)", "5.97303(7)", "11.076(1)"],
    ]);
    expect(columns.every(entries => entries.slice(0, 4).every(entry => entry.value.value === null && entry.value.unit === null && entry.value.status === "unit_requires_review"))).toBe(true);
    expect(columns.every(entries => entries.slice(2, 4).every(entry => entry.value.raw_unit === "A\u030a"))).toBe(true);
    expect(columns.map(entries => entries.slice(0, 5).map(entry => entry.locator.column))).toEqual([[2, 2, 2, 2, 2], [3, 3, 3, 3, 3]]);
    expect(JSON.stringify(rawBatch)).not.toContain("9.2(1)");
  });
  it("keeps Tc pressure missing and room-temperature conditions restricted to XRD fields", () => {
    const mo = batch.entries.filter(entry => entry.source_subject_id.startsWith("mo_"));
    expect(mo.filter(entry => entry.field_id === "tc_kelvin").every(entry => entry.conditions.map(condition => condition.field_id).join(",") === "method_statement,criterion_statement")).toBe(true);
    expect(mo.filter(entry => entry.field_id.startsWith("lattice_") || entry.field_id === "structure_statement").every(entry => entry.conditions[0].value.raw_value === "room temperature" && entry.window.id.endsWith("room-temperature-xrd"))).toBe(true);
    expect(mo.filter(entry => entry.field_id === "tc_kelvin").map(entry => entry.conditions[1].value.raw_value)).toEqual(["resistivity reaches zero", "onset of\ndiamagnetism", "resistivity reaches zero", "onset of\ndiamagnetism"]);
  });
  it("rejects authority changes, invented values, hidden keys, reordered source subjects and foreign links", () => {
    const added = clone(rawBatch); (added.entries[0] as unknown as Record<string, unknown>).private_note = "must not export";
    const invented = clone(rawBatch); invented.entries[6].value.value = 8.7;
    const accepted = clone(rawBatch); accepted.entries[0].scientific_acceptance = true;
    const reordered = clone(rawBatch); reordered.entries.reverse();
    [added, invented, accepted, reordered].forEach(value => expect(loadPressureTableBatch(value)).toBeNull());
    expect(pressureTableSourceHref("https://arxiv.org/pdf/1501.06203", 2)).toBe("https://arxiv.org/pdf/1501.06203#page=2");
    ["https://arxiv.org@untrusted.invalid/pdf/1501.06203", "javascript:alert(1)", "https://arxiv.org/pdf/9999.99999", "https://arxiv.org:4433/pdf/1501.06203"].forEach(value => expect(pressureTableSourceHref(value)).toBeNull());
    expect(pressureTableSourceHref("https://arxiv.org/pdf/1501.06203", 0)).toBeNull();
  });
  it("does not redistribute source fulltext, package encodings or private filesystem paths", () => {
    expect(JSON.stringify(rawBatch)).not.toMatch(/source_text_base64|retained_text|source_excerpt|\/Users\/|\/private\/|\/tmp\/|password|access_token/);
    expect(rawBatch.sources.every(source => /^[a-f0-9]{64}$/.test(source.parent_pdf_sha256) && /^[a-f0-9]{64}$/.test(source.source_content_sha256))).toBe(true);
    expect(rawBatch.entries.every(entry => entry.field_spans.value_spans.length === 1 && entry.field_spans.value_spans[0].end > entry.field_spans.value_spans[0].start)).toBe(true);
  });
  it("pins three readable six-entry subject resources to their exact immutable whole-batch entries", () => {
    const resources = [
      ["bitecl", "materials-pressure-table-bitecl-2026-10-02.json", "01b164002ff2e092dd7f52cbba095acf3ae31322b97d25346b4f211d7cb5f5b3"],
      ["mo_nominal_column_2", "materials-pressure-table-mo-column-2-2026-10-02.json", "2e3652462a9ae3e5610b24cc86dbedad237423ab8d0f61234e9589468c1db149"],
      ["mo_nominal_column_3", "materials-pressure-table-mo-column-3-2026-10-02.json", "93fc3388cc32ab05c0a1e985d917aff256b1c6ba5eaf337ade209dceae3eaa9d"],
    ];
    for (const [subjectId, fileName, pin] of resources) {
      const bytes = readFileSync(resolve(process.cwd(), `public/research-pilots/${fileName}`));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(pin);
      const subset = JSON.parse(bytes.toString("utf8"));
      expect(loadPressureTableSubject(subjectId)).toEqual(subset);
      expect(loadPressureTableSubject(subjectId, subset)).toEqual(subset);
      expect(subset.entries).toEqual(pressureTableSubjectEntries(batch, subjectId));
      expect(subset.entries).toHaveLength(6); expect(subset.sources).toHaveLength(1);
      expect(subset.sources).toEqual(batch.sources.filter(source => source.id === subset.entries[0].source_id));
      expect(subset).toMatchObject({ original_batch_sha256: "788144f67d439d0a5051e3b5144c988311e5423ccfa56402beb5566744ebe284", status: "pending", selected_result_association: "unestablished", scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false, counts_are_independent_experiments: false, database_changed: false });
      expect(pressureTableSubjectPath(subjectId)).toBe(`/research-pilots/${fileName}`);
      expect(subset.source_label_conflict).toEqual(subjectId === "bitecl" ? batch.source_label_conflict : undefined);
      expect(JSON.stringify(subset)).not.toMatch(/source_text_base64|retained_text|source_excerpt|\/Users\/|\/private\/|\/tmp\/|password|access_token/);
    }
  });
  it("rejects crossed subject files, altered original binding, approvals and unsupported subjects", () => {
    const original = clone(loadPressureTableSubject("mo_nominal_column_2")!);
    const alias = clone(original), accepted = clone(original);
    (alias.entries as { source_id: string }[])[0].source_id = "public-alias";
    accepted.ml_training_approved = true;
    expect(loadPressureTableSubject("mo_nominal_column_2", alias)).toBeNull();
    expect(loadPressureTableSubject("mo_nominal_column_2", accepted)).toBeNull();
    expect(loadPressureTableSubject("mo_nominal_column_3", original)).toBeNull();
    expect(loadPressureTableSubject("unknown")).toBeNull();
    expect(pressureTableSubjectPath("unknown")).toBeNull();
    expect(pressureTableSubjectPath("__proto__")).toBeNull();
  });
});
