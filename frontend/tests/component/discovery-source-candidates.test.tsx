import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { webcrypto } from "node:crypto";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverySourceCandidates, readSourceHypothesisDetail } from "@/components/DiscoverySourceCandidates";
import { DiscoveryTabs } from "@/components/DiscoveryTabs";
import { DiscoveryDisclosure } from "@/components/DiscoveryDisclosure";
import { getSourceHypothesisBrowseCatalogue } from "@/lib/discovery-source-hypotheses";
import { compareResearchPriority } from "@/lib/discovery-evidence-policy";

const catalogue = getSourceHypothesisBrowseCatalogue();
const order = new Intl.Collator("en-US", { numeric: true, sensitivity: "base" });
const sorted = [...catalogue.candidates].sort((a, b) => compareResearchPriority(a, b, "source_pairing"));
const rows = () => [...document.querySelectorAll<HTMLTableRowElement>("tr[data-source-candidate]")];
const rowIds = () => rows().map(row => row.dataset.sourceCandidate);
const allRows = () => {
  const options = document.querySelector<HTMLDetailsElement>(".discovery-source-secondary-filters")!;
  options.open = true;
  fireEvent.change(screen.getByRole("combobox", { name: "Rows per page" }), { target: { value: String(catalogue.candidates.length) } });
};

const sourceBytes = (candidate: typeof sorted[number]) => readFileSync(join(process.cwd(), "public", candidate.detail.url));
const response = (body: Uint8Array) => new Response(body, { status: 200, headers: { "content-type": "application/json" } });
const staticResponse = (url: string) => response(readFileSync(join(process.cwd(), "public", url)));
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { window.history.replaceState(null, "", "/"); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Public unscored source-computed Discovery directory", () => {
  it("uses the real 103 composition-distinct candidates, provisional groups and closed evidence rows", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    expect(catalogue.candidates).toHaveLength(103);
    expect(catalogue.candidates.every(candidate => !Object.hasOwn(candidate, "physical_summary") && !Object.hasOwn(candidate, "countercontrols") && !Object.hasOwn(candidate, "seven_criteria"))).toBe(true);
    expect(rowIds()).toEqual(sorted.slice(0, 24).map(candidate => candidate.id));
    expect(screen.getByRole("status")).toHaveTextContent("103 / 103 materials · Showing 1 to 24 · Provisional groups");
    expect(screen.getByText("Page 1 of 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous materials" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeDisabled();
    expect(screen.getAllByRole("button", { name: /^Show details for / })).toHaveLength(24);
    for (const button of screen.getAllByRole("button", { name: /^Show details for / })) expect(button).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelectorAll(".discovery-source-detail-row")).toHaveLength(0);
    expect(container.querySelector(".discovery-source-scope")).not.toHaveAttribute("open");
    expect(container.querySelector(".discovery-source-secondary-filters")).not.toHaveAttribute("open");
    expect(document.getElementById("discovery-source-tc-scope")).toHaveTextContent("μ* = 0.1");
    expect(document.getElementById("discovery-source-tc-scope")).toHaveTextContent("Experimental and room-temperature superconductivity are unknown");
    expect(screen.getByRole("columnheader", { name: "Material" })).not.toHaveAttribute("aria-sort");
    expect(screen.getByRole("link", { name: "Download catalogue JSON" })).toHaveAttribute("href", catalogue.download_url);
    expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("allows every candidate to be reached once across all five pages without a score or Tc sort", () => {
    render(<DiscoverySourceCandidates catalogue={catalogue} />);
    const visited: (string | undefined)[] = [];
    for (let page = 1; page <= 5; page++) {
      expect(screen.getByText(`Page ${page} of 5`)).toBeInTheDocument();
      visited.push(...rowIds());
      if (page < 5) fireEvent.click(screen.getByRole("button", { name: "Next materials" }));
    }
    expect(visited).toEqual(sorted.map(candidate => candidate.id));
    expect(new Set(visited).size).toBe(103);
    expect(rows()).toHaveLength(7);
    expect(screen.getByRole("button", { name: "Next materials" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Go to page" }), { target: { value: "2" } });
    expect(rowIds()).toEqual(sorted.slice(24, 48).map(candidate => candidate.id));
    allRows(); expect(rowIds()).toEqual(sorted.map(candidate => candidate.id));
    expect(screen.getByRole("combobox", { name: "Browse order" })).toHaveValue("priority");
    fireEvent.change(screen.getByRole("combobox", { name: "Browse order" }), { target: { value: "formula" } });
    expect(rowIds()).toEqual([...catalogue.candidates].sort((a, b) => order.compare(a.formula, b.formula)).map(candidate => candidate.id));
    expect(screen.getByRole("columnheader", { name: "Material" })).toHaveAttribute("aria-sort", "ascending");
  });

  it("identifies the three particular source phases without assigning them to every related composition", () => {
    render(<DiscoverySourceCandidates catalogue={catalogue} />); allRows();
    const phases = [
      ["agm002028410", "Ti", "FCC source phase"],
      ["agm003157370", "TiZr", "Ordered tetragonal source phase"],
      ["agm001192155", "MoH", "B1 / rock-salt source phase"],
    ];
    expect(document.querySelectorAll(".discovery-source-phase")).toHaveLength(3);
    for (const [state, formula, caption] of phases) {
      const candidate = catalogue.candidates.find(item => item.source_state === state)!;
      expect(candidate.formula).toBe(formula);
      const row = rows().find(item => item.dataset.sourceCandidate === candidate.id)!;
      expect(within(row).getByRole("rowheader")).toHaveTextContent(caption);
    }
    const otherTi = rows().find(row => row.dataset.formula === "Ti3Ge")!;
    expect(otherTi.querySelector(".discovery-source-phase")).toBeNull();
  });

  it("changes the research target without treating source Tc as support for room-temperature superconductivity", () => {
    render(<DiscoverySourceCandidates catalogue={catalogue} />); allRows();
    fireEvent.change(screen.getByRole("combobox", { name: "Research target" }), { target: { value: "ambient_300K" } });
    expect(rowIds()).toEqual([...catalogue.candidates].sort((a, b) => order.compare(a.formula, b.formula)).map(candidate => candidate.id));
    expect(screen.getAllByText("No direct target support")).toHaveLength(103);
    expect(document.querySelectorAll(".discovery-source-detail-row")).toHaveLength(0);
  });

  it("filters composition concerns against real tags, preserving Tc values and formula order", () => {
    render(<DiscoverySourceCandidates catalogue={catalogue} />);
    const concerned = sorted.filter(candidate => candidate.risk_tags.includes("technetium"));
    expect(concerned.length).toBeGreaterThan(0);
    allRows();
    fireEvent.change(screen.getByRole("combobox", { name: "Composition or model concern" }), { target: { value: "technetium" } });
    expect(rowIds()).toEqual(concerned.map(candidate => candidate.id));
    expect(screen.getByRole("status")).toHaveTextContent(`${concerned.length} / 103 materials`);
    for (const row of rows()) {
      const candidate = concerned.find(item => item.id === row.dataset.sourceCandidate)!;
      expect(within(row).getByText(candidate.source_tc.target_K.toLocaleString("en-US", { maximumFractionDigits: 3 }))).toBeInTheDocument();
      expect(within(row).getByText("C · E1")).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(rows()).toHaveLength(103);
  });

  it("normalizes chemical subscripts, searches all pages and recovers from an empty result", () => {
    render(<DiscoverySourceCandidates catalogue={catalogue} />);
    const query = screen.getByRole("searchbox", { name: "Find a source candidate" });
    fireEvent.change(query, { target: { value: "ti₃ge" } });
    expect(rows().map(row => row.dataset.formula)).toEqual(["Ti3Ge"]);
    fireEvent.change(query, { target: { value: sorted[102].source_state.toLowerCase() } });
    expect(rowIds()).toEqual([sorted[102].id]);
    fireEvent.change(query, { target: { value: "<script>missing-material</script>" } });
    expect(rows()).toHaveLength(0);
    expect(screen.getByText("No source candidates match this search and concern tag.")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all materials" }));
    expect(rows()).toHaveLength(24); expect(query).toHaveValue("");
  });

  it("fetches only requested evidence, preserves original control signs and restores trigger focus", async () => {
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    const candidate = sorted[0];
    const bytes = sourceBytes(candidate), full = JSON.parse(bytes.toString("utf8")).candidate;
    const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(staticResponse(url))); vi.stubGlobal("fetch", fetch);
    const trigger = screen.getByRole("button", { name: `Show details for ${candidate.formula}` });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Loading and verifying source evidence…")).toBeInTheDocument();
    await screen.findByText("Source calculation and selected control");
    const detail = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    expect(detail).toHaveTextContent(candidate.source_state);
    expect(detail).toHaveTextContent(candidate.control_state);
    expect(detail).toHaveTextContent(full.next_action);
    expect(detail).toHaveTextContent(full.risk_summary);
    expect(container.querySelectorAll(".discovery-source-detail-row")).toHaveLength(1);
    expect(detail.querySelectorAll("details")).toHaveLength(3);
    for (const disclosure of detail.querySelectorAll("details")) expect(disclosure).not.toHaveAttribute("open");
    const evidence = JSON.parse(detail.querySelector("pre")!.textContent!);
    expect(evidence).toEqual(full);
    expect(evidence.formal_RPS).toBeNull(); expect(evidence.source_tc.sigma_binding).toBeNull();
    fireEvent.click(within(detail).getByRole("button", { name: `Close details for ${candidate.formula}` }));
    expect(trigger).toHaveFocus(); expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelectorAll(".discovery-source-detail-row")).toHaveLength(0);
    fireEvent.click(trigger); await screen.findByText("Source calculation and selected control");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenCalledWith(candidate.detail.url, expect.objectContaining({ credentials: "omit", cache: "no-store", redirect: "error" }));
  });

  it("shows a local error for a corrupted detail and succeeds only after explicit retry", async () => {
    const candidate = sorted[0], bytes = sourceBytes(candidate), corrupt = new Uint8Array(bytes); corrupt[0] ^= 1;
    let corruptRead = true;
    const fetch = vi.fn().mockImplementation((url: string) => {
      if (url === candidate.detail.url && corruptRead) { corruptRead = false; return Promise.resolve(response(corrupt)); }
      return Promise.resolve(staticResponse(url));
    }); vi.stubGlobal("fetch", fetch);
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    fireEvent.click(screen.getByRole("button", { name: `Show details for ${candidate.formula}` }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(container.querySelector(".discovery-source-detail pre")).toBeNull();
    expect(rows()).toHaveLength(24); expect(fetch).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Retry source evidence" }));
    await screen.findByText("Source calculation and selected control"); expect(fetch).toHaveBeenCalledTimes(4);
  });

  it("labels relative percent coupling separately from an absolute lambda difference", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(staticResponse(url))));
    render(<DiscoverySourceCandidates catalogue={catalogue} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: "Nb6GaRh" } });
    fireEvent.click(screen.getByRole("button", { name: "Show details for Nb6GaRh" }));
    await screen.findByText("Decision bottleneck");
    const controls = document.querySelector(".discovery-source-counterevidence")!;
    expect(controls).toHaveTextContent("Relative λ change (target vs control): -34.54 to -14.541 %");
    expect(controls).not.toHaveTextContent("λ target minus control:");
  });

  it("cancels a pending detail when its row closes and does not show stale evidence", async () => {
    const candidate = sorted[0];
    let release: (value: Response) => void = () => {};
    const fetch = vi.fn().mockImplementation((url: string) => url === candidate.detail.url
      ? new Promise<Response>(resolve => { release = resolve; }) : Promise.resolve(staticResponse(url))); vi.stubGlobal("fetch", fetch);
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    fireEvent.click(screen.getByRole("button", { name: `Show details for ${candidate.formula}` }));
    const signal = fetch.mock.calls[0][1].signal as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: `Close details for ${candidate.formula}` }));
    expect(signal.aborted).toBe(true);
    await act(async () => release(response(sourceBytes(candidate))));
    expect(container.querySelectorAll(".discovery-source-detail-row")).toHaveLength(0);
    expect(screen.queryByText("Source calculation and selected control")).not.toBeInTheDocument();
  });

  it("rejects external detail URLs and incomplete or oversized response bodies", async () => {
    const candidate = sorted[0], bytes = sourceBytes(candidate);
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(readSourceHypothesisDetail({ ...candidate, detail: { ...candidate.detail, url: "https://example.com/detail.json" } }, new AbortController().signal)).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockResolvedValueOnce(response(bytes.subarray(0, bytes.length - 1)));
    await expect(readSourceHypothesisDetail(candidate, new AbortController().signal)).rejects.toThrow("Incomplete");
    fetch.mockResolvedValueOnce(response(new Uint8Array(bytes.length + 1)));
    await expect(readSourceHypothesisDetail(candidate, new AbortController().signal)).rejects.toThrow("pinned size");
  });

  it("keeps searches when visiting the separate RPS and coordinate research tab", () => {
    render(<DiscoveryTabs candidates={<DiscoverySourceCandidates catalogue={catalogue} />} research={<>
      <DiscoveryDisclosure id="discovery-formal-assessments" summary="Published RPS"><p>Formal assessment service</p></DiscoveryDisclosure>
      <DiscoveryDisclosure id="discovery-coordinate-proposals" summary="COD coordinate proposals"><p>Separate coordinate catalogue</p></DiscoveryDisclosure>
    </>} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: "Ti3Ge" } });
    const scope = document.querySelector<HTMLDetailsElement>(".discovery-source-scope")!; scope.open = true;
    fireEvent.click(within(scope).getByRole("link", { name: "Research & tools" }));
    expect(screen.getByRole("tab", { name: "Research & tools" })).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById("discovery-formal-assessments")).toHaveAttribute("open");
    fireEvent.click(screen.getByRole("tab", { name: "Candidates", exact: true }));
    expect(screen.getByRole("searchbox", { name: "Find a source candidate" })).toHaveValue("Ti3Ge");
    expect(rowIds()).toEqual([catalogue.candidates.find(candidate => candidate.formula === "Ti3Ge")!.id]);
  });

  it("hydrates the frozen real catalogue without changing row order or auto-opening details", async () => {
    const element = document.createElement("div");
    element.innerHTML = renderToString(<DiscoverySourceCandidates catalogue={catalogue} />); document.body.append(element);
    const recoverable = vi.fn(); let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(element, <DiscoverySourceCandidates catalogue={catalogue} />, { onRecoverableError: recoverable }); });
      expect(recoverable).not.toHaveBeenCalled();
      expect(rowIds()).toEqual(sorted.slice(0, 24).map(candidate => candidate.id));
      expect(element.querySelectorAll(".discovery-source-detail-row")).toHaveLength(0);
    } finally { await act(async () => root?.unmount()); element.remove(); }
  });
});
