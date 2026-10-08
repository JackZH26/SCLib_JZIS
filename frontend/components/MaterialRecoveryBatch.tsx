import { verifiedRecoveryBatch } from "@/lib/material-recovery-batch";
import type { MaterialEnrichmentReport } from "@/lib/api";

export function MaterialRecoveryBatch({ report, materialId }: { report: MaterialEnrichmentReport; materialId: string }) {
  const batch = verifiedRecoveryBatch(report, materialId);
  if (!batch) return null;
  return <details className="mt-4 rounded-lg border border-sage-border bg-white p-4">
    <summary className="cursor-pointer text-sm font-medium">Primary-source inspection · {batch.observations.length} observations</summary>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-700">{batch.summary}</p>
    <p className="mt-2 text-xs leading-5 text-slate-500">AI-assisted checks of original paper expressions. Sample/state association and scientific approval remain pending; no retained value has been changed. These are not independent experiments or human-approved facts.</p>
    <dl className="mt-3 space-y-3">{batch.observations.map(o => <div key={o.id}>
      <dt className="text-sm font-medium">{o.label}: <span className="font-normal">{o.value}</span></dt>
      <dd className="mt-1 text-xs leading-5 text-slate-600">{o.knowledge_origin} source scope · {o.scope}
        <a className="ml-2 text-accent-deep underline underline-offset-2" href={`${o.source.source_url}#page=${o.source.locator.page}`} target="_blank" rel="noopener noreferrer">{o.source.paper_id} · PDF page {o.source.locator.page}</a>
      </dd>
    </div>)}</dl>
    <p className="mt-4 text-xs font-medium text-slate-700">Still unresolved</p>
    <ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">{batch.unknowns.map(x => <li key={x}>{x}</li>)}</ul>
    <p className="mt-3 text-xs text-slate-500">Full source locators, byte hashes and current record references are included in the recovery metadata download. Original passages are not republished.</p>
  </details>;
}
