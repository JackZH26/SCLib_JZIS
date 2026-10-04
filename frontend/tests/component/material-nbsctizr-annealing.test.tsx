import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  loadNbsctizrAnnealing, nbsctizrAnnealingDownloadPath, nbsctizrAnnealingReading,
  nbsctizrAnnealingRoute, nbsctizrAnnealingSnapshotSha256, nbsctizrSourceHref,
} from "@/lib/material-nbsctizr-annealing";

afterEach(() => { vi.unstubAllEnvs(); });

describe("NbScTiZr source-qualified annealing comparison", () => {
  it("pins 210 reported source cells and nine unlisted cells without private text or canonical quantities", () => {
    const name = "materials-nbsctizr-annealing-2026-10-04.json";
    const raw = readFileSync(`public/research-pilots/${name}`);
    expect(createHash("sha256").update(raw).digest("hex")).toBe(nbsctizrAnnealingSnapshotSha256);
    expect(readFileSync(`public/research-pilots/${name}.sha256`, "utf8")).toBe(`${nbsctizrAnnealingSnapshotSha256}  ${name}\n`);
    expect(nbsctizrAnnealingDownloadPath).toContain(`/research-pilots/${name}`);
    const data = loadNbsctizrAnnealing()!;
    expect(data.authority).toEqual({ canonical_updates: 0, scientific_acceptance: false, formal_human_review: false,
      ml_training_approved: false, calculation_executed: false, selected_result_sample_state_phase_association: "unestablished",
      cross_publication_physical_sample_equivalence: "unestablished" });
    expect(data.source_windows).toHaveLength(19);
    expect(data.counts.reported_value_cells).toBe(210);
    expect(data.counts.source_blank_cells).toBe(9);
    const cells = [data.phase_table, data.phase_table_2023, data.parameter_table, data.gap_fits, data.tc_2023]
      .flatMap(table => table.rows.flatMap(row => Object.values(row.cells)));
    expect(cells.filter(cell => cell.raw_value !== null)).toHaveLength(210);
    expect(cells.filter(cell => cell.raw_value === null)).toHaveLength(9);
    for (const cell of cells) expect(cell.normalized_value).toBeNull();
    expect(data.counts.independent_experiment_count_established).toBe(false);
    expect(raw.toString()).not.toMatch(/\/Users\/|\/private\/|"full_text"|"material_id"|"result_id"|"source_text"/);
  });

  it("retains distinct 2023 and 2024 transition sequences and processing groups", () => {
    const data = loadNbsctizrAnnealing()!;
    expect(data.samples.map(sample => [sample.id, sample.processing_temperature_value, sample.hold_duration_value]))
      .toEqual([["as-cast", null, null], ["400-c", "400", "4"], ["600-c", "600", "4"], ["800-c", "800", "4"], ["1000-c", "1000", "4"]]);
    expect(data.samples.every(sample => sample.processing_temperature_is_measurement_temperature === false)).toBe(true);
    expect(data.samples.find(sample => sample.id === "600-c")?.sample_listed_2023).toBe(false);
    expect(data.tc_2023.rows.map(row => [row.sample_id, row.cells.tc_k.raw_value]))
      .toEqual([["as-cast", "7.9"], ["400-c", "8.4"], ["800-c", "9.0"], ["1000-c", "8.7"]]);
    expect(data.parameter_table.rows.map(row => row.cells.tc_k.raw_value)).toEqual(["8.11", "8.71", "9.36", "9.13", "9.03"]);
    expect(data.parameter_table.tc_criterion_attribution).toBe("refined_hc2_analysis_context_without_calorimetric_midpoint_assignment");
    expect(data.methods.find(method => method.id === "2024-m-and-rho")?.summary).toContain("refined Tc from upper-critical-field analysis");
    expect(data.methods.find(method => method.id === "2024-m-and-rho")?.locator_ids).toContain("2024-refined-tc-analysis");
    expect(data.methods.find(method => method.id === "2023-tc-definition")?.summary).toContain("5 Oe at 800 Hz over 3–20 K");
  });

  it("keeps phase chemistry, SEM volume fraction and source-derived VEC independent of superconducting fractions", () => {
    const data = loadNbsctizrAnnealing()!;
    expect(data.phase_table.rows).toHaveLength(10);
    expect(data.phase_table_2023.rows).toHaveLength(8);
    expect(data.phase_table.composition_unit).toBe("not_printed_in_table");
    expect(data.phase_table.rows[1].cells.Sc.raw_value).toBe("30(1)");
    expect(data.phase_table.rows[1].cells.Sc.raw_unit).toBeNull();
    expect(data.phase_table.rows[0].cells.lattice_c.raw_value).toBeNull();
    expect(data.phase_table.rows[0].cells.lattice_c.status).toBe("not_listed_in_source_row");
    expect(data.phase_table.rows[1].cells.lattice_c.raw_value).toBe("5.152(3)");
    expect(data.phase_table.rows[1].cells.lattice_c.raw_unit).toBe("Å");
    expect(data.phase_table_2023.rows.map(row => row.cells.volume_percent.raw_value)).toEqual(["57", "43", "57", "43", "50", "50", "50", "50"]);
    expect(data.phase_table_2023.rows.map(row => row.cells.vec.raw_value)).toEqual(["4.04", "3.91", "4.06", "3.90", "4.18", "3.74", "4.35", "3.47"]);
    expect(data.phase_table.composition_source_attribution).toContain("preceding study [46]");
    expect(data.phase_table.composition_source_attribution).toContain("600 °C is not listed");
    expect(data.parameter_table.specific_heat_phase_scope).toContain("Both bcc and hcp");
    expect(data.methods.find(method => method.id === "2024-specific-heat")?.locator_ids).toContain("2024-normal-state-specific-heat");
    expect(data.methods.find(method => method.id === "2023-phase-volume")?.summary).toContain("not superconducting volume fractions");
  });

  it("distinguishes measured probes, WHH/GL derived roles and critical-field units", () => {
    const data = loadNbsctizrAnnealing()!;
    expect(data.parameter_table.columns).toHaveLength(15);
    for (const row of data.parameter_table.rows) {
      expect(row.cells.hc1_zero_mt.raw_unit).toBe("mT");
      expect(row.cells.hc2_m_zero_t.raw_unit).toBe("T");
      expect(row.cells.hc2_m_zero_t.role).toContain("magnetization");
      expect(row.cells.hc2_rho_zero_t.role).toContain("resistivity");
      expect(row.cells.lambda_m_zero_nm.raw_unit).toBe("nm");
      expect(row.cells.lambda_m_zero_nm.role).toBe("gl_penetration_depth_derived_from_hc1_and_xi_m");
      expect(row.cells.lambda_rho_zero_nm.role).toBe("gl_penetration_depth_derived_from_hc1_and_xi_rho");
      expect(row.cells.gamma_el.role).toContain("bcc_and_hcp");
    }
    expect(data.parameter_table.rows[4].cells.hc1_zero_mt.raw_value).toBe("4.46");
    expect(data.parameter_table.rows[4].cells.hc2_m_zero_t.raw_value).toBe("14.3");
    expect(data.parameter_table.rows[3].cells.hc2_rho_zero_t.raw_value).toBe("15.0");
    expect(data.parameter_table.rows[0].cells.hardness_hv.raw_value).toBe("336(1)");
    expect(data.methods.find(method => method.id === "2024-gl-derived")?.summary).toContain("not direct length measurements or electron–phonon coupling");
  });

  it("preserves four source calorimetric fits and ratio estimates without recomputing with the Table 2 Tc", () => {
    const data = loadNbsctizrAnnealing()!;
    expect(data.gap_fits.rows.map(row => row.sample_id)).toEqual(["400-c", "600-c", "800-c", "1000-c"]);
    expect(data.gap_fits.rows.map(row => row.cells.gap_zero_mev.raw_value)).toEqual(["1.16", "1.73", "1.84", "1.66"]);
    expect(data.gap_fits.rows.map(row => row.cells.gamma_residual.raw_value)).toEqual(["2.8", "2.7", "2.8", "2.6"]);
    expect(data.gap_fits.rows.map(row => row.cells.gap_ratio.raw_value)).toEqual(["3.22", "4.43", "4.85", "4.56"]);
    expect(data.gap_fits.rows.map(row => row.cells.normalized_jump.raw_value)).toEqual(["1.63", "2.83", "3.97", "2.68"]);
    expect(data.gap_fits.as_cast_status).toBe("not_established_in_source_analysis");
    expect(data.gap_fits.as_cast_reason).toContain("broadening");
    expect(data.methods.find(method => method.id === "2024-specific-heat")?.summary).toContain("does not assign midpoint to the whole Table 2 Tc row");
  });

  it("links only exact captured PDF editions and in-range pages", () => {
    expect(nbsctizrSourceHref("2023", 4)).toBe("https://arxiv.org/pdf/2311.00195v1#page=4");
    expect(nbsctizrSourceHref("2024", 9)).toBe("https://arxiv.org/pdf/2406.19553v1#page=9");
    expect(nbsctizrSourceHref("2023")).toBe("https://arxiv.org/pdf/2311.00195v1");
    for (const page of [0, -1, 1.5, 19, Infinity, NaN]) expect(nbsctizrSourceHref("2023", page)).toBeNull();
    expect(nbsctizrSourceHref("2024", 29)).toBeNull();
    expect(nbsctizrSourceHref("https://arxiv.org/pdf/2311.00195v2")).toBeNull();
  });

  it("matches finite material/result/source tuples without asserting source sample identity", () => {
    const result = { result_id: "legacy-result:4dcee198b26f5c2315199a06cce5c2b2c55ea83eb46e71a71a1b88e315379089", source: { paper_id: "arxiv:2311.00195" } };
    expect(nbsctizrAnnealingReading("mat:nbsctizr", result)?.href).toBe(nbsctizrAnnealingRoute);
    expect(nbsctizrAnnealingReading("mat:nbsctizr", result)?.note).toContain("does not assign the selected result");
    expect(nbsctizrAnnealingReading("mat:nbsctizr", { ...result, source: { paper_id: "arxiv:2406.19553" } })).toBeNull();
    expect(nbsctizrAnnealingReading("mat:nbsctizr", { ...result, source: { paper_id: "__proto__" } })).toBeNull();
    expect(nbsctizrAnnealingReading("mat:other", result)).toBeNull();
    expect(nbsctizrAnnealingReading("mat:nbsctizr", { ...result, result_id: "legacy-result:new" })).toBeNull();
    expect(nbsctizrAnnealingReading("mat:nbsctizr", { ...result, source: { paper_id: "arxiv:2311.00195v2" } })).toBeNull();
    expect(nbsctizrAnnealingReading("mat:nbsctizr", null)).toBeNull();
    const structural = { result_id: "legacy-result:ed551e132e4a3fb2a0b6ce12b57d1acfef815e250492f81cee70606334d48fdf", source: { paper_id: "arxiv:2406.19553" } };
    expect(nbsctizrAnnealingReading("mat:nbsctizr", structural)?.href).toBe(nbsctizrAnnealingRoute);
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    expect(nbsctizrAnnealingReading("mat:nbsctizr", result)?.href).toBe("/sclib-preview" + nbsctizrAnnealingRoute);
  });

  it("rejects altered values, physical roles, source editions, normalized quantities, source windows and approvals", () => {
    const edits = [
      (data: any) => { data.samples[0].processing_temperature_value = "0"; },
      (data: any) => { data.samples[2].sample_listed_2023 = true; },
      (data: any) => { data.parameter_table.rows[4].cells.hc1_zero_mt.raw_unit = "T"; },
      (data: any) => { data.parameter_table.rows[0].cells.lambda_m_zero_nm.role = "electron_phonon_lambda"; },
      (data: any) => { data.gap_fits.rows[0].cells.gap_ratio.raw_value = "3.09"; },
      (data: any) => { data.phase_table_2023.rows[0].cells.volume_percent.role = "meissner_fraction"; },
      (data: any) => { data.tc_2023.rows[0].cells.tc_k.normalized_value = 7.9; },
      (data: any) => { data.parameter_table.tc_criterion_attribution = "specific_heat_midpoint"; },
      (data: any) => { data.sources[0].edition = "2311.00195v2"; },
      (data: any) => { data.source_windows[0].char_end += 1; },
      (data: any) => { data.authority.scientific_acceptance = true; },
      (data: any) => { data.authority.cross_publication_physical_sample_equivalence = "established"; },
      (data: any) => { data.full_text = "unreviewed original manuscript"; },
    ];
    for (const edit of edits) { const data = loadNbsctizrAnnealing()!; edit(data); expect(loadNbsctizrAnnealing(data)).toBeNull(); }
    expect(loadNbsctizrAnnealing(null)).toBeNull();
    expect(loadNbsctizrAnnealing()!.samples[0].processing_temperature_value).toBeNull();
  });
});
