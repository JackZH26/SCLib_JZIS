import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PressurePage from "@/app/materials/source-observations/pressure-and-tables/page";
import FollowupPage from "@/app/materials/source-observations/followup/page";
import { loadStudyContextBatch, studyContextDownloadPath, studyContextSnapshotSha256, studyContextSourceHref } from "@/lib/material-study-context";
import { materialStudyReading } from "@/lib/material-study-reading";
import { MaterialPressureTableSources } from "@/components/MaterialPressureTableSources";
import { loadPressureTableBatch } from "@/lib/material-pressure-table-sources";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("Inspected study context", () => {
  it("keeps frozen source-resource files and the new literal metadata byte-pinned", () => {
    const pins = [
      ["materials-pressure-table-sources-2026-10-02.json", "788144f67d439d0a5051e3b5144c988311e5423ccfa56402beb5566744ebe284"],
      ["materials-source-followup-2026-10-02.json", "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8"],
      ["materials-study-context-2026-10-04.json", studyContextSnapshotSha256],
    ];
    for (const [name, digest] of pins) {
      expect(createHash("sha256").update(readFileSync(`public/research-pilots/${name}`)).digest("hex")).toBe(digest);
      expect(readFileSync(`public/research-pilots/${name}.sha256`, "utf8")).toBe(`${digest}  ${name}\n`);
    }
    const batch = loadStudyContextBatch()!;
    expect(batch.entries.flatMap(entry => entry.fields)).toHaveLength(19);
    for (const field of batch.entries.flatMap(entry => entry.fields)) {
      expect(createHash("sha256").update(field.raw_value, "utf8").digest("hex")).toBe(field.locator.literal_sha256);
    }
  });

  it("rejects moving a repeated composition, inventing a calorimetric Tc or promoting review authority", () => {
    const moved = loadStudyContextBatch()!;
    moved.entries.find(entry => entry.id.endsWith("column-3"))!.fields[1].locator.occurrence_in_source_window = 1;
    expect(loadStudyContextBatch(moved)).toBeNull();
    const changedRole = loadStudyContextBatch()!;
    changedRole.entries.at(-1)!.fields[2].source_role = "calorimetric_tc";
    expect(loadStudyContextBatch(changedRole)).toBeNull();
    const promoted = loadStudyContextBatch()!;
    promoted.authority.scientific_acceptance = true;
    expect(loadStudyContextBatch(promoted)).toBeNull();
    expect(studyContextSourceHref("https://arxiv.org/pdf/1603.02892?unreviewed=1")).toBeNull();
    expect(studyContextSourceHref("javascript:alert(1)")).toBeNull();
  });

  it("keeps transport medium, Raman medium and calibration temperature in their source roles", () => {
    render(<PressurePage />);
    const bi = within(screen.getByRole("region", { name: "BiTeCl: separate pressure windows" }));
    expect(bi.getByText("Daphne oil 7373")).toBeInTheDocument();
    expect(bi.getByText("Neon")).toBeInTheDocument();
    expect(bi.getByText("488 nm")).toBeInTheDocument();
    expect(within(document.querySelector("#study-context-bi-transport > dl") as HTMLElement).getByText("Calibration temperature")).toBeInTheDocument();
    expect(document.querySelector("#study-context-bi-transport")!.closest("details")).not.toHaveAttribute("open");
    expect(bi.getByText(/The caption criterion is not assigned to the 7 K report/)).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    expect(screen.getByRole("heading", { name: "Mo borophosphide: two original table columns" })).toHaveClass("scroll-mt-24");
    expect(table.getByText(/original column 2 · row 2/)).toBeInTheDocument();
    expect(table.getByText(/original column 3 · row 2/)).toBeInTheDocument();
    expect(table.getByText(/occurrence 1 of 2 in this source window/)).toBeInTheDocument();
    expect(table.getByText(/occurrence 2 of 2 in this source window/)).toBeInTheDocument();
    expect(table.getAllByText(/The PDF URL can return a different version/)).toHaveLength(2);
  });

  it("keeps the calibration distinction when an optional supplement fails validation", () => {
    const invalid = loadStudyContextBatch()!;
    invalid.authority.scientific_acceptance = true;
    render(<MaterialPressureTableSources batch={loadPressureTableBatch()} studyContext={invalid} />);
    expect(screen.getByText("Room-temperature pressure calibration is separate from the superconducting measurement temperature.")).toBeInTheDocument();
    expect(screen.queryByText("Daphne oil 7373")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "BiTeCl: separate pressure windows" })).toHaveTextContent("7 K");
  });

  it("separates caption Tc attribution, calorimetry features and XRD temperature", () => {
    render(<FollowupPage />);
    const table = within(screen.getByRole("table", { name: "Caption Tc attribution and separate calorimetry feature descriptions." }));
    const captionRow = within(table.getByRole("row", { name: /Tc attributed in Figure 4 caption/ }));
    expect(captionRow.getByText("23 K")).toBeInTheDocument();
    expect(captionRow.getByText("resistivity and magnetic susceptibility measurements")).toBeInTheDocument();
    const featureRow = within(table.getByRole("row", { name: /Heat-capacity feature/ }));
    expect(featureRow.getByText("≈ 20 K")).toBeInTheDocument();
    expect(featureRow.getByText("Feature center in the caption")).toBeInTheDocument();
    expect(table.getByRole("row", { name: /Heat-capacity shift/ })).toHaveTextContent("below 21 K");
    expect(screen.getByText(/no distinct calorimetric Tc is assigned here/)).toBeInTheDocument();
    expect(screen.getByText("BaFe1.906(8)Pt0.094(8)As2")).toBeInTheDocument();
    expect(within(document.querySelector("#study-context-pt-xrd-correspondence > dl") as HTMLElement).getByText("XRD measurement temperature")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Pt source transition methods, horizontally scrollable" })).toHaveAttribute("tabindex", "0");
  });

  it("offers a closed, contained English metadata reader with actual download links", () => {
    render(<PressurePage />);
    const pre = screen.getByLabelText("Study context metadata JSON");
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(pre).toHaveClass("max-h-80", "max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
    expect(pre.closest("details")).not.toHaveAttribute("open");
    expect(JSON.parse(pre.textContent!)).toEqual(loadStudyContextBatch());
    expect(screen.getByRole("link", { name: "Download study context (JSON)" })).toHaveAttribute("href", studyContextDownloadPath);
    expect(screen.getByRole("link", { name: "Download study context SHA-256" })).toHaveAttribute("download");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("requires the inspected material, selected result and paper together for related readings", () => {
    const selected = { result_id: "legacy-result:728957cf5518e15646f532d9d27aedd22bca169618e1ef790265914d1d76bad9", source: { paper_id: "arxiv:1501.06203" } };
    expect(materialStudyReading("mat:bitecl", selected)?.href).toContain("#study-context-bi-transport");
    expect(materialStudyReading("mat:other-bitecl", selected)).toBeNull();
    expect(materialStudyReading("mat:bitecl", { ...selected, result_id: "legacy-result:changed" })).toBeNull();
    expect(materialStudyReading("mat:bitecl", { ...selected, source: { paper_id: "arxiv:other-edition" } })).toBeNull();
    expect(materialStudyReading("mat:bitecl", { formula: "BiTeCl", source: selected.source })).toBeNull();
    expect(materialStudyReading("mat:bitecl", null)).toBeNull();
  });

  it("keeps native paper-reading navigation inside a configured mounted base path", () => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    const selected = { result_id: "legacy-result:728957cf5518e15646f532d9d27aedd22bca169618e1ef790265914d1d76bad9", source: { paper_id: "arxiv:1501.06203" } };
    expect(materialStudyReading("mat:bitecl", selected)?.href).toBe("/sclib-preview/materials/source-observations/pressure-and-tables#study-context-bi-transport");
    expect(materialStudyReading("mat:bitecl", { ...selected, result_id: "legacy-result:changed" })).toBeNull();
  });
});
