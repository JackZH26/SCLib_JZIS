import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistorySaveNotice } from "@/components/HistorySaveNotice";
import { knownAnswerReceipt, knownHistoryDetail, knownHistorySave, knownHistorySummary } from "@/lib/answer-history";
import type { HistorySaveDisposition } from "@/lib/answer-history";
import { ScientificMixedNotice } from "@/components/ScientificMixedNotice";
import { mixedResponse } from "../fixtures/scientific-mixed";
import { emptyHistoryFixture, historyDetailFixture, historyId, legacyHistoryFixture } from "../fixtures/answer-history";
import { AskHistoryDetail, HistoryReceiptContent } from "@/components/dashboard/AskHistoryDetail";
import { ApiError, historyDetail } from "@/lib/api";
import actualOrdinary from "../fixtures/answer-history-http-ordinary.json";
import actualStructured from "../fixtures/answer-history-http-structured.json";
import actualMixed from "../fixtures/answer-history-http-mixed.json";
import actualClarification from "../fixtures/answer-history-http-clarification.json";
import actualLegacy from "../fixtures/answer-history-http-legacy.json";

vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), historyDetail: vi.fn() }));

const id = "11111111-1111-4111-8111-111111111111", sha = "a".repeat(64);
function saved(patch: Partial<HistorySaveDisposition> = {}): HistorySaveDisposition {
  return { version: "ask-history-save/1.0.0", status: "saved", history_id: id,
    receipt_sha256: sha, reason_code: null, ...patch };
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("honest private history save disposition", () => {
  it("links only a confirmed saved receipt and does not claim scientific review", () => {
    render(<HistorySaveNotice value={saved()} />);
    expect(screen.getByRole("link", { name: "View saved receipt" })).toHaveAttribute("href", `/dashboard/history/${id}`);
    expect(screen.getByText(/not scientific approval or a current source-permission check/)).toBeVisible();
  });

  it("uses an unknown outcome identifier only for recovery", () => {
    render(<HistorySaveNotice value={saved({ status: "unknown", receipt_sha256: null, reason_code: "commit_unconfirmed" })} />);
    expect(screen.getByText(/save outcome is unknown/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Check save outcome" })).toHaveAttribute("href", `/dashboard/history/${id}`);
    expect(screen.queryByText("Saved to your private history.")).not.toBeInTheDocument();
  });

  it.each(["not_saved", "not_requested"] as const)("does not link %s", status => {
    render(<HistorySaveNotice value={saved({ status, history_id: null, receipt_sha256: null,
      reason_code: status === "not_saved" ? "storage_unavailable" : null })} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved to your private history.")).not.toBeInTheDocument();
  });

  it.each([undefined, null, false, {}, [], "saved"])("missing or malformed metadata cannot mean saved: %j", value => {
    expect(knownHistorySave(value)).toBeNull();
    render(<HistorySaveNotice value={value} />);
    expect(screen.getByText(/does not confirm a saved receipt/)).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each([
    { version: "future" }, { status: true }, { history_id: null }, { history_id: "../../other" },
    { receipt_sha256: null }, { receipt_sha256: "A".repeat(64) }, { reason_code: "PRIVATE SOURCE / path" },
    { status: "unknown", receipt_sha256: sha }, { status: "unknown", history_id: null, receipt_sha256: null },
    { status: "not_saved" }, { status: "not_requested", history_id: null }, { unexpected: false },
  ])("rejects contradictory/extra save fields %j", patch => {
    expect(knownHistorySave({ ...saved(), ...patch })).toBeNull();
  });

  it("requires a digest only for a recorded list summary", () => {
    for (const status of ["legacy_unpinned", "recorded", "unavailable"] as const) {
      const value = { version: "ask-history-receipt-summary/1.0.0", status,
        receipt_sha256: status === "recorded" ? sha : null };
      expect(knownHistorySummary(value)?.status).toBe(status);
      expect(knownHistorySummary({ ...value, receipt_sha256: status === "recorded" ? null : sha })).toBeNull();
      expect(knownHistorySummary({ ...value, verified: true })).toBeNull();
    }
  });

  it("marks all nested mixed-source provenance as historical", () => {
    const response = mixedResponse();
    render(<ScientificMixedNotice response={response} rawQuery={response.scientific_query!.raw_query} historical />);
    expect(screen.getByText(/Saved retrieval observations only/)).toBeVisible();
    expect(screen.getAllByLabelText("Saved evidence provenance")).toHaveLength(response.sources.length);
    expect(screen.getAllByLabelText("Saved context selection")).toHaveLength(response.sources.length);
    expect(screen.queryByText(/Current catalogue binding; not scientific acceptance/)).not.toBeInTheDocument();
    expect(screen.getByText(/Saved interpretation and extraction records from answer time/)).toBeVisible();
  });
});

describe("complete saved response and exact receipt display bindings", () => {
  it.each([["ordinary", actualOrdinary], ["structured", actualStructured], ["mixed", actualMixed],
    ["clarification", actualClarification], ["legacy", actualLegacy]] as const)(
    "accepts and renders actual guarded SQL→HTTP %s history without recomputing or remapping hashes", (_name, value) => {
      const checked = knownHistoryDetail(value, value.entry.id);
      expect(checked).not.toBeNull();
      render(<HistoryReceiptContent detail={checked!} />);
      expect(screen.getByRole("region", { name: "Saved question" })).toHaveTextContent(value.entry.question);
      expect(screen.getByRole("region", { name: "Historical receipt integrity" })).toHaveTextContent(
        value.evidence.status === "verified" ? "Historical receipt integrity checked" : "Legacy unpinned history");
    });

  function overlay(paperIds: string[], status = "retracted") {
    const visibility = historyDetailFixture().evidence.receipt!.response.sources[0].source_visibility!;
    return { version: "ask-history-current-evidence/1.0.0", scope: "current_paper_metadata_not_saved_excerpt",
      metadata_snapshot_at: "2026-09-09T10:00:00Z", saved_answer_revalidated: false, scientific_acceptance: false,
      ml_training_eligibility_established: false, warning_codes: [], sources: paperIds.map((paper_id, index) => ({
        saved_source_position: index, paper_id, metadata_status: "checked", occurrence_visibility_summary: null, warning_codes: [],
        source_visibility: { ...visibility, source_status: status, reported_claim_filter_eligible: false } })) };
  }

  it("accepts a complete synthetic mixed receipt, with opaque server-side checksums", () => {
    const value = historyDetailFixture();
    expect(knownAnswerReceipt(value.evidence.receipt)).not.toBeNull();
    expect(knownHistoryDetail(value, historyId)).not.toBeNull();
    render(<HistoryReceiptContent detail={value} />);
    expect(screen.getByText("Historical receipt integrity checked")).toBeVisible();
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
    expect(screen.getByRole("region", { name: "Original explanation candidates" })).toHaveTextContent("specimen U");
    expect(screen.getByText(/historical identifiers, not a claim that this generation is active today/)).toBeInTheDocument();
  });

  it.each([true, false])("preserves no-selected-evidence with generation present = %s", generation => {
    const value = emptyHistoryFixture(generation);
    expect(knownHistoryDetail(value, historyId)).not.toBeNull();
    render(<HistoryReceiptContent detail={value} />);
    expect(screen.getByText(/No source input was selected/)).toBeVisible();
    expect(screen.getByText(/No selected evidence; no missing input is invented/)).toBeInTheDocument();
    expect(screen.queryByText("Recorded generation") !== null).toBe(generation);
    expect(screen.queryByRole("region", { name: "Structured extraction records" })).not.toBeInTheDocument();
  });

  it("never reconstructs structured rows from a legacy source card", () => {
    const value = legacyHistoryFixture();
    expect(knownHistoryDetail(value, historyId)).not.toBeNull();
    render(<HistoryReceiptContent detail={value} />);
    expect(screen.getByRole("heading", { name: "Legacy unpinned history" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Structured extraction records" })).not.toBeInTheDocument();
    expect(screen.queryByText("Recorded generation")).not.toBeInTheDocument();
  });

  it("keeps current numerical and original-source holds separate from immutable saved results", () => {
    const value = historyDetailFixture(), receipt = JSON.stringify(value.evidence.receipt);
    value.entry.current_evidence = overlay(value.entry.sources.map(source => source.paper_id!)) as any;
    value.result_current_evidence = overlay(value.evidence.receipt!.response.scientific_results!.map(result => result.binding.paper_id));
    expect(knownHistoryDetail(value, historyId)).not.toBeNull();
    render(<HistoryReceiptContent detail={value} />);
    for (const label of ["Current metadata for saved citation source papers", "Current metadata for saved numerical-result source papers"]) {
      const section = screen.getByRole("region", { name: label });
      expect(section).toHaveTextContent("current source status retracted");
      expect(section).toHaveTextContent("current claim-support eligibility withheld");
      expect(section).toHaveTextContent("does not revalidate saved excerpts");
    }
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
    expect(JSON.stringify(value.evidence.receipt)).toBe(receipt);
  });

  it("retains current occurrence holds and incomplete-coverage warnings without using them as saved result labels", () => {
    const value = historyDetailFixture();
    value.entry.current_evidence = overlay(value.entry.sources.map(source => source.paper_id!)) as any;
    const current = value.entry.current_evidence as any;
    current.warning_codes = ["current_evidence_output_budget_exhausted"];
    current.sources[0].occurrence_visibility_summary = { version: "material-visibility/1.0.0", total_occurrences: 2,
      returned_occurrences: 1, omitted_occurrences: 1, state_counts: { catalogue: 1, quarantined: 1 },
      scientific_acceptance: false, warning_codes: ["restricted_or_malformed_occurrences_omitted"] };
    render(<HistoryReceiptContent detail={value} />);
    const original = screen.getByRole("region", { name: "Current metadata for saved citation source papers" });
    expect(original).toHaveTextContent("quarantined: 1");
    expect(original).toHaveTextContent("1 restricted or malformed occurrences omitted");
    expect(original).toHaveTextContent("coverage is incomplete");
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
  });

  it("withholds inconsistent occurrence counts instead of coercing numeric-looking values", () => {
    const value = historyDetailFixture();
    value.entry.current_evidence = overlay(value.entry.sources.map(source => source.paper_id!)) as any;
    (value.entry.current_evidence as any).sources[0].occurrence_visibility_summary = { version: "material-visibility/1.0.0",
      total_occurrences: 1, returned_occurrences: 1, omitted_occurrences: 0, state_counts: { catalogue: "1" }, scientific_acceptance: false };
    render(<HistoryReceiptContent detail={value} />);
    expect(screen.getByText(/occurrence metadata is inconsistent/)).toBeVisible();
  });

  it("never attaches a current status to another paper or coerces a malformed status", () => {
    const value = historyDetailFixture();
    value.entry.current_evidence = overlay(["UNRELATED_PAPER"]) as any;
    value.result_current_evidence = overlay(value.evidence.receipt!.response.scientific_results!.map(result => result.binding.paper_id));
    (value.result_current_evidence.sources as any[])[0].source_visibility.source_status = ["active"];
    render(<HistoryReceiptContent detail={value} />);
    expect(within(screen.getByRole("region", { name: "Current metadata for saved citation source papers" })).getByText(/unavailable or inconsistent/)).toBeVisible();
    expect(screen.queryByText(/UNRELATED_PAPER/)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Current metadata for saved numerical-result source papers" })).toHaveTextContent("current status unavailable");
  });

  it.each([
    ["unknown version", (v: ReturnType<typeof historyDetailFixture>) => { (v as any).version = "future"; }],
    ["extra top field", (v: ReturnType<typeof historyDetailFixture>) => { (v as any).approved = true; }],
    ["missing result overlay", (v: ReturnType<typeof historyDetailFixture>) => { delete (v as any).result_current_evidence; }],
    ["other owner entry id", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.id = "22222222-2222-4222-8222-222222222222"; }],
    ["other receipt id", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.history_id = "22222222-2222-4222-8222-222222222222"; }],
    ["scientific flag", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence as any).scientific_acceptance = true; }],
    ["false integer", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence as any).public_release_authorized = 0; }],
    ["currentness claim", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence as any).currentness_revalidated = true; }],
    ["integrity false", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.historical_integrity_verified = false; }],
    ["summary checksum", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.receipt!.receipt_sha256 = "b".repeat(64); }],
    ["question mismatch", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.question = "Different question"; }],
    ["answer mismatch", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.answer = "Different answer"; }],
    ["source mismatch", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.sources = []; }],
    ["null usage vs zero", (v: ReturnType<typeof historyDetailFixture>) => { v.entry.tokens_used = null; }],
    ["recursive history", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt!.response as any).history = saved(); }],
    ["quota field", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt!.response as any).remaining = 10; }],
    ["omitted complete response field", (v: ReturnType<typeof historyDetailFixture>) => { delete v.evidence.receipt!.response.input_budget; }],
    ["mixed scientific approval", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt!.response.scientific_mixed as any).scientific_acceptance = true; }],
    ["extra receipt field", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt as any).authority = true; }],
    ["unsupported mode", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt!.bindings as any).mode = "current"; }],
    ["wrong binding scope", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.binding_scope = "legacy_snapshot"; }],
    ["missing input", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items.pop(); }],
    ["duplicate input", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items.push(v.evidence.receipt!.bindings.items[0]); }],
    ["changed order", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items.reverse(); }],
    ["missing member hash", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items[0].member_record_sha256 = null; }],
    ["wrong content hash", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items[0].content_sha256 = "f".repeat(64); }],
    ["wrong snapshot hash", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items[0].source_snapshot_sha256 = "f".repeat(64); }],
    ["wrong vector generation", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items[0].chunk_revision_sha256 = "f".repeat(64); }],
    ["extra item field", (v: ReturnType<typeof historyDetailFixture>) => { (v.evidence.receipt!.bindings.items[0] as any).scientific_acceptance = false; }],
    ["missing evidence pin", (v: ReturnType<typeof historyDetailFixture>) => { v.evidence.receipt!.bindings.items[0].has_evidence_pin = false; }],
    ["nonfinite metadata", (v: ReturnType<typeof historyDetailFixture>) => { (v.entry.current_evidence as any).bad = Infinity; }],
  ])("rejects %s", (_label, change) => {
    const value = historyDetailFixture();
    (change as (v: typeof value) => void)(value);
    expect(knownHistoryDetail(value, historyId)).toBeNull();
  });

  it("rejects missing/forged legacy pin observations rather than filling them", () => {
    const value = legacyHistoryFixture();
    value.evidence.binding_scope = "generation_members";
    expect(knownHistoryDetail(value, historyId)).toBeNull();
    const missing = historyDetailFixture();
    (missing.evidence.receipt as any).bindings.items[0].evidence_record_sha256 = null;
    expect(knownHistoryDetail(missing, historyId)).toBeNull();
  });

  it("rejects oversized and excessively nested input before rendering", () => {
    const value = historyDetailFixture();
    value.evidence.receipt!.response.answer = "x".repeat(1024 * 1024);
    value.entry.answer = value.evidence.receipt!.response.answer;
    expect(knownHistoryDetail(value, historyId)).toBeNull();
    let nested: unknown = null;
    for (let i = 0; i < 34; i++) nested = { child: nested };
    const deep = historyDetailFixture();
    (deep.entry.current_evidence as any).nested = nested;
    expect(knownHistoryDetail(deep, historyId)).toBeNull();
    const many = historyDetailFixture();
    (many.entry.current_evidence as any).many = Array(100001).fill(null);
    expect(knownHistoryDetail(many, historyId)).toBeNull();
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("owner-private asynchronous history detail", () => {
  it("does not request malformed history identifiers", async () => {
    render(<AskHistoryDetail historyId="../../private" />);
    expect(await screen.findByText(/history identifier is invalid/)).toBeVisible();
    expect(historyDetail).not.toHaveBeenCalled();
  });
  it("fetches once with a cancellation signal and never reruns Ask", async () => {
    vi.mocked(historyDetail).mockResolvedValue(historyDetailFixture());
    const view = render(<AskHistoryDetail historyId={historyId} />);
    await screen.findByText("Historical receipt integrity checked");
    expect(historyDetail).toHaveBeenCalledTimes(1);
    expect(vi.mocked(historyDetail).mock.calls[0][0]).toBe(historyId);
    const signal = vi.mocked(historyDetail).mock.calls[0][1];
    view.unmount(); expect(signal?.aborted).toBe(true);
  });

  it("ignores late previous history even if its transport ignores abort", async () => {
    const old = deferred<unknown>(), next = deferred<unknown>(), otherId = "22222222-2222-4222-8222-222222222222";
    vi.mocked(historyDetail).mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const view = render(<AskHistoryDetail historyId={historyId} />);
    view.rerender(<AskHistoryDetail historyId={otherId} />);
    const value = legacyHistoryFixture(); value.entry.id = otherId; value.entry.answer = "NEW_PRIVATE_ANSWER";
    await act(async () => { next.resolve(value); });
    await act(async () => { old.resolve(historyDetailFixture()); });
    expect(screen.getByText("NEW_PRIVATE_ANSWER")).toBeVisible();
    expect(screen.queryByText("Historical receipt integrity checked")).not.toBeInTheDocument();
    expect(vi.mocked(historyDetail).mock.calls[0][1]?.aborted).toBe(true);
  });

  it.each([401, 403, 404, 503])("shows static private read failure %s without raw server content", async status => {
    vi.mocked(historyDetail).mockRejectedValue(new ApiError(status, { raw: "SECRET" }, "SECRET"));
    render(<AskHistoryDetail historyId={historyId} />);
    await screen.findByRole("alert");
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Saved answer-time output" })).not.toBeInTheDocument();
    if (status === 404) expect(screen.getByText(/does not resolve an earlier unknown save outcome/)).toBeVisible();
  });

  it("withholds malformed detail and retries only the read", async () => {
    vi.mocked(historyDetail).mockResolvedValueOnce({ ...historyDetailFixture(), extra: true }).mockResolvedValueOnce(legacyHistoryFixture());
    render(<AskHistoryDetail historyId={historyId} />);
    await screen.findByRole("alert");
    expect(screen.queryByRole("region", { name: "Structured extraction records" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry history read" }));
    await screen.findByRole("heading", { name: "Legacy unpinned history" });
    await waitFor(() => expect(historyDetail).toHaveBeenCalledTimes(2));
  });
});
