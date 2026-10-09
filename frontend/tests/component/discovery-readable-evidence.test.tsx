import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverySourceCandidates } from "@/components/DiscoverySourceCandidates";
import { compareResearchPriority, sourceSupport, verifyDiscoveryEvidenceCard } from "@/lib/discovery-evidence-policy";
import { getSourceHypothesisBrowseCatalogue } from "@/lib/discovery-source-hypotheses";
import { verifySourceHypothesisDetail } from "@/lib/discovery-source-hypothesis-detail";
import { readReadableEvidence } from "@/lib/discovery-readable-evidence";
import companion from "@/lib/resources/discovery-readable-evidence-2026-10-09.json";

const catalogue = getSourceHypothesisBrowseCatalogue();
const bytes = (url: string) => readFileSync(join(process.cwd(), "public", url));
const hash = (value: string | Uint8Array) => createHash("sha256").update(value).digest("hex");
const copy = () => structuredClone(companion);
const candidateFor = (formula: string) => catalogue.candidates.find(item => item.formula === formula)!;
async function verified(formula = "TiZr3") {
  const candidate = candidateFor(formula);
  const [detail, card] = await Promise.all([
    verifySourceHypothesisDetail(bytes(candidate.detail.url), candidate),
    verifyDiscoveryEvidenceCard(bytes(candidate.research_evidence.detail.url), candidate),
  ]);
  return { candidate, detail: detail.candidate, card };
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Pinned readable Discovery evidence", () => {
  it("covers exactly the 21 reviewed fields in nine materials and preserves every public source pin", async () => {
    expect(companion.entries).toHaveLength(21);
    expect(new Set(companion.entries.map(entry => entry.formula))).toEqual(new Set([
      "Ti2ZrW", "TiTa2W", "TiTa3", "TiZr3", "ZrTc2", "Cr2Tc", "ScZr3N4", "YZr3N4", "ZrNb2Ta",
    ]));
    expect(hash(bytes(catalogue.download_url))).toBe("4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98");
    const sourceBefore = JSON.stringify(catalogue);
    const priorities = ["source_pairing", "ambient_300K"] as const;
    const orderBefore = priorities.map(goal => [...catalogue.candidates].sort((a, b) => compareResearchPriority(a, b, goal)).map(item => item.id));
    for (const candidate of catalogue.candidates) {
      const { detail, card } = await verified(candidate.formula);
      const detailBefore = JSON.stringify(detail), cardBefore = JSON.stringify(card);
      expect(hash(bytes(candidate.detail.url))).toBe(candidate.detail.sha256);
      expect(hash(bytes(candidate.research_evidence.detail.url))).toBe(candidate.research_evidence.detail.sha256);
      const display = await readReadableEvidence(candidate, detail, card);
      const entries = companion.entries.filter(entry => entry.id === candidate.id);
      expect(Object.keys(display)).toHaveLength(entries.length);
      for (const entry of entries) {
        const field = entry.field as keyof typeof display;
        expect(display[field]?.text).toBe(entry.text);
        expect(hash(display[field]!.original)).toBe(entry.original_text_sha256);
        expect(entry.text).not.toMatch(/[\u3400-\u9fff]|—/);
      }
      expect(JSON.stringify(detail)).toBe(detailBefore);
      expect(JSON.stringify(card)).toBe(cardBefore);
      for (const goal of priorities) expect(sourceSupport(candidate.research_evidence, goal)).toMatchObject({ grade: "C", evidence_level: "E1" });
      expect(detail.formal_RPS).toBeNull(); expect(detail.experimental_superconductivity).toBeNull();
    }
    expect(JSON.stringify(catalogue)).toBe(sourceBefore);
    expect(priorities.map(goal => [...catalogue.candidates].sort((a, b) => compareResearchPriority(a, b, goal)).map(item => item.id))).toEqual(orderBefore);
  });

  it("fails closed for stale identity, source, dossier or field pins without partial candidate copy", async () => {
    const { candidate, detail, card } = await verified();
    for (const [key, value] of [
      ["id", "source-hypothesis:agm999999999"], ["source_state", "agm999999999"], ["formula", "TiZr"],
      ["dossier_sha256", "0".repeat(64)], ["source_detail_sha256", "0".repeat(64)], ["original_text_sha256", "0".repeat(64)],
    ]) {
      const changed = copy();
      Object.assign(changed.entries.find(entry => entry.id === candidate.id)!, { [key]: value });
      expect(await readReadableEvidence(candidate, detail, card, changed)).toEqual({});
    }
    expect(await readReadableEvidence({ ...candidate, formula: "TiZr" }, detail, card)).toEqual({});
    expect(await readReadableEvidence(candidate, { ...detail, source_state: "agm999999999" }, card)).toEqual({});
    expect(await readReadableEvidence(candidate, detail, { ...card, id: "other" })).toEqual({});
    const changedCard = structuredClone(card); changedCard.bottleneck.summary += " changed";
    expect(await readReadableEvidence(candidate, detail, changedCard)).toEqual({});
    const changedDetail = structuredClone(detail); changedDetail.risk_summary += " changed";
    expect(await readReadableEvidence(candidate, changedDetail, card)).toEqual({});
  });

  it("rejects unknown schema, duplicate fields, scientific write keys and invalid display prose", async () => {
    const { candidate, detail, card } = await verified();
    const altered = [
      { ...copy(), version: "future" }, { ...copy(), schema_version: "future" }, { ...copy(), source_catalogue_sha256: "0".repeat(64) },
      { ...copy(), score: 100 }, { ...copy(), entries: null },
    ];
    for (const data of altered) expect(await readReadableEvidence(candidate, detail, card, data)).toEqual({});
    for (const extra of [{ field: "source_tc.target_K" }, { score: 100 }, { text: "" }, { text: "中文" }, { text: "x".repeat(1601) }]) {
      const data = copy(); Object.assign(data.entries.find(entry => entry.id === candidate.id)!, extra);
      expect(await readReadableEvidence(candidate, detail, card, data)).toEqual({});
    }
    const duplicate = copy(); duplicate.entries.push({ ...duplicate.entries.find(entry => entry.id === candidate.id)! });
    expect(await readReadableEvidence(candidate, detail, card, duplicate)).toEqual({});
    vi.stubGlobal("crypto", {});
    expect(await readReadableEvidence(candidate, detail, card)).toEqual({});
  });

  it("binds ambient copy to the actually displayed detail field as well as its dossier copy", async () => {
    const { candidate, detail, card } = await verified();
    const entry = companion.entries.find(item => item.id === candidate.id)!;
    const data = { ...copy(), entries: [{ ...entry, field: "bottleneck.ambient_scope", original_text_sha256: hash(detail.ambient_scope), text: "Test-only ambient paraphrase." }] };
    expect((await readReadableEvidence(candidate, detail, card, data))["bottleneck.ambient_scope"]).toEqual({ text: "Test-only ambient paraphrase.", original: detail.ambient_scope });
    expect(await readReadableEvidence(candidate, { ...detail, ambient_scope: "Changed original detail" }, card, data)).toEqual({});
    expect(await readReadableEvidence(candidate, detail, { ...card, bottleneck: { ...card.bottleneck, ambient_scope: "Changed dossier" } }, data)).toEqual({});
  });

  it("shows reader copy only after verified expansion, with exact originals closed by default", async () => {
    const { candidate, detail } = await verified();
    const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(bytes(url), { headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    expect(screen.queryByText("Reader’s summary")).not.toBeInTheDocument();
    expect(screen.queryByText("Original source notes")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: candidate.source_state } });
    const trigger = screen.getByRole("button", { name: "Show details for TiZr3" });
    fireEvent.click(trigger);
    await screen.findByText("Reader’s summary");
    expect(fetch).toHaveBeenCalledTimes(2);
    const notes = container.querySelector<HTMLDetailsElement>(".discovery-source-original-notes")!;
    expect(notes).not.toHaveAttribute("open");
    const fields = [...notes.querySelectorAll("dd")].map(item => item.textContent);
    expect(fields).toEqual(companion.entries.filter(entry => entry.id === candidate.id).map(entry => {
      if (entry.field === "prior.case_context") return detail.seven_criteria.novelty;
      if (entry.field === "bottleneck.summary") return detail.risk_summary;
      if (entry.field === "proposed_contribution.intervention") return detail.route_response;
      return detail.next_action;
    }));
    for (const entry of companion.entries.filter(item => item.id === candidate.id)) expect(screen.getByText(entry.text)).toBeInTheDocument();
    fireEvent.click(within(notes).getByText("Original source notes"));
    expect(notes).toHaveAttribute("open");
    expect(container.querySelector(".discovery-source-detail pre")!.textContent).toBe(JSON.stringify(detail, null, 2));
    expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/);
    fireEvent.click(screen.getByRole("button", { name: "Close details for TiZr3" }));
    expect(trigger).toHaveFocus(); expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Reader’s summary")).not.toBeInTheDocument();
  });

  it("never exposes reader copy when source verification fails", async () => {
    const candidate = candidateFor("TiZr3");
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      const body = new Uint8Array(bytes(url)); if (url === candidate.detail.url) body[0] ^= 1;
      return Promise.resolve(new Response(body, { headers: { "content-type": "application/json" } }));
    }));
    render(<DiscoverySourceCandidates catalogue={catalogue} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: candidate.source_state } });
    fireEvent.click(screen.getByRole("button", { name: "Show details for TiZr3" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByText("Reader’s summary")).not.toBeInTheDocument();
    expect(screen.queryByText("Original source notes")).not.toBeInTheDocument();
  });

  it("does not reopen a row closed during display-copy hashing", async () => {
    const candidate = candidateFor("TiZr3");
    let release: () => void = () => {};
    const pending = new Promise<void>(resolve => { release = resolve; });
    let calls = 0;
    const digest = vi.fn(async (algorithm: AlgorithmIdentifier, value: BufferSource) => {
      if (++calls === 3) await pending;
      return webcrypto.subtle.digest(algorithm, value as Uint8Array);
    });
    vi.stubGlobal("crypto", { subtle: { digest } });
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(bytes(url), { headers: { "content-type": "application/json" } }))));
    const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: candidate.source_state } });
    fireEvent.click(screen.getByRole("button", { name: "Show details for TiZr3" }));
    await waitFor(() => expect(digest).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole("button", { name: "Close details for TiZr3" }));
    await act(async () => { release(); });
    await waitFor(() => expect(digest).toHaveBeenCalledTimes(6));
    expect(container.querySelector(".discovery-source-detail-row")).toBeNull();
    expect(screen.queryByText("Reader’s summary")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show details for TiZr3" })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps verified originals readable when the companion becomes stale", async () => {
    const { candidate, detail } = await verified();
    const entry = companion.entries.find(item => item.id === candidate.id)!;
    const originalPin = entry.original_text_sha256;
    entry.original_text_sha256 = "0".repeat(64);
    try {
      vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(bytes(url), { headers: { "content-type": "application/json" } }))));
      const { container } = render(<DiscoverySourceCandidates catalogue={catalogue} />);
      fireEvent.change(screen.getByRole("searchbox", { name: "Find a source candidate" }), { target: { value: candidate.source_state } });
      const rowBefore = container.querySelector("tr[data-source-candidate]")!.textContent;
      fireEvent.click(screen.getByRole("button", { name: "Show details for TiZr3" }));
      await screen.findByText("Source calculation and selected control");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByText("Reader’s summary")).not.toBeInTheDocument();
      expect(screen.queryByText("Original source notes")).not.toBeInTheDocument();
      expect(container.querySelector(".discovery-source-dossier")).toHaveTextContent(detail.risk_summary);
      expect(container.querySelector(".discovery-source-dossier")).toHaveTextContent(detail.next_action);
      expect(container.querySelector("tr[data-source-candidate]")!.textContent).toBe(rowBefore!.replace("Details", "Hide details"));
    } finally { entry.original_text_sha256 = originalPin; }
  });
});
