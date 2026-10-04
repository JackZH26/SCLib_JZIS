"use client";

import { useId, useState } from "react";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import {
  discoveryPressurePaperHref, discoveryPressurePoints, discoveryPressureQuantityOptions,
  discoveryPressureSeriesCsv, discoveryPressureSeriesDownloadPath, discoveryPressureSeriesFilename,
  discoveryPressureSeriesSha256, loadDiscoveryPressureSeries,
  type DiscoveryPressureCompound, type DiscoveryPressureQuantity, type DiscoveryPressureSeries as PressureData,
} from "@/lib/discovery-pressure-series";

const controlStyle = "min-h-11 rounded-lg border border-sage-border bg-white px-3 py-2 text-sm text-sage-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep";
const unitLabel = (unit: string) => unit === "1" ? "dimensionless" : unit;

function PressurePlot({ table, quantity, compound, id }: { table: PressureData; quantity: DiscoveryPressureQuantity; compound: DiscoveryPressureCompound; id: string }) {
  const points = discoveryPressurePoints(table, quantity, compound);
  const descriptor = discoveryPressureQuantityOptions(table).find(item => item.id === quantity)!;
  const domain = quantity === "electron_phonon_lambda" ? [1, 4] : quantity === "omega_log" ? [50, 150] : [100, 280];
  const ticks = quantity === "electron_phonon_lambda" ? [1, 1.5, 2, 2.5, 3, 3.5, 4] : quantity === "omega_log" ? [50, 75, 100, 125, 150] : [100, 140, 180, 220, 260];
  const x = (pressure: number) => 66 + (pressure - 120) / 160 * 450;
  const y = (value: number) => 264 - (value - domain[0]) / (domain[1] - domain[0]) * 230;
  return <figure className="max-w-3xl min-w-0 space-y-2">
    <figcaption className="text-sm font-medium">{descriptor.label} across reported pressure points</figcaption>
    <div role="region" aria-label="Source pressure plot, horizontally scrollable" tabIndex={0}
      className="max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
      <svg viewBox="0 0 560 326" className="block h-auto w-full min-w-[32rem]" role="img" aria-labelledby={`${id}-plot-title ${id}-plot-description`}>
        <title id={`${id}-plot-title`}>{compound}: {descriptor.label} and quantum pressure</title>
        <desc id={`${id}-plot-description`}>{points.length} source-computed points for one compound and one quantity. Pressure is in GPa; the vertical unit is {unitLabel(descriptor.unit)}. Markers show original table values, without an interpolated curve, derivative or ambient-pressure prediction. The table provides the same values.</desc>
        {ticks.map(tick => <g key={`y-${tick}`}>
          <line x1={66} x2={516} y1={y(tick)} y2={y(tick)} stroke="#d4e4d4" />
          <text x={56} y={y(tick) + 4} textAnchor="end" fill="#5a6b5a" fontSize={12}>{tick}</text>
        </g>)}
        {[120, 160, 200, 240, 280].map(tick => <g key={`x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={264} y2={270} stroke="#5a6b5a" />
          <text x={x(tick)} y={290} textAnchor="middle" fill="#5a6b5a" fontSize={12}>{tick}</text>
        </g>)}
        <line x1={66} x2={516} y1={264} y2={264} stroke="#5a6b5a" />
        <line x1={66} x2={66} y1={34} y2={264} stroke="#5a6b5a" />
        <text x={291} y={317} textAnchor="middle" fill="#2d3b2d" fontSize={13}>Quantum pressure (GPa)</text>
        <text transform="translate(18 149) rotate(-90)" textAnchor="middle" fill="#2d3b2d" fontSize={13}>{quantity === "electron_phonon_lambda" ? "EPC λ (dimensionless)" : quantity === "omega_log" ? "ωlog (meV)" : "Computed Tc (K)"}</text>
        {points.map(point => <circle key={point.row_id} data-source-row-id={point.row_id} data-pressure={point.pressure_raw} data-source-value={point.value_raw}
          cx={x(point.pressure)} cy={y(point.value)} r={5} fill="#ffffff" stroke="#24503A" strokeWidth={1.75}>
          <title>{point.formula}: {point.pressure_raw} GPa; {descriptor.label} {point.value_raw} {unitLabel(point.unit)}; source row {point.source_data_row}</title>
        </circle>)}
      </svg>
    </div>
    <p className="text-xs leading-5 text-sage-muted">Markers retain the reported values. Axes stay fixed when switching compounds; all Tc solvers share the same K axis. No values are interpolated or extrapolated to 1 atm.</p>
  </figure>;
}

/** Independent finite source reading; no native state association or scientific write path. */
export function DiscoveryPressureSeries({ table: input }: { table?: unknown } = {}) {
  const table = loadDiscoveryPressureSeries(input);
  const id = useId();
  const [quantity, setQuantity] = useState<DiscoveryPressureQuantity>("tc_anisotropic_me");
  const [compound, setCompound] = useState<DiscoveryPressureCompound>("LaH10");
  const [csvStatus, setCsvStatus] = useState("");
  if (!table) return <section id="discovery-pressure-response" className="scroll-mt-24 space-y-3 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <h2 className="text-xl font-semibold">Pressure study comparison</h2>
    <p role="status" className="text-sm text-sage-muted">The captured pressure series is unavailable.</p>
  </section>;
  const options = discoveryPressureQuantityOptions(table);
  const descriptor = options.find(item => item.id === quantity)!;
  const solver = table.solvers.find(item => item.quantity_id === quantity);
  const rows = table.rows.filter(row => row.formula === compound);
  function exportCsv() {
    let url: string | null = null;
    try {
      url = URL.createObjectURL(new Blob([discoveryPressureSeriesCsv(table)], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url;
      link.download = `sclib-lah10-pressure-series-${discoveryPressureSeriesSha256.slice(0, 12)}.csv`;
      document.body.appendChild(link); link.click(); link.remove();
      setCsvStatus("CSV download requested for all seven source rows and every reported solver.");
    } catch { setCsvStatus("The browser could not start the CSV download. The static JSON resource remains available."); }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000); }
  }
  return <section id="discovery-pressure-response" aria-labelledby={`${id}-heading`} className="scroll-mt-24 min-w-0 space-y-5 rounded-xl border border-sage-border bg-white p-4 sm:p-5">
    <header className="space-y-2">
      <h2 id={`${id}-heading`} className="text-xl font-semibold tracking-tight">Pressure study comparison</h2>
      <h3 className="text-base font-medium">Quantum anharmonic calculations in <FormulaDisplay formula="LaH10" /> and <FormulaDisplay formula="LaD10" /></h3>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Compare one composition and one reported quantity across its pressure points in the source-defined cubic Fm-3m phase. This study uses SSCHA anharmonic phonons and source-specific Tc solvers.</p>
      <p className="text-sm font-medium text-accent-deep">Pressure calculated from quantum E(R) · arXiv:1907.11916v1 · Extended Data Table I</p>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">Source-reported calculations. The series does not establish catalogue-result associations or a stable host at 300 K and 1 atm.</p>
    </header>
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <label htmlFor={`${id}-compound`} className="min-w-0 text-sm">Source composition
        <select id={`${id}-compound`} className={`${controlStyle} mt-1 block w-full`} value={compound} onChange={event => { setCompound(event.target.value as DiscoveryPressureCompound); setCsvStatus(""); }}>
          {table.compounds.map(item => <option value={item} key={item}>{item}</option>)}
        </select>
      </label>
      <label htmlFor={`${id}-quantity`} className="min-w-0 text-sm">Reported quantity / solver
        <select id={`${id}-quantity`} className={`${controlStyle} mt-1 block w-full`} value={quantity} onChange={event => { setQuantity(event.target.value as DiscoveryPressureQuantity); setCsvStatus(""); }}>
          {options.map(item => <option value={item.id} key={item.id}>{item.label} ({unitLabel(item.unit)})</option>)}
        </select>
      </label>
    </div>
    <div className="max-w-3xl space-y-2 text-xs leading-5 text-sage-muted">
      <p role="status">{rows.length} source rows shown for {compound}, in original table order. Selected quantity: {descriptor.label} ({unitLabel(descriptor.unit)}).</p>
      <p>{solver ? `${solver.display_label}. ${solver.coulomb_treatment}` : "Reported electron–phonon quantities use the source's SSCHA phonons and DFPT electron–phonon matrix elements."}</p>
    </div>
    <PressurePlot table={table} quantity={quantity} compound={compound} id={id} />
    <div role="region" aria-label="Selected compound pressure table, horizontally scrollable" tabIndex={0}
      className="max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
      <table className="w-full min-w-[48rem] border-collapse text-left text-sm tabular-nums">
        <caption className="sr-only">{compound} source pressure rows from Extended Data Table I. All solver columns retain their own assumptions. Tc values are in K; omega-log is in meV.</caption>
        <thead className="bg-sage-surface"><tr>
          <th scope="col" className="p-3 font-medium">Pressure <span className="block text-xs font-normal text-sage-muted">GPa · quantum E(R)</span></th>
          <th scope="col" className="p-3 font-medium">EPC λ <span className="block text-xs font-normal text-sage-muted">dimensionless</span></th>
          <th scope="col" className="p-3 font-medium">ωlog <span className="block text-xs font-normal text-sage-muted">meV</span></th>
          <th scope="col" className="p-3 font-medium">McMillan Tc <span className="block text-xs font-normal text-sage-muted">K · μ*=0.1</span></th>
          <th scope="col" className="p-3 font-medium">Allen–Dynes Tc <span className="block text-xs font-normal text-sage-muted">K · μ*=0.1</span></th>
          <th scope="col" className="p-3 font-medium">Anisotropic ME Tc <span className="block text-xs font-normal text-sage-muted">K · RPA Coulomb</span></th>
          <th scope="col" className="p-3 font-medium">Isotropic SCDFT Tc <span className="block text-xs font-normal text-sage-muted">K · no empirical μ*</span></th>
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.id} className="border-t border-sage-border">
          <th scope="row" className="p-3 font-medium">{row.pressure.raw_value}</th>
          {(["electron_phonon_lambda", "omega_log", "tc_mcmillan", "tc_allen_dynes", "tc_anisotropic_me", "tc_isotropic_sc_dft"] as const).map(key => <td key={key} className={`p-3 ${key === quantity ? "bg-sage-surface font-medium" : ""}`}>{row[key].raw_value ?? "Not listed"}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">Methods and pressure-comparison scope</summary>
      <div className="mt-3 max-w-3xl space-y-3 text-xs leading-5 text-sage-muted">
        <p>{table.common_context.pressure_definition.scope}</p>
        <p>{table.common_context.structure.scope}</p>
        <p>{table.common_context.structural_calculation_temperature.scope}</p>
        <p>PBE / Quantum ESPRESSO DFPT with SSCHA phonon frequencies and polarization vectors. The superconductivity calculations set Φ(4)=0 in the quantum energy Hessian; detailed settings and source windows are retained in the metadata.</p>
        {table.source_notes.map(note => <p key={note.id}>{note.summary}</p>)}
        <p>LaH10 and LaD10 use different pressure grids. This reader keeps their series separate and derives no isotope coefficient, fitted pressure derivative or ambient-pressure outcome. Printed uncertainties are absent, without an assumption of zero uncertainty.</p>
      </div>
    </details>
    <details className="min-w-0 border-t border-sage-border pt-4 text-sm">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">Pressure study source and downloads</summary>
      <div className="mt-3 min-w-0 space-y-3 text-xs leading-5 text-sage-muted">
        <p>{table.source.authors.join(", ")}. {table.source.title}. Captured edition: arXiv:1907.11916v1, submitted 27 July 2019; PDF dated 30 July 2019.</p>
        <p>The related Nature article is a separate version of record. Its table equivalence and current publication status have not been verified.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-3">
          <a className="site-text-link inline-flex min-h-11 items-center" href={discoveryPressurePaperHref(11)!} target="_blank" rel="noopener noreferrer">Read the seven-row source table</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={discoveryPressurePaperHref(6)!} target="_blank" rel="noopener noreferrer">Read pressure study methods</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={table.source.related_version_of_record.url} target="_blank" rel="noopener noreferrer">Read the related Nature article</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={discoveryPressureSeriesDownloadPath()} download={discoveryPressureSeriesFilename}>Download all seven source rows (JSON)</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={`${discoveryPressureSeriesDownloadPath()}.sha256`} download={`${discoveryPressureSeriesFilename}.sha256`}>Download pressure file SHA-256</a>
        </div>
        <button type="button" className={controlStyle} onClick={exportCsv}>Export all seven pressure rows (CSV)</button>
        {csvStatus && <p role="status">{csvStatus}</p>}
        <p>Downloads contain both compositions and every reported solver, independent of the display selection. Values, units, method assumptions and source pins are preserved. No calculation is executed and no scientific or ML approval is granted.</p>
        <p className="break-all font-mono">Source PDF SHA-256: {table.source.pdf_sha256}</p>
        <p className="break-all font-mono">Source text SHA-256: {table.source.derived_text_sha256}</p>
        <p className="break-all font-mono">Metadata file SHA-256: {discoveryPressureSeriesSha256}</p>
        <details className="min-w-0"><summary className="w-fit cursor-pointer text-accent-deep">Inspect pressure metadata (JSON)</summary>
          <pre role="region" aria-label="Pressure source metadata JSON" tabIndex={0} className="mt-3 max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-lg border border-sage-border bg-sage-surface p-3 text-xs">{JSON.stringify(table, null, 2)}</pre>
        </details>
      </div>
    </details>
  </section>;
}
