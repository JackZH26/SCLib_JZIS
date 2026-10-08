import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialRecoveryBatch } from "@/components/MaterialRecoveryBatch";
import { verifiedRecoveryBatch } from "@/lib/material-recovery-batch";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";
import type { MaterialEnrichmentReport } from "@/lib/api";

const seed = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_recovery_batch_20261008_seed.json"), "utf8"));
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
function report(id: string): MaterialEnrichmentReport {
  const row = clone(seed.rows.find((r: { material_id: string }) => r.material_id === id));
  const batch = { ...row, version: seed.version, seed_id: seed.seed_id, seed_sha256: seed.seed_sha256,
    pending_candidates_in_batch: row.pending_candidates };
  return { version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false,
    candidates: [], counts: {}, source_recovery_batch: batch,
    coverage: [{ material_id: id, formula: row.formula, fields: [] }] };
}

describe("Original-source batch disclosure", () => {
  it("validates all 16 actual rows, 55 observations and 34 pending candidates", () => {
    const rows = seed.rows.map((r: { material_id: string }) => verifiedRecoveryBatch(report(r.material_id), r.material_id));
    expect(rows.every(Boolean)).toBe(true);
    expect(rows.flatMap((r: NonNullable<ReturnType<typeof verifiedRecoveryBatch>>) => r.observations)).toHaveLength(55);
    expect(rows.reduce((sum: number, r: NonNullable<ReturnType<typeof verifiedRecoveryBatch>>) => sum + r.pending_candidates_in_batch, 0)).toBe(34);
    const exported = seed.rows.map((r: { material_id: string }) => materialRecoveryMetadata(report(r.material_id), r.material_id));
    expect(JSON.stringify(exported)).not.toMatch(/\/Users\/|page-texts|evidence_text|private_notes/);
  });

  it("keeps computed MgH26 conditions and explicit uncertainty in a collapsed disclosure", () => {
    render(<MaterialRecoveryBatch report={report("mat:mgh26")} materialId="mat:mgh26" />);
    const summary = screen.getByText(/Primary-source inspection/);
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(summary.closest("details")).toHaveTextContent("200 GPa");
    expect(summary.closest("details")).toHaveTextContent("Computed source scope");
    expect(summary.closest("details")).toHaveTextContent("not independent experiments or human-approved facts");
    for (const link of screen.getAllByRole("link", { hidden: true })) expect(link.getAttribute("href")).toMatch(/^https:\/\/arxiv\.org\/pdf\/\d{4}\.\d{4,5}v\d+#page=\d+$/);
  });

  it("retains source-internal composition conflicts and criterion-separated Tc values", () => {
    const ca = verifiedRecoveryBatch(report("mat:cafe0.93co0.07ash"), "mat:cafe0.93co0.07ash")!;
    expect(JSON.stringify(ca)).toContain("0.09");
    const ta = verifiedRecoveryBatch(report("mat:ta2pdse5"), "mat:ta2pdse5")!;
    expect(JSON.stringify(ta)).toContain("2.6");
    expect(JSON.stringify(ta)).toContain("2.2");
    expect(ca.human_reviewed).toBe(false);
  });

  it("hides invalid authority, stale material identity, unsafe URLs and broken spans", () => {
    for (const change of ["authority", "material", "url", "span"]) {
      const r = report("mat:mgh26"), b = r.source_recovery_batch as Record<string, any>;
      if (change === "authority") b.human_reviewed = true;
      if (change === "material") b.material_id = "other";
      if (change === "url") b.observations[0].source.source_url = "javascript:alert(1)";
      if (change === "span") b.observations[0].source.span.char_end = -1;
      expect(verifiedRecoveryBatch(r, "mat:mgh26")).toBeNull();
    }
  });

  it("redacts arbitrary nested private fields from downloaded metadata", () => {
    const r = report("mat:mgh26"), b = r.source_recovery_batch as Record<string, any>;
    b.private_notes = "PRIVATE CONTEXT";
    b.observations[0].source.raw_text = "PRIVATE CONTEXT";
    b.observations[0].source.locator.private_path = "PRIVATE CONTEXT";
    const projected = materialRecoveryMetadata(r, "mat:mgh26")!;
    expect(projected.source_recovery_batch?.observations.length).toBeGreaterThan(0);
    expect(JSON.stringify(projected)).not.toContain("PRIVATE CONTEXT");
  });
});
