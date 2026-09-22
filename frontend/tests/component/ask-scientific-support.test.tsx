import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AskSupportNotice } from "@/components/AskSupportNotice";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { AskHistoryList } from "@/components/dashboard/AskHistoryList";
import { displayedAskSupportStatus, resolveAskSource, supportEvidenceSource, supportStatusLabel } from "@/lib/ask-support";
import type { AskResponse, AskSource } from "@/lib/api";
import { sourceVisibility } from "../fixtures/material-visibility";

const source: AskSource = { index: 1, paper_id: "doi:10.0000/synthetic", arxiv_id: null, title: "Synthetic source — 测试材料", authors_short: "Synthetic author", year: 2026, section: "Results", snippet: "Nb has a reported Tc of 9.2 K.", source_visibility: sourceVisibility() };
function response(patch: Partial<AskResponse> = {}): AskResponse {
  return { answer: "Nb has a reported Tc of 9.2 K [1].", sources: [source], tokens_used: 10, query_time_ms: 20, citation_valid: true, citation_warnings: [], guest_remaining: null, remaining: null, support_policy_version: "scientific-claim-support/1.0.0", citation_indices_valid: true, lexical_support_checked: true, scientific_support_status: "supported", answer_mode: "synthesis", assessment_scope: "generated_draft", support_warnings: [], support_coverage: { total_claims: 1, assessed_claims: 1, supported_claims: 1, contradicted_claims: 0, undetermined_claims: 0, truncated: false, limits: { claims: 32 } }, claim_assessments: [{ claim_id: "claim:1", text: "Nb has a reported Tc of 9.2 K [1].", cited_indices: [1], status: "supported", reason_codes: ["reported_tuple_matches_excerpt"], evidence: [{ source_index: 1, paper_id: source.paper_id, excerpt: source.snippet }] }], ...patch };
}

describe("scientific-support metadata compatibility and attribution", () => {
  it("never promotes the legacy citation_valid flag into scientific support", () => {
    const old = response({ support_policy_version: undefined, citation_indices_valid: undefined, lexical_support_checked: undefined, scientific_support_status: undefined, claim_assessments: undefined, support_coverage: undefined, answer_mode: undefined, assessment_scope: undefined });
    expect(displayedAskSupportStatus(old)).toBe("not_checked");
    render(<AskSupportNotice response={old} />);
    expect(screen.getByRole("status")).toHaveTextContent("Scientific support not checked");
    expect(screen.getByText(/legacy citation_valid flag is only a mechanical check/)).toBeInTheDocument();
    expect(screen.getByText(/Assessment coverage was not supplied/)).toBeInTheDocument();
    expect(screen.queryByText("Excerpt consistency checks passed")).not.toBeInTheDocument();
  });
  it.each(["scientific-claim-support/99.0.0", undefined])("does not trust unknown policy %s", policy => {
    expect(displayedAskSupportStatus(response({ support_policy_version: policy }))).toBe("not_checked");
  });
  it("keeps mechanically valid citations separate from contradicted draft claims", () => {
    const input = response({ scientific_support_status: "contradicted", answer_mode: "abstention" });
    input.claim_assessments![0].status = "contradicted";
    input.claim_assessments![0].text = "Nb has a Tc of 90 K [1].";
    input.claim_assessments![0].reason_codes = ["tc_value_conflict"];
    render(<AskSupportNotice response={input} />);
    expect(screen.getByRole("status")).toHaveTextContent("Draft claim checks: Excerpt checks found a conflict");
    expect(screen.getByText(/Citation indices: mechanically valid/)).toBeInTheDocument();
    expect(screen.getByText(/Abstention — no supported synthesis provided/)).toBeInTheDocument();
    expect(screen.getByText(/generated draft, not a verification of any delivered fallback/)).toBeInTheDocument();
  });
  it("uses narrow consistency wording for attributable, supported excerpt checks", () => {
    render(<AskSupportNotice response={response()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Excerpt consistency checks passed");
    expect(screen.getByText(/do not establish scientific truth, experimental confirmation/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Source [1]", hidden: true })).toHaveAttribute("href", "#src-1");
    expect(screen.getByRole("link", { name: /Synthetic source/, hidden: true })).toHaveAttribute("href", "/paper/doi%3A10.0000%2Fsynthetic");
    expect(screen.getByText(/Active bibliographic source — not scientific approval/)).toBeInTheDocument();
  });
  it.each(["undetermined", "not_checked"] as const)("distinguishes %s from support", status => {
    render(<AskSupportNotice response={response({ scientific_support_status: status, lexical_support_checked: status !== "not_checked" })} />);
    expect(screen.getByRole("status")).toHaveTextContent(supportStatusLabel(status));
  });
  it("does not replace an undetermined scientific check with the independent lexical flag", () => {
    const input = response({ scientific_support_status: "undetermined", lexical_support_checked: false, citation_indices_valid: false });
    expect(displayedAskSupportStatus(input)).toBe("undetermined");
    render(<AskSupportNotice response={input} />);
    expect(screen.getByRole("status")).toHaveTextContent("Scientific support remains undetermined");
    expect(screen.getByText(/Lexical excerpt checks: not established/)).toBeInTheDocument();
  });
  it("does not invent an assessment for a no-source abstention", () => {
    render(<AskSupportNotice response={response({ sources: [], claim_assessments: [], scientific_support_status: "not_checked", lexical_support_checked: false, assessment_scope: "none", answer_mode: "abstention" })} />);
    expect(screen.getByText("No retrieved sources are available for inspection.")).toBeInTheDocument();
    expect(screen.getByText(/No generated draft was assessed/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Scientific support not checked");
  });
  it("does not label extractive fallback as verified generated conclusions", () => {
    render(<AskSupportNotice response={response({ scientific_support_status: "undetermined", answer_mode: "extractive_fallback" })} />);
    expect(screen.getByText(/Extractive fallback — retrieved excerpts, not a validated answer/)).toBeInTheDocument();
    expect(screen.getByText(/Source excerpts are not verified conclusions/)).toBeInTheDocument();
  });
  it("requires nonempty and attributable claim evidence before showing support", () => {
    expect(displayedAskSupportStatus(response({ claim_assessments: [] }))).toBe("undetermined");
    expect(displayedAskSupportStatus(response({ sources: [] }))).toBe("undetermined");
    const wrong = response();
    wrong.claim_assessments![0].evidence[0].paper_id = "doi:unrelated";
    expect(displayedAskSupportStatus(wrong)).toBe("undetermined");
    render(<AskSupportNotice response={wrong} />);
    expect(screen.getByText(/Evidence source could not be matched/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Synthetic source/, hidden: true })).not.toBeInTheDocument();
  });
  it("does not assume checks apply to the answer when assessment_scope is absent", () => {
    expect(displayedAskSupportStatus(response({ assessment_scope: undefined }))).toBe("not_checked");
    render(<AskSupportNotice response={response({ assessment_scope: undefined })} />);
    expect(screen.getByText(/Assessment scope was not supplied/)).toBeInTheDocument();
  });
  it("requires unique positive integer indices and matching paper identity", () => {
    expect(resolveAskSource(1, [source])).toEqual(source);
    for (const index of [0, -1, 1.5, "1", NaN, Infinity]) expect(resolveAskSource(index, [source])).toBeNull();
    expect(resolveAskSource(1, [source, { ...source, paper_id: "doi:other" }])).toBeNull();
    expect(supportEvidenceSource(1, "doi:other", [source])).toBeNull();
    expect(supportEvidenceSource(1, null, [source])).toBeNull();
  });
  it("shows truncation and bounded coverage without claiming complete verification", () => {
    render(<AskSupportNotice response={response({ scientific_support_status: "undetermined", support_coverage: { total_claims: 40, assessed_claims: 32, supported_claims: 2, contradicted_claims: 0, undetermined_claims: 30, truncated: true, limits: { claims: 32, source_chars: 6000 } } })} />);
    expect(screen.getByText("Bounded assessment coverage — incomplete")).toBeInTheDocument();
    expect(screen.getByText(/unchecked portions remain unresolved/)).toBeInTheDocument();
    expect(screen.getByText(/not coverage of every scientific assertion/)).toBeInTheDocument();
  });
  it("does not display support from a contradictory truncated envelope", () => {
    expect(displayedAskSupportStatus(response({ support_coverage: { truncated: true } }))).toBe("undetermined");
  });
  it.each([
    { citation_indices_valid: false },
    { citation_indices_valid: undefined },
    { support_coverage: undefined },
    { support_coverage: {} },
    { support_coverage: { total_claims: 2, assessed_claims: 1, supported_claims: 1, contradicted_claims: 0, undetermined_claims: 0, truncated: false } },
  ])("does not show passed support for incomplete mechanical/coverage metadata %j", patch => {
    expect(displayedAskSupportStatus(response(patch))).toBe("undetermined");
    render(<AskSupportNotice response={response(patch)} />);
    expect(screen.queryByText("Excerpt consistency checks passed")).not.toBeInTheDocument();
  });
  it("withholds support when the only cited source has a current retraction hold", () => {
    const input = response({ sources: [{ ...source, source_visibility: sourceVisibility("retracted") }] });
    expect(displayedAskSupportStatus(input)).toBe("undetermined");
    render(<AskSupportNotice response={input} />);
    expect(screen.getByRole("status")).toHaveTextContent("Scientific support remains undetermined");
    expect(screen.getByText("Source Archive — retracted")).toBeInTheDocument();
    expect(screen.queryByText("Excerpt consistency checks passed")).not.toBeInTheDocument();
  });
  it("keeps saved history support status unknown even when citations exist", () => {
    render(<AskHistoryList entries={[{ id: "history:1", question: "What was reported?", answer: "A saved claim [1].", sources: [source], tokens_used: 5, latency_ms: 10, language: "en", created_at: "2026-09-07T00:00:00Z" }]} onDeleted={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText(/Scientific support status is unknown for this saved answer snapshot/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Synthetic source/ })).toBeInTheDocument();
    expect(screen.queryByText(/Excerpt consistency checks passed/)).not.toBeInTheDocument();
    expect(screen.getByText(/Current source status is unavailable/)).toBeInTheDocument();
  });
  it("shows a live retraction beside the untouched saved citation without approving the old answer", () => {
    render(<AskHistoryList entries={[{ id: "history:1", question: "What was reported?", answer: "A saved claim [1].", sources: [source], tokens_used: 5, latency_ms: 10, language: "en", created_at: "2026-09-07T00:00:00Z", current_evidence: { scope: "current_paper_metadata_not_saved_excerpt", saved_answer_revalidated: false, warning_codes: [], sources: [{ saved_source_position: 0, paper_id: source.paper_id, metadata_status: "checked", source_visibility: { source_status: "retracted", reported_claim_filter_eligible: false }, occurrence_visibility_summary: { total_occurrences: 2, state_counts: { retracted: 1, quarantined: 1 }, omitted_occurrences: 1 }, warning_codes: ["source_retracted"] }] } }]} onDeleted={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText("A saved claim [1].")).toBeInTheDocument();
    expect(screen.getByText(/Current source status: retracted/)).toHaveTextContent("claim-support eligibility is withheld; review is required");
    expect(screen.getByText(/Current paper occurrences/)).toHaveTextContent("Explicit material links only; no matching by formula");
    expect(screen.getByText(/not a revalidation of the saved excerpt or answer/)).toBeInTheDocument();
    expect(screen.getByText(/Scientific support status is unknown for this saved answer snapshot/)).toBeInTheDocument();
    expect(screen.queryByText(/Excerpt consistency checks passed/)).not.toBeInTheDocument();
  });
  it("does not attach current metadata to a different saved citation identity", () => {
    render(<AskHistoryList entries={[{ id: "history:1", question: "What was reported?", answer: "A saved claim [1].", sources: [source], tokens_used: 5, latency_ms: 10, language: "en", created_at: "2026-09-07T00:00:00Z", current_evidence: { scope: "current_paper_metadata_not_saved_excerpt", saved_answer_revalidated: false, warning_codes: ["saved_source_inventory_truncated", "current_evidence_output_budget_exhausted"], sources: [{ saved_source_position: 0, paper_id: "different-source", metadata_status: "checked", source_visibility: { source_status: "active", reported_claim_filter_eligible: true }, occurrence_visibility_summary: null, warning_codes: [] }] } }]} onDeleted={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText(/Current source status is unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Some saved sources exceed the current-check limit/)).toBeInTheDocument();
    expect(screen.getByText(/Some current source summaries exceed the response limit/)).toHaveTextContent("Missing summaries do not establish current support");
    expect(screen.queryByText(/Current source status: active/)).not.toBeInTheDocument();
  });
  it("renders claim text, evidence and warnings as literal text, preserving CJK source content", () => {
    const input = response({ support_warnings: ["<img src=x onerror=alert(1)>"] });
    input.claim_assessments![0].text = "<script>alert(1)</script> 测试材料";
    input.claim_assessments![0].evidence[0].excerpt = "<img src=evil> 原文报告";
    const { container } = render(<AskSupportNotice response={input} />);
    expect(container.querySelector("script, img")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script> 测试材料")).toBeInTheDocument();
    expect(screen.getByText("<img src=evil> 原文报告")).toBeInTheDocument();
  });
});

describe("answer citation rendering", () => {
  it("links only resolvable source indices and rejects fabricated citation anchors", () => {
    render(<MarkdownAnswer markdown="Reported result [1]; missing [99]; [fabricated](#src-99)." sources={[source]} />);
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#src-1");
    expect(screen.queryByRole("link", { name: "fabricated" })).not.toBeInTheDocument();
    expect(screen.getByText(/missing \[99\]/)).toBeInTheDocument();
  });
  it("does not link an ambiguous duplicated source index", () => {
    render(<MarkdownAnswer markdown="Reported result [1]." sources={[source, { ...source, paper_id: "doi:other" }]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("normalizes a valid zero-padded index to its actual source anchor", () => {
    render(<MarkdownAnswer markdown="Reported result [001]; [same source](#src-0001)." sources={[source]} />);
    expect(screen.getByRole("link", { name: "[001]" })).toHaveAttribute("href", "#src-1");
    expect(screen.getByRole("link", { name: "same source" })).toHaveAttribute("href", "#src-1");
  });
  it("blocks raw HTML, script URLs, and generated remote image loads", () => {
    const { container } = render(<MarkdownAnswer markdown={'<script>alert(1)</script>\n\n[bad](javascript:alert(1)) ![unverified image](https://untrusted.invalid/pixel)'} sources={[]} />);
    expect(container.querySelector("script, img")).toBeNull();
    expect(screen.queryByRole("link", { name: "bad" })).not.toBeInTheDocument();
    expect(screen.getByText(/Image omitted: unverified image/)).toBeInTheDocument();
  });
});
