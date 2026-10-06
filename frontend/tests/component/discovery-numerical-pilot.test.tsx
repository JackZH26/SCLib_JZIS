import { createHash, webcrypto } from "node:crypto";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { exportResearchCase, importResearchCase, prepareResearchCase } from "@/lib/discovery-research-cycle";
import { verifyWorkspaceState } from "@/lib/discovery-research-workspace";
import type { DiscoveryNumericalPilotSummary } from "@/lib/discovery-numerical-pilot";
import { DiscoveryNumericalPilot } from "@/components/DiscoveryNumericalPilot";
import { compareQeReadings, type QeConvergenceReading } from "@/lib/discovery-qe-convergence";

const virtualFiles = { replacements: new Map<string, Buffer>(), reads: [] as string[] };
const realRead = fs.readFileSync.bind(fs);
let getDiscoveryNumericalPilot: typeof import("@/lib/discovery-numerical-pilot-loader")["getDiscoveryNumericalPilot"];
const summaryPath = resolve("public/research-pilots/discovery-qe-pilot-2026-10-06.json");
const pinsPath = resolve("public/research-pilots/discovery-qe-pilot-2026-10-06.pins.json");
const actualSummary = JSON.parse(realRead(summaryPath, "utf8")) as DiscoveryNumericalPilotSummary;
const actualPins = JSON.parse(realRead(pinsPath, "utf8"));
const replacements = virtualFiles.replacements;
const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const bytes = (value: unknown) => Buffer.from(JSON.stringify(value, null, 2) + "\n");
const publicPath = (url: string) => resolve("public", url.slice(1));
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(value);
}
function replaceSummary(value: DiscoveryNumericalPilotSummary, repin = true) {
  const file = bytes(value); replacements.set(summaryPath, file);
  if (repin) replacements.set(pinsPath, bytes({ ...actualPins, summary_sha256: sha(file) }));
}
function mutateSummary(edit: (summary: DiscoveryNumericalPilotSummary) => void, repin = true) {
  const summary = structuredClone(actualSummary); edit(summary); replaceSummary(summary, repin); return summary;
}
function replaceCase(summary: DiscoveryNumericalPilotSummary, phase: "prepared" | "returned" | "decided" | "child", json: string) {
  const pin = summary.states[0].case_exports[phase]!;
  replacements.set(publicPath(pin.download_url!), Buffer.from(json)); pin.sha256 = sha(json); replaceSummary(summary);
}
beforeEach(async () => {
  vi.resetModules();
  vi.stubGlobal("crypto", webcrypto); replacements.clear(); virtualFiles.reads.length = 0;
  vi.spyOn(fs, "readFileSync").mockImplementation(((path: Parameters<typeof fs.readFileSync>[0], options?: unknown) => {
    virtualFiles.reads.push(String(path));
    const content = typeof path === "string" ? replacements.get(resolve(path)) : undefined;
    if (!content) return realRead(path, options as never);
    const encoding = typeof options === "string" ? options : options && typeof options === "object" && "encoding" in options ? options.encoding : null;
    return typeof encoding === "string" ? content.toString(encoding as BufferEncoding) : Buffer.from(content);
  }) as typeof fs.readFileSync);
  syncBuiltinESMExports();
  getDiscoveryNumericalPilot = (await import("@/lib/discovery-numerical-pilot-loader")).getDiscoveryNumericalPilot;
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); syncBuiltinESMExports(); vi.unstubAllGlobals(); replacements.clear(); });

describe("Actual nine-run pilot and twelve research-case exports", () => {
  it("loads the retained outside-tolerance states and independently imports all twelve exact case files", async () => {
    const catalog = getResearchCatalogue(), summary = await getDiscoveryNumericalPilot(catalog);
    expect(summary).toEqual(actualSummary);
    expect(sha(realRead(summaryPath))).toBe(actualPins.summary_sha256);
    expect(summary.states.map(s => s.strain_percent)).toEqual([-2, 0, 2]);
    expect(summary.states.map(s => s.energy_spread_hartree_per_atom)).toEqual([0.0006334572564270502, 0.0007494048434040224, 0.0008587643862464726]);
    const imported: string[] = [];
    for (const state of summary.states) {
      expect(state.assessment).toBe("sampled_window_outside_tolerance");
      expect(state.decision).toMatchObject({ outcome: "redirect", next_direction: "refine_method" });
      expect(state.points).toHaveLength(3);
      expect(state.points.every(p => p.comparison_eligible && p.status === "scf_reported_converged" && p.initialization_status === "initialization_only" && p.exit_code === 0 && p.timed_out === false)).toBe(true);
      const comparisonBytes = realRead(publicPath(state.comparison_download_url!));
      expect(sha(comparisonBytes)).toBe(state.comparison_sha256);
      const comparison = JSON.parse(comparisonBytes.toString("utf8")) as QeConvergenceReading["report"];
      const replayed = await compareQeReadings(comparison.readings.map(reading => ({ ...reading, json: JSON.stringify(reading.report, null, 2) + "\n" })), "mesh", summary.protocol.tolerance_hartree_per_atom);
      expect(replayed.json).toBe(comparisonBytes.toString("utf8"));
      for (const [phase, pin] of Object.entries(state.case_exports)) {
        expect(pin?.download_url).toMatch(/^\/research-pilots\/discovery-qe-pilot-20261006\/sclib-research-case-[a-f0-9]{16}\.json$/);
        const file = realRead(publicPath(pin!.download_url!)); expect(sha(file)).toBe(pin!.sha256);
        const record = await importResearchCase(file.toString("utf8")); imported.push(pin!.sha256);
        await verifyWorkspaceState(catalog, state.catalogue_state_id, record.definition.state);
        expect(record.definition.state.structure?.sha256).toBe(state.generated_cif_sha256);
        expect(record.authority).toMatchObject({ rps_score: null, rank: null, scientific_acceptance: false, public_release: false });
        if (phase === "prepared") { expect(record.returns).toEqual([]); expect(record.decision).toBeNull(); }
        if (phase === "returned" || phase === "decided") {
          expect(record.returns).toHaveLength(1);
          expect(record.returns[0]).toMatchObject({ numerical_assessment: state.assessment, return_sha256: state.decision!.return_sha256 });
          expect(record.returns[0].artifacts[0].sha256).toBe(state.comparison_sha256);
        }
        if (phase === "decided") expect(record.decision).toMatchObject({ decision: state.decision!.outcome, next_direction: state.decision!.next_direction, decision_sha256: state.decision!.decision_sha256 });
        if (phase === "child") { expect(record.parent?.decision_sha256).toBe(state.decision!.decision_sha256); expect(record.returns).toEqual([]); expect(record.parent?.properties_inherited).toBe(false); }
      }
    }
    expect(new Set(imported).size).toBe(12);
  });

  it("rejects changed summary bytes without a new public pin", async () => {
    replacements.set(summaryPath, Buffer.concat([realRead(summaryPath), Buffer.from("\n")]));
    const rejected = await getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => false, () => true);
    expect(virtualFiles.reads).toContain(summaryPath);
    expect(rejected).toBe(true);
  });
  it("rejects changed case bytes without the exact case digest", async () => {
    const path = publicPath(actualSummary.states[0].case_exports.prepared!.download_url!);
    replacements.set(path, Buffer.concat([realRead(path), Buffer.from("\n")]));
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });
  it("rejects changed original comparison bytes", async () => {
    const path = publicPath(actualSummary.states[0].comparison_download_url!);
    replacements.set(path, Buffer.concat([realRead(path), Buffer.from("\n")]));
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });
  it("rejects a re-pinned comparison that disagrees with replay of its original native readings", async () => {
    const summary = structuredClone(actualSummary), state = summary.states[0], path = publicPath(state.comparison_download_url!);
    const comparison = JSON.parse(realRead(path, "utf8"));
    comparison.sampled_window.energy_spread_hartree_per_atom = 0;
    const file = bytes(comparison); replacements.set(path, file); state.comparison_sha256 = sha(file); state.energy_spread_hartree_per_atom = 0;
    replaceSummary(summary);
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });
  it("rejects re-pinned point energies shifted together even if the reported finite spread remains unchanged", async () => {
    mutateSummary(summary => { summary.states[0].points.forEach(point => { point.energy_hartree_per_cell! += 1; }); });
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });

  it.each([
    ["source CIF", (s: DiscoveryNumericalPilotSummary) => { s.states[0].source.cif_sha256 = "0".repeat(64); }],
    ["source record", (s: DiscoveryNumericalPilotSummary) => { s.states[0].source.record_id = "1510641"; }],
    ["source revision", (s: DiscoveryNumericalPilotSummary) => { s.states[0].source.revision = "1"; }],
    ["occurrence CIF", (s: DiscoveryNumericalPilotSummary) => { s.states[0].original_cif_sha256[0] = "0".repeat(64); }],
    ["coordinate state", (s: DiscoveryNumericalPilotSummary) => { s.states[0].catalogue_state_id = s.states[1].catalogue_state_id; }],
    ["strain", (s: DiscoveryNumericalPilotSummary) => { s.states[0].strain_percent = 1; }],
    ["RPS score", (s: DiscoveryNumericalPilotSummary) => { Object.assign(s.authority, { rps_score: 9000 }); }],
    ["RPS release", (s: DiscoveryNumericalPilotSummary) => { Object.assign(s.authority, { rps_release: true }); }],
    ["scientific approval", (s: DiscoveryNumericalPilotSummary) => { Object.assign(s.authority, { formal_scientific_approval: true }); }],
    ["reviewer", (s: DiscoveryNumericalPilotSummary) => { Object.assign(s.authority, { human_scientific_review: "invented" }); }],
    ["host", (s: DiscoveryNumericalPilotSummary) => { s.host_formula = "LaH10"; }],
    ["charge model", (s: DiscoveryNumericalPilotSummary) => { s.protocol.conditions.charge = 1; }],
    ["wavefunction cutoff", (s: DiscoveryNumericalPilotSummary) => { s.protocol.cutoffs_ry.wavefunction = 120; }],
    ["smearing width", (s: DiscoveryNumericalPilotSummary) => { s.protocol.smearing.width_ry = 0.01; }],
    ["pseudopotential digest", (s: DiscoveryNumericalPilotSummary) => { s.pseudopotentials[0].sha256 = "0".repeat(64); }],
    ["SCF iteration count", (s: DiscoveryNumericalPilotSummary) => { s.states[0].points[0].scf_iterations! += 1; }],
    ["native XML digest", (s: DiscoveryNumericalPilotSummary) => { s.states[0].points[0].file_hashes.xml = "0".repeat(64); }],
  ])("rejects re-pinned %s impersonation", async (_name, mutate) => {
    mutateSummary(mutate as (s: DiscoveryNumericalPilotSummary) => void);
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });

  it.each(["source", "coordinates"])("rejects a self-consistently exported prepared case with changed %s", async field => {
    const summary = structuredClone(actualSummary), pin = summary.states[0].case_exports.prepared!;
    const record = await importResearchCase(realRead(publicPath(pin.download_url!), "utf8"));
    if (field === "source") record.definition.state.source_pins[0].sha256 = "0".repeat(64);
    else { record.definition.state.structure!.sha256 = "0".repeat(64); summary.states[0].generated_cif_sha256 = "0".repeat(64); }
    const exported = await exportResearchCase(await prepareResearchCase(record.definition));
    replaceCase(summary, "prepared", exported.json);
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });

  it.each(["scientific_acceptance", "rps_score"])("rejects forged case %s after recomputing export and public pins", async field => {
    const summary = structuredClone(actualSummary), pin = summary.states[0].case_exports.prepared!;
    const envelope = JSON.parse(realRead(publicPath(pin.download_url!), "utf8"));
    envelope.record.authority[field] = field === "rps_score" ? 9000 : true;
    envelope.payload_sha256 = sha(canonical(envelope.record));
    replaceCase(summary, "prepared", JSON.stringify(envelope, null, 2) + "\n");
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });

  it.each(["null_exports", "null_urls"])("rejects an invented regenerated CIF hidden behind %s", async mode => {
    mutateSummary(summary => {
      const state = summary.states[0]; state.generated_cif_sha256 = "0".repeat(64);
      for (const key of Object.keys(state.case_exports) as (keyof typeof state.case_exports)[]) {
        if (mode === "null_exports") state.case_exports[key] = null;
        else state.case_exports[key]!.download_url = null;
      }
    });
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });
  it.each([
    ["assessment", (s: DiscoveryNumericalPilotSummary) => { s.states[0].assessment = "sampled_window_within_tolerance"; }],
    ["comparison digest", (s: DiscoveryNumericalPilotSummary) => { s.states[0].comparison_sha256 = "0".repeat(64); }],
    ["decision outcome", (s: DiscoveryNumericalPilotSummary) => { s.states[0].decision!.outcome = "continue"; }],
    ["decision digest", (s: DiscoveryNumericalPilotSummary) => { s.states[0].decision!.decision_sha256 = "0".repeat(64); }],
    ["model identity", (s: DiscoveryNumericalPilotSummary) => { s.states[0].generated_candidate_id = "combined-candidate:" + "0".repeat(64); }],
    ["energy spread", (s: DiscoveryNumericalPilotSummary) => { s.states[0].energy_spread_hartree_per_atom = 0; }],
    ["swapped case phases", (s: DiscoveryNumericalPilotSummary) => { [s.states[0].case_exports.prepared, s.states[0].case_exports.decided] = [s.states[0].case_exports.decided, s.states[0].case_exports.prepared]; }],
  ])("rejects re-pinned %s that contradicts the actual retained cases and points", async (_name, mutate) => {
    mutateSummary(mutate as (s: DiscoveryNumericalPilotSummary) => void);
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
  });

  it("rejects a private or traversal case URL before reading that path", async () => {
    mutateSummary(summary => { summary.states[0].case_exports.prepared!.download_url = "/research-pilots/../private/receipt.json"; });
    await expect(getDiscoveryNumericalPilot(getResearchCatalogue()).then(() => "accepted", () => "rejected")).resolves.toBe("rejected");
    expect(virtualFiles.reads.some(file => file.includes("private/receipt"))).toBe(false);
  });
});

describe("Compact numerical pilot display using only the real public summary", () => {
  it("starts folded, keeps one row per state and exposes exact case links and hashes only on request", () => {
    const ui = render(<DiscoveryNumericalPilot summary={actualSummary} />);
    expect(ui.container.querySelectorAll("details[open]")).toHaveLength(0);
    expect(screen.getByRole("table")).not.toBeVisible();
    fireEvent.click(ui.container.querySelector("summary")!);
    expect(screen.getAllByRole("row")).toHaveLength(4);
    expect(screen.getAllByText("Exceeds the sampled tolerance")).toHaveLength(3);
    expect(screen.getByText("RPS: unassigned")).toBeVisible();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    const trigger = screen.getByRole("button", { name: "Mg7AlB16, lattice change -2%" }); fireEvent.click(trigger);
    fireEvent.click(screen.getByText("Research-case exports"));
    const links = screen.getAllByRole("link", { name: /^Download .* case$/ }); expect(links).toHaveLength(4);
    for (const [index, pin] of Object.values(actualSummary.states[0].case_exports).entries()) {
      expect(links[index]).toHaveAttribute("href", pin!.download_url); expect(links[index]).toHaveAttribute("download");
      expect(screen.getByText(`SHA-256 ${pin!.sha256}`)).toBeVisible();
    }
    fireEvent.click(screen.getByRole("button", { name: "Close" })); expect(trigger).toHaveFocus();
    expect(ui.container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it("does not expose unavailable, external, private or encoded traversal download links", () => {
    const summary = structuredClone(actualSummary), state = summary.states[0];
    state.case_exports.prepared!.download_url = null;
    state.case_exports.returned!.download_url = "https://example.com/case.json";
    state.case_exports.decided!.download_url = "/private/case.json";
    state.case_exports.child!.download_url = "/research-pilots/%2e%2e/private/case.json";
    state.comparison_download_url = "https://example.com/comparison.json";
    state.source.cif_url = "https://example.com/source.cif";
    const ui = render(<DiscoveryNumericalPilot summary={summary} />);
    fireEvent.click(ui.container.querySelector("summary")!);
    fireEvent.click(screen.getByRole("button", { name: "Mg7AlB16, lattice change -2%" }));
    fireEvent.click(screen.getByText("Research-case exports"));
    fireEvent.click(screen.getByText("Original coordinates and reading hashes"));
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});
