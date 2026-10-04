import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compareQeReadings } from "@/lib/discovery-qe-convergence";
import { readQeNativeOutput, type QeResultReading } from "@/lib/discovery-qe-result";
import type { PreparedQe } from "@/lib/discovery-qe-input";
import { DiscoveryQeConvergence } from "@/components/DiscoveryQeConvergence";

const source = (name: string) => readFileSync(`tests/fixtures/qe-convergence/${name}`, "utf8");
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const signed = (report: QeResultReading["report"]): QeResultReading => {
  const json = JSON.stringify(report, null, 2) + "\n", digest = sha(json);
  return { report, json, sha256: digest, filename: `sclib-qe-output-${digest.slice(0, 16)}.json` };
};
const native = (k: number) => signed(JSON.parse(source(`k${k}-reading.json`)));
const all = () => [2, 4, 6].map(native);
const changed = (edit: (report: QeResultReading["report"]) => void) => {
  const values = all(); edit(values[1].report); values[1] = signed(values[1].report); return values;
};
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Actual QE refinement outputs", () => {
  it("pins the original files and re-reads all three native outputs", () => {
    const capture = JSON.parse(source("capture.json"));
    for (const entry of capture.files) {
      const raw = readFileSync(`tests/fixtures/qe-convergence/${entry.file}`);
      expect(raw.length).toBe(entry.bytes); expect(createHash("sha256").update(raw).digest("hex")).toBe(entry.sha256);
    }
    for (const k of [2, 4, 6]) {
      const prepared = { manifest: JSON.parse(source(`k${k}-manifest.json`)) } as PreparedQe;
      const parsed = readQeNativeOutput(prepared, "execution", source(`k${k}-data-file-schema.xml`), source(`k${k}-pw.out`));
      expect(native(k).report).toMatchObject(parsed);
      expect(sha(source(`k${k}-input.in`))).toBe(prepared.manifest.files.execution.sha256);
      expect(parsed.status).toBe("scf_reported_converged");
    }
  });

  it("distinguishes converged SCF cycles from a coarse k mesh and normalizes by the actual atom count", async () => {
    const study = await compareQeReadings(all().reverse(), "mesh", 0.0001);
    expect(study.report.atom_count).toBe(3);
    expect(study.report.points.map(point => point.parameter)).toEqual([[2, 2, 2], [4, 4, 4], [6, 6, 6]]);
    expect(study.report.sampled_window.assessment).toBe("sampled_window_outside_tolerance");
    expect(study.report.sampled_window.energy_spread_hartree_per_atom).toBeCloseTo(0.016918366228363624, 14);
    expect(study.report.points[1].difference_from_last_hartree_per_atom).toBeCloseTo(0.0026491570079407722, 14);
    expect(study.report.scope).toMatchObject({ limit_established: false, joint_numerical_convergence_established: false, stable_host_validated: false, tc_calculated: false });
    expect(study.sha256).toBe(sha(study.json));
    expect(await compareQeReadings(all(), "mesh", 0.0001)).toEqual(study);
    expect(study.report.readings.map(reading => signed(reading.report).sha256)).toEqual(study.report.readings.map(reading => reading.sha256));
  });

  it("requires an explicit tolerance and reports only the requested finite window", async () => {
    expect((await compareQeReadings(all(), "mesh", 0.02)).report.sampled_window.assessment).toBe("sampled_window_within_tolerance");
    expect((await compareQeReadings(all(), "mesh", 1e-10)).report.sampled_window.assessment).toBe("scf_precision_insufficient");
    for (const invalid of [NaN, Infinity, 0, -1]) await expect(compareQeReadings(all(), "mesh", invalid)).rejects.toThrow(/positive energy tolerance/);
    await expect(compareQeReadings(all().slice(0, 2), "mesh", 0.01)).rejects.toThrow(/3 to 16/);
    await expect(compareQeReadings(Array.from({ length: 17 }, () => native(2)), "mesh", 0.01)).rejects.toThrow(/3 to 16/);
  });

  it.each([
    ["candidate", (r: QeResultReading["report"]) => { r.candidate_id += "x"; }, /same source-linked/],
    ["coordinates", (r: QeResultReading["report"]) => { r.candidate_cif_sha256 = "0".repeat(64); }, /same source-linked/],
    ["UPF bytes", (r: QeResultReading["report"]) => { r.pseudopotentials[0].sha256 = "0".repeat(64); }, /exact UPF/],
    ["charge", (r: QeResultReading["report"]) => { r.settings.charge = 1; }, /other prepared settings/],
    ["smearing", (r: QeResultReading["report"]) => { r.settings.degauss = 0.04; }, /other prepared settings/],
    ["mesh shift", (r: QeResultReading["report"]) => { r.settings.shifts[0] = 1; }, /other prepared settings/],
    ["SCF controls", (r: QeResultReading["report"]) => { r.settings.conv_thr *= 2; }, /other prepared settings/],
    ["engine", (r: QeResultReading["report"]) => { r.engine.version = "7.4"; }, /same supported engine/],
    ["relaxation", (r: QeResultReading["report"]) => { r.settings.calculation = "relax"; }, /fixed-geometry SCF/],
    ["initialization", (r: QeResultReading["report"]) => { r.input_kind = "initialization"; }, /fixed-geometry SCF/],
    ["nonconvergence", (r: QeResultReading["report"]) => { r.status = "scf_not_converged"; }, /fixed-geometry SCF/],
    ["magnetic branch", (r: QeResultReading["report"]) => { r.settings.nspin = 2; }, /Magnetic branch/],
  ] as const)("rejects a changed %s", async (_, edit, message) => {
    await expect(compareQeReadings(changed(edit), "mesh", 0.01)).rejects.toThrow(message);
  });

  it("does not sort incompatible anisotropic meshes only by their products", async () => {
    await expect(compareQeReadings(changed(r => { r.settings.mesh = [1, 8, 8]; }), "mesh", 0.01)).rejects.toThrow(/every direction/);
    await expect(compareQeReadings([native(2), native(4), native(4)], "mesh", 0.01)).rejects.toThrow(/Repeated parameter/);
  });

  it.each(["ecutwfc", "ecutrho", "degauss"] as const)("orders synthetic %s controls while keeping the other settings fixed", async axis => {
    // Counterfactual settings test control semantics only; they are not new native calculations.
    const values = (axis === "ecutwfc" ? [40, 60, 80] : axis === "ecutrho" ? [320, 480, 640] : [0.01, 0.02, 0.04]).map(value => {
      const reading = native(4); reading.report.settings[axis] = value; return signed(reading.report);
    });
    const result = await compareQeReadings(values, axis, 0.01);
    expect(result.report.points.map(point => point.parameter)).toEqual(axis === "degauss" ? [0.04, 0.02, 0.01] : axis === "ecutwfc" ? [40, 60, 80] : [320, 480, 640]);
  });

  it("rejects stale bytes and copies readings before asynchronous digests", async () => {
    const stale = all(); stale[0].report.observations.total_energy!.value = 0;
    await expect(compareQeReadings(stale, "mesh", 0.01)).rejects.toThrow(/has changed/);
    const readings = all(); const pending = compareQeReadings(readings, "mesh", 0.0001);
    readings[2].report.observations.total_energy!.value = 0;
    expect((await pending).report.points[2].energy_hartree_per_cell).toBeCloseTo(-31.20129293781947, 12);
  });
});

describe("Refinement study interaction", () => {
  it("retains explicitly added readings across file changes, compares, exports, then invalidates on edits", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const view = render(<DiscoveryQeConvergence current={native(2)} />);
    for (const k of [2, 4, 6]) {
      view.rerender(<DiscoveryQeConvergence current={native(k)} />);
      fireEvent.click(screen.getByRole("button", { name: "Add current reading" }));
      expect(screen.getByRole("button", { name: "Current reading added" })).toBeDisabled();
    }
    view.rerender(<DiscoveryQeConvergence current={null} />);
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.0001" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare readings" }));
    await screen.findByRole("heading", { name: "Sampled energy window exceeds your tolerance" });
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", { createObjectURL: vi.fn(blob => { blobs.push(blob); return "blob:study"; }), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download convergence study" }));
    fireEvent.click(screen.getByRole("button", { name: "Download study checksum" }));
    expect(blobs).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Parameter varied"), { target: { value: "ecutrho" } });
    expect(screen.queryByRole("button", { name: "Download convergence study" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove reading 2" }));
    expect(screen.getByRole("button", { name: "Compare readings" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear study" }));
    expect(screen.queryByRole("region", { name: "Scrollable numerical refinement readings" })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled(); expect(view.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("does not restore a delayed comparison after clearing the study", async () => {
    const view = render(<DiscoveryQeConvergence current={native(2)} />);
    for (const k of [2, 4, 6]) { view.rerender(<DiscoveryQeConvergence current={native(k)} />); fireEvent.click(screen.getByRole("button", { name: "Add current reading" })); }
    let release: () => void = () => {};
    const digest = vi.fn().mockImplementationOnce(async (algorithm, bytes) => { await new Promise<void>(resolve => { release = resolve; }); return webcrypto.subtle.digest(algorithm, bytes); }).mockImplementation((algorithm, bytes) => webcrypto.subtle.digest(algorithm, bytes));
    vi.stubGlobal("crypto", { subtle: { digest } });
    fireEvent.change(screen.getByLabelText("Energy tolerance (Hartree/atom)"), { target: { value: "0.01" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare readings" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear study" }));
    await act(async () => { release(); });
    expect(screen.queryByRole("button", { name: "Download convergence study" })).not.toBeInTheDocument();
  });
});
