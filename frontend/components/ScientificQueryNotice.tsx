import Link from "next/link";

import type { ScientificQuantityConstraint, ScientificReportQuantity } from "@/lib/api";
import { displayQuantity, knownScientificLookup, knownScientificQuery, knownScientificResults } from "@/lib/scientific-query";

const fieldLabels = { tc_kelvin: "Tc", pressure_gpa: "Pressure" };
const evidenceLabels = { knowledge_origin: "Requested origin", source_role: "Requested source role", experimental_outcome: "Requested outcome" };
const outcomeLabels = {
  positive_reported: "Positive report (unreviewed)",
  not_detected: "No transition reported within stated conditions",
  unspecified: "Outcome not specified", unresolved: "Outcome unresolved", conflicted: "Conflicting outcome fields",
};
function constraintText(value: ScientificQuantityConstraint) {
  if (value.unit_basis === "explicit_ambient_reference") return "Explicit ambient reference (0 GPa reference; not a measured zero)";
  return displayQuantity({ ...value, status: "parsed", uncertainty: null, approximate: false,
    uncertainty_interpretation: null } as ScientificReportQuantity);
}

/** Server interpretation is explained, not upgraded to scientific approval. */
export function ScientificQueryNotice({ query: input, lookup: lookupInput, results: resultsInput, generation,
  rawQuery, context = "Search" }: {
  query?: unknown; lookup?: unknown; results?: unknown; generation?: unknown; rawQuery: string; context?: "Search" | "Ask";
}) {
  if (input === undefined || input === null) return null;
  const query = knownScientificQuery(input, rawQuery);
  if (!query) return <p role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
    Scientific query interpretation unavailable or inconsistent with this query. No interpreted conditions or numerical records are displayed.
  </p>;
  const lookup = knownScientificLookup(lookupInput);
  const results = lookup ? knownScientificResults(resultsInput, lookup, generation, query) : null;
  return <section aria-label={`${context} scientific query`} className="space-y-3 rounded-lg border border-sage-border bg-sage-bg p-4 text-sm">
    <h3 className="font-semibold text-sage-ink">{context} query interpretation</h3>
    <p className="break-words"><span className="font-medium">Original query: </span>{query.raw_query}</p>
    <p className="text-xs text-sage-muted">Bounded interpretation only; not scientific acceptance, an identity adjudication or permission to reuse source content.</p>
    <p><span className="font-medium">Requested task: </span>{query.intent === "numerical" ? "Numerical lookup" : query.intent === "mechanism" ? "Mechanism explanation"
      : query.intent === "mixed" ? "Numerical lookup and explanation" : query.intent === "comparison" ? "Comparison" : "General retrieval"}
      {query.requested_fields.length > 0 && ` · ${query.requested_fields.map(field => fieldLabels[field]).join(", ")}`}</p>
    {query.formulas.length > 0 && <ul className="list-inside list-disc space-y-1" aria-label="Interpreted formulas">
      {query.formulas.map((item, index) => <li key={index} className="break-words">
        <span className="font-medium">Formula notation: </span><code>{item.raw_text}</code>{" → "}
        {item.normalization.status === "normalized" ? <><code>{item.normalization.normalized_formula}</code>{" (notation match only; not sample or phase identity)"}</>
          : <span>Unresolved; no exact formula identity inferred. {item.normalization.reason_codes.map(value => value.replaceAll("_", " ")).join("; ")}.</span>}
      </li>)}
    </ul>}
    {(query.constraints.length > 0 || query.evidence_constraints.length > 0) && <ul className="list-inside list-disc space-y-1" aria-label="Interpreted conditions">
      {query.constraints.map((item, index) => <li key={`quantity-${index}`} className="break-words">
        <span className="font-medium">{fieldLabels[item.field]}: </span>{constraintText(item)} <span className="text-sage-muted">(from “{item.raw_text}”)</span>
      </li>)}
      {query.evidence_constraints.map((item, index) => <li key={`evidence-${index}`} className="break-words">
        <span className="font-medium">{evidenceLabels[item.field]}: </span>{item.value.replaceAll("_", " ")} <span className="text-sage-muted">(from “{item.raw_text}”)</span>
      </li>)}
    </ul>}
    {query.status === "clarification_required" && <div role="status" className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3 text-amber-900">
      <p className="font-medium">Clarification required. Unresolved conditions have not been silently dropped.</p>
      {query.unresolved_clauses.length > 0 && <ul className="list-inside list-disc space-y-1">
        {query.unresolved_clauses.map((item, index) => <li key={index}>“{item.raw_text}” — {item.reason_code.replaceAll("_", " ")}</li>)}
      </ul>}
      <ul className="list-inside list-disc space-y-1">{query.clarification_questions.map((question, index) => <li key={index}>{question}</li>)}</ul>
    </div>}
    {(query.intent === "mixed" || lookup?.reason_codes.includes("explanatory_synthesis_not_performed"))
      && <p className="text-amber-900">This bounded result lookup does not establish the requested mechanism explanation.</p>}
    {!lookup || results === null ? <p role="status" className="text-amber-900">Source-linked result metadata unavailable or inconsistent; numerical records are withheld.</p>
      : lookup.status === "unavailable" ? <p role="status" className="text-amber-900">Source-linked numerical lookup is unavailable. No fallback numbers or material-wide maxima are substituted.</p>
        : lookup.status === "not_requested" ? <p className="text-xs text-sage-muted">No structured numerical lookup was requested.</p>
          : lookup.status === "completed" && results.length === 0 ? <p role="status">No matching source-linked extractions were found in this declared generation. This does not establish absence of a material or result.</p>
            : lookup.status === "completed" && <div className="space-y-3 border-t border-sage-border pt-3">
              <h4 className="font-semibold">Source-linked machine extractions</h4>
              <p className="text-xs text-amber-900">Reported fields from a derived extraction, not an original quotation, independent confirmation, scientific acceptance or ML-training approval. A non-detection does not prove a material cannot superconduct; detection adequacy has not been verified.</p>
              {results.map(({ result, binding }, index) => <article id={`${context.toLowerCase()}-result-${binding.parent_result_revision_id}`} key={`${binding.vector_id}:${result.result_id}:${index}`} className="space-y-2 rounded border border-sage-border bg-white p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h5 className="font-semibold"><code>{result.formula}</code>{result.family ? ` · ${result.family}` : ""}</h5>
                  <Link className="text-accent-deep underline" href={`/paper/${encodeURIComponent(binding.paper_id)}`}>Source paper · extraction {index + 1}</Link>
                </div>
                <p>{result.result_classification.knowledge_origin} · {result.result_classification.source_role} source role · classification {result.result_classification.classification_status}</p>
                <p className="font-medium">{outcomeLabels[result.outcome_state]}</p>
                <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
                  <dt>Tc field{result.outcome_state === "not_detected" ? " (not positive evidence)" : ""}</dt><dd>{displayQuantity(result.tc)}</dd>
                  <dt>Pressure</dt><dd>{result.pressure.pressure_state === "not_reported" ? "Not reported; not assumed ambient"
                    : result.pressure.pressure_state === "ambiguous" ? "Ambiguous pressure; no exact condition inferred"
                      : result.pressure.pressure_state === "explicit_ambient" ? "Explicit ambient reference (not a measured zero)" : displayQuantity(result.pressure)}</dd>
                  <dt>Minimum temperature</dt><dd>{displayQuantity(result.minimum_temperature)}</dd>
                  <dt>Reported method</dt><dd>{result.reported_context.measurement_method || "Not reported"}</dd>
                  <dt>Tc criterion</dt><dd>{result.reported_context.tc_criterion || "Not reported"}</dd>
                  <dt>Sample / form / phase</dt><dd>{[result.reported_context.sample_label, result.reported_context.sample_form, result.reported_context.structure_phase].filter(Boolean).join(" / ") || "Not reported; no shared state inferred"}</dd>
                </dl>
                {result.warning_codes.length > 0 && <p className="text-xs text-amber-900">Warnings: {result.warning_codes.map(value => value.replaceAll("_", " ")).join("; ")}.</p>}
                <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Exact extraction binding</summary>
                  <dl className="mt-2 space-y-1 break-all">
                    <div><dt className="inline font-medium">Result reference: </dt><dd className="inline">{result.result_id}</dd></div>
                    <div><dt className="inline font-medium">Machine extraction revision: </dt><dd className="inline">{binding.parent_result_revision_id}</dd></div>
                    <div><dt className="inline font-medium">Evidence revision: </dt><dd className="inline">{binding.evidence_revision_id}</dd></div>
                    <div><dt className="inline font-medium">Generation / activation: </dt><dd className="inline">{binding.generation_id} / {binding.activation_event_id}</dd></div>
                  </dl>
                </details>
              </article>)}
              {lookup.has_more && <p className="text-xs text-amber-900">Only the first {results.length.toLocaleString("en-US")} matching extraction records are shown. This is a bounded result set, not full-corpus coverage.</p>}
            </div>}
    <details className="text-xs text-sage-muted"><summary className="cursor-pointer">Interpretation details</summary>
      <p className="mt-2 break-words">Normalized query: {query.normalized_query}</p>
      <p>Policy: {query.version}. Recognized language: {query.language}.</p>
      {lookup?.reason_codes.length ? <p>Lookup notes: {lookup.reason_codes.map(value => value.replaceAll("_", " ")).join("; ")}.</p> : null}
    </details>
  </section>;
}
