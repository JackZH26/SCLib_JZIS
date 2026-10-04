"use client";

import { useId, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { discoverySourcePaperHref, discoverySourceTableCsv, discoverySourceTableDownloadPath, discoverySourceTableFilename,
  discoverySourceTableSha256, filterDiscoverySourceRows, loadDiscoverySourceTable,
  type DiscoverySourceRow, type DiscoverySourceTable } from "@/lib/discovery-source-comparison";

const controlStyle = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep disabled:cursor-not-allowed disabled:opacity-60";

/** The physical axes show published scalars. Open circles remain separate source rows, including overlaps. */
function SourceScatter({ rows, selected, id }: { rows: DiscoverySourceRow[]; selected: string[]; id: string }) {
  const x = (lambda: number) => 62 + lambda / 3.2 * 454;
  const y = (tc: number) => 274 - tc / 320 * 246;
  return <figure className="max-w-3xl min-w-0 space-y-2">
    <figcaption id={`${id}-plot-caption`} className="text-sm font-medium">EPC λ and computed Tc</figcaption>
    <div role="region" aria-label="Published lambda and Tc plot, horizontally scrollable" tabIndex={0}
      className="max-w-full overflow-x-auto rounded-lg border border-sage-border bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
      <svg viewBox="0 0 560 332" className="block h-auto w-full min-w-[32rem]" role="img" aria-labelledby={`${id}-plot-title ${id}-plot-description`}>
        <title id={`${id}-plot-title`}>Published EPC lambda and computed Tc at 300 GPa</title>
        <desc id={`${id}-plot-description`}>{`${rows.length} separate source rows, with lambda in dimensionless units and computed Tc in kelvin. Filled markers identify selected table rows. Use the table checkboxes to select up to two compounds. Fixed axes are retained across filters.`}</desc>
        {[0, 50, 100, 150, 200, 250, 300].map(tick => <g key={`y-${tick}`}>
          <line x1={62} x2={516} y1={y(tick)} y2={y(tick)} stroke="#d4e4d4" />
          <text x={52} y={y(tick) + 4} textAnchor="end" fill="#5a6b5a" fontSize={12}>{tick}</text>
        </g>)}
        {[0, 0.5, 1, 1.5, 2, 2.5, 3].map(tick => <g key={`x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={274} y2={279} stroke="#5a6b5a" />
          <text x={x(tick)} y={296} textAnchor="middle" fill="#5a6b5a" fontSize={12}>{tick}</text>
        </g>)}
        <line x1={62} x2={516} y1={274} y2={274} stroke="#5a6b5a" />
        <line x1={62} x2={62} y1={28} y2={274} stroke="#5a6b5a" />
        <text x={289} y={322} textAnchor="middle" fill="#2d3b2d" fontSize={13}>Electron–phonon λ (dimensionless)</text>
        <text transform="translate(17 151) rotate(-90)" textAnchor="middle" fill="#2d3b2d" fontSize={13}>Computed Tc (K)</text>
        {rows.map(row => <circle key={row.id} data-source-row-id={row.id} data-selected={selected.includes(row.id) ? "true" : "false"}
          cx={x(row.electron_phonon_lambda.value)} cy={y(row.computed_tc.value)} r={selected.includes(row.id) ? 6 : 4.5}
          stroke="#24503A" strokeWidth={1.5} fill={selected.includes(row.id) ? "#24503A" : "#ffffff"}>
          <title>{`${row.formula}: λ ${row.electron_phonon_lambda.raw_value}; computed Tc ${row.computed_tc.raw_value} K; source row ${row.source_data_row}`}</title>
        </circle>)}
      </svg>
    </div>
    <p className="text-xs leading-5 text-sage-muted">Open markers show source values; filled markers show your selections. Every plotted row remains in the table, including nearby points. ωlog has no printed table unit and is excluded from the plot.</p>
  </figure>;
}

function SelectedRows({ rows, clear, id }: { rows: DiscoverySourceRow[]; clear: () => void; id: string }) {
  if (!rows.length) return null;
  return <section aria-labelledby={`${id}-selection-heading`} className="space-y-3 border-t border-sage-border pt-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 id={`${id}-selection-heading`} className="scroll-mt-24 text-base font-semibold">Selected source rows</h3>
      <button type="button" className={controlStyle} onClick={clear}>Clear comparison</button>
    </div>
    <div className="grid gap-4 sm:grid-cols-2">{rows.map(row => <div key={row.id} className="min-w-0 rounded-lg bg-sage-surface p-4">
      <h4 className="text-base font-semibold"><FormulaDisplay formula={row.formula} /></h4>
      <p className="mt-1 text-xs text-sage-muted">Table I row {row.source_data_row} · A: {row.a_element} · B: {row.b_element}</p>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div><dt className="text-xs text-sage-muted">EPC λ (dimensionless)</dt><dd className="mt-1 font-medium tabular-nums">{row.electron_phonon_lambda.raw_value}</dd></div>
        <div><dt className="text-xs text-sage-muted">Computed Tc (K)</dt><dd className="mt-1 font-medium tabular-nums">{row.computed_tc.raw_value}</dd></div>
        <div className="col-span-2"><dt className="text-xs text-sage-muted">ωlog (unit not printed)</dt><dd className="mt-1 font-medium tabular-nums">{row.omega_log.raw_value}</dd></div>
      </dl>
    </div>)}</div>
    <p className="text-xs leading-5 text-sage-muted">Both rows use the common table pressure and μ* assumption. Changing the metal labels does not establish a physical parent–child structure or an ambient-pressure outcome.</p>
  </section>;
}

function SourceDetails({ table, exportCsv, csvStatus, id }: { table: DiscoverySourceTable; exportCsv: () => void; csvStatus: string; id: string }) {
  return <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
    <summary className="w-fit cursor-pointer font-medium text-accent-deep">Source, row locators and downloads</summary>
    <div className="mt-3 min-w-0 space-y-3 text-xs leading-5 text-sage-muted">
      <p>{table.source.authors.join(", ")}. {table.source.title}. {table.source.journal} {table.source.volume}, {table.source.article} ({table.source.year}). DOI: {table.source.doi}. Published 23 June 2025.</p>
      <p>Captured edition: {table.source.captured_edition}. Table I is on PDF page 3. The PDF states CC BY 4.0; this resource contains finite factual table metadata and source-qualified paraphrases.</p>
      <p>Current publication status and equivalence to retained ingestion bytes have not been checked. The publisher URL may return different bytes.</p>
      <div className="flex flex-wrap gap-x-5 gap-y-3">
        <a className="site-text-link inline-flex min-h-11 items-center" href={discoverySourcePaperHref(3)!} target="_blank" rel="noopener noreferrer">Read Table I in the publisher PDF</a>
        <a className="site-text-link inline-flex min-h-11 items-center" href={discoverySourcePaperHref(2)!} target="_blank" rel="noopener noreferrer">Read computational methods</a>
        <a className="site-text-link inline-flex min-h-11 items-center" href={discoverySourceTableDownloadPath()} download={discoverySourceTableFilename}>Download all 21 source rows (JSON)</a>
        <a className="site-text-link inline-flex min-h-11 items-center" href={`${discoverySourceTableDownloadPath()}.sha256`} download={`${discoverySourceTableFilename}.sha256`}>Download file SHA-256</a>
      </div>
      <button type="button" className={controlStyle} onClick={exportCsv}>Export all 21 source rows (CSV)</button>
      {csvStatus && <p role="status">{csvStatus}</p>}
      <p>JSON and CSV include original row order, source values, the common pressure/model assumptions, unresolved ωlog unit and scientific-use limits. Neither export changes catalogue values or grants ML training approval.</p>
      <p className="break-all font-mono">Source PDF SHA-256: {table.source.pdf_sha256}</p>
      <p className="break-all font-mono">Source text SHA-256: {table.source.derived_text_sha256}</p>
      <p className="break-all font-mono">Metadata file SHA-256: {discoverySourceTableSha256}</p>
      <details className="min-w-0">
        <summary className="w-fit cursor-pointer text-accent-deep">Inspect source table metadata (JSON)</summary>
        <pre id={`${id}-metadata`} role="region" aria-label="Source table metadata JSON" tabIndex={0}
          className="mt-3 max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-lg border border-sage-border bg-sage-surface p-3 text-xs">{JSON.stringify(table, null, 2)}</pre>
      </details>
    </div>
  </details>;
}

/** Reads only the finite source snapshot. No API, auth, catalogue linkage or scientific write path. */
export function DiscoverySourceComparison({ table: input }: { table?: unknown } = {}) {
  const table = loadDiscoverySourceTable(input);
  const id = useId();
  const [aElement, setAElement] = useState("");
  const [bElement, setBElement] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [csvStatus, setCsvStatus] = useState("");
  if (!table) return <section id="discovery-source-comparisons" aria-labelledby={`${id}-heading`} className="scroll-mt-24 space-y-3 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <h2 id={`${id}-heading`} className="text-xl font-semibold">Source study comparison</h2>
    <p role="status" className="text-sm text-sage-muted">The captured source comparison is unavailable.</p>
  </section>;
  const rows = filterDiscoverySourceRows(table, aElement, bElement);
  const selectedRows = table.rows.filter(row => selected.includes(row.id));
  const elements = (key: "a_element" | "b_element") => Array.from(new Set(table.rows.map(row => row[key]))).sort();
  const editFilter = (which: "a" | "b", value: string) => {
    (which === "a" ? setAElement : setBElement)(value); setSelected([]); setCsvStatus("");
  };
  function select(rowId: string) {
    setSelected(current => current.includes(rowId) ? current.filter(id => id !== rowId) : current.length < 2 ? [...current, rowId] : current);
  }
  function exportCsv() {
    let url: string | null = null;
    try {
      url = URL.createObjectURL(new Blob([discoverySourceTableCsv(table)], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url;
      link.download = `sclib-ab2h24-source-table-${discoverySourceTableSha256.slice(0, 12)}.csv`;
      document.body.appendChild(link); link.click(); link.remove();
      setCsvStatus("CSV download requested for all 21 source rows, including conditions and source locators.");
    } catch { setCsvStatus("The browser could not start the CSV download. The static JSON resource remains available."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  }
  return <section id="discovery-source-comparisons" aria-labelledby={`${id}-heading`} className="scroll-mt-24 min-w-0 space-y-5 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <header className="space-y-2">
      <h2 id={`${id}-heading`} className="text-xl font-semibold tracking-tight">Source study comparison</h2>
      <h3 className="text-base font-medium">Metal substitutions in <FormulaDisplay formula="AB2H24" /></h3>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare 21 published calculations in one hydride framework. Select two source rows to inspect how EPC λ and computed Tc vary with metal composition.</p>
      <p className="text-sm font-medium text-accent-deep">300 GPa · isotropic Eliashberg equation · assumed μ* = 0.1</p>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">Different compounds at one pressure. This source study does not establish a pressure response curve or survival at 300 K and 1 atm.</p>
    </header>
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
      <label className="min-w-0 text-sm" htmlFor={`${id}-a-element`}>A element<select id={`${id}-a-element`} className={`${controlStyle} mt-1 block w-full`} value={aElement} onChange={event => editFilter("a", event.target.value)}>
        <option value="">All A elements</option>{elements("a_element").map(element => <option key={element} value={element}>{element}</option>)}
      </select></label>
      <label className="min-w-0 text-sm" htmlFor={`${id}-b-element`}>B element<select id={`${id}-b-element`} className={`${controlStyle} mt-1 block w-full`} value={bElement} onChange={event => editFilter("b", event.target.value)}>
        <option value="">All B elements</option>{elements("b_element").map(element => <option key={element} value={element}>{element}</option>)}
      </select></label>
      <button type="button" className={controlStyle} disabled={!aElement && !bElement} onClick={() => { setAElement(""); setBElement(""); setSelected([]); setCsvStatus(""); }}>Clear element filters</button>
    </div>
    <p role="status" className="text-xs leading-5 text-sage-muted">{rows.length} of 21 source rows shown, in original Table I order. {selected.length === 2 ? "Two compounds selected. Clear a selection to choose another." : selected.length === 1 ? "One compound selected. Select one more to compare." : "Select up to two compounds from the table."} Element-filter changes clear the comparison.</p>
    <SelectedRows rows={selectedRows} clear={() => setSelected([])} id={id} />
    {rows.length ? <>
      <SourceScatter rows={rows} selected={selected} id={id} />
      <div role="region" aria-label="AB2H24 source table, horizontally scrollable" tabIndex={0}
        className="max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
        <table className="w-full min-w-[40rem] border-collapse text-left text-sm tabular-nums">
          <caption className="sr-only">Original Table I rows. All source compounds are computed at 300 GPa with assumed μ* 0.1. Choose up to two rows using the comparison checkboxes.</caption>
          <thead className="bg-sage-surface"><tr>
            <th scope="col" className="p-3 font-medium">Compare</th><th scope="col" className="p-3 font-medium">Row</th><th scope="col" className="p-3 font-medium">Source compound</th>
            <th scope="col" className="p-3 font-medium">EPC λ <span className="block text-xs font-normal text-sage-muted">dimensionless</span></th>
            <th scope="col" className="p-3 font-medium">ωlog <span className="block text-xs font-normal text-sage-muted">unit not printed</span></th>
            <th scope="col" className="p-3 font-medium">Computed Tc <span className="block text-xs font-normal text-sage-muted">K</span></th>
          </tr></thead>
          <tbody>{rows.map(row => <tr key={row.id} className={`border-t border-sage-border align-middle ${selected.includes(row.id) ? "bg-sage-surface" : "bg-white"}`}>
            <td className="px-3"><label className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center">
              <input type="checkbox" aria-label={`Compare ${row.formula}`} className="h-4 w-4 shrink-0 accent-accent-deep" checked={selected.includes(row.id)} disabled={selected.length >= 2 && !selected.includes(row.id)} onChange={() => select(row.id)} />
            </label></td>
            <td className="p-3 text-sage-muted">{row.source_data_row}</td>
            <th scope="row" className="p-3 font-medium"><FormulaDisplay formula={row.formula} /><span className="mt-1 block text-xs font-normal text-sage-muted">A: {row.a_element} · B: {row.b_element}</span></th>
            <td className="p-3">{row.electron_phonon_lambda.raw_value}</td><td className="p-3">{row.omega_log.raw_value}</td><td className="p-3">{row.computed_tc.raw_value}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {selected.length > 0 && <a href={`#${id}-selection-heading`} className="site-text-link inline-flex min-h-11 items-center text-sm">Jump to selected comparison</a>}
    </> : <p className="rounded-lg bg-sage-surface p-4 text-sm">No Table I source rows match these elements. Clear or change an element filter.</p>}
    <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">Source interpretation and comparison limits</summary>
      <div className="mt-3 max-w-3xl space-y-3 text-xs leading-5 text-sage-muted">
        <p>The Table I caption describes the selected compounds as dynamically stable at 300 GPa. That is an author-reported selection criterion, without individual stability validation here.</p>
        {table.source_notes.map(note => <p key={note.id}>{note.summary}</p>)}
        <p>Shared pressure, solver and prototype labels support this source-table comparison. Exact atomic structures, retained run identities, numerical convergence and catalogue result associations remain unestablished.</p>
        <p>The table prints no uncertainties for λ or Tc. Displayed digits retain source precision; absence of printed uncertainty does not establish zero uncertainty. ωlog stays as raw text with an unresolved unit.</p>
        <p>These 21 rows are published predictions, not independent experiments. No new calculation, canonical field update, formal scientific acceptance or ML training approval is established.</p>
      </div>
    </details>
    <SourceDetails table={table} exportCsv={exportCsv} csvStatus={csvStatus} id={id} />
  </section>;
}
