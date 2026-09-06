import type { MaterialAnomalyReview, MaterialRawArchive, ScientificAnomalyFinding } from "@/lib/api";
import { evidenceText, objectValue } from "@/lib/property-evidence";
import { anomalyStatus, archiveJson, hasAnomalyPolicy, hasMaterialAnomalyReview, hasRawArchive, RAW_ARCHIVE_DISPLAY_LIMIT } from "@/lib/scientific-anomalies";

const label = (value: unknown) => evidenceText(value)?.replaceAll("_", " ") ?? "Not reported";

function FindingDetails({ finding }: { finding: ScientificAnomalyFinding }) {
  const quantity = objectValue(finding.quantity);
  return <li className="border-t border-amber-200 pt-2">
    <p className="font-medium">{finding.description}</p>
    <dl className="mt-1 space-y-1">
      <div><dt className="inline">Rule: </dt><dd className="inline break-all">{finding.rule_id} · {finding.rule_version}</dd></div>
      <div><dt className="inline">Category / severity: </dt><dd className="inline">{label(finding.category)} / {label(finding.severity)}</dd></div>
      <div><dt className="inline">Reason: </dt><dd className="inline">{label(finding.reason)}</dd></div>
      <div><dt className="inline">Review outcome: </dt><dd className="inline">{label(finding.outcome)}</dd></div>
      <div><dt className="inline">Affected properties: </dt><dd className="inline break-words">{Array.isArray(finding.affected_properties) ? finding.affected_properties.join(", ") : "Unavailable"}</dd></div>
      {Object.keys(quantity).length > 0 && <div><dt className="inline">Retained source token: </dt><dd className="inline break-words font-mono">{archiveJson(quantity.raw_value)}{evidenceText(quantity.raw_unit) ? ` · source unit: ${evidenceText(quantity.raw_unit)}` : ""}</dd></div>}
    </dl>
    <details className="mt-2">
      <summary className="cursor-pointer">Rule applicability and reference conditions</summary>
      <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2 text-[11px]">{archiveJson(finding.applicability)}</pre>
    </details>
  </li>;
}

/** The input is the assessment of this record, not a guessed material-level join. */
export function RecordAnomalyReview({ assessment }: { assessment: unknown }) {
  const review = objectValue(assessment);
  const known = hasAnomalyPolicy(assessment);
  const findings = known && Array.isArray(review.findings) ? review.findings as ScientificAnomalyFinding[] : [];
  return <details className="max-w-lg text-left text-xs font-normal">
    <summary className="cursor-pointer text-amber-900">{anomalyStatus(assessment)}</summary>
    <p className="mt-2 text-slate-600">{known ? `Policy: ${review.version}. No findings is not scientific acceptance. A format issue means the parser or metadata needs review, not that the physics is impossible.` : "This response does not establish a supported anomaly assessment. Missing or unknown policy metadata is not approval."}</p>
    {known && <>
      <p className="mt-1 break-all text-slate-600">Result: {evidenceText(review.result_id) ?? "Unavailable"}</p>
      <p className="mt-1 text-slate-600">Operational references are review triggers, not physical upper limits. Values are not clipped or replaced by this display; source corrections require separate evidence-backed revision.</p>
      {findings.length > 0 && <ul className="mt-2 space-y-2 text-amber-950">{findings.slice(0, 40).map((finding, index) => <FindingDetails key={`${finding.finding_id}:${index}`} finding={finding} />)}</ul>}
      {(review.findings_truncated === true || findings.length > 40) && <p className="mt-2 text-amber-900">Only a bounded set of findings is included; absence from this list does not mean a rule did not fire.</p>}
    </>}
  </details>;
}

export function ScientificAnomalyNotice({ review, compact = false }: { review?: MaterialAnomalyReview; compact?: boolean }) {
  if (!review && compact) return null;
  const known = hasMaterialAnomalyReview(review);
  const counts = objectValue(review?.counts);
  const count = (key: string) => { const value = counts[key]; return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "Unavailable"; };
  return <details className={compact ? "mt-1 max-w-sm text-xs" : "rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm"}>
    <summary className="cursor-pointer font-medium text-amber-950">{!known ? "Anomaly policy unavailable" : review?.needs_review ? "Scientific anomaly review required" : "Operational policy: no findings"}</summary>
    <p className="mt-2 text-xs text-slate-600">Anomaly rules flag records for review, not scientific rejection or acceptance. Historical thresholds are operational references, not universal physical limits. This view does not cap or rewrite retained values.</p>
    {known ? <>
      <p className="mt-2 break-all text-xs text-slate-600">Policy: {review!.version}</p>
      <p className="mt-1 text-xs text-slate-600">Retained records assessed: {count("total_records")} · no findings: {count("no_findings")} · review required: {count("review_required")} · format or parser review: {count("format_invalid")}</p>
      <p className="mt-1 text-xs text-slate-600">Counts describe extracted records, not independent experiments. “No findings” does not establish scientific validity or ML readiness.</p>
      {review!.records_truncated && <p className="mt-1 text-xs text-slate-600">The response contains a bounded assessment list, not every retained record.</p>}
      {!compact && <p className="mt-2 text-xs text-slate-600">Inspect each record&apos;s review status and the retained-record Archive below for the authorized source fields. Pending source corrections are not applied by this view.</p>}
    </> : <p className="mt-2 text-xs text-slate-600">No supported policy assessment was supplied. A legacy review flag or source tier does not substitute for a versioned result assessment.</p>}
  </details>;
}

/** No fetch or permission inference: render only this server-provided archive contract. */
export function RawScientificArchive({ archive }: { archive?: MaterialRawArchive }) {
  const known = hasRawArchive(archive);
  const records = known ? archive!.records.slice(0, RAW_ARCHIVE_DISPLAY_LIMIT) : [];
  return <section>
    <details className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-700">Retained-record Archive</summary>
      <p className="mt-2 text-xs text-slate-600">Only scientific fields authorized by the server for this material are shown. This is not a full historical archive, the complete source document or a guarantee that all previously excluded data can be recovered. Restricted or quarantined data is not retrieved through another route.</p>
      {!known ? <p className="mt-3 text-sm text-slate-600">Archive unavailable in this response. No raw records are reconstructed from catalogue values or another endpoint.</p> : <>
        <p className="mt-2 break-all text-xs text-slate-600">Policy: {archive!.version} · scope: retained material records · field policy: scientific allowlist, not full source</p>
        <p className="mt-1 text-xs text-slate-600">Showing {records.length.toLocaleString("en-US")} returned records. Raw means the retained extraction representation; it is not necessarily a verbatim source quotation or an accepted scientific result.</p>
        {(archive!.truncated || archive!.records.length > RAW_ARCHIVE_DISPLAY_LIMIT) && <p className="mt-2 text-xs text-amber-900">This Archive response is truncated. Omitted records are not treated as absent or approved.</p>}
        {records.length === 0 && <p className="mt-3 text-sm text-slate-600">No retained records were returned in this authorized Archive response.</p>}
        <ul className="mt-3 space-y-3">{records.map((record, index) => <li key={`${record.result_id}:${record.record_index}:${index}`}>
          <details className="rounded border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer break-all text-xs font-medium">Retained record {index + 1} · {record.result_id}</summary>
            <p className="mt-2 text-xs text-slate-500">Returned record index: {record.record_index}. This index is not a persistent scientific identity.</p>
            <div className="mt-2"><RecordAnomalyReview assessment={record.assessment} /></div>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-3 text-[11px] text-slate-700" aria-label={`Retained raw scientific fields for ${record.result_id}`}>{archiveJson(record.raw)}</pre>
          </details>
        </li>)}</ul>
      </>}
    </details>
  </section>;
}
