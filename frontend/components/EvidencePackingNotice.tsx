import { knownInputBudget, knownPackingInventory, knownPackingSummary, type PackingSource } from "@/lib/evidence-packing";

const number = (value: number) => value.toLocaleString("en-US");
const roleLabels = { methods: "Methods", results: "Results", table: "Table context", other: "Other / unclassified" };
const selectionLabels = { source_diversity: "Selection diversity", source_coverage: "Additional source coverage", complementary_role: "Complementary context role" };

/** A context budget is operational accounting, not an assessment of evidence. */
export function EvidencePackingNotice({ packing, inputBudget, sources, historical = false }: {
  packing?: unknown; inputBudget?: unknown; sources: PackingSource[]; historical?: boolean;
}) {
  if (packing === undefined && inputBudget === undefined) return null;
  const summary = knownPackingSummary(packing, sources);
  const budget = knownInputBudget(inputBudget);
  const disagreement = summary?.status === "packed" && budget?.payload_bytes !== null && budget?.payload_bytes !== undefined
    && summary.payload_bytes !== budget.payload_bytes;
  return <section aria-label="Context selection and input budget" className="mb-4 space-y-2 rounded border border-sage-border bg-sage-bg p-3 text-sm">
    <h3 className="font-semibold">Context selection and input budget</h3>
    {historical && <p className="text-xs text-amber-900">Saved answer-time accounting. No new provider count, generation request or present-day source check was performed for this history view.</p>}
    <p className="text-xs text-amber-900">Citation entries are passages, not independent papers, experiments or confirmations. Catalogue-source snapshots group retained metadata, not authenticated original documents or shared samples. Scientific independence remains unestablished.</p>
    {disagreement ? <p role="status" className="text-amber-900">Input-budget and selected-context accounting disagree. Counts and completeness claims are withheld.</p>
      : <>
        {!summary ? <p role="status" className="text-amber-900">Context-selection metadata unavailable or inconsistent. No grouping or coverage count is established.</p>
          : summary.status === "not_requested" ? <p>Context packing was not requested.</p>
            : summary.status === "withheld" ? <p role="status" className="text-amber-900">Selected context was withheld. Previous source groups and selection counts are not displayed.</p>
              : summary.status === "unavailable" ? <p role="status" className="text-amber-900">Context packing is unavailable. No complete input selection is established.</p>
                : <>
                  <p>{number(summary.selected_count)} cited passage{summary.selected_count === 1 ? "" : "s"} · {number(summary.source_group_count)} catalogue-source group{summary.source_group_count === 1 ? "" : "s"} · {number(summary.diversity_group_count)} selection-diversity group{summary.diversity_group_count === 1 ? "" : "s"}.</p>
                  <p className="text-xs">{number(summary.candidate_count)} admitted candidates in this bounded retrieval set; {number(summary.candidate_count - summary.selected_count)} excluded from context. These are not full-corpus coverage counts.</p>
                  {summary.status === "base_budget_exceeded" ? <p role="status" className="text-amber-900">The base request exceeds the local byte budget; no source passage was selected.</p>
                    : summary.status === "empty" ? <p role="status">No passage was selected within this declared packing policy.</p>
                      : <p>Selected context fits the declared local byte budget. This does not establish a complete scientific answer.</p>}
                  <p className="text-xs">Complete-payload UTF-8 accounting: {number(summary.payload_bytes!)} / {number(summary.byte_budget!)} bytes. This is a resource limit, not a tokenizer or scientific-support measurement.</p>
                  <details className="text-xs"><summary className="cursor-pointer">Selection limits and exclusions</summary>
                    <p className="mt-1">At most {number(summary.max_chunks)} passages, {number(summary.max_per_source)} per catalogue-source metadata snapshot and {number(summary.max_per_work)} per catalogue Work group. Unresolved legacy paper groups permit only one passage.</p>
                    {Object.entries(summary.reason_counts).map(([reason, count]) => <p key={reason}>{reason.replaceAll("_", " ")}: {number(count!)}</p>)}
                    {summary.reason_codes.length > 0 && <p>Notes: {summary.reason_codes.map(reason => reason.replaceAll("_", " ")).join("; ")}.</p>}
                  </details>
                </>}
        {!budget ? <p role="status" className="text-amber-900">Provider input-budget metadata unavailable or inconsistent. Do not infer a successful token preflight.</p>
          : <div className="space-y-1 border-t border-sage-border pt-2 text-xs">
            <p className="font-medium">Provider input preflight: {budget.status === "counted" ? "counted within the configured input limit" : budget.status === "not_requested" ? "not requested" : budget.status === "rejected" ? "rejected" : "unavailable"}.</p>
            {budget.input_tokens !== null && <p>Provider-counted input: {number(budget.input_tokens)} tokens{budget.max_input_tokens !== null && ` / ${number(budget.max_input_tokens)} configured input tokens`}.</p>}
            {budget.payload_bytes !== null && <p>Preflight payload: {number(budget.payload_bytes)} / {number(budget.byte_limit)} bytes.</p>}
            <p>Generation request started: {budget.generation_started === true ? "yes" : budget.generation_started === false ? "no" : "unknown"}. This does not report completion or scientific correctness.</p>
            <p>The provider count covers the prepared request. It is not billed token usage, model-version attestation, proof of delivery, or scientific validation.</p>
            {summary?.status === "withheld" && <p>The retained preflight describes the earlier prepared request, not the withdrawn source inventory.</p>}
          </div>}
      </>}
  </section>;
}

/** One citation keeps its own index even when several passages share a paper. */
export function PackingSourceNotice({ source, sources, historical = false }: {
  source: PackingSource; sources: PackingSource[]; historical?: boolean;
}) {
  if (source.packing_info === undefined || source.packing_info === null) return null;
  const inventory = knownPackingInventory(sources);
  const item = inventory?.find(row => row.position === source.index);
  if (!inventory || !item) return <span className="mt-1 block text-xs text-amber-900">{historical ? "Saved context" : "Context"} grouping unresolved; no shared source snapshot is asserted.</span>;
  const group = [...new Set(inventory.map(row => row.source_group_id))].indexOf(item.source_group_id) + 1;
  return <span aria-label={historical ? "Saved context selection" : "Citation context selection"} className="mt-1 block space-y-1 text-xs text-sage-muted">
    <span className="block">{historical ? "Saved context role hint" : "Context role hint"}: {roleLabels[item.role_hint]} (retrieval heuristic).</span>
    <span className="block">{item.source_group_basis === "source_snapshot" ? `${historical ? "Saved catalogue-source" : "Retained catalogue-source"} metadata group ${number(group)}` : "Legacy paper group — source snapshot unresolved"}. {selectionLabels[item.selection_reason]}.</span>
    <span className="block text-amber-900">{historical ? "Saved labels only; current grouping and the original prompt budget have not been rechecked." : "Group membership is not independent scientific evidence or permission to reuse source content."}</span>
  </span>;
}
