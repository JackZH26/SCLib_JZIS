import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { act, render, screen, fireEvent, within } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DiscoveryHostReference } from "@/components/DiscoveryHostReference";
import { DiscoverySourceComparison } from "@/components/DiscoverySourceComparison";
import { DiscoveryPressureSeries } from "@/components/DiscoveryPressureSeries";
import { filterHostReferences, hostReferenceAsset, hostReferenceFilename, hostReferencePoint, hostReferenceSha256, loadHostReference } from "@/lib/discovery-host-reference";

describe("captured host physical references", () => {
  it.each([
    ["host reference", DiscoveryHostReference, 180],
    ["metal-substitution comparison", DiscoverySourceComparison, 21],
    ["pressure series", DiscoveryPressureSeries, 4],
  ] as const)("hydrates %s SVG titles without regenerating the server tree", async (_label, Component, count) => {
    const container = document.createElement("div");
    container.innerHTML = renderToString(<Component />);
    document.body.appendChild(container);
    const recoverable = vi.fn();
    let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(container, <Component />, { onRecoverableError: recoverable }); });
      expect(recoverable).not.toHaveBeenCalled();
      expect(container.querySelectorAll("svg circle")).toHaveLength(count);
    } finally {
      await act(async () => root?.unmount());
      container.remove();
    }
  });

  it("keeps the original scalar tokens, source identities and file hashes", () => {
    const reference = loadHostReference()!;
    const data = readFileSync(`public/research-pilots/${hostReferenceFilename}`);
    expect(createHash("sha256").update(data).digest("hex")).toBe(hostReferenceSha256);
    const sourceBytes = readFileSync(`public/research-pilots/${reference.source.subset_filename}`);
    expect(createHash("sha256").update(sourceBytes).digest("hex")).toBe(reference.source.subset_sha256);
    const source = JSON.parse(sourceBytes.toString());
    for (const row of reference.rows) {
      const entry = source.entries.find((item: { dataset_row_index: number }) => item.dataset_row_index === row.source.dataset_row_index);
      expect(createHash("sha256").update(entry.source_record_json).digest("hex")).toBe(row.source.record_sha256);
      // Original strings retain upstream NaN in one unrelated elastic tensor.
      // Check the exact displayed tokens without rewriting or parsing that field.
      expect(entry.source_record_json).toContain(`"jid": "${row.id}"`);
      expect(entry.source_record_json).toContain(`"formula": "${row.formula}"`);
      expect(entry.source_record_json).toContain(`"func": "${row.method}"`);
      expect(entry.source_record_json).toContain(`"formation_energy_peratom": ${row.formation_energy.raw},`);
      expect(entry.source_record_json).toContain(`"optb88vdw_bandgap": ${row.band_gap.raw},`);
      expect(row).not.toHaveProperty("ehull");
    }
  });

  it("withholds four cell mismatches without deleting them or imputing a gap", () => {
    const reference = loadHostReference()!;
    expect(reference.rows).toHaveLength(184);
    expect(reference.rows.filter(row => hostReferencePoint(row))).toHaveLength(180);
    const reviewed = reference.rows.filter(row => !row.plottable);
    expect(reviewed.map(row => row.id)).toEqual(["JVASP-86503", "JVASP-63690", "JVASP-152573", "JVASP-190301"]);
    expect(reviewed.every(row => hostReferencePoint(row) === null)).toBe(true);
    const zeroGap = reference.rows.find(row => row.plottable && row.band_gap.value === 0)!;
    expect(hostReferencePoint(zeroGap)?.y).toBe(284);
  });

  it("rejects changed source metadata and returns isolated copies", () => {
    const value = loadHostReference()!;
    value.rows[0].band_gap.value = 999;
    expect(loadHostReference(value)).toBeNull();
    expect(loadHostReference()!.rows[0].band_gap.value).not.toBe(999);
    expect(loadHostReference(null)).toBeNull();
    expect(hostReferenceAsset("../../private.json")).toBeNull();
    expect(hostReferenceAsset(hostReferenceFilename)).toContain(`/research-pilots/${hostReferenceFilename}`);
  });

  it("retains late records and clears stale selections when filters change", () => {
    const { container } = render(<DiscoveryHostReference />);
    expect(screen.getByText("184 of 184 source records · 180 plotted · 4 awaiting cell review")).toBeInTheDocument();
    expect(container.querySelectorAll("circle[data-reference-id]")).toHaveLength(180);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(13);
    fireEvent.click(screen.getByRole("button", { name: "Next", exact: true }));
    fireEvent.click(within(table).getAllByRole("button")[0]);
    expect(screen.getByRole("region", { name: "Inspected host reference" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Host formula"), { target: { value: "NbN" } });
    expect(screen.queryByRole("region", { name: "Inspected host reference" })).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Inspect JVASP-190301" }));
    expect(screen.getByText(/Source nat differs/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Inspected host reference" })).toHaveFocus();
    expect(container.querySelector('[data-reference-id="JVASP-190301"]')).toBeNull();
    expect(within(table).getByText("JVASP-191357")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close record", exact: true }));
    expect(screen.getByRole("button", { name: "Inspect JVASP-190301" })).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Host family"), { target: { value: "Oxide" } });
    expect(screen.getByLabelText("Host formula")).toHaveValue("");
    expect(screen.getByText("Page 1 of 5")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Inspected host reference" })).not.toBeInTheDocument();
  });

  it("preserves all phases within one formula and labels the scientific limits", () => {
    expect(filterHostReferences(loadHostReference()!, "", "BN")).toHaveLength(36);
    render(<DiscoveryHostReference />);
    expect(screen.getByText(/not convex-hull, phonon/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded from axes/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download original record strings/ })).toHaveAttribute("download");
    expect(screen.getByText(/Downloads always contain the complete 184-record subset/)).toBeInTheDocument();
  });

  it("shows a bounded unavailable state for an invalid edition", () => {
    render(<DiscoveryHostReference reference={{ rows: [] }} />);
    expect(screen.getByRole("status")).toHaveTextContent("The captured host reference is unavailable.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
