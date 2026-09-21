import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AskHistoryEntry, AskResponse } from "@/lib/api";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";
import { ScientificMixedNotice } from "@/components/ScientificMixedNotice";
import { AskHistoryList } from "@/components/dashboard/AskHistoryList";
import { mixedResponse, withdrawnMixedResponse } from "../fixtures/scientific-mixed";
import actualSyntheticWire from "../fixtures/scientific-mixed-http.json";
import currentSyntheticWire from "../fixtures/scientific-mixed-http.delivery20260921.json";

const raw = "Why is Tc of MgB₂ 39 K?";
const validate = (value: unknown, query = raw) => knownScientificMixedResponse(value, query);

describe("closed mixed numerical/original wire contract", () => {
  it("accepts the current 1.1 SQL/HTTP response alongside retained 1.0 history", () => {
    const query = currentSyntheticWire.scientific_query.raw_query;
    const result = validate(currentSyntheticWire, query);
    expect(result?.version).toBe("scientific-mixed-evidence/1.1.0");
    expect(result?.status).toBe("completed");
    expect(result?.associations.every(item => item.bridge_revision_id === null)).toBe(true);
  });
  it("accepts actual guarded disposable SQL+HTTP output, not just a hand-written DTO", () => {
    // Captured from test_synthetic_mixed_http_wire_round_trip; synthetic records,
    // real generation/lineage/HTTP path, no cloud calls or scientific authority.
    const query = actualSyntheticWire.scientific_query.raw_query;
    expect(validate(actualSyntheticWire, query)?.status).toBe("completed");
    render(<ScientificMixedNotice response={actualSyntheticWire as unknown as AskResponse} rawQuery={query} />);
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
    expect(screen.getByRole("region", { name: "Original explanation candidates" })).toHaveTextContent("specimen U");
    expect(screen.getByRole("region", { name: "Original explanation candidates" })).toHaveTextContent("Missing pressure does not establish ambient conditions");
    expect(screen.getByText(/14,098 \/ 262,144 canonical UTF-8 bytes/)).toBeVisible();
    expect(screen.getByText(/These counts are not independent evidence/)).toBeVisible();
  });

  it("accepts the complete synthetic Cartesian inventory without scientific acceptance", () => {
    const response = mixedResponse();
    expect(validate(response)).toEqual(response.scientific_mixed);
    expect(validate(response)?.independent_support_count).toBeNull();
  });

  it("retains missing/default metadata compatibility but rejects malformed present values", () => {
    const response = mixedResponse();
    delete response.scientific_mixed;
    expect(validate(response)?.status).toBe("not_requested");
    const empty = validate(response)!;
    expect(validate({ ...response, scientific_mixed: empty })?.status).toBe("not_requested");
    for (const value of [null, false, 0, "", [], {}, { ...empty, result_count: 1 }]) {
      expect(validate({ ...response, scientific_mixed: value })).toBeNull();
    }
  });

  it("accepts typed comparisons without asserting an experimental comparison or an explanation request", () => {
    const query = "Compare MgB2 and Nb Tc", response = mixedResponse(query);
    response.scientific_query!.intent = "comparison";
    expect(validate(response, query)?.status).toBe("completed");
    render(<ScientificMixedNotice response={response} rawQuery={query} />);
    expect(screen.getByRole("heading", { name: "Numerical explanation not established" })).toBeVisible();
    expect(screen.getByText(/same experiment, sample/)).toBeVisible();
    expect(screen.queryByText(/requested mechanism explanation/)).not.toBeInTheDocument();
    response.scientific_query!.requested_fields = [];
    expect(validate(response, query)).toBeNull();
  });

  const badMixed: [string, unknown][] = [
    ["version", "scientific-mixed-evidence/future"], ["status", ["completed"]], ["result_count", true],
    ["source_count", NaN], ["max_selected_inputs", 2], ["max_selected_inputs", 21], ["scientific_acceptance", 0],
    ["scientific_acceptance", true], ["independent_support_count", 1], ["associations", []],
    ["reason_codes", ["reviewed_result_passage_bridge_missing"]], ["reason_codes", ["unknown_reason"]],
    ["reason_codes", ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing", "no_original_context"]],
  ];
  it.each(badMixed)("rejects malformed mixed %s = %j", (key, value) => {
    const response = mixedResponse();
    Object.assign(response.scientific_mixed!, { [key]: value });
    expect(validate(response)).toBeNull();
  });

  const badAssociation: [string, unknown][] = [
    ["source_index", true], ["source_index", 3], ["source_index", 0], ["source_index", 1.5],
    ["parent_result_revision_id", "55555555-5555-5555-5555-555555555555"], ["parent_result_revision_id", "not-a-uuid"],
    ["source_vector_id", `ig62_${"9".repeat(32)}_${"1".repeat(64)}`], ["source_vector_id", "old-positional-id"],
    ["source_evidence_revision_id", "66666666-6666-6666-6666-666666666666"],
    ["source_evidence_record_sha256", "f".repeat(64)], ["source_content_sha256", "e".repeat(64)],
    ["result_source_snapshot_sha256", "C".repeat(64)], ["catalogue_relation", "not_same_snapshot"],
    ["catalogue_relation", ["same_snapshot"]], ["status", "established"], ["reason_code", "reviewed"],
  ];
  it.each(badAssociation)("rejects malformed or mismatched association %s = %j", (key, value) => {
    const response = mixedResponse();
    Object.assign(response.scientific_mixed!.associations[0], { [key]: value });
    expect(validate(response)).toBeNull();
  });

  it("rejects unknown keys and repeated pairs/reasons, not just counts", () => {
    const response = mixedResponse();
    expect(validate({ ...response, scientific_mixed: { ...response.scientific_mixed, confidence: 0.99 } })).toBeNull();
    Object.assign(response.scientific_mixed!.associations[0], { verified: false });
    expect(validate(response)).toBeNull();
    const repeated = mixedResponse();
    repeated.scientific_mixed!.associations[1] = { ...repeated.scientific_mixed!.associations[0] };
    expect(validate(repeated)).toBeNull();
    const reasons = mixedResponse();
    reasons.scientific_mixed!.reason_codes.push("numerical_explanation_not_established");
    expect(validate(reasons)).toBeNull();
  });

  it("requires all two-result × two-source pairs and consistent per-parent catalogue snapshots", () => {
    const response = mixedResponse(), second = structuredClone(response.scientific_results![0]);
    second.binding.parent_result_revision_id = "55555555-5555-5555-5555-555555555555";
    second.binding.vector_id = second.binding.vector_id.slice(0, -64) + "d".repeat(64);
    second.result.result_id = `legacy-result:${"9".repeat(64)}`;
    response.scientific_results!.push(second);
    response.scientific_lookup!.returned_count = 2;
    response.scientific_mixed!.result_count = 2;
    response.scientific_mixed!.associations.push(...response.scientific_mixed!.associations.map(item => ({ ...item,
      parent_result_revision_id: second.binding.parent_result_revision_id })));
    expect(validate(response)?.associations).toHaveLength(4);
    response.scientific_mixed!.associations[3].result_source_snapshot_sha256 = "a".repeat(64);
    response.scientific_mixed!.associations[3].catalogue_relation = "not_same_snapshot";
    expect(validate(response)).toBeNull();
  });

  it("requires matching generation, activation, manifest and unique numerical parents", () => {
    for (const field of ["generation_id", "activation_event_id", "manifest_sha256"] as const) {
      const response = mixedResponse();
      response.scientific_results![0].binding[field] = field.endsWith("sha256") ? "0".repeat(64) : "99999999-9999-9999-9999-999999999999";
      expect(validate(response)).toBeNull();
    }
    const response = mixedResponse();
    response.scientific_results!.push(structuredClone(response.scientific_results![0]));
    response.scientific_lookup!.returned_count = 2;
    response.scientific_mixed!.result_count = 2;
    response.scientific_mixed!.associations.push(...structuredClone(response.scientific_mixed!.associations));
    expect(validate(response)).toBeNull();
  });

  it("never accepts original/numerical vector overlap or a foreign generation original", () => {
    for (const vector of [mixedResponse().scientific_results![0].binding.vector_id, `ig62_${"9".repeat(32)}_${"1".repeat(64)}`]) {
      const response = mixedResponse();
      response.sources[0].packing_info!.chunk_id = vector;
      response.scientific_mixed!.associations[0].source_vector_id = vector;
      expect(validate(response)).toBeNull();
    }
  });

  it("withholds stale, restricted, non-original or lifecycle-held source snippets", () => {
    for (const patch of [{ currentness: "stale" }, { permission_status: "restricted" }, { chunk_kind: "abstract" }, { scientific_acceptance: true }]) {
      const response = mixedResponse();
      Object.assign(response.sources[0].evidence_provenance!, patch);
      expect(validate(response)).toBeNull();
    }
    for (const state of ["retracted", "corrected", "disputed"] as const) {
      const response = mixedResponse();
      response.sources[0].source_visibility!.source_status = state;
      expect(validate(response)).toBeNull();
    }
    const response = mixedResponse();
    response.sources[0].packing_info = null;
    expect(validate(response)).toBeNull();
  });

  it("rejects coercible visibility status and sticky lifecycle contradictions", () => {
    for (const patch of [{ source_status: ["active"] }, { lifecycle_review_required: true }, { bibliography_available: 1 },
      { reported_claim_filter_eligible: false }, { warning_codes: [false] }]) {
      const response = mixedResponse();
      Object.assign(response.sources[0].source_visibility!, patch);
      expect(validate(response)).toBeNull();
    }
  });

  it("requires nonempty pinned originals even when no numerical rows match", () => {
    const response = mixedResponse();
    response.scientific_results = [];
    response.scientific_lookup!.returned_count = 0;
    response.scientific_mixed!.result_count = 0;
    response.scientific_mixed!.associations = [];
    response.scientific_mixed!.reason_codes.push("no_matching_extraction");
    expect(validate(response)?.status).toBe("completed");
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByText(/No matching source-linked extractions/)).toBeVisible();
    expect(screen.getByText("Synthetic passage 1")).toBeVisible();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(validate({ ...response, retrieval_generation: null })).toBeNull();
    response.sources[0].evidence_provenance!.chunk_kind = "legacy_unknown";
    expect(validate(response)).toBeNull();
  });

  it("does not turn an empty completed inventory into an unpinned absence claim", () => {
    const response = withdrawnMixedResponse();
    response.scientific_lookup!.status = "completed";
    response.scientific_mixed!.status = "completed";
    response.scientific_mixed!.reason_codes = ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing",
      "no_original_context", "no_matching_extraction"];
    expect(validate(response)?.status).toBe("completed");
    expect(validate({ ...response, retrieval_generation: undefined })).toBeNull();
    response.scientific_mixed!.reason_codes.pop();
    expect(validate(response)).toBeNull();
  });

  it("does not upgrade unresolved currentness into a grant", () => {
    const response = mixedResponse();
    response.sources[0].evidence_provenance!.currentness = "unresolved";
    expect(validate(response)?.scientific_acceptance).toBe(false);
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByText("Current catalogue binding unresolved.")).toBeVisible();
  });

  it("requires actual no-model metadata and strict finite reported quantities", () => {
    const patches = [{ tokens_used: 1 }, { tokens_used: false }, { answer_mode: "generated" }, { assessment_scope: "answer" },
      { scientific_support_status: "supported" }, { claim_assessments: [{}] }];
    for (const patch of patches) expect(validate({ ...mixedResponse(), ...patch })).toBeNull();
    for (const patch of [{ generation_started: false }, { input_tokens: 1 }, { status: "unavailable" }]) {
      const response = mixedResponse();
      Object.assign(response.input_budget!, patch);
      expect(validate(response)).toBeNull();
    }
    for (const value of [true, NaN, Infinity]) {
      const response = mixedResponse();
      Object.assign(response.scientific_results![0].result.tc, { value });
      expect(validate(response)).toBeNull();
    }
    expect(validate(mixedResponse(), "a different query")).toBeNull();
  });

  it("withdraws both inventories together and does not preserve an old association", () => {
    const response = withdrawnMixedResponse();
    expect(validate(response)?.status).toBe("unavailable");
    expect(validate({ ...response, sources: mixedResponse().sources })).toBeNull();
    expect(validate({ ...response, scientific_results: mixedResponse().scientific_results })).toBeNull();
    expect(validate({ ...response, scientific_mixed: { ...response.scientific_mixed, associations: mixedResponse().scientific_mixed!.associations } })).toBeNull();
  });
});

describe("separate qualified candidate display", () => {
  it("shows a reviewed exact relation without presenting it as a causal explanation or scientific acceptance", () => {
    const response = mixedResponse();
    Object.assign(response.scientific_mixed!.associations[0], {
      status: "established",
      reason_code: "reviewed_result_passage_bridge_current",
      bridge_revision_id: "77777777-7777-4777-8777-777777777777",
      bridge_record_sha256: "7".repeat(64),
      claim_identity_sha256: "8".repeat(64),
      sample_identity_sha256: "9".repeat(64),
      source_locator_sha256: "a".repeat(64),
    });
    expect(validate(response)?.associations[0].status).toBe("established");
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByText(/1 exact record–passage pair has a current reviewed link/)).toBeVisible();
    expect(screen.getByText(/does not establish a numerical or causal explanation/)).toBeVisible();
    fireEvent.click(screen.getByText("Inspect reviewed and unresolved record–passage associations (2)"));
    expect(screen.getByText("Reviewed exact relation — no causal or scientific acceptance")).toBeVisible();
    expect(screen.getByText("Not established — reviewed bridge missing")).toBeVisible();
  });

  it("allows a complete reviewed pair inventory to omit the missing-bridge reason", () => {
    const response = mixedResponse();
    response.scientific_mixed!.associations.forEach((association, index) => Object.assign(association, {
      status: "established",
      reason_code: "reviewed_result_passage_bridge_current",
      bridge_revision_id: `77777777-7777-4777-8777-77777777777${index}`,
      bridge_record_sha256: String(index + 3).repeat(64),
      claim_identity_sha256: String(index + 5).repeat(64),
      sample_identity_sha256: String(index + 7).repeat(64),
      source_locator_sha256: index === 0 ? "a".repeat(64) : "b".repeat(64),
    }));
    response.scientific_mixed!.reason_codes = ["numerical_explanation_not_established"];
    expect(validate(response)?.associations.every(item => item.status === "established")).toBe(true);
  });

  it("shows English-owned two-panel UI with original language retained and no synthesized answer", () => {
    const response = mixedResponse();
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByRole("heading", { name: "Numerical explanation not established" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Structured extraction records" })).toHaveTextContent("39 K");
    const originals = screen.getByRole("region", { name: "Original explanation candidates" });
    expect(within(originals).getByText("Synthetic passage 1")).toBeVisible();
    expect(within(originals).getByRole("link", { name: "[1] Synthetic source — 原始文献" })).toHaveAttribute("href", "/paper/synthetic%3AMgB2");
    expect(screen.getByText(/Original query:/).parentElement).toHaveTextContent("MgB₂");
    expect(screen.getByText(/not a provider token measurement/)).toHaveTextContent("2,048 / 4,096");
    expect(screen.getByText(/same experiment, sample/)).toBeVisible();
    expect(screen.getByText(/not independent evidence/)).toBeVisible();
    expect(screen.queryByText(/UNREVIEWED_MIXED_PROSE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence|probability/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Inspect unresolved record–passage associations (2)"));
    expect(screen.getByRole("link", { name: "Original [2]" })).toHaveAttribute("href", "#src-2");
    const target = `ask-result-${response.scientific_results![0].binding.parent_result_revision_id}`;
    expect(screen.getAllByRole("link", { name: "Extraction 1 · MgB2" })[0]).toHaveAttribute("href", `#${target}`);
    expect(document.getElementById(target)).toHaveTextContent("39 K");
    expect(screen.getAllByText("Not established — reviewed bridge missing")).toHaveLength(2);
  });

  it("does not merge different catalogue snapshots even within an accepted Work grouping", () => {
    const response = mixedResponse();
    response.sources.forEach(source => { source.packing_info!.group_basis = "accepted_work_mapping"; });
    Object.assign(response.sources[1].packing_info!, { source_snapshot_sha256: "d".repeat(64), source_group_id: `src:${"d".repeat(64)}`,
      selection_reason: "source_coverage" });
    response.evidence_packing!.source_group_count = 2;
    response.scientific_mixed!.associations[1].catalogue_relation = "not_same_snapshot";
    expect(validate(response)).not.toBeNull();
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    fireEvent.click(screen.getByText("Inspect unresolved record–passage associations (2)"));
    expect(screen.getByText("Not the same retained paper/catalogue snapshot")).toBeVisible();
    expect(screen.getByText(/does not prove scientific independence/)).toBeVisible();
  });

  it("withdraws every mixed display on malformed source binding, including untrusted prose", () => {
    const response = mixedResponse();
    response.scientific_mixed!.associations[0].source_content_sha256 = "a".repeat(64);
    render(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByRole("status")).toHaveTextContent("withheld");
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic passage 1")).not.toBeInTheDocument();
    expect(screen.queryByText(/UNREVIEWED_MIXED_PROSE/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("explains unavailable and budget-limited single-input states without inferring a mechanism", () => {
    const view = render(<ScientificMixedNotice response={withdrawnMixedResponse()} rawQuery={raw} />);
    expect(screen.getByRole("status")).toHaveTextContent("Both numerical records and original passage candidates have been withdrawn");
    const response = mixedResponse();
    response.sources = [];
    response.evidence_packing = { ...withdrawnMixedResponse().evidence_packing!, status: "not_requested", byte_budget: null,
      reason_codes: ["packing_not_requested"] };
    Object.assign(response.scientific_mixed!, { source_count: 0, max_selected_inputs: 1, associations: [],
      reason_codes: ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing", "no_original_context", "combined_source_limit"] });
    expect(validate(response)?.status).toBe("completed");
    view.rerender(<ScientificMixedNotice response={response} rawQuery={raw} />);
    expect(screen.getByText("39 K")).toBeVisible();
    expect(screen.getByText(/No original passage candidate is available/)).toBeVisible();
    expect(screen.getByText(/1 extraction record \+ 0 original candidates \/ 1 combined/)).toBeVisible();
    expect(screen.queryByText(/Inspect unresolved/)).not.toBeInTheDocument();
  });

  it("cannot reconstruct unsaved numerical rows or associations in history", () => {
    const response = mixedResponse();
    const entry = { ...response, id: "synthetic-history", question: raw, answer: "Saved static mixed notice only.",
      sources: [], latency_ms: 10, created_at: "2026-09-08T00:00:00Z" } as unknown as AskHistoryEntry;
    render(<AskHistoryList entries={[entry]} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText(/association metadata are not reconstructed/)).toBeVisible();
    expect(screen.getByText("Saved static mixed notice only.")).toBeVisible();
    expect(screen.queryByText("39 K")).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic passage 1")).not.toBeInTheDocument();
    expect(screen.queryByText(/Inspect unresolved/)).not.toBeInTheDocument();
  });
});
