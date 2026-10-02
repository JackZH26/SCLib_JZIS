import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import publicBatch from "@/public/research-pilots/materials-source-followup-2026-10-02.json";
import { groupSourceFollowup, loadSourceFollowupBatch, sourceFollowupHref } from "@/lib/material-source-followup";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const entry = (field: string) => loadSourceFollowupBatch()!.entries.find(item => item.field === field)!;
const row = (value: unknown) => value as Record<string, unknown>;
describe("Finite source-expression follow-up", () => {
  it("preserves the actual task denominators, immutable projection checksum and all eight separate source groups", () => {
    const batch = loadSourceFollowupBatch()!;
    expect(batch).not.toBeNull();
    expect(batch.entries).toHaveLength(34);
    expect(batch.entries.filter(item => item.value !== null)).toHaveLength(31);
    expect(batch.entries.filter(item => item.belongs_to_remaining29_plan)).toHaveLength(29);
    expect(groupSourceFollowup(batch).map(group => group.entries.length)).toEqual([4, 5, 4, 4, 4, 4, 4, 5]);
    const file = readFileSync(resolve(process.cwd(), "public/research-pilots/materials-source-followup-2026-10-02.json"));
    const sha = createHash("sha256").update(file).digest("hex");
    expect(sha).toBe("c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8");
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots/materials-source-followup-2026-10-02.json.sha256"), "utf8")).toBe(`${sha}  materials-source-followup-2026-10-02.json\n`);
    expect(batch.entries.every(item => item.selected_result_association === "unestablished")).toBe(true);
  });

  it("retains the three unavailable EPC settings instead of guessing them from Tc or an abstract", () => {
    const missing = loadSourceFollowupBatch()!.entries.filter(item => item.inspection_status === "source_unavailable");
    expect(missing.map(item => item.field)).toEqual(["electron_phonon_lambda_source_value", "omega_log_source_value", "mu_star_source_parameter"]);
    expect(missing.every(item => item.value === null && item.field_locators.length === 0)).toBe(true);
    expect(row(entry("calculation_method_and_origin_statement").value).knowledge_origin).toBe("Computed");
  });

  it("keeps neighboring members, related database curves and optical conditions separate", () => {
    const magnetic = row(entry("reported_magnetic_order_and_temperature").value);
    const transition = row(entry("tm_member_transition_criterion").value);
    expect(row(magnetic.tm_source_tn).value).toBe(17);
    expect(row(transition.source_tm_tc).value).toBe(24);
    expect(transition.source_criterion_raw).toContain("χ′");
    const fraction = row(entry("meissner_measurement_method_and_conditions").value);
    expect(row(fraction.database_row155423_vols_raw)).toMatchObject({ value: 80, raw_unit: null, unit: "%" });
    expect(fraction.source80_exact_dc_or_ac_curve_assignment).toBe("unestablished");
    expect(entry("tc_applied_pressure_context").source_window.study_max_pressure_is_selected_tc_pressure).toBe(false);
    expect(entry("optical_measurement_temperature_window").source_window.these_temperatures_are_tc).toBe(false);
    expect(row(row(entry("hall_carrier_density_and_conditions").value).carrier_density_raw)).toMatchObject({ raw_value: "8 × 10²⁰", value: 8e20, unit: "cm⁻³" });
  });

  it("preserves source unit conflicts and derived-estimate assumptions, without silently repairing the source", () => {
    expect(row(entry("specific_heat_jump_over_tc").value)).toMatchObject({ raw_value: "20", raw_unit: "mJ/mol K", unit: null, parse_status: "unit_requires_review" });
    const gamma = entry("electronic_specific_heat_coefficient_model");
    expect(row(gamma.value)).toMatchObject({ value: 14, approximate: true, unit: "mJ/(mol·K²)" });
    expect(gamma.source_role).toBe("source_BCS_assumption_derived_estimate");
    expect(gamma.source_window).toEqual({ bcs_ratio: 1.43, assumed_superconducting_volume_percent: 100 });
    expect(entry("sample_anneal_conditions").source_window.specific_x016_anneal_temperature_and_duration).toBe("not_established_by_source_link");
  });

  it("rejects changed keys, values, authorities or conditions and permits official links only", () => {
    const unknown = clone(publicBatch);
    (unknown.entries[0].source_window as Record<string, unknown>).private_notes = "must not export";
    expect(loadSourceFollowupBatch(unknown)).toBeNull();
    const changed = clone(publicBatch);
    const model = changed.entries.find(item => item.field === "hc2_curve_slope_and_model")!;
    row(row(model.value).hc2_slope).value = 2.9;
    expect(loadSourceFollowupBatch(changed)).toBeNull();
    const accepted = clone(publicBatch);
    accepted.entries[0].scientific_acceptance = true;
    expect(loadSourceFollowupBatch(accepted)).toBeNull();
    const missingWindow = clone(publicBatch);
    (missingWindow.entries[0] as unknown as Record<string, unknown>).source_window = null;
    expect(loadSourceFollowupBatch(missingWindow)).toBeNull();
    expect(sourceFollowupHref("https://arxiv.org/pdf/1706.06999")).toBe("https://arxiv.org/pdf/1706.06999");
    expect(sourceFollowupHref("https://arxiv.org@untrusted.invalid/pdf/1706.06999")).toBeNull();
    expect(sourceFollowupHref("javascript:alert(1)")).toBeNull();
    expect(JSON.stringify(publicBatch)).not.toMatch(/private_notes|evidence_text|\/Users\/|\/tmp\/|raw_record|source_excerpt/);
  });
});
