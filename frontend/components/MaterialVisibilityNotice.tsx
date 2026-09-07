import { knownOccurrenceVisibility, knownSourceVisibility, knownVisibility, sourceVisibilityLabel, visibilityLabel, visibilityWarning } from "@/lib/material-visibility";

/** Reason codes only: private reviewer notes and source text never become UI advice. */
export function MaterialVisibilityNotice({ visibility, compact = false, scope = "material" }: {
  visibility: unknown; compact?: boolean; scope?: "material" | "source occurrence";
}) {
  const v = scope === "source occurrence" ? knownOccurrenceVisibility(visibility) : knownVisibility(visibility);
  const catalogue = v?.state === "catalogue" && v.public_catalogue_eligible;
  return <div className={`${compact ? "mt-1 text-[11px]" : "rounded-lg border p-4 text-sm"} ${catalogue ? "border-slate-200 bg-slate-50 text-slate-600" : "border-amber-200 bg-amber-50 text-amber-950"}`} aria-label={`${scope} visibility`}>
    <p className="font-medium">{visibilityLabel(v, scope)}</p>
    {!compact && <p className="mt-1">{visibilityWarning(v, scope)}</p>}
    {scope === "source occurrence" && <p className="mt-1">Source-occurrence policy only; no material identity or catalogue acceptance is inferred from the formula.</p>}
    {!compact && v && <>
      {v.reason_codes.length > 0 && <p className="mt-2">Reasons: {v.reason_codes.map(code => code.replaceAll("_", " ")).join("; ")}</p>}
      <p className="mt-2 break-all text-xs">Policy: {v.version} · source status: {v.source_status} · review revision: {v.review_revision ?? "No resolved material revision"}</p>
    </>}
  </div>;
}

export function SourceVisibilityNotice({ visibility, compact = false }: { visibility: unknown; compact?: boolean }) {
  const v = knownSourceVisibility(visibility);
  const active = v?.source_status === "active";
  return <div aria-label="Bibliographic source visibility" className={`mt-2 rounded border p-2 text-xs ${active ? "border-slate-200 bg-slate-50 text-slate-600" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
    <p className="font-medium">{sourceVisibilityLabel(v)}</p>
    {!compact && <p className="mt-1">Bibliographic access preserves source history; it does not approve extracted materials or validate reported claims. Review warnings on each occurrence separately.</p>}
  </div>;
}
