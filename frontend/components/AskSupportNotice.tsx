import Link from "next/link";
import type { AskClaimAssessment, AskResponse, AskSupportCoverage } from "@/lib/api";
import { SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { EvidenceProvenanceNotice } from "@/components/EvidenceProvenanceNotice";
import { displayedAskSupportStatus, excerptSourceIsHeld, resolveAskSource, SCIENTIFIC_SUPPORT_POLICY_VERSION, supportEvidenceSource, supportStatusLabel } from "@/lib/ask-support";

const ANSWER_MODE_LABELS = {
  synthesis: "Generated synthesis",
  limited_synthesis: "Limited synthesis — evidence gaps remain",
  extractive_fallback: "Extractive fallback — retrieved excerpts, not a validated answer",
  abstention: "Abstention — no supported synthesis provided",
};

export function AskSupportNotice({ response, historical = false }: { response: AskResponse; historical?: boolean }) {
  const status = displayedAskSupportStatus(response);
  const knownPolicy = response.support_policy_version === SCIENTIFIC_SUPPORT_POLICY_VERSION;
  const claims = response.claim_assessments ?? [];
  const supportedMetadataMismatch = response.scientific_support_status === "supported" && status !== "supported";
  const mode = response.answer_mode && Object.hasOwn(ANSWER_MODE_LABELS, response.answer_mode)
    ? ANSWER_MODE_LABELS[response.answer_mode] : "Answer mode unavailable (legacy response)";

  return <section className={`mb-4 rounded-md border p-3 text-sm ${status === "contradicted" ? "border-red-200 bg-red-50 text-red-950" : status === "supported" ? "border-slate-200 bg-slate-50 text-sage-ink" : "border-amber-200 bg-amber-50 text-amber-950"}`} aria-label="Answer evidence checks">
    {historical && <p className="mb-2 font-medium">Saved answer-time checks only. The answer and source permissions have not been revalidated today.</p>}
    <p className="font-semibold" role="status">{response.assessment_scope === "generated_draft" ? "Draft claim checks: " : ""}{supportStatusLabel(status)}</p>
    <p className="mt-1 text-xs">{mode}. These bounded checks compare answer claims with retrieved excerpts; they do not establish scientific truth, experimental confirmation, or permission to use a claim as an ML label.</p>
    <p className="mt-2 text-xs">Citation indices: {response.citation_indices_valid === true ? "mechanically valid" : response.citation_indices_valid === false ? "invalid indices were detected" : "not reported by this API version"}. Lexical excerpt checks: {knownPolicy && response.lexical_support_checked === true ? "performed" : "not established"}. Valid source references alone do not demonstrate support.</p>
    {!knownPolicy && <p className="mt-2 text-xs">Scientific support metadata is missing or uses an unsupported policy version. The legacy citation_valid flag is only a mechanical check, not a scientific assessment.</p>}
    {response.assessment_scope === "generated_draft" && <p className="mt-2 text-xs">These checks concern the generated draft, not a verification of any delivered fallback. Source excerpts are not verified conclusions.</p>}
    {response.assessment_scope === "none" && <p className="mt-2 text-xs">No generated draft was assessed. Retrieved excerpts, if present, are source material rather than checked conclusions.</p>}
    {response.assessment_scope === undefined && knownPolicy && <p className="mt-2 text-xs">Assessment scope was not supplied. Do not assume these checks cover the displayed answer.</p>}
    {supportedMetadataMismatch && <p className="mt-2 text-xs">The reported support status lacks compatible claim-level evidence. Support is not established by this response.</p>}
    {response.sources.length === 0 && <p className="mt-2 text-xs">No retrieved sources are available for inspection.</p>}
    {(response.support_warnings?.length || response.citation_warnings?.length) ? <details className="mt-2 text-xs"><summary className="cursor-pointer font-medium">Check limitations and warnings</summary><ul className="mt-1 list-disc space-y-1 pl-4">{[...(response.support_warnings ?? []), ...(response.citation_warnings ?? [])].map((warning, index) => <li key={index}>{warning}</li>)}</ul></details> : null}
    <SupportCoverage coverage={response.support_coverage} />
    {claims.length > 0 ? <details className="mt-3"><summary className="cursor-pointer text-xs font-medium">Inspect draft claim checks ({claims.length}) and cited excerpts</summary><ol className="mt-3 space-y-3">{claims.map((claim, index) => <ClaimAssessment key={`${claim.claim_id}:${index}`} claim={claim} sources={response.sources} historical={historical} knownPolicy={knownPolicy && response.assessment_scope === "generated_draft" && !supportedMetadataMismatch} />)}</ol></details> : <p className="mt-2 text-xs">No claim-level assessments were supplied. An unchecked answer is not the same as an answer shown to be unsupported.</p>}
  </section>;
}

function SupportCoverage({ coverage }: { coverage?: AskSupportCoverage }) {
  if (!coverage) return <p className="mt-2 text-xs">Assessment coverage was not supplied; completeness is unknown.</p>;
  const fields = [
    ["total_claims", "Draft claims identified"], ["assessed_claims", "Claims assessed"],
    ["supported_claims", "Excerpt-consistent"], ["contradicted_claims", "Conflicts detected"],
    ["undetermined_claims", "Undetermined"],
  ] as const;
  return <details className="mt-2 text-xs"><summary className="cursor-pointer font-medium">Bounded assessment coverage{coverage.truncated ? " — incomplete" : ""}</summary>
    <dl className="mt-2 grid gap-1 sm:grid-cols-2">{fields.map(([key, label]) => {
      const value = coverage[key];
      return <div className="flex gap-2" key={key}><dt>{label}:</dt><dd>{typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "not reported"}</dd></div>;
    })}</dl>
    <p className="mt-2">Counts describe bounded draft/excerpt checks, not coverage of every scientific assertion or every relevant paper.{coverage.truncated ? " The input or assessments were truncated; unchecked portions remain unresolved." : " No completeness of scientific evidence is implied."}</p>
    {coverage.limits && <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words">{JSON.stringify(coverage.limits, null, 2)}</pre>}
  </details>;
}

function ClaimAssessment({ claim, sources, knownPolicy, historical }: { claim: AskClaimAssessment; sources: AskResponse["sources"]; knownPolicy: boolean; historical: boolean }) {
  const supportedEvidence = claim.evidence.some(evidence => {
    const source = supportEvidenceSource(evidence.source_index, evidence.paper_id, sources);
    return claim.cited_indices.includes(evidence.source_index) && evidence.excerpt.trim() && source && !excerptSourceIsHeld(source) && !source.evidence_provenance;
  });
  const status = !knownPolicy ? "not_checked" : claim.status === "supported" && !supportedEvidence ? "undetermined" : claim.status;
  return <li className="rounded border border-slate-200 bg-white p-3 text-sage-ink">
    <p className={`text-xs font-semibold ${status === "contradicted" ? "text-red-900" : ""}`}>{supportStatusLabel(status)}</p>
    <p className="mt-1 whitespace-pre-wrap break-words">{claim.text}</p>
    <p className="mt-1 break-all text-[11px] text-slate-500">Claim ID: {claim.claim_id}</p>
    <div className="mt-2 flex flex-wrap gap-2 text-xs" aria-label="Claim cited sources">{claim.cited_indices.length ? claim.cited_indices.map((index, position) => resolveAskSource(index, sources) ? <a href={`#src-${index}`} className="text-sky-800 underline" key={`${index}:${position}`}>Source [{index}]</a> : <span className="text-amber-900" key={position}>Unresolved citation [{String(index)}]</span>) : <span>No citation indices attached.</span>}</div>
    {claim.reason_codes.length > 0 && <p className="mt-2 text-xs text-slate-600">Check reasons: {claim.reason_codes.map(reason => reason.replaceAll("_", " ")).join("; ")}</p>}
    {claim.evidence.length > 0 ? <ul className="mt-2 space-y-2">{claim.evidence.map((evidence, index) => {
      const source = claim.cited_indices.includes(evidence.source_index) ? supportEvidenceSource(evidence.source_index, evidence.paper_id, sources) : null;
      return <li className="border-l-2 border-slate-200 pl-3" key={index}>
        {source ? <div className="text-xs"><Link href={`/paper/${encodeURIComponent(source.paper_id)}`} className="text-sky-800 underline">[{source.index}] {source.title || source.paper_id}</Link>{historical && <p>Saved source status:</p>}<SourceVisibilityNotice visibility={source.source_visibility} compact />{source.evidence_provenance !== undefined && <EvidenceProvenanceNotice evidence={source.evidence_provenance} historical={historical} />}</div> : <p className="text-xs text-amber-900">Evidence source could not be matched to a unique cited source. No source link is asserted.</p>}
        <blockquote className="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed">{!source || excerptSourceIsHeld(source) ? historical ? "Excerpt withheld: saved evidence was restricted, stale, or unavailable." : "Excerpt withheld: current evidence is restricted, stale, or unavailable." : evidence.excerpt || "No excerpt supplied."}</blockquote>
      </li>;
    })}</ul> : <p className="mt-2 text-xs text-slate-600">No supporting or conflicting excerpts were supplied for this claim.</p>}
  </li>;
}
