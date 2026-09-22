import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidencePackingNotice, PackingSourceNotice } from "@/components/EvidencePackingNotice";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { AskHistoryList } from "@/components/dashboard/AskHistoryList";
import { knownInputBudget, knownPackingInventory, knownPackingSelection, knownPackingSummary } from "@/lib/evidence-packing";
import { inputBudget, packedSources, packingInfo, packingSummary } from "../fixtures/evidence-packing";
import { evidenceProvenance } from "../fixtures/evidence-provenance";

describe("operational context packing and exact citation grouping", () => {
  it("keeps complementary same-paper passages separately cited and labels heuristic roles in English", () => {
    const sources = packedSources();
    render(<><MarkdownAnswer markdown="Methods [1]. Results [2]." sources={sources} />
      {sources.map(source => <div key={source.index} id={`src-${source.index}`}><PackingSourceNotice source={source} sources={sources} /></div>)}</>);
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#src-1");
    expect(screen.getByRole("link", { name: "[2]" })).toHaveAttribute("href", "#src-2");
    expect(screen.getByText("Context role hint: Methods (retrieval heuristic).")).toBeVisible();
    expect(screen.getByText("Context role hint: Results (retrieval heuristic).")).toBeVisible();
    expect(screen.getAllByText(/Retained catalogue-source metadata group 1/)).toHaveLength(2);
    expect(screen.getAllByText(/not independent scientific evidence/)).toHaveLength(2);
  });

  it("distinguishes UTF-8 resource limits from actual provider token preflight and scientific support", () => {
    render(<EvidencePackingNotice packing={packingSummary()} inputBudget={inputBudget()} sources={packedSources()} />);
    const notice = screen.getByLabelText("Context selection and input budget");
    expect(notice).toHaveTextContent("2 cited passages · 1 catalogue-source group · 1 selection-diversity group");
    expect(notice).toHaveTextContent("3 admitted candidates in this bounded retrieval set; 1 excluded");
    expect(notice).toHaveTextContent("not independent papers, experiments or confirmations");
    expect(notice).toHaveTextContent("retained metadata, not authenticated original documents or shared samples");
    expect(notice).toHaveTextContent("2,048 / 4,096 bytes");
    expect(notice).toHaveTextContent("Provider-counted input: 500 tokens / 1,024 configured input tokens");
    expect(notice).toHaveTextContent("not billed token usage, model-version attestation, proof of delivery, or scientific validation");
    expect(notice).toHaveTextContent("does not establish a complete scientific answer");
    expect(notice).not.toHaveTextContent(/independently verified|confidence|probability/);
  });

  it("never interprets an unknown generation-start state as no provider work", () => {
    render(<EvidencePackingNotice packing={packingSummary()} inputBudget={inputBudget({ status: "unavailable", generation_started: null })} sources={packedSources()} />);
    expect(screen.getByText(/Generation request started: unknown/)).toBeVisible();
    expect(screen.queryByText(/Generation request started: no/)).not.toBeInTheDocument();
  });

  it("keeps different snapshots of the same paper in different groups", () => {
    const sources = packedSources();
    sources[1].packing_info = packingInfo({ position: 2, chunk_id: "synthetic:chunk-2", source_snapshot_sha256: "e".repeat(64),
      source_group_id: `src:${"f".repeat(64)}`, diversity_group_id: `div:${"1".repeat(64)}` });
    expect(knownPackingInventory(sources)).not.toBeNull();
    render(<PackingSourceNotice source={sources[1]} sources={sources} />);
    expect(screen.getByText(/Retained catalogue-source metadata group 2/)).toBeVisible();
    sources[1].packing_info.source_group_id = sources[0].packing_info!.source_group_id;
    expect(knownPackingInventory(sources)).toBeNull();
  });

  it("rejects shared group IDs across different papers or mismatched source snapshots", () => {
    const sources = packedSources();
    sources[1].paper_id = "synthetic:other-paper";
    expect(knownPackingInventory(sources)).toBeNull();
    sources[1].paper_id = sources[0].paper_id;
    sources[1].packing_info!.source_snapshot_sha256 = "f".repeat(64);
    expect(knownPackingInventory(sources)).toBeNull();
    render(<PackingSourceNotice source={sources[1]} sources={sources} />);
    expect(screen.getByText(/no shared source snapshot is asserted/)).toBeVisible();
  });

  it("rejects duplicate or missing citation positions and duplicate chunk identities", () => {
    for (const mutation of ["index", "position", "chunk_id"] as const) {
      const sources = packedSources();
      if (mutation === "index") sources[1].index = 1;
      else if (mutation === "position") sources[1].packing_info!.position = 1;
      else sources[1].packing_info!.chunk_id = sources[0].packing_info!.chunk_id;
      expect(knownPackingInventory(sources)).toBeNull();
    }
  });

  it("does not label repeated roles or derived Facts as complementary original passages", () => {
    const sources = packedSources();
    sources[1].packing_info!.role_hint = "methods";
    expect(knownPackingInventory(sources)).toBeNull();
    sources[1].packing_info!.role_hint = "results";
    sources[1].evidence_provenance = evidenceProvenance();
    expect(knownPackingInventory(sources)).toBeNull();
  });

  it("shows legacy grouping as unresolved and does not permit multiple complementary legacy passages", () => {
    const sources = packedSources().slice(0, 1);
    sources[0].packing_info = packingInfo({ source_snapshot_sha256: null, source_group_basis: "legacy_paper", group_basis: "legacy_paper" });
    render(<PackingSourceNotice source={sources[0]} sources={sources} />);
    expect(screen.getByText(/Legacy paper group — source snapshot unresolved/)).toBeVisible();
    expect(screen.queryByText(/Retained catalogue-source metadata group/)).not.toBeInTheDocument();
    expect(knownPackingInventory([...sources, { ...sources[0], index: 2, packing_info: { ...sources[0].packing_info!, position: 2, chunk_id: "synthetic:second-legacy", selection_reason: "complementary_role" } }])).toBeNull();
  });

  it("treats catalogue Work grouping as selection diversity, not independent replication", () => {
    const sources = packedSources();
    sources[0].packing_info!.group_basis = "accepted_work_mapping";
    sources[1].paper_id = "synthetic:second-version";
    sources[1].packing_info = packingInfo({ position: 2, chunk_id: "synthetic:chunk-2", group_basis: "accepted_work_mapping",
      source_group_id: `src:${"f".repeat(64)}`, source_snapshot_sha256: "e".repeat(64), selection_reason: "source_coverage" });
    expect(knownPackingSummary(packingSummary({ source_group_count: 2 }), sources)).not.toBeNull();
    render(<EvidencePackingNotice packing={packingSummary({ source_group_count: 2 })} inputBudget={inputBudget()} sources={sources} />);
    expect(screen.getByLabelText("Context selection and input budget")).toHaveTextContent("2 catalogue-source groups · 1 selection-diversity group");
    expect(screen.getByText(/Scientific independence remains unestablished/)).toBeVisible();
  });

  it.each([false, 0, {}, { ...packingInfo(), scientific_acceptance: true }, { ...packingInfo(), source_snapshot_sha256: null },
    { ...packingInfo(), position: true }, { ...packingInfo(), source_group_id: "src:invalid" }, { ...packingInfo(), role_hint: "approved" },
    { ...packingInfo(), secret: "raw Work UUID" }])("fails closed for malformed item metadata %j", value => {
    expect(knownPackingSelection(value)).toBeNull();
  });

  it.each([
    { independent_support_count: 1 }, { independence_status: "independent" }, { scientific_acceptance: 0 },
    { selected_count: 1 }, { candidate_count: true }, { source_group_count: 2 }, { max_per_source: 1 },
    { reason_counts: {} }, { reason_counts: { raw_quote: 1 } }, { reason_codes: ["packing_unavailable", "packing_unavailable"] },
    { excluded: ["PRIVATE_CHUNK"] }, { payload_bytes: 5000 },
  ])("withholds misleading summary counts or unsupported metadata %j", patch => {
    expect(knownPackingSummary({ ...packingSummary(), ...patch }, packedSources())).toBeNull();
  });

  it.each([
    { input_tokens: true }, { input_tokens: NaN }, { input_tokens: 1025 }, { payload_bytes: 4097 },
    { count_method: "estimated_from_bytes" }, { generation_started: 0 }, { scientific_acceptance: 0 },
    { request_sha256: null }, { model: "unknown" }, { status: "rejected", generation_started: true },
    { status: "counted", generation_started: null }, { status: "counted", generation_started: false },
  ])("does not present malformed token/budget reports as a valid preflight %j", patch => {
    expect(knownInputBudget({ ...inputBudget(), ...patch })).toBeNull();
  });

  it.each(["model", "request_sha256", "payload_bytes", "input_tokens", "max_input_tokens", "generation_started"] as const)(
    "rejects an unrequested preflight that retains an observation field: %s", field => {
      const empty = inputBudget({ status: "not_requested", model: null, request_sha256: null, payload_bytes: null,
        input_tokens: null, max_input_tokens: null, generation_started: null });
      expect(knownInputBudget(empty)).not.toBeNull();
      expect(knownInputBudget({ ...empty, [field]: field === "generation_started" ? false : inputBudget()[field] })).toBeNull();
    });

  it("withholds contradictory complete-payload accounting instead of choosing either count", () => {
    render(<EvidencePackingNotice packing={packingSummary()} inputBudget={inputBudget({ payload_bytes: 2049 })} sources={packedSources()} />);
    expect(screen.getByRole("status")).toHaveTextContent("accounting disagree");
    expect(screen.queryByText(/Provider-counted input/)).not.toBeInTheDocument();
    expect(screen.queryByText(/2 cited passages/)).not.toBeInTheDocument();
  });

  it("withholds previous counts after current context is withdrawn", () => {
    const summary = packingSummary({ status: "withheld", selected_count: 0, source_group_count: 0, diversity_group_count: 0,
      payload_bytes: null, reason_counts: {}, reason_codes: ["selected_context_withheld"] });
    render(<EvidencePackingNotice packing={summary} inputBudget={inputBudget()} sources={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Previous source groups and selection counts are not displayed");
    expect(screen.queryByText(/2 cited passages/)).not.toBeInTheDocument();
    expect(screen.getByText(/earlier prepared request, not the withdrawn source inventory/)).toBeVisible();
    expect(knownPackingSummary(summary, packedSources())).toBeNull();
  });

  it("reports provider-token rejection separately from successful local byte packing", () => {
    render(<EvidencePackingNotice packing={packingSummary()} inputBudget={inputBudget({ status: "rejected", input_tokens: 2048, generation_started: false })} sources={packedSources()} />);
    expect(screen.getByText("Provider input preflight: rejected.")).toBeVisible();
    expect(screen.getByText(/Generation request started: no/)).toBeVisible();
    expect(screen.getByText(/Selected context fits the declared local byte budget/)).toBeVisible();
    expect(screen.queryByText(/counted within the configured input limit/)).not.toBeInTheDocument();
  });

  it("does not imply a provider call when the complete base payload exceeds the local budget", () => {
    render(<EvidencePackingNotice packing={packingSummary({ status: "base_budget_exceeded", selected_count: 0, source_group_count: 0,
      diversity_group_count: 0, payload_bytes: 4097, reason_counts: { base_payload_budget: 3 }, reason_codes: ["base_payload_budget_exceeded"] })}
      inputBudget={inputBudget({ status: "not_requested", model: null, request_sha256: null, payload_bytes: null, input_tokens: null, max_input_tokens: null, generation_started: null })} sources={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent("no source passage was selected");
    expect(screen.getByText("Provider input preflight: not requested.")).toBeVisible();
  });

  it("keeps budget unavailability explicit instead of guessing tokens from bytes", () => {
    render(<EvidencePackingNotice packing={packingSummary()} inputBudget={inputBudget({ status: "unavailable", input_tokens: null, generation_started: null })} sources={packedSources()} />);
    expect(screen.getByText("Provider input preflight: unavailable.")).toBeVisible();
    expect(screen.queryByText(/Provider-counted input/)).not.toBeInTheDocument();
    expect(screen.getByText(/Generation request started: unknown/)).toBeVisible();
  });

  it("does not manufacture new packing metadata for legacy responses", () => {
    const { container } = render(<EvidencePackingNotice sources={packedSources().map(source => ({ ...source, packing_info: undefined }))} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("retains saved item labels without reconstructing historical budget or current source support", () => {
    const sources = packedSources();
    render(<AskHistoryList entries={[{ id: "synthetic:history", question: "Why?", answer: "Saved text [1] [2].", sources,
      tokens_used: 999, latency_ms: 1, language: "en", created_at: "2026-09-08T00:00:00Z" }]} onDeleted={() => {}} />);
    expect(screen.getByText(/2 saved citation entries/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getAllByLabelText("Saved context selection")).toHaveLength(2);
    expect(screen.getAllByText(/Saved catalogue-source metadata group 1/)).toHaveLength(2);
    expect(screen.getByText(/cannot reconstruct the original input-budget report/)).toBeVisible();
    expect(screen.queryByLabelText("Context selection and input budget")).not.toBeInTheDocument();
    expect(screen.queryByText(/Provider-counted input/)).not.toBeInTheDocument();
    expect(screen.getByText(/Scientific support status is unknown/)).toBeVisible();
  });
});
