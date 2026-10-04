import type { MaterialRecordCoverage } from "@/lib/api";
import Link from "@/components/AppLink";
import { recordCoverageFieldRows, recordCoverageReasonLabel } from "@/lib/material-record-coverage";

/** Inspected eligible-pool positions are not raw array indices or physical samples. */
export function MaterialRecordFieldCoverage({ coverage, field, label }: {
  coverage: MaterialRecordCoverage; field: string; label: string;
}) {
  const rows = recordCoverageFieldRows(coverage, field);
  if (rows === null) return null;
  const statuses = { present: "Retained value", missing: "Missing retained value", not_applicable: "Not applicable" };
  return <details className="mt-2 max-w-[26rem] text-xs">
    <summary className="min-h-11 cursor-pointer content-center text-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep">Inspect {label} records ({rows.length})</summary>
    <p className="mt-1 leading-5 text-sage-muted">Positions refer to the current eligible record inventory. These are separate catalogue records, not sample identities or independent experiments.</p>
    {rows.length > 0 ? <div role="region" aria-label={`Scrollable ${label} record coverage`} tabIndex={0}
      className="mt-2 max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep">
      <table className="w-full min-w-[42rem] text-left text-xs">
        <caption className="sr-only">{label}: inspected record statuses</caption>
        <thead className="bg-sage-surface"><tr>{["Eligible inventory position / result", "Source ID", "Record origin / classification", "Field status / reason"].map(heading => <th key={heading} scope="col" className="px-3 py-2 font-medium">{heading}</th>)}</tr></thead>
        <tbody>{rows.map(item => <tr key={item.recordOffset} className="border-t border-sage-border align-top">
          <th scope="row" className="max-w-[18rem] px-3 py-2 font-normal"><span className="block font-medium">Eligible record {item.recordOffset + 1}</span><code className="mt-1 block break-all text-[11px]">{item.resultId}</code></th>
          <td className="max-w-[12rem] break-all px-3 py-2">{item.paperId === null ? "Source ID not supplied" : <Link className="text-accent-deep underline underline-offset-2" href={`/paper/${encodeURIComponent(item.paperId)}`}>{item.paperId}</Link>}</td>
          <td className="px-3 py-2"><span className="block">{item.origin}</span><span className="mt-1 block text-sage-muted">{item.classification}</span></td>
          <td className="max-w-[22rem] px-3 py-2"><span className="font-medium">{statuses[item.status]}</span>
            {item.reasons.length ? <ul className="mt-1 space-y-1 text-sage-muted">{item.reasons.map((reason, index) => <li key={`${reason}:${index}`}>{recordCoverageReasonLabel(reason)}</li>)}</ul>
              : <p className="mt-1 text-sage-muted">No reason supplied in this snapshot.</p>}
          </td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="mt-2 text-sage-muted">No inspected record rows supplied.</p>}
    {coverage.records_unchecked > 0 && <p className="mt-2 leading-5 text-sage-muted">{coverage.records_unchecked} current eligible records are unchecked. Their identities and field assessments are not supplied in this response.</p>}
  </details>;
}
