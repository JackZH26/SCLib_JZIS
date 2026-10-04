import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Page from "@/app/materials/source-observations/paper-contexts/page";
import { MaterialNativePaperContexts } from "@/components/MaterialNativePaperContexts";
import { loadNativePaperContexts, nativePaperContextDownloadPath, nativePaperContextSnapshotSha256, nativePaperContextSourceHref } from "@/lib/material-native-paper-context";
import { materialStudyReading } from "@/lib/material-study-reading";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("Native paper context preserves sample and interpretation boundaries", () => {
  it("pins downloadable metadata and keeps paraphrases separate from normalized material values", () => {
    const name = "materials-native-paper-context-2026-10-04-r2.json";
    const raw = readFileSync(`public/research-pilots/${name}`);
    expect(createHash("sha256").update(raw).digest("hex")).toBe(nativePaperContextSnapshotSha256);
    expect(readFileSync(`public/research-pilots/${name}.sha256`, "utf8")).toBe(`${nativePaperContextSnapshotSha256}  ${name}\n`);
    const batch = loadNativePaperContexts()!;
    expect(batch.canonical_field_updates).toBe(0);
    expect(batch.counts_are_independent_experiments).toBe(false);
    expect(batch.authority.scientific_acceptance).toBe(false);
    for (const context of batch.contexts) {
      expect(context.selected_result_association).toBe("unestablished");
      for (const row of context.rows) {
        expect(row.kind).toBe("source_summary");
        expect(row.normalized_value).toBeNull();
      }
    }
    expect(raw.toString()).not.toMatch(/\/private\/tmp|\/Users\/|"raw_value"|"full_text"/);
    const previous = readFileSync("public/research-pilots/materials-native-paper-context-2026-10-04.json");
    expect(createHash("sha256").update(previous).digest("hex")).toBe("6c8b6b57c8a0e66a916ba2abf8bcafe9b849f56ef9a6ff0e4b4a8f0b4c1b4404");
    expect(batch.contexts.filter(context => context.source_id !== "thca")).toEqual(JSON.parse(previous.toString()).contexts);
  });

  it("separates the hydride table result, assumed Tc model and paper-wide calculation settings", () => {
    render(<Page />);
    const section = within(screen.getByRole("region", { name: "ThCa₂H₂₄: calculated Tc and computational methods" }));
    expect(section.getByText(/Table I reports predicted Tc = 250 K/)).toHaveTextContent("300 GPa");
    expect(section.getByText(/Direct solution of the isotropic Migdal–Eliashberg/)).toHaveTextContent("Elk, with assumed Coulomb pseudopotential μ* = 0.1");
    expect(section.getByText(/electron–phonon λ = 2.96/)).toHaveTextContent("ωlog = 530");
    expect(section.getByText(/Table I does not print an ωlog unit/)).toHaveTextContent("unit remains unresolved");
    expect(section.getByText(/Paper-wide EPC settings/)).toHaveTextContent("Quantum ESPRESSO, ultrasoft pseudopotentials, 60 Ry");
    expect(section.getByText(/Paper-wide structure\/band settings/)).toHaveTextContent("VASP, PBE-GGA/PAW, 750 eV");
    expect(section.getByText(/class-level discussion/)).toHaveTextContent("compound-specific stability conclusion for ThCa2H24 requires further source review");
    expect(section.queryByText(/530 K|Allen–Dynes|experimentally verified|QE.*PAW.*750 eV/)).not.toBeInTheDocument();
    const context = loadNativePaperContexts()!.contexts.find(context => context.source_id === "thca")!;
    expect(context.selected_result_association).toBe("unestablished");
    expect(context).not.toHaveProperty("frozen_classification_statuses");
    for (const row of context.rows) expect(row.normalized_value).toBeNull();
  });

  it("requires the hydride material, selected result and APS identity together for related reading", () => {
    const material = "mat:thca2h24";
    const selected = { result_id: "legacy-result:4d9aa6126689e8fad54ce66a8bd0667b65f7aa5587d7cc6e4de1e90dc08700d2", source: { paper_id: "aps:10.1103/7lg7-l3x8" } };
    expect(materialStudyReading(material, selected)?.href).toBe("/materials/source-observations/paper-contexts#paper-context-thca");
    expect(materialStudyReading("mat:thca2h20", selected)).toBeNull();
    expect(materialStudyReading(material, { ...selected, result_id: "legacy-result:other-pressure" })).toBeNull();
    expect(materialStudyReading(material, { ...selected, source: { paper_id: "aps:10.1103/other-edition" } })).toBeNull();
    expect(materialStudyReading(material, { source: selected.source })).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    expect(materialStudyReading(material, selected)?.href).toBe("/sclib-preview/materials/source-observations/paper-contexts#paper-context-thca");
  });

  it("shows Fe NMR attribution to other compositions without assigning their pairing to x = 0.48", () => {
    render(<Page />);
    const section = within(screen.getByRole("region", { name: "FeTeSe: methods and sample scope" }));
    expect(section.getByText(/NMR\/d-wave discussion concerns Fe1.04Te0.67Se0.33/)).toHaveTextContent("no pairing assignment for x = 0.48");
    expect(section.getByText(/Table I has no EDX row for x = 0.48/)).toHaveTextContent("uncorrected for Fe(II)");
    expect(section.getByText(/Parent antiferromagnetism/)).toHaveTextContent("do not establish static order at x = 0.48");
    expect(section.getByText(/SQUID ZFC\/FC at 20 Oe/)).toHaveTextContent("four-probe resistivity to 14 T");
  });

  it("keeps organic tentative AF and superconducting temperatures in separate roles and thermal histories distinct", () => {
    render(<Page />);
    const section = within(screen.getByRole("region", { name: "κ-H8-Br: ultrasound and thermal history" }));
    expect(section.getByText(/≈ 15 K anomaly/)).toHaveTextContent("authors suggest an antiferromagnetic interpretation. Near 11.9 K: separate superconducting phase-coherence context");
    expect(section.getByText(/Methods: FT before annealing/)).toHaveTextContent("Figure 1: SL before the 70 K anneal");
    expect(section.getByText(/A-70K attenuation challenges/)).toHaveTextContent("leaves pairing symmetry unresolved");
    expect(section.getByText(/internal-pressure proxy/)).toHaveTextContent("no numerical hydrostatic pressure is recovered");
    expect(section.getByText(/No selected catalogue Tc or result is linked/)).toBeInTheDocument();
    expect(section.getByText("Superconducting phase coherence near 11.9 K")).toBeInTheDocument();
    expect(section.queryByText("119K phase coherence")).not.toBeInTheDocument();
    expect(materialStudyReading("mat:κ-[bedtttf]2cun(cn)2br", null)).toBeNull();
    expect(materialStudyReading("mat:κ-[bedtttf]2cun(cn)2br", { result_id: "legacy-result:invented", source: { paper_id: "arxiv:cond-mat/0612431" } })).toBeNull();
  });

  it("requires the Fe material, selected result and source identity together and preserves configured base paths", () => {
    const material = "mat:fe1te0.52se0.48";
    const selected = { result_id: "legacy-result:17c34bd20d1efd2f3d2cae898af035089b6e0e53a04489f96bfd6c10c000478a", source: { paper_id: "arxiv:0911.4758" } };
    expect(materialStudyReading(material, selected)?.href).toBe("/materials/source-observations/paper-contexts#paper-context-fete");
    expect(materialStudyReading("mat:other-fe1te0.52se0.48", selected)).toBeNull();
    expect(materialStudyReading(material, { ...selected, result_id: "legacy-result:changed" })).toBeNull();
    expect(materialStudyReading(material, { ...selected, source: { paper_id: "arxiv:0911.4758v2" } })).toBeNull();
    expect(materialStudyReading(material, { formula: "Fe1+δTe0.52Se0.48", source: selected.source })).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    expect(materialStudyReading(material, selected)?.href).toBe("/sclib-preview/materials/source-observations/paper-contexts#paper-context-fete");
  });

  it("separates the nickelate onset pressure, field state and computed stoichiometric model", () => {
    render(<Page />);
    const section = within(screen.getByRole("region", { name: "La4Ni3O9.99: experiment and calculated model" }));
    expect(section.getByText(/resistance onset of 23 K at 79.2 GPa/)).toHaveTextContent("Authors require further confirmation");
    expect(section.getByText(/Field curves at 69.4 GPa/)).toHaveTextContent("separate from the 79.2 GPa onset point");
    expect(section.getByText(/resistance drop below 5 K at 32.8 GPa/)).toHaveTextContent("Field curves at 69.4 GPa");
    expect(section.getByText(/DFT\/FLEX predictions concern stoichiometric La4Ni3O10/)).toHaveTextContent("Model λ denotes a linearized Eliashberg eigenvalue, not electron–phonon coupling");
    expect(section.getByText(/Predicted tetragonal I4\/mmm/)).toHaveTextContent("10–15 GPa in detailed results; around 20 GPa later");
    expect(section.getByText(/CDW competition is speculative/)).toHaveTextContent("observed order and unconventional classification remain unresolved");
    expect(section.getByText("Onset confirmation: 23 K at 79.2 GPa")).toBeInTheDocument();
    expect(section.queryByText(/onset23K792GPa/)).not.toBeInTheDocument();
    const material = "mat:la4ni3o9.99";
    const selected = { result_id: "legacy-result:575b0f079349106ca62b042e5602c02142d387af0c99ff57d14fe40bc0530d9a", source: { paper_id: "aps:10.1103/PhysRevB.109.144511" } };
    expect(materialStudyReading(material, selected)?.href).toContain("#paper-context-nickelate");
    expect(materialStudyReading("mat:la4ni3o10", selected)).toBeNull();
    expect(materialStudyReading(material, { ...selected, result_id: "legacy-result:other-pressure" })).toBeNull();
    expect(materialStudyReading(material, { ...selected, source: { paper_id: "arxiv:2309.09462" } })).toBeNull();
  });

  it("rejects caller edits to authority, scientific interpretation, source scope, locators and extra text", () => {
    const edits = [
      (b: any) => { b.authority.scientific_acceptance = true; },
      (b: any) => { b.contexts[0].rows[2].summary = "d-wave pairing established for x = 0.48"; },
      (b: any) => { b.contexts[0].rows[0].normalized_value = 12; },
      (b: any) => { b.contexts[0].rows[0].locator_ids = ["organic:methods-thermal-history-field"]; },
      (b: any) => { b.sources[0].source_url = "https://example.org/unreviewed.pdf"; },
      (b: any) => { b.locators[0].char_end += 1; },
      (b: any) => { b.raw_full_text = "unreviewed source text"; },
      (b: any) => { b.contexts.find((c: any) => c.source_id === "thca").rows[2].summary = "ωlog = 530 K"; },
      (b: any) => { b.sources.find((s: any) => s.id === "thca").source_url = "https://journals.aps.org/prresearch/pdf/10.1103/other-edition"; },
    ];
    for (const edit of edits) {
      const changed = loadNativePaperContexts()!;
      edit(changed);
      expect(loadNativePaperContexts(changed)).toBeNull();
    }
    expect(loadNativePaperContexts(null)).toBeNull();
  });

  it("restricts source links to captured editions and valid PDF pages", () => {
    expect(nativePaperContextSourceHref("fete", 6)).toBe("https://arxiv.org/pdf/0911.4758v1#page=6");
    expect(nativePaperContextSourceHref("organic", 4)).toBe("https://arxiv.org/pdf/cond-mat/0612431v1#page=4");
    for (const page of [0, -1, 1.2, 9, NaN, Infinity]) expect(nativePaperContextSourceHref("fete", page)).toBeNull();
    expect(nativePaperContextSourceHref("https://example.org/unreviewed.pdf")).toBeNull();
    expect(nativePaperContextSourceHref("thca", 2)).toBe("https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8#page=2");
    expect(nativePaperContextSourceHref("thca", 7)).toBe("https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8#page=7");
    for (const page of [0, -1, 1.2, 8, NaN, Infinity]) expect(nativePaperContextSourceHref("thca", page)).toBeNull();
    expect(nativePaperContextSourceHref("https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8", 2)).toBeNull();
  });

  it("keeps provenance and downloadable JSON closed, contained and English by default", () => {
    render(<Page />);
    for (const fold of document.querySelectorAll("details")) expect(fold).not.toHaveAttribute("open");
    const pre = screen.getByLabelText("Paper context metadata JSON");
    expect(pre).toHaveClass("max-h-80", "max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "Paper context metadata JSON" })).toBe(pre);
    pre.focus(); expect(pre).toHaveFocus();
    expect(JSON.parse(pre.textContent!)).toEqual(loadNativePaperContexts());
    expect(screen.getByRole("link", { name: "Download paper contexts (JSON)" })).toHaveAttribute("href", nativePaperContextDownloadPath);
    expect(screen.getByRole("link", { name: "Download paper context SHA-256" })).toHaveAttribute("download");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    expect(document.querySelector("#paper-context-fete")).toHaveClass("scroll-mt-24", "min-w-0");
  });

  it("keeps an unavailable optional reading visible as an unavailable state", () => {
    const invalid = loadNativePaperContexts()!;
    invalid.authority.scientific_acceptance = true;
    render(<MaterialNativePaperContexts batch={invalid} />);
    expect(screen.getByRole("status")).toHaveTextContent("Captured paper contexts are unavailable");
    expect(screen.queryByText(/NMR\/d-wave/)).not.toBeInTheDocument();
  });
});
