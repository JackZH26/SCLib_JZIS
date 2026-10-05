import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compareQeMeshSmearing } from "@/lib/discovery-qe-joint-refinement";
import { DiscoveryQeConvergence } from "@/components/DiscoveryQeConvergence";
import { readQeNativeOutput, type QeResultReading } from "@/lib/discovery-qe-result";
import type { PreparedQe } from "@/lib/discovery-qe-input";

const sha = (text: string) => createHash("sha256").update(text).digest("hex");
function sign(report: QeResultReading["report"]): QeResultReading {
  const json = JSON.stringify(report, null, 2) + "\n", sha256 = sha(json);
  return { report, json, sha256, filename: `synthetic-joint-${sha256.slice(0, 16)}.json` };
}
// These counterfactual energies exercise grid arithmetic, not scientific evidence.
function grid() {
  return [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(width => {
    const report = JSON.parse(readFileSync("tests/fixtures/qe-convergence/k2-reading.json", "utf8"));
    report.settings.mesh = [k, k, k]; report.settings.degauss = width;
    report.observations.total_energy.value = -30 + 1 / k ** 4 + width ** 2;
    report.convergence.scf_error_hartree = 3e-9;
    return sign(report);
  }));
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Joint mesh and smearing comparison", () => {
  it("re-reads six additional real native executions and combines them with the original three", async () => {
    const folder = "tests/fixtures/qe-joint-refinement/";
    const capture = JSON.parse(readFileSync(folder + "capture.json", "utf8"));
    for (const file of capture.files) {
      const bytes = readFileSync(folder + file.file);
      expect(bytes.length).toBe(file.bytes); expect(createHash("sha256").update(bytes).digest("hex")).toBe(file.sha256);
    }
    const readings = [2, 4, 6].flatMap(k => [0.04, 0.02, 0.01].map(width => {
      const stem = width === 0.02 ? `tests/fixtures/qe-convergence/k${k}-` : `${folder}k${k}-s${width}-`;
      const read = (name: string) => readFileSync(stem + name, "utf8");
      const manifest = JSON.parse(read("manifest.json"));
      expect(sha(read("input.in"))).toBe(manifest.files.execution.sha256);
      const parsed = readQeNativeOutput({ manifest } as PreparedQe, "execution", read("data-file-schema.xml"), read("pw.out"));
      const report = JSON.parse(read("reading.json"));
      expect(report).toMatchObject(parsed);
      expect(parsed.status).toBe("scf_reported_converged");
      return sign(report);
    }));
    const report = (await compareQeMeshSmearing(readings, 0.0001)).report;
    expect(report.coverage).toMatchObject({ supplied: 9, expected: 9, missing: [] });
    expect(report.sampled_window.assessment).toBe("sampled_window_outside_tolerance");
    expect(report.sampled_window.energy_range_hartree_per_atom).toBeCloseTo(0.016965894419036214, 13);
    expect(report.smallest_three_width_range_at_finest_mesh_hartree_per_atom).toBeLessThan(0.0001);
  });

  it("sorts the exact Cartesian grid, uses nine native etot values, and preserves the finite-window scope", async () => {
    const input = grid(), study = await compareQeMeshSmearing([...input].reverse(), 0.0001);
    expect(study).toEqual(await compareQeMeshSmearing(input, 0.0001));
    expect(study.report.coverage).toMatchObject({ supplied: 9, expected: 9, missing: [] });
    expect(study.report.axes).toMatchObject({ meshes: [[2, 2, 2], [4, 4, 4], [6, 6, 6]], smearing_widths_ry: [0.04, 0.02, 0.01] });
    expect(study.report.sampled_window.energy_range_hartree_per_atom).toBeCloseTo((1 / 16 - 1 / 1296 + 0.04 ** 2 - 0.01 ** 2) / 3, 13);
    expect(study.report.mesh_sensitivity_by_width.every(row => Math.abs(row.energy_range_hartree_per_atom! - (1 / 16 - 1 / 1296) / 3) < 1e-13)).toBe(true);
    expect(study.report.smallest_three_width_range_at_finest_mesh_hartree_per_atom).toBeCloseTo(0.0005, 13);
    expect(study.report.sampled_window.assessment).toBe("sampled_window_outside_tolerance");
    expect(study.report.scope).toMatchObject({ joint_numerical_convergence_established: false, zero_smearing_extrapolated: false, execution_authenticated: false, scientific_acceptance: false });
    expect(study.sha256).toBe(sha(study.json));
    expect(study.report.readings).toHaveLength(9);
  });

  it("retains missing cells and withholds joint statistics instead of averaging or filling zero", async () => {
    const input = grid(); input.splice(4, 1);
    const report = (await compareQeMeshSmearing(input, 1)).report;
    expect(report.cells[4]).toMatchObject({ energy_hartree_per_cell: null, reading_sha256: null, scf_error_hartree_per_atom: null });
    expect(report.coverage.missing).toEqual([{ mesh: [4, 4, 4], smearing_width_ry: 0.02 }]);
    expect(report.sampled_window).toMatchObject({ assessment: "incomplete_grid", energy_range_hartree_per_atom: null });
    expect(report.mesh_sensitivity_by_width[1].energy_range_hartree_per_atom).toBeNull();
    const small = grid().filter(r => r.report.settings.mesh[0] !== 6 && r.report.settings.degauss !== 0.01);
    expect((await compareQeMeshSmearing(small, 1)).report.sampled_window.assessment).toBe("insufficient_axis_samples");
  });

  it("gives SCF precision precedence and never applies a default scientific tolerance", async () => {
    expect((await compareQeMeshSmearing(grid(), 1)).report.sampled_window.assessment).toBe("sampled_window_within_tolerance");
    expect((await compareQeMeshSmearing(grid(), 1e-9)).report.sampled_window.assessment).toBe("scf_precision_insufficient");
    for (const tolerance of [NaN, Infinity, 0, -1]) await expect(compareQeMeshSmearing(grid(), tolerance)).rejects.toThrow(/positive energy tolerance/);
  });

  it("selects the finest three meshes and smallest three widths from a complete 4 by 4 grid", async () => {
    const input = [2, 4, 6, 8].flatMap(k => [0.08, 0.04, 0.02, 0.01].map(width => {
      const report = structuredClone(grid()[0].report);
      report.settings.mesh = [k, k, k]; report.settings.degauss = width;
      report.observations.total_energy!.value = k === 2 || width === 0.08 ? -20 : -30;
      return sign(report);
    }));
    const result = await compareQeMeshSmearing(input, 0.0001);
    expect(result.report.coverage).toMatchObject({ supplied: 16, expected: 16, missing: [] });
    expect(result.report.sampled_window).toMatchObject({ meshes: [[4, 4, 4], [6, 6, 6], [8, 8, 8]], smearing_widths_ry: [0.04, 0.02, 0.01], energy_range_hartree_per_atom: 0 });
    expect(result.report.cells[0].energy_hartree_per_cell).toBe(-20);
    input.shift();
    expect((await compareQeMeshSmearing(input, 1)).report.sampled_window.assessment).toBe("incomplete_grid");
  });

  it.each([
    ["candidate", (r: QeResultReading["report"]) => { r.candidate_id += "different"; }, /same source-linked/],
    ["UPF", (r: QeResultReading["report"]) => { r.pseudopotentials[0].sha256 = "0".repeat(64); }, /exact UPF/],
    ["cutoff", (r: QeResultReading["report"]) => { r.settings.ecutrho += 10; }, /Only mesh/],
    ["smearing method", (r: QeResultReading["report"]) => { r.settings.smearing = "fd"; }, /Only mesh/],
    ["shift", (r: QeResultReading["report"]) => { r.settings.shifts = [1, 1, 1]; }, /Only mesh/],
    ["charge", (r: QeResultReading["report"]) => { r.settings.charge = 1; }, /Only mesh/],
    ["engine", (r: QeResultReading["report"]) => { r.engine.version = "other"; }, /same supported engine/],
    ["magnetic run", (r: QeResultReading["report"]) => { r.settings.nspin = 2; }, /spin-unpolarized/],
    ["nonconvergence", (r: QeResultReading["report"]) => { r.status = "scf_not_converged"; }, /electronically converged/],
    ["initialization", (r: QeResultReading["report"]) => { r.input_kind = "initialization"; }, /fixed-geometry/],
    ["invalid inventory", (r: QeResultReading["report"]) => { r.composition.Al = -1; }, /inventory/],
  ] as const)("rejects a changed %s", async (_, change, message) => {
    const input = grid(); change(input[4].report); input[4] = sign(input[4].report);
    await expect(compareQeMeshSmearing(input, 0.01)).rejects.toThrow(message);
  });

  it("rejects duplicate cells, nonmonotonic meshes, one-dimensional input and excess input", async () => {
    await expect(compareQeMeshSmearing([...grid(), grid()[0]], 1)).rejects.toThrow(/Duplicate/);
    const input = grid(); input[4].report.settings.mesh = [1, 8, 8]; input[4] = sign(input[4].report);
    await expect(compareQeMeshSmearing(input, 1)).rejects.toThrow(/every direction/);
    await expect(compareQeMeshSmearing(grid().slice(0, 3), 1)).rejects.toThrow(/at least two/);
    await expect(compareQeMeshSmearing([...grid(), ...grid()], 1)).rejects.toThrow(/3 to 16/);
  });

  it("rejects stale bytes and snapshots before awaiting a digest", async () => {
    const input = grid(); input[0].report.observations.total_energy!.value = 0;
    await expect(compareQeMeshSmearing(input, 1)).rejects.toThrow(/has changed/);
    const fresh = grid(), pending = compareQeMeshSmearing(fresh, 1);
    fresh[0].report.observations.total_energy!.value = 0;
    expect((await pending).report.cells[0].energy_hartree_per_cell).toBeLessThan(-29);
  });
});

describe("Joint study interaction", () => {
  it("switches modes without losing readings, shows missing cells, exports, and invalidates stale results", async () => {
    const input = grid(); input.splice(4, 1);
    const view = render(<DiscoveryQeConvergence current={null} />);
    for (const reading of input) { view.rerender(<DiscoveryQeConvergence current={reading} />); fireEvent.click(screen.getByRole("button", { name: "Add current reading" })); }
    fireEvent.change(screen.getByLabelText("Study mode"), { target: { value: "joint" } });
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.0001" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare readings" }));
    await screen.findByRole("heading", { name: "Some mesh–smearing combinations are missing" });
    expect(screen.getByText("Not calculated")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scrollable mesh and smearing energy grid" })).toHaveAttribute("tabindex", "0");
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", { createObjectURL: vi.fn(blob => { blobs.push(blob); return "blob:joint"; }), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download mesh–smearing study" }));
    fireEvent.click(screen.getByRole("button", { name: "Download study checksum" }));
    expect(blobs).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Study mode"), { target: { value: "single" } });
    expect(screen.queryByRole("button", { name: "Download mesh–smearing study" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scrollable numerical refinement readings" })).toBeInTheDocument();
    expect(view.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("does not restore a joint result after clearing during a digest", async () => {
    const view = render(<DiscoveryQeConvergence current={null} />);
    for (const reading of grid()) { view.rerender(<DiscoveryQeConvergence current={reading} />); fireEvent.click(screen.getByRole("button", { name: "Add current reading" })); }
    let release: () => void = () => {};
    const digest = vi.fn().mockImplementationOnce(async (algorithm, bytes) => { await new Promise<void>(resolve => { release = resolve; }); return webcrypto.subtle.digest(algorithm, bytes); }).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    fireEvent.change(screen.getByLabelText("Study mode"), { target: { value: "joint" } });
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.01" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare readings" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear study" }));
    await act(async () => { release(); });
    expect(screen.queryByRole("region", { name: "Scrollable mesh and smearing energy grid" })).not.toBeInTheDocument();
  });
});
