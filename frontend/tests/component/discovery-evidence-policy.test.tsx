import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";
import { assessSupport, compareResearchPriority, commonWeights, sourceSupport, verifyDiscoveryEvidenceCard } from "@/lib/discovery-evidence-policy";
import type { AxisEvidence, SupportAxis } from "@/lib/discovery-evidence-policy";
import { getSourceHypothesisBrowseCatalogue, getSourceHypothesisCatalogue } from "@/lib/discovery-source-hypotheses";
import { loadDiscoveryEvidenceSummaries } from "@/lib/discovery-evidence-cards";

vi.stubGlobal("crypto", webcrypto);
afterAll(() => vi.unstubAllGlobals());
const browse = getSourceHypothesisBrowseCatalogue(), frozen = getSourceHypothesisCatalogue();
const row = (formula: string) => browse.candidates.find(item => item.formula === formula)!;
const bytes = (url: string) => readFileSync(join(process.cwd(), "public", url));
const card = (formula: string) => JSON.parse(bytes(row(formula).research_evidence.detail.url).toString("utf8"));

describe("Discovery provisional P/E/N contracts", () => {
  it("covers every exact source state once and preserves immutable source values and unknowns", async () => {
    expect(createHash("sha256").update(bytes("/research-hypotheses/source-computed-candidates-2026-10-07.json")).digest("hex"))
      .toBe("4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98");
    expect(new Set(browse.candidates.map(item => item.source_state)).size).toBe(103);
    for (const candidate of browse.candidates) {
      const dossier = await verifyDiscoveryEvidenceCard(bytes(candidate.research_evidence.detail.url), candidate);
      const original = frozen.candidates.find(item => item.id === candidate.id)!;
      expect(dossier.prior.summary).toBe(original.newness_scope);
      expect(dossier.prior.case_context).toBe(original.seven_criteria.novelty);
      expect(dossier.bottleneck.summary).toBe(original.risk_summary);
      expect(dossier.proposed_contribution.next_action).toBe(original.next_action);
      expect(dossier.evidence_level).toBe("E1");
      expect(dossier.prior.exact_experimental_status).toBe("unresolved");
      expect(dossier.prior.search_completeness).toBe("unknown");
      expect(original.formal_RPS).toBeNull(); expect(original.experimental_superconductivity).toBeNull();
      expect(candidate.source_tc).toEqual(original.source_tc);
      expect(JSON.stringify(dossier)).not.toMatch(/\/Users\/|\/home\/|jack@|api_key|password|private_key|[\u3400-\u9fff]/);
    }
  });

  it("does not turn old support 3/4 into P75, or unknown axes into quantified coverage", () => {
    for (const candidate of browse.candidates) {
      const support = sourceSupport(candidate.research_evidence, "source_pairing");
      expect(candidate.support_grade).toBe(3);
      expect(support).toMatchObject({ grade: "C", evidence_level: "E1", lower: 6.25, upper: 87.5, coverage_percent: 25 });
      expect(Object.values(support.axes).filter(axis => axis.quantified_for_goal)).toHaveLength(1);
      const room = sourceSupport(candidate.research_evidence, "ambient_300K");
      expect(room).toMatchObject({ grade: "C", lower: 0, upper: 100, coverage_percent: 0, target_fit: "no_direct_support" });
      expect(room.axes.pairing.scope).toContain("broader material feasibility remains unassessed");
    }
  });

  it("cannot hide definite adverse evidence behind high support on other axes", () => {
    const axes = Object.fromEntries(Object.keys(commonWeights).map(axis => [axis,
      { anchor: "robust_positive", quantified_for_goal: true, scope: "Synthetic contract fixture, not a material claim" }])) as Record<SupportAxis, AxisEvidence>;
    expect(assessSupport(axes, "source_pairing", "E3").grade).toBe("A");
    axes.competition = { anchor: "adverse", quantified_for_goal: true, scope: "Specific target condition has adverse competition evidence" };
    const constrained = assessSupport(axes, "source_pairing", "E3");
    expect(constrained.lower).toBe(67.5); expect(constrained.grade).toBe("C"); expect(constrained.adverse_axes).toEqual(["competition"]);
    axes.competition = { anchor: "unknown", quantified_for_goal: false, scope: "Unknown" };
    expect(assessSupport(axes, "source_pairing", "E1").grade).toBe("C");
    expect(assessSupport(axes, "source_pairing", "E3", false).grade).toBe("U");
    axes.pairing = { anchor: "source_pairing", quantified_for_goal: true, scope: "Source-only low-T chain" };
    expect(() => assessSupport(axes, "ambient_300K", "E1")).toThrow("does not correspond");
    axes.pairing = { anchor: "unknown", quantified_for_goal: true, scope: "Bad coverage assertion" };
    expect(() => assessSupport(axes, "source_pairing", "E1")).toThrow("cannot count");
  });

  it("retains comparator-specific adverse and discordant evidence, without rejecting the composition", () => {
    const nb = card("Nb6GaSb");
    expect(nb.bottleneck.counterevidence.some((item: { direction: string; source_tc_target_minus_control_K: number }) =>
      item.direction === "joint_adverse" && Math.abs(item.source_tc_target_minus_control_K + 1.017) < 1e-9)).toBe(true);
    const ti = card("TiZr3");
    expect(ti.bottleneck.counterevidence).toEqual(expect.arrayContaining([expect.objectContaining({ direction: "discordant",
      source_tc_target_minus_control_K: expect.closeTo(0.608, 12) })]));
    expect(card("TiZr").bottleneck.summary).toContain("23.25");
    expect(card("ScZr2").bottleneck.counterevidence).toEqual(expect.arrayContaining([expect.objectContaining({
      comparison_origin: "selected_source_control", countercontrol_index: null, direction: "discordant" })]));
    expect(row("TiZr").risk_tags).toEqual([]); // An empty element tag list does not clear its actual bottleneck.
    expect(nb.proposed_contribution.status).toBe("proposed_not_completed");
  });

  it("keeps element concerns as attention, target-specific groups and deterministic complete ties", () => {
    const clean = row("YNbN2"), constrained = row("Nb6GaRh");
    expect(compareResearchPriority(clean, constrained, "source_pairing")).toBeLessThan(0);
    expect(compareResearchPriority(clean, { ...constrained, source_tc: { ...constrained.source_tc, target_K: 999 } }, "source_pairing")).toBeLessThan(0);
    // Source comparator limits cannot be projected to room-temperature physics.
    const roomOrder = [...browse.candidates].sort((a, b) => compareResearchPriority(a, b, "ambient_300K"));
    const formulaOrder = [...browse.candidates].sort((a, b) => new Intl.Collator("en-US", { numeric: true, sensitivity: "base" }).compare(a.formula, b.formula));
    expect(roomOrder.map(item => item.id)).toEqual(formulaOrder.map(item => item.id));
    const changedAttention = { ...clean, risk_tags: ["magnetic_model", "hydrogen_anharmonicity"] as typeof clean.risk_tags };
    expect(compareResearchPriority(clean, changedAttention, "source_pairing")).toBe(0);
    const order = [...browse.candidates].sort((a, b) => compareResearchPriority(a, b, "source_pairing"));
    expect(new Set(order.map(item => item.id)).size).toBe(103);
  });

  it("rejects duplicates, wrong identities, corrupt card bytes and transplanted hash-valid cards", async () => {
    const details = new Map(browse.candidates.map(item => [item.id, item.detail]));
    const duplicates = [...browse.candidates]; duplicates[1] = duplicates[0];
    expect(() => loadDiscoveryEvidenceSummaries(duplicates, details)).toThrow();
    const first = browse.candidates[0], second = browse.candidates[1];
    const corrupt = Buffer.from(bytes(first.research_evidence.detail.url)); corrupt[0] ^= 1;
    await expect(verifyDiscoveryEvidenceCard(corrupt, first)).rejects.toThrow();
    await expect(verifyDiscoveryEvidenceCard(bytes(second.research_evidence.detail.url), { ...first, research_evidence: second.research_evidence })).rejects.toThrow();
  });
});
