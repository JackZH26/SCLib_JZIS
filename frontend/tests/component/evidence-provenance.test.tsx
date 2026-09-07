import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceProvenanceNotice } from "@/components/EvidenceProvenanceNotice";
import { AskSupportNotice } from "@/components/AskSupportNotice";
import { AskHistoryList } from "@/components/dashboard/AskHistoryList";
import { knownEvidenceProvenance } from "@/lib/evidence-provenance";
import { displayedAskSupportStatus, excerptSourceIsHeld } from "@/lib/ask-support";
import type { AskResponse, AskSource, EvidenceProvenance } from "@/lib/api";
import { evidenceProvenance } from "../fixtures/evidence-provenance";
import { sourceVisibility } from "../fixtures/material-visibility";

const source = (evidence = evidenceProvenance()): AskSource => ({ index: 1, paper_id: "synthetic:lineage", arxiv_id: null,
  title: "Synthetic lineage source", authors_short: "Synthetic author", year: 2026, section: "Facts", snippet: "SECRET_EXCERPT",
  source_visibility: sourceVisibility(), evidence_provenance: evidence });
function response(evidence = evidenceProvenance()): AskResponse {
  return { answer: "A synthetic draft [1].", sources: [source(evidence)], tokens_used: 0, query_time_ms: 1,
    citation_valid: true, citation_warnings: [], guest_remaining: null, remaining: null,
    support_policy_version: "scientific-claim-support/1.0.0", assessment_scope: "generated_draft", scientific_support_status: "supported",
    citation_indices_valid: true, support_coverage: { total_claims: 1, assessed_claims: 1, supported_claims: 1,
      contradicted_claims: 0, undetermined_claims: 0, truncated: false },
    claim_assessments: [{ claim_id: "synthetic:claim", text: "A synthetic draft [1].", cited_indices: [1], status: "supported",
      reason_codes: [], evidence: [{ source_index: 1, paper_id: "synthetic:lineage", excerpt: "SECRET_EXCERPT" }] }] };
}

describe("typed evidence provenance", () => {
  it("distinguishes current binding, extraction, and unresolved scientific authority in English", () => {
    const evidence = evidenceProvenance({ source_locator: { page: 1200, table: "Table 2" } });
    expect(knownEvidenceProvenance(evidence)).toEqual(evidence);
    render(<EvidenceProvenanceNotice evidence={evidence} />);
    const notice = screen.getByLabelText("Evidence provenance");
    expect(notice).toHaveTextContent("Derived fact · Original evidence root unresolved");
    expect(notice).toHaveTextContent("Current catalogue binding; not scientific acceptance");
    expect(notice).toHaveTextContent("not an independent confirmation or original quotation");
    expect(notice).toHaveTextContent("page: 1,200");
    expect(notice).toHaveTextContent("grants no new use rights");
  });
  it.each([null, false, 0, "", [], {}, { version: "unknown" }])("fails closed for malformed runtime input %j", value => {
    expect(knownEvidenceProvenance(value)).toBeNull();
    render(<EvidenceProvenanceNotice evidence={value as EvidenceProvenance} />);
    expect(screen.getByText(/no independent support established/)).toBeInTheDocument();
  });
  it.each([
    { support_eligible: true }, { independent_evidence: true }, { scientific_acceptance: true }, { root_status: "resolved" },
    { permission_status: "allowed" }, { currentness: "future" }, { chunk_kind: ["derived_fact"] },
    { content_sha256: "invalid" }, { parent_result_revision_id: null }, { rendering_version: null },
    { source_locator: { source_quote: "SECRET" } }, { source_locator: { page: true } },
    { source_locator: { span_start: 1 } }, { source_locator: { span_start: 2, span_end: 2 } },
    { source_locator: { page_start: 5, page_end: 4 } }, { warning_codes: ["Raw quoted prose"] },
    { scientific_label: "confirmed" },
  ])("rejects forged authority or malformed closed fields %j", patch => {
    expect(knownEvidenceProvenance({ ...evidenceProvenance(), ...patch })).toBeNull();
  });
  it("does not allow legacy records to fabricate a retained revision or originals to fabricate a derived parent", () => {
    expect(knownEvidenceProvenance(evidenceProvenance({ chunk_kind: "legacy_unknown" }))).toBeNull();
    expect(knownEvidenceProvenance(evidenceProvenance({ chunk_kind: "original_passage" }))).toBeNull();
    expect(knownEvidenceProvenance(evidenceProvenance({ chunk_kind: "abstract", parent_result_revision_id: null,
      parent_result_sha256: null, extraction_version: null, rendering_version: null }))).not.toBeNull();
  });
  it.each([false, 0, "", [], null])("holds malformed falsy provenance %j instead of treating it as missing", value => {
    expect(excerptSourceIsHeld(source(value as unknown as EvidenceProvenance))).toBe(true);
  });
  it("does not show a forged pass badge for an unresolved derived root", () => {
    const input = response();
    expect(displayedAskSupportStatus(input)).toBe("undetermined");
    render(<AskSupportNotice response={input} />);
    expect(screen.queryByText("Excerpt consistency checks passed")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Scientific support remains undetermined");
  });
  it.each([{ permission_status: "restricted" }, { currentness: "stale" }] as const)("withholds stale/restricted claim excerpts %j", patch => {
    const input = response(evidenceProvenance(patch));
    expect(excerptSourceIsHeld(input.sources[0])).toBe(true);
    render(<AskSupportNotice response={input} />);
    expect(screen.queryByText("SECRET_EXCERPT")).not.toBeInTheDocument();
    expect(screen.getByText(/Excerpt withheld/)).toBeInTheDocument();
  });
  it("does not present saved currentness as a live recheck", () => {
    render(<AskHistoryList entries={[{ id: "history:lineage", question: "Synthetic question", answer: "Saved draft [1].",
      sources: [source()], tokens_used: 0, latency_ms: 1, language: "en", created_at: "2026-09-08T00:00:00Z" }]} onDeleted={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByLabelText("Saved evidence provenance")).toHaveTextContent("current lineage has not been rechecked here");
    expect(screen.queryByText("Current catalogue binding; not scientific acceptance.")).not.toBeInTheDocument();
  });
  it("withholds excerpts that cannot be attributed to a unique current source", () => {
    const input = response();
    input.claim_assessments![0].evidence[0].paper_id = "synthetic:wrong-source";
    render(<AskSupportNotice response={input} />);
    expect(screen.queryByText("SECRET_EXCERPT")).not.toBeInTheDocument();
    expect(screen.getByText(/Excerpt withheld/)).toBeInTheDocument();
  });
});
