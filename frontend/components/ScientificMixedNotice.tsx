import Link from "next/link";

import type { AskResponse } from "@/lib/api";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";
import { knownPackingSummary } from "@/lib/evidence-packing";
import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";
import { SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { EvidenceProvenanceNotice } from "@/components/EvidenceProvenanceNotice";
import { PackingSourceNotice } from "@/components/EvidencePackingNotice";

/** Separate candidate displays, never a generated explanation of a numerical result. */
export function ScientificMixedNotice({ response, rawQuery, historical = false }: { response: AskResponse; rawQuery: string; historical?: boolean }) {
  const mixed = knownScientificMixedResponse(response, rawQuery);
  if (mixed?.status === "not_requested") return null;
  if (!mixed) return <section aria-label="Mixed scientific retrieval" className="space-y-2 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
    <h3 className="font-semibold">Numerical explanation not established</h3>
    <p role="status">Mixed result and passage metadata is unavailable or inconsistent. Numerical records, explanation candidates and association links are withheld.</p>
  </section>;
  if (mixed.status === "unavailable") return <section aria-label="Mixed scientific retrieval" className="space-y-2 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
    <h3 className="font-semibold">Numerical explanation not established</h3>
    <p role="status">{historical ? "The saved mixed retrieval was unavailable. It retained no numerical records, original passage candidates or associations. This history view does not retry the query." : "Mixed retrieval is unavailable. Both numerical records and original passage candidates have been withdrawn; no previous association is retained. Please retry the query."}</p>
    <p>No provider token count or answer generation was requested for this mixed lookup.</p>
  </section>;

  const results = response.scientific_results!, packing = knownPackingSummary(response.evidence_packing, response.sources)!;
  const number = (value: number) => value.toLocaleString("en-US");
  return <section aria-label="Mixed scientific retrieval" className="space-y-5">
    <div className="space-y-2 rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <h3 className="font-semibold">Numerical explanation not established</h3>
      {historical && <p>Saved retrieval observations only. These rows and associations have not been refreshed or scientifically revalidated in this history view.</p>}
      <p>Structured extraction records and original passage candidates are shown separately. A reviewed Result-to-passage bridge is missing.</p>
      <p>Sharing a paper, Work group or catalogue snapshot does not establish the same experiment, sample, conditions or a causal explanation. Catalogue snapshots describe retained metadata, not authenticated original documents.</p>
      <p>No provider token count or answer generation was requested for this mixed lookup. No numerical synthesis or scientific acceptance is asserted.</p>
      <p>{number(mixed.result_count)} extraction record{mixed.result_count === 1 ? "" : "s"} + {number(mixed.source_count)} original candidate{mixed.source_count === 1 ? "" : "s"} / {number(mixed.max_selected_inputs)} combined input limit. These counts are not independent evidence.</p>
      {mixed.reason_codes.includes("combined_source_limit") && <p>The combined input limit restricted candidate selection; this is not complete literature coverage.</p>}
    </div>

    <section aria-label="Structured extraction records" className="space-y-3">
      <h3 className="font-semibold text-sage-ink">Structured extraction records</h3>
      <ScientificQueryNotice context="Ask" rawQuery={rawQuery} query={response.scientific_query}
        lookup={response.scientific_lookup} results={results} generation={response.retrieval_generation} historical={historical} />
    </section>

    <section aria-label="Original explanation candidates" className="space-y-3">
      <h3 className="font-semibold text-sage-ink">Original explanation candidates</h3>
      <p className="text-sm text-amber-950">Retained original-passage candidates for inspection, not established explanations of the numerical records above. Citation indices [n] refer only to this original-passage list, not extraction-record numbering.</p>
      {response.sources.length === 0 ? <p role="status" className="text-sm text-sage-muted">No original passage candidate is available within this combined input limit. No numerical explanation is inferred.</p>
        : <div className="grid gap-3 lg:grid-cols-2">{response.sources.map(source => <article key={source.index} id={`src-${source.index}`}
          className="space-y-2 rounded border border-sage-border bg-white p-4 text-sm">
          <Link href={`/paper/${encodeURIComponent(source.paper_id)}`} className="font-medium text-accent-deep underline">[{source.index}] {source.title}</Link>
          <p className="text-xs text-sage-muted">{source.authors_short}{source.year !== null ? ` · ${source.year}` : ""}{source.section ? ` · ${source.section}` : ""}</p>
          {historical && <p className="text-xs text-sage-muted">Saved source status:</p>}
          <SourceVisibilityNotice visibility={source.source_visibility} compact />
          <EvidenceProvenanceNotice evidence={source.evidence_provenance} historical={historical} />
          <blockquote className="border-l-2 border-sage-border pl-3 text-sm leading-relaxed">{source.snippet || "No excerpt supplied."}</blockquote>
          <PackingSourceNotice source={source} sources={response.sources} historical={historical} />
        </article>)}</div>}
      {packing.payload_bytes !== null && packing.byte_budget !== null && <p className="text-xs text-sage-muted">
        Original-candidate context: {number(packing.payload_bytes)} / {number(packing.byte_budget)} canonical UTF-8 bytes.
        This is local resource accounting, not a provider token measurement or a submitted generation request.
      </p>}
    </section>

    {mixed.associations.length > 0 && <details className="rounded border border-sage-border p-3 text-xs text-sage-muted">
      <summary className="cursor-pointer font-medium">Inspect unresolved record–passage associations ({number(mixed.associations.length)})</summary>
      <p className="my-3">Every displayed pair remains unestablished. Same catalogue metadata is only a declared relation; different metadata does not prove scientific independence.</p>
      <div className="overflow-x-auto"><table className="w-full border-collapse text-left">
        <caption className="sr-only">Unresolved extraction-record and original-passage pairs</caption>
        <thead><tr>{["Extraction record", "Original candidate", "Declared catalogue relation", "Scientific association"].map(label => <th key={label} scope="col" className="border-b border-sage-border p-2 font-medium">{label}</th>)}</tr></thead>
        <tbody>{mixed.associations.map(item => {
          const index = results.findIndex(result => result.binding.parent_result_revision_id === item.parent_result_revision_id);
          return <tr key={`${item.parent_result_revision_id}:${item.source_index}`}>
            <td className="border-b border-sage-border p-2"><a className="text-accent-deep underline" href={`#ask-result-${item.parent_result_revision_id}`}>Extraction {index + 1} · {results[index].result.formula}</a></td>
            <td className="border-b border-sage-border p-2"><a className="text-accent-deep underline" href={`#src-${item.source_index}`}>Original [{item.source_index}]</a></td>
            <td className="border-b border-sage-border p-2">{item.catalogue_relation === "same_snapshot" ? "Same retained paper/catalogue snapshot" : "Not the same retained paper/catalogue snapshot"}</td>
            <td className="border-b border-sage-border p-2 text-amber-950">Not established — reviewed bridge missing</td>
          </tr>;
        })}</tbody>
      </table></div>
    </details>}
  </section>;
}
