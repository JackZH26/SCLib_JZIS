import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MaterialsProposalReview } from "@/components/MaterialsProposalReview";
import { materialsProposalCapabilities, materialsProposalDetail, materialsProposalRuns } from "@/lib/api";
import { projectorReview, proposalDetail, proposalExport, type ProjectorReview, type Json } from "@/lib/materials-proposal-review";
import { access, detail, exportDescriptor, queue } from "../helpers/materials-proposal-test-data";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), materialsProposalCapabilities: vi.fn(), materialsProposalDetail: vi.fn(), materialsProposalRuns: vi.fn() }));
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const quote = "Synthetic source extrapolates to T=0; <script>alert(1)</script> is literal text.";
function fixture(failed = false) {
  const page = copy(detail), list = copy(queue);
  page.run.model = list.items[0].model = "gpt-6-luna";
  const context: ProjectorReview = {
    version: "materials-projector-review-context/1", graph_authorship: "gpt-6-luna", provider: "codex", model: "gpt-6-luna", reasoning: "medium",
    producer_interface: "materials-source-projector-interface/5", evidence_binding: "materials-projection-binding/5",
    terminal: { job_id: "1".repeat(64), attempt_id: "2".repeat(32), receipt_sha256: "3".repeat(64), config_sha256: "4".repeat(64), raw_output_sha256: "5".repeat(64), state: "quarantined", outcome: failed ? "graph_not_validated" : "graph_drafted_pending_semantic_review", error_code: failed ? "projector_schema_invalid" : null, diagnostic: failed ? { details: [] } : null },
    disposition: failed ? "unparsed_model_graph" : "draft_pending_review", raw_result_objects: failed ? 8 : 1, retained_result_rows: failed ? 0 : 1,
    publication_version: "v3", coverage_sha256: "6".repeat(64), findings_author: { kind: "assistant", identity: "Synthetic source assessment", thread_id: "synthetic:test" }, findings_created_at: "2026-10-26T00:00:00Z", findings_sha256: "7".repeat(64),
    findings: [{ id: "missing", kind: "source_completeness", path: "/paper", code: "cited_result_omitted", note: "A cited comparison is missing from the draft.", source_quotes: [{ block_id: "B1", document_id: "D1", locator: "paragraph:1", block_sha256: "8".repeat(64), quote_sha256: "9".repeat(64), start_char: 0, end_char: Array.from(quote).length, quote }] }],
    source_completeness_findings: 1, independent_review: false, paper_completed: false, scientific_acceptance: false, ml_training_eligible: false,
  };
  if (failed) { page.results = []; page.run.result_count = list.items[0].result_count = 0; page.run.extraction_version = list.items[0].extraction_version = null; }
  page.coverage.projector_review = context as unknown as Json;
  return { page, list, context };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(materialsProposalCapabilities).mockResolvedValue(copy(access)); });

it("shows an invalid eight-object graph without implying a result-free paper", async () => {
  const f = fixture(true);
  vi.mocked(materialsProposalRuns).mockResolvedValue(f.list); vi.mocked(materialsProposalDetail).mockResolvedValue(f.page);
  render(<MaterialsProposalReview />);
  fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
  expect(await screen.findByRole("heading", { name: "Model draft and source review" })).toBeVisible();
  expect(screen.getByText(/8 raw result objects remain in the diagnostic download/)).toBeVisible();
  expect(screen.getByText(/not evidence that the paper reports no results/)).toBeVisible();
  expect(screen.getByText(/Graph authored by gpt-6-luna/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Download complete run (ZIP)" })).toBeVisible();
  expect(screen.queryByRole("button", { name: /approve|promote|publish/i })).toBeNull();
});

it("keeps source omissions, source coordinates and assistant authorship visible", async () => {
  const f = fixture();
  vi.mocked(materialsProposalRuns).mockResolvedValue(f.list); vi.mocked(materialsProposalDetail).mockResolvedValue(f.page);
  const { container } = render(<MaterialsProposalReview />);
  fireEvent.click(await screen.findByRole("button", { name: /arxiv:0001.00001 · Synthetic/ }));
  expect(await screen.findByRole("heading", { name: "Missing from draft" })).toBeVisible();
  expect(screen.getByText(quote)).toBeVisible(); expect(container.querySelector("script")).toBeNull();
  expect(screen.getByText(/Synthetic source assessment \(assistant\)/)).toBeVisible();
  expect(screen.getByText(/paragraph:1 · characters 0/)).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Source item accounting" })).toBeNull();
});

it.each(["author", "completion", "quote", "count", "owner", "model", "terminal"])("rejects mismatched projector context: %s", kind => {
  const f = fixture(), bad = f.context as unknown as Record<string, any>;
  if (kind === "author") bad.findings_author.kind = "human";
  if (kind === "completion") bad.paper_completed = true;
  if (kind === "quote") bad.findings[0].source_quotes[0].end_char++;
  if (kind === "count") bad.source_completeness_findings = 0;
  if (kind === "owner") bad.findings[0].path = "/results/0";
  if (kind === "model") bad.graph_authorship = "assistant";
  if (kind === "terminal") bad.terminal.outcome = "success-empty";
  expect(projectorReview(bad, f.page.run)).toBeNull();
  expect(proposalDetail(f.page, f.page.run)).toBeNull();
});

it("requires the exact raw model file for projector exports", () => {
  const f = fixture(); const d = { ...copy(exportDescriptor), run: f.page.run, version: "materials-proposal-export/4" };
  d.files = ["README.txt", "graph.json", "manifest.json", "raw-model-graph.json", "results.csv"].map(name => ({ name, bytes: 1, sha256: "a".repeat(64) }));
  expect(proposalExport(d, f.page.run)).not.toBeNull();
  d.files = d.files.filter(x => x.name !== "raw-model-graph.json");
  expect(proposalExport(d, f.page.run)).toBeNull();
});
