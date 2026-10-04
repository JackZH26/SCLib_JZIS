"use client";

import { useEffect, useId, useRef, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { filterHostReferences, HOST_REFERENCE_PAGE_SIZE, hostReferenceAsset, hostReferenceFilename,
  hostReferencePoint, loadHostReference, type HostReferenceRow } from "@/lib/discovery-host-reference";

const control = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep disabled:cursor-not-allowed disabled:opacity-60";

function ReferencePlot({ rows, selected, id }: { rows: HostReferenceRow[]; selected: string; id: string }) {
  const points = rows.flatMap(row => { const point = hostReferencePoint(row); return point ? [{ row, ...point }] : []; });
  return <figure className="min-w-0 space-y-2">
    <figcaption id={`${id}-chart-heading`} className="text-base font-semibold">Formation energy and electronic band gap</figcaption>
    {points.length ? <div role="region" aria-label="Host reference plot, horizontally scrollable" tabIndex={0}
      className="max-w-full overflow-x-auto rounded-lg border border-sage-border bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
      <svg viewBox="0 0 600 348" className="block h-auto w-full min-w-[32rem]" role="img" aria-labelledby={`${id}-chart-title ${id}-chart-desc`}>
        <title id={`${id}-chart-title`}>OptB88vdW formation energy versus electronic band gap</title>
        <desc id={`${id}-chart-desc`}>{`${points.length} provider records. Fixed linear axes use eV per atom and eV. Nearby and overlapping records remain separate in the table. A filled point identifies the inspected record.`}</desc>
        {[0, 1, 2, 3, 4, 5, 6, 7].map(tick => <g key={`y-${tick}`}>
          <line x1={64} x2={556} y1={284 - tick * 36} y2={284 - tick * 36} stroke="#d4e4d4" />
          <text x={52} y={288 - tick * 36} textAnchor="end" fill="#536853" fontSize={12}>{tick}</text>
        </g>)}
        {[-4, -2, 0, 2, 4, 6].map(tick => <g key={`x-${tick}`}>
          <line x1={64 + (tick + 4) * 49.2} x2={64 + (tick + 4) * 49.2} y1={284} y2={289} stroke="#536853" />
          <text x={64 + (tick + 4) * 49.2} y={310} textAnchor="middle" fill="#536853" fontSize={12}>{tick}</text>
        </g>)}
        <line x1={64} x2={64} y1={32} y2={284} stroke="#536853" />
        <line x1={64} x2={556} y1={284} y2={284} stroke="#536853" />
        <text x={310} y={337} textAnchor="middle" fill="#2d3b2d" fontSize={13}>Formation energy (eV/atom)</text>
        <text transform="translate(18 158) rotate(-90)" textAnchor="middle" fill="#2d3b2d" fontSize={13}>Electronic band gap (eV)</text>
        {points.filter(point => point.row.id !== selected).map(({ row, x, y }) => <circle key={row.id} data-reference-id={row.id} cx={x} cy={y} r={4} fill="white" stroke="#24503A" strokeWidth={1.5}>
          <title>{`${row.formula} · ${row.id} · ${row.formation_energy.raw} eV/atom · ${row.band_gap.raw} eV`}</title>
        </circle>)}
        {points.filter(point => point.row.id === selected).map(({ row, x, y }) => <circle key={row.id} data-reference-id={row.id} data-selected="true" cx={x} cy={y} r={6} fill="#24503A" stroke="white" strokeWidth={1.5}>
          <title>{`Inspected: ${row.formula} · ${row.id} · ${row.formation_energy.raw} eV/atom · ${row.band_gap.raw} eV`}</title>
        </circle>)}
      </svg>
    </div> : <p className="rounded-lg bg-sage-surface p-4 text-sm">No records in this selection have the required metadata checks for plotting.</p>}
    <p className="text-xs leading-5 text-sage-muted">The plot shows every eligible record in the current filters, across all table pages. Axes stay fixed; overlapping points are not moved.</p>
  </figure>;
}

function RecordDetails({ row, close }: { row: HostReferenceRow; close: () => void }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => { panel.current?.focus(); panel.current?.scrollIntoView?.({ block: "start" }); }, [row.id]);
  return <section ref={panel} tabIndex={-1} aria-label="Inspected host reference" className="scroll-mt-24 min-w-0 space-y-3 rounded-lg border border-sage-border bg-sage-surface p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold"><FormulaDisplay formula={row.formula} /> <span className="text-sm font-normal">{row.id}</span></h2>
      <button className={control} type="button" onClick={close}>Close record</button>
    </div>
    <dl className="grid gap-3 text-sm sm:grid-cols-3">
      <div><dt className="text-sage-muted">Formation energy (eV/atom)</dt><dd className="mt-1 font-semibold tabular-nums">{row.formation_energy.raw}</dd></div>
      <div><dt className="text-sage-muted">Electronic band gap (eV)</dt><dd className="mt-1 font-semibold tabular-nums">{row.band_gap.raw}</dd></div>
      <div><dt className="text-sage-muted">Provider space group</dt><dd className="mt-1">{row.space_group} (No. {row.space_group_number})</dd></div>
    </dl>
    <p className="text-xs leading-5 text-sage-muted">Method: {row.method}. Source nat: {row.cell_atoms}; atoms in supplied coordinates: {row.coordinate_atoms}. Source array index: {row.source.dataset_row_index} (zero-based).</p>
    {row.review_note && <p role="status" className="text-sm font-medium">{row.review_note}</p>}
    <details className="text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Record identity and source fields</summary>
      <div className="mt-3 space-y-2">
        <p>Both displayed quantities come from this provider record. Its supplied coordinates are a reference; input/output run matching, temperature, pressure and convergence remain unchecked.</p>
        <p>Fields: formation_energy_peratom (eV/atom), optb88vdw_bandgap (eV). Original numeric tokens are displayed without rounding. No uncertainty is supplied here.</p>
        <p className="break-all font-mono">Source record SHA-256: {row.source.record_sha256}</p>
        <p className="break-all font-mono">Canonical atoms SHA-256: {row.source.atoms_sha256}</p>
      </div>
    </details>
  </section>;
}

export function DiscoveryHostReference({ reference: input }: { reference?: unknown } = {}) {
  const reference = loadHostReference(input);
  const id = useId();
  const [family, setFamily] = useState("");
  const [formula, setFormula] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState("");
  const selectionTrigger = useRef<HTMLButtonElement | null>(null);
  if (!reference) return <p role="status">The captured host reference is unavailable.</p>;
  const rows = filterHostReferences(reference, family, formula);
  const pageCount = Math.ceil(rows.length / HOST_REFERENCE_PAGE_SIZE);
  const visible = rows.slice(page * HOST_REFERENCE_PAGE_SIZE, (page + 1) * HOST_REFERENCE_PAGE_SIZE);
  const selectedRow = rows.find(row => row.id === selected);
  const plotted = rows.filter(row => hostReferencePoint(row) !== null).length;
  function resetSelection() { setPage(0); setSelected(""); }
  return <div className="min-w-0 space-y-5">
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
      <label className="min-w-0 text-sm" htmlFor={`${id}-family`}>Host family<select id={`${id}-family`} className={`${control} mt-1 block w-full`} value={family}
        onChange={event => { setFamily(event.target.value); setFormula(""); resetSelection(); }}>
        <option value="">All host families</option>{Array.from(new Set(reference.rows.map(row => row.family))).sort().map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label className="min-w-0 text-sm" htmlFor={`${id}-formula`}>Host formula<select id={`${id}-formula`} className={`${control} mt-1 block w-full`} value={formula}
        onChange={event => { setFormula(event.target.value); resetSelection(); }}>
        <option value="">All host formulas</option>{Array.from(new Set(filterHostReferences(reference, family).map(row => row.formula))).sort().map(value => <option key={value}>{value}</option>)}
      </select></label>
      <button type="button" className={control} disabled={!family && !formula} onClick={() => { setFamily(""); setFormula(""); resetSelection(); }}>Clear filters</button>
    </div>
    <p role="status" className="text-sm text-sage-muted">{rows.length} of {reference.rows.length} source records · {plotted} plotted · {rows.length - plotted} awaiting cell review</p>
    <div className="max-w-4xl"><ReferencePlot rows={rows} selected={selected} id={id} /></div>
    {selectedRow && <RecordDetails row={selectedRow} close={() => { setSelected(""); selectionTrigger.current?.focus(); }} />}
    <div role="region" aria-label="Host reference records, horizontally scrollable" tabIndex={0}
      className="max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
      <table className="w-full min-w-[44rem] border-collapse text-left text-sm tabular-nums">
        <caption className="sr-only">Provider records in original dataset order. Inspect a row for its original values, identity and review notes.</caption>
        <thead className="bg-sage-surface"><tr>
          <th scope="col" className="p-3 font-medium">Host / record</th><th scope="col" className="p-3 font-medium">Space group</th>
          <th scope="col" className="p-3 font-medium">Formation energy<span className="block text-xs font-normal">eV/atom</span></th>
          <th scope="col" className="p-3 font-medium">Band gap<span className="block text-xs font-normal">eV</span></th>
          <th scope="col" className="p-3 font-medium">Inspect</th>
        </tr></thead>
        <tbody>{visible.map(row => <tr key={row.id} className={`border-t border-sage-border ${selected === row.id ? "bg-sage-surface" : "bg-white"}`}>
          <th scope="row" className="p-3 font-medium"><FormulaDisplay formula={row.formula} /><span className="mt-1 block text-xs font-normal text-sage-muted">{row.id}</span></th>
          <td className="p-3">{row.space_group}<span className="mt-1 block text-xs text-sage-muted">No. {row.space_group_number}</span></td>
          <td className="p-3">{row.formation_energy.raw}</td><td className="p-3">{row.band_gap.raw}</td>
          <td className="p-3"><button type="button" className={control} aria-label={`Inspect ${row.id}`} aria-pressed={selected === row.id} onClick={event => { selectionTrigger.current = event.currentTarget; setSelected(row.id); }}>Inspect</button>
            {!row.plottable && <span className="mt-1 block text-xs">Cell review needed</span>}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <nav aria-label="Host reference table pages" className="flex flex-wrap items-center gap-3 text-sm">
      <button type="button" className={control} disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button>
      <span aria-live="polite">Page {page + 1} of {pageCount}</span>
      <button type="button" className={control} disabled={page + 1 >= pageCount} onClick={() => setPage(value => value + 1)}>Next</button>
    </nav>
    <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">How to interpret these axes</summary>
      <div className="mt-3 max-w-3xl space-y-3 text-sm leading-6 text-sage-muted">
        <p>{reference.scope.inference}</p><p>{reference.scope.conditions}</p><p>{reference.scope.ehull}</p>
        <p>The four cell-review records have different nat and coordinate counts. Both inventories remain unchanged in the download; their points are withheld.</p>
        <p>These descriptors help select structures for further investigation. A low band gap does not establish carriers, pairing, coherence or Tc, and a zero gap is retained as the computed value. Cross-composition formation energies do not rank superconducting promise.</p>
      </div>
    </details>
    <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">Source edition and downloads</summary>
      <div className="mt-3 min-w-0 space-y-3 text-xs leading-5 text-sage-muted">
        <p>{reference.source.author}. {reference.source.title}. Dataset file dated 24 September 2025, Figshare article version 11. {reference.source.license}. All 184 matching records for the 22 formulas are retained from {reference.source.dataset_records.toLocaleString("en-US")} records, including multiple structures with the same formula.</p>
        <p>{reference.source.changes} {reference.scope.association}</p>
        <p>The source download is valid JSON containing original record strings. One string retains provider NaN tokens in its elastic tensor; those unrelated values are not displayed or used as axes.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          <a className="site-text-link inline-flex min-h-11 items-center" href={`https://doi.org/${reference.source.doi}`}>JARVIS dataset edition</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={reference.source.license_url}>CC BY 4.0 license</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={reference.source.unit_reference}>Provider unit definitions</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={hostReferenceAsset(hostReferenceFilename)!} download>Download all reference values (JSON)</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={hostReferenceAsset(reference.source.subset_filename)!} download>Download original record strings and coordinates (JSON)</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={hostReferenceAsset(`${hostReferenceFilename}.sha256`)!} download>Reference file SHA-256</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={hostReferenceAsset(`${reference.source.subset_filename}.sha256`)!} download>Source file SHA-256</a>
        </div>
        <p>Downloads always contain the complete 184-record subset. This view adds no catalogue measurements, native scientific release, new calculation, host certification or reviewed training data.</p>
        <p className="break-all font-mono">Original archive SHA-256: {reference.source.archive_sha256}</p>
      </div>
    </details>
  </div>;
}
