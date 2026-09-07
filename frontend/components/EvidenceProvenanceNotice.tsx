import type { EvidenceProvenance } from "@/lib/api";
import { knownEvidenceProvenance } from "@/lib/evidence-provenance";

const LABELS = { original_passage: "Original passage", abstract: "Abstract", derived_fact: "Derived fact", legacy_unknown: "Legacy evidence type unresolved" };

export function EvidenceProvenanceNotice({ evidence: input, historical = false }: { evidence?: EvidenceProvenance; historical?: boolean }) {
  const evidence = knownEvidenceProvenance(input);
  if (!evidence) return <span className="mt-1 block text-xs text-amber-900">Evidence lineage unresolved; no independent support established.</span>;
  return <span className="mt-1 block space-y-1 text-xs text-amber-900" aria-label={historical ? "Saved evidence provenance" : "Evidence provenance"}>
    <span className="block">{LABELS[evidence.chunk_kind]} · Original evidence root unresolved.</span>
    <span className="block">{historical ? "Saved provenance only; current lineage has not been rechecked here." :
      evidence.currentness === "stale" ? "Stale retrieval projection; text withheld." :
      evidence.currentness === "current" ? "Current catalogue binding; not scientific acceptance." : "Current catalogue binding unresolved."}</span>
    <span className="block">{evidence.permission_status === "restricted" ? "Text restricted; consult the source record." : "Text permissions remain unreviewed; this record grants no new use rights."}</span>
    {evidence.chunk_kind === "derived_fact" && <span className="block">Generated from an extraction; not an independent confirmation or original quotation.</span>}
    {evidence.evidence_revision_id && <span className="block break-all">{historical ? "Saved evidence revision" : "Evidence revision"}: {evidence.evidence_revision_id}</span>}
    {evidence.parent_result_revision_id && <span className="block break-all">Machine extraction revision: {evidence.parent_result_revision_id}</span>}
    {evidence.rendering_version && <span className="block">Renderer: {evidence.rendering_version}</span>}
    {Object.keys(evidence.source_locator ?? {}).length > 0 && <span className="block">Reported source coordinates: {Object.entries(evidence.source_locator).map(([key, value]) => `${key}: ${typeof value === "number" ? value.toLocaleString("en-US") : value}`).join("; ")}</span>}
  </span>;
}
