import { retainedHc2, retainedTcCriteria } from "@/lib/material-retained-record";

/** Retained lexical fields do not inherit the selected headline's criterion. */
export function RetainedTcCriteria({ record }: { record: Record<string, unknown> }) {
  const criteria = retainedTcCriteria(record);
  if (!criteria.length) return <span className="mt-1 block text-left text-xs font-normal text-sage-muted">Criterion not supplied</span>;
  return <dl aria-label="Retained Tc criteria" className="mt-1 space-y-1 text-left text-xs font-normal leading-5">
    {criteria.map(item => <div key={item.key} className="max-w-[20rem] break-words">
      <dt className="inline text-sage-muted">{item.label}: </dt><dd className="inline">{item.value}</dd>
    </div>)}
  </dl>;
}

/** Hc2 is displayed as a retained field, without inferring Hc2(0) or probe role. */
export function RetainedHc2({ record }: { record: Record<string, unknown> }) {
  const reading = retainedHc2(record);
  if (!reading) return <span className="text-xs text-sage-muted">Not supplied or unresolved</span>;
  return <div className="min-w-[9rem] max-w-[22rem] break-words text-xs leading-5">
    <p className="font-medium tabular-nums">{reading.value}{reading.displayUnit && ` ${reading.displayUnit}`}</p>
    {reading.representation === "source_token" && <p className="text-sage-muted">Stored source token</p>}
    <details className="mt-1">
      <summary className="min-h-11 cursor-pointer content-center text-accent-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep">Hc2 field context</summary>
      <div className="space-y-2 pb-1">
        <p className="text-sage-muted">API field: hc2_tesla (T). This field unit does not establish the source's printed unit.</p>
        <dl className="space-y-1">{reading.units.map(item => <div key={item.key}><dt className="inline text-sage-muted">{item.label}: </dt><dd className="inline">{item.value}</dd></div>)}</dl>
        {reading.unitMetadataUnresolved ? <p className="text-sage-muted">Stored unit metadata is unresolved.</p>
          : !reading.units.length && <p className="text-sage-muted">Source unit token not supplied.</p>}
        {reading.context.length ? <dl className="space-y-1">{reading.context.map(item => <div key={item.key}><dt className="inline text-sage-muted">{item.label}: </dt><dd className="inline">{item.value}</dd></div>)}</dl>
          : <p className="text-sage-muted">Hc2 conditions and direction not supplied.</p>}
      </div>
    </details>
  </div>;
}
