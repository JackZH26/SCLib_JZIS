"use client";

import { useEffect, useId, useState } from "react";
import Link from "@/components/AppLink";
import { getMaterialReports } from "@/lib/api";
import { outcomeLabel, reportLocator, reportPressureRole, reportPropertyLabel, reportQuantity, type MaterialReports as Reports } from "@/lib/material-reports";

export function MaterialReports({ materialId, initiallyOpen = false, snapshotId }: { materialId: string; initiallyOpen?: boolean; snapshotId?: string }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Reports | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true); setError(false); setData(null);
    getMaterialReports(materialId, offset, controller.signal, snapshotId).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [materialId, offset, open, retry, snapshotId]);
  return <section className="material-reports rounded-xl border border-border bg-white" aria-labelledby={titleId}>
    <button type="button" className="flex w-full items-center justify-between gap-4 p-4 text-left text-accent-deeper focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <span><strong id={titleId}>Papers and results</strong><span className="mt-1 block text-xs text-mute">Inspect samples, measurement points and Tc criteria by source.</span></span><span aria-hidden="true">{open ? "−" : "+"}</span>
    </button>
    {open && <div className="space-y-4 border-t border-border p-4">
      {loading && <p role="status" className="text-sm text-mute">Loading source reports…</p>}
      {error && <p role="alert" className="text-sm">Source reports are unavailable. <button type="button" className="underline" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      {data && <>
        {snapshotId && <p className="rounded border border-border bg-surface p-3 text-sm">Candidate extraction preview. Material links and scientific claims await review.</p>}
        {snapshotId && data.display_formula && <h2 className="text-lg font-semibold text-accent-deeper">{data.display_formula}</h2>}
        <p className="text-xs text-mute">{data.support_counts.source_ids.toLocaleString("en-US")} source identifiers · {data.total_points.toLocaleString("en-US")} result rows · {data.support_counts.verified_unique_works.toLocaleString("en-US")} verified work identities. Independent experiments have not been counted.</p>
        {data.report_groups.length === 0 && <p role="status" className="text-sm">No eligible result points are available in this source scope.</p>}
        {data.report_groups.map(group => <article key={group.group_id} className="min-w-0 space-y-2">
          <header><h3 className="break-words text-sm font-semibold">{group.points[0].title ?? group.points[0].paper_id ?? "Source identity unavailable"}</h3><p className="text-xs text-mute">{group.work_id ? "Grouped by verified work identity" : "Work identity unresolved; retained as a separate source report"}</p></header>
          <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Source result points">
            <table className="w-full min-w-[650px] text-left text-xs">
              <thead className="bg-surface"><tr>{["Sample / point", "Pressure", "Tc / outcome", "Criterion / method", "Origin / source role", "Evidence"].map(label => <th key={label} scope="col" className="p-2 font-semibold">{label}</th>)}</tr></thead>
              <tbody>{group.points.map(point => <tr key={point.point_id} className="border-t border-border align-top">
                <td className="p-2"><span>{point.sample_label ?? "Sample not supplied"}</span><span className="block text-mute">{point.point_label ?? point.sample_form ?? "Point identity unresolved"}</span>{point.path_direction !== "unknown" && <span className="block">{point.path_direction}</span>}{point.replicate_label && <span className="block">Replicate: {point.replicate_label}</span>}</td>
                <td className="p-2 whitespace-nowrap">{point.pressure_semantics === "explicit_ambient" ? "Ambient (reported)" : reportQuantity(point.pressure)}<span className="block text-mute">{reportPressureRole(point.pressure_role)}</span></td>
                <td className="p-2 whitespace-nowrap"><span>{point.sc_outcome === "not_detected" ? outcomeLabel(point.sc_outcome) : reportQuantity(point.tc)}</span>{point.sc_outcome === "not_detected" && <span className="block text-mute">Minimum tested T: {reportQuantity(point.minimum_test_temperature)}</span>}{point.sc_outcome === "inconclusive" && <span className="block">Inconclusive</span>}</td>
                <td className="max-w-56 p-2"><span>{point.tc_definition.replaceAll("_", " ")}</span><span className="block text-mute">{point.method ?? "Method not supplied"}</span></td>
                <td className="p-2"><span>{point.knowledge_origin}</span><span className="block text-mute">{point.source_role}</span></td>
                <td className="p-2">{point.paper_id && <Link className="underline" href={`/paper/${encodeURIComponent(point.paper_id)}`}>Paper</Link>}<details className="mt-1"><summary className="cursor-pointer text-accent-deeper">Locator and properties</summary><div className="mt-2 space-y-1"><p>{reportLocator(point.source_locator)}</p>{point.conditions?.filter(condition => condition.key !== point.pressure_role).map((condition, index) => <p key={`condition:${condition.key}:${index}`}>{condition.key.replaceAll("_", " ")}: {condition.status === "explicit_ambient" ? "Ambient (reported)" : condition.value_raw ?? reportQuantity(condition.quantity)}</p>)}{point.properties.map((prop, index) => <p key={`${prop.key}:${index}`}><span title={prop.key}>{reportPropertyLabel(prop.key)}</span>: {prop.value_raw ?? reportQuantity(prop.quantity)}{prop.knowledge_origin && <span className="block text-mute">{prop.knowledge_origin} · {prop.source_role ?? "unknown"}</span>}</p>)}</div></details></td>
              </tr>)}</tbody>
            </table>
          </div>
        </article>)}
        <p className="text-xs text-mute">Values remain linked to their own source result. Unknown conditions are retained; separate reports are not averaged. {snapshotId ? "Full-paper coverage still requires review." : "The legacy extraction scope has not established full-paper coverage."}</p>
        {(offset > 0 || data.has_more) && <nav className="flex items-center justify-between gap-3 text-sm" aria-label="Source result pages"><button type="button" disabled={offset === 0} className="rounded border border-border px-3 py-1 disabled:opacity-40" onClick={() => setOffset(value => Math.max(0, value - 50))}>Previous results</button><span>{(offset + 1).toLocaleString("en-US")}–{Math.min(offset + 50, data.total_points).toLocaleString("en-US")}</span><button type="button" disabled={!data.has_more} className="rounded border border-border px-3 py-1 disabled:opacity-40" onClick={() => setOffset(value => value + 50)}>Next results</button></nav>}
      </>}
    </div>}
  </section>;
}
