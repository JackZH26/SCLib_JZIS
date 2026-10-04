import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import snapshot from "@/public/research-pilots/materials-yin3-source-context-2026-10-04.json";
import { MaterialYin3SourceContext } from "@/components/MaterialYin3SourceContext";
import Yin3SourceTransitionsPage from "@/app/materials/source-observations/yin3-transitions/page";
import { loadYin3SourceContext, yin3SourceContextHref, yin3SourceContextSnapshotSha256 } from "@/lib/material-yin3-source-context";
import { materialStudyReading } from "@/lib/material-study-reading";

describe("YIn3 source-qualified sample contexts", () => {
  it("pins the captured edition, separate samples and unchanged catalogue context", () => {
    const name = "materials-yin3-source-context-2026-10-04.json";
    const bytes = readFileSync(resolve(process.cwd(), "public/research-pilots", name));
    const digest = createHash("sha256").update(bytes).digest("hex");
    expect(digest).toBe(yin3SourceContextSnapshotSha256);
    expect(readFileSync(resolve(process.cwd(), "public/research-pilots", name + ".sha256"), "utf8")).toBe(`${digest}  ${name}\n`);
    const data = loadYin3SourceContext()!;
    expect(data.source).toMatchObject({ paper_id: "arxiv:1112.3083", edition: "v1", bytes: 58286, sha256: "10b8722eb2a7f8d8a7e41aa6b797ab2ffb8ed749e550522ec0a0de16c2248dc5" });
    expect(data.observations).toHaveLength(9);
    expect(Object.keys(data.source_locators)).toHaveLength(12);
    expect(data.saved_catalogue_context).toMatchObject({ id: "mat:yin3", retained_raw_tc_kelvin: 1.2, retained_method: "resistivity", retained_criterion: "onset", sample_id: null, state_id: null, legacy_pressure_read_state: "ambiguous" });
    expect(data.classification).toMatchObject({ author_qualifier: "likely", is_unconventional: null, classification_assigned: null });
    expect(data.authority.scientific_acceptance).toBe(false);
    expect(JSON.stringify(data)).not.toMatch(/\/private\/|\/Users\/|"derived_text":/);
  });

  it("retains method-specific onsets, original mK roles and approximation words", () => {
    render(<Yin3SourceTransitionsPage />);
    const onsets = screen.getByRole("table", { name: "Three source-reported onset temperatures for sample B." });
    expect(within(onsets).getAllByRole("row").slice(1).map(row => within(row).getByRole("cell").textContent)).toEqual(["1.08 K", "0.95 K", "0.90 K"]);
    const descriptions = screen.getByRole("region", { name: "YIn3 source temperature descriptions, horizontally scrollable" });
    expect(descriptions).toHaveAttribute("tabindex", "0");
    expect(within(descriptions).getAllByRole("row")).toHaveLength(10);
    for (const value of ["about 1.2 K", "above 1 K", "1.08 – 0.98 K", "950 mK", "960 mK"]) expect(within(descriptions).getByText(value)).toBeInTheDocument();
    expect(within(descriptions).getAllByText("825 mK")).toHaveLength(2);
    expect(screen.getByText("likely conventional")).toBeInTheDocument();
    expect(screen.getByText(/binary material classification/, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText(/The saved catalogue selection/)).toHaveTextContent("no established sample association");
    expect(screen.getByText(/Legacy pressure/)).toHaveTextContent("ambiguous read state");
    expect(screen.getByText("12 Hz")).toBeInTheDocument();
    expect(screen.getByText("about 0.4 gauss")).toBeInTheDocument();
    expect(screen.getByText("57.55 mg")).toBeInTheDocument();
    for (const title of ["Other temperature descriptions in the paper", "Preparation, measurement conditions and indium context", "Catalogue association, provenance and downloads"]) expect(screen.getByText(title).closest("details")).not.toHaveAttribute("open");
    expect(screen.getByRole("region", { name: "YIn3 source-context metadata JSON" })).toHaveAttribute("tabindex", "0");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|\u2014/);
  });

  it("rejects loss of qualifiers or promotion of source observations", () => {
    const mutations = [
      (value: typeof snapshot) => { value.classification.is_unconventional = false; },
      (value: typeof snapshot) => { value.classification.author_qualifier = "established"; },
      (value: typeof snapshot) => { value.saved_catalogue_context.sample_id = "B"; },
      (value: typeof snapshot) => { value.saved_catalogue_context.legacy_pressure_read_state = "ambient"; },
      (value: typeof snapshot) => { value.authority.scientific_acceptance = true; },
      (value: typeof snapshot) => { value.source.edition = "v2"; },
    ];
    for (const mutate of mutations) { const value = JSON.parse(JSON.stringify(snapshot)); mutate(value); expect(loadYin3SourceContext(value)).toBeNull(); }
    const first = loadYin3SourceContext()!;
    first.classification.author_qualifier = "changed";
    expect(loadYin3SourceContext()!.classification.author_qualifier).toBe("likely");
    const accessor = JSON.parse(JSON.stringify(snapshot)); let calls = 0;
    Object.defineProperty(accessor, "source", { get() { calls++; return snapshot.source; } });
    expect(loadYin3SourceContext(accessor)).toBeNull(); expect(calls).toBe(0);
    expect(loadYin3SourceContext({ ...snapshot, observations: new Array(9) })).toBeNull();
  });

  it("binds the reading link to the exact retained material, result and source paper", () => {
    const identity = snapshot.saved_catalogue_context;
    const selected = { result_id: identity.result_id, source: { paper_id: identity.paper_id } };
    expect(materialStudyReading("mat:yin3", selected)).toMatchObject({ href: "/materials/source-observations/yin3-transitions" });
    expect(materialStudyReading("mat:other", selected)).toBeNull();
    expect(materialStudyReading("mat:yin3", { ...selected, result_id: "different" })).toBeNull();
    expect(materialStudyReading("mat:yin3", { ...selected, source: { paper_id: "arxiv:other" } })).toBeNull();
    expect(yin3SourceContextHref(snapshot.source.final_url)).toBe(snapshot.source.final_url);
    expect(yin3SourceContextHref(snapshot.source_locators["S3.p5.1"].source_url)).toBe(snapshot.source_locators["S3.p5.1"].source_url);
    for (const url of [snapshot.source.final_url.replace("v1", "v2"), snapshot.source.final_url + "?token=secret", snapshot.source.final_url + "#unknown", "javascript:alert(1)"]) expect(yin3SourceContextHref(url)).toBeNull();
  });

  it("shows the unavailable state without substitute sample values", () => {
    render(<MaterialYin3SourceContext data={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Captured YIn₃ source context is unavailable");
    expect(screen.queryByRole("table")).toBeNull();
  });
});
