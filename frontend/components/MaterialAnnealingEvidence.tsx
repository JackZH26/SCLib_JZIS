import type { ReactNode } from "react";
import {
  loadNbsctizrAnnealing, nbsctizrAnnealingDownloadPath, nbsctizrAnnealingSnapshotSha256,
  nbsctizrSourceHref, type NbsctizrAnnealing, type NbsctizrSourceCell,
} from "@/lib/material-nbsctizr-annealing";

type SourceRow = { sample_id: string; cells: Record<string, NbsctizrSourceCell> };
type SourceColumn = { field: string; label: string; raw_unit: string | null };
const th = "px-3 py-2 text-left font-medium";
const td = "px-3 py-2 align-top tabular-nums";

// Typography only: source-specific heat units have mol and temperature powers in the denominator.
function displayUnit(unit: string) {
  return unit === "mJ/mol·K2" ? "mJ/(mol·K²)" : unit === "mJ/mol·K4" ? "mJ/(mol·K⁴)" : unit;
}

function ScrollTable({ name, children }: { name: string; children: ReactNode }) {
  return <div role="region" aria-label={`${name}, horizontally scrollable`} tabIndex={0}
    className="max-w-full overflow-x-auto rounded-lg border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-deep">
    {children}
  </div>;
}

function Value({ cell }: { cell: NbsctizrSourceCell }) {
  return cell.raw_value === null ? <span className="text-xs text-sage-muted">Not listed</span> : <>{cell.raw_value}</>;
}

function PassageLink({ data, sourceId, locator, children }: { data: NbsctizrAnnealing; sourceId: string; locator: string; children: ReactNode }) {
  const window = data.source_windows.find(item => item.id === locator && item.source_id === sourceId);
  const href = window ? nbsctizrSourceHref(sourceId, window.pdf_page_one_based) : null;
  return href ? <a className="site-text-link inline-flex min-h-11 items-center text-sm" href={href} target="_blank" rel="noopener noreferrer">{children}</a> : null;
}

function SampleLabel({ data, sampleId }: { data: NbsctizrAnnealing; sampleId: string }) {
  return <>{data.samples.find(sample => sample.id === sampleId)!.label}</>;
}

function ParameterRows({ data, name, columns, rows }: { data: NbsctizrAnnealing; name: string; columns: SourceColumn[]; rows: SourceRow[] }) {
  return <ScrollTable name={name}>
    <table className="w-full min-w-[40rem] border-collapse text-sm">
      <caption className="sr-only">{name}</caption>
      <thead className="bg-sage-surface"><tr><th scope="col" className={th}>Source parameter</th>
        {rows.map(row => <th key={row.sample_id} scope="col" className={th}><SampleLabel data={data} sampleId={row.sample_id} /></th>)}
      </tr></thead>
      <tbody>{columns.map(column => <tr key={column.field} className="border-t border-sage-border">
        <th scope="row" className={th}>{column.label}{column.raw_unit && <> <span className="block text-xs font-normal text-sage-muted">{displayUnit(column.raw_unit)}</span></>}</th>
        {rows.map(row => <td key={row.sample_id} className={td}><Value cell={row.cells[column.field]} /></td>)}
      </tr>)}</tbody>
    </table>
  </ScrollTable>;
}

function PhaseRows({ data, edition }: { data: NbsctizrAnnealing; edition: "2023" | "2024" }) {
  const table = edition === "2023" ? data.phase_table_2023 : data.phase_table;
  const labels: Record<string, string> = { Nb: "Nb", Sc: "Sc", Ti: "Ti", Zr: "Zr", lattice_a: "a", lattice_c: "c", volume_percent: "Phase volume", vec: "VEC" };
  const rows: (SourceRow & { phase_label: string })[] = table.rows;
  return <div className="min-w-0 space-y-2">
    <h3 className="text-base font-semibold">{table.label}</h3>
    <p className="max-w-3xl text-xs leading-5 text-sage-muted">{table.composition_scope}</p>
    {edition === "2024" && <p className="max-w-3xl text-xs leading-5 text-sage-muted">{data.phase_table.composition_source_attribution}</p>}
    <ScrollTable name={`${edition} phase compositions and lattice parameters`}>
      <table className="w-full min-w-[48rem] border-collapse text-sm">
        <caption className="sr-only">{table.label}</caption>
        <thead className="bg-sage-surface"><tr><th scope="col" className={th}>Preparation label</th><th scope="col" className={th}>Reported phase</th>
          {table.columns.map(column => <th key={column} scope="col" className={th}>{labels[column]}{rows[0].cells[column].raw_unit && <> <span className="block text-xs font-normal text-sage-muted">{rows[0].cells[column].raw_unit}</span></>}</th>)}
        </tr></thead>
        <tbody>{rows.map(row => <tr key={`${row.sample_id}-${row.phase_label}`} className="border-t border-sage-border">
          <th scope="row" className={th}><SampleLabel data={data} sampleId={row.sample_id} /></th><td className={td}>{row.phase_label}</td>
          {table.columns.map(column => <td key={column} className={td}><Value cell={row.cells[column]} /></td>)}
        </tr>)}</tbody>
      </table>
    </ScrollTable>
    <PassageLink data={data} sourceId={edition} locator={table.source_locator_id}>Read the {edition} Table 1</PassageLink>
  </div>;
}

/** Captured source reports are rendered separately from selected catalogue properties. */
export function MaterialAnnealingEvidence({ data: input }: { data?: unknown } = {}) {
  const data = loadNbsctizrAnnealing(input);
  if (!data) return <p role="status" className="text-sm text-sage-muted">The captured NbScTiZr annealing comparison is unavailable.</p>;
  const table = data.parameter_table;
  return <div className="min-w-0 space-y-8">
    <section aria-labelledby="nbsctizr-transition-heading" className="min-w-0 space-y-4">
      <h2 id="nbsctizr-transition-heading" className="text-xl font-semibold">Transition reports by preparation</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">The papers describe nominal Nb:Sc:Ti:Zr = 1:1:1:1 and bcc/hcp phases. Annealed groups are held for four days in an evacuated quartz tube. As-cast has no annealing temperature. These labels describe processing conditions.</p>
      <div className="grid min-w-0 gap-6 md:grid-cols-2">
        <section className="min-w-0 space-y-3" aria-labelledby="nbsctizr-tc-2023">
          <h3 id="nbsctizr-tc-2023" className="font-semibold">2023: ac-susceptibility onset</h3>
          <p className="text-xs leading-5 text-sage-muted">5 Oe · 800 Hz · measurement range 3-20 K. The source lists no 600 °C row.</p>
          <ScrollTable name="2023 transition temperatures">
            <table className="w-full border-collapse text-sm"><caption className="sr-only">2023 Table 1 transition temperatures</caption>
              <thead className="bg-sage-surface"><tr><th scope="col" className={th}>Preparation label</th><th scope="col" className={th}>Reported Tc (K)</th></tr></thead>
              <tbody>{data.tc_2023.rows.map(row => <tr key={row.sample_id} className="border-t border-sage-border"><th scope="row" className={th}><SampleLabel data={data} sampleId={row.sample_id} /></th><td className={td}><Value cell={row.cells.tc_k} /></td></tr>)}</tbody>
            </table>
          </ScrollTable>
          <PassageLink data={data} sourceId="2023" locator={data.tc_2023.source_locator_id}>Read the 2023 Tc table</PassageLink>
        </section>
        <section className="min-w-0 space-y-3" aria-labelledby="nbsctizr-tc-2024">
          <h3 id="nbsctizr-tc-2024" className="font-semibold">2024: refined Tc, Hc2 analysis</h3>
          <p className="text-xs leading-5 text-sage-muted">Table 2 retains the upper-critical-field analysis context. Its Tc values are not assigned the calorimetry midpoint criterion.</p>
          <ScrollTable name="2024 refined transition temperatures">
            <table className="w-full border-collapse text-sm"><caption className="sr-only">2024 Table 2 refined transition temperatures</caption>
              <thead className="bg-sage-surface"><tr><th scope="col" className={th}>Preparation label</th><th scope="col" className={th}>Tabulated Tc (K)</th></tr></thead>
              <tbody>{table.rows.map(row => <tr key={row.sample_id} className="border-t border-sage-border"><th scope="row" className={th}><SampleLabel data={data} sampleId={row.sample_id} /></th><td className={td}><Value cell={row.cells.tc_k} /></td></tr>)}</tbody>
            </table>
          </ScrollTable>
          <PassageLink data={data} sourceId="2024" locator={table.source_locator_id}>Read the 2024 parameter table</PassageLink>
        </section>
      </div>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">These are distinct source reports. Matching preparation labels does not establish identical physical specimens across editions or assign a selected catalogue Tc to either phase. Measurement pressure is not supplied.</p>
    </section>

    <section aria-labelledby="nbsctizr-fields-heading" className="min-w-0 space-y-3 border-t border-sage-border pt-6">
      <h2 id="nbsctizr-fields-heading" className="text-xl font-semibold">Upper critical field: two probe channels</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">The authors fit magnetization onset (M) and resistivity onset (ρ) separately with WHH. Hc2(0) is an extrapolated source fit, rather than a measurement at 0 K.</p>
      <ScrollTable name="2024 upper critical field probe channels">
        <table className="w-full min-w-[28rem] border-collapse text-sm"><caption className="sr-only">2024 Table 2 WHH upper critical field channels</caption>
          <thead className="bg-sage-surface"><tr><th scope="col" className={th}>Preparation label</th><th scope="col" className={th}>μ0 Hc2ᴹ(0) (T)</th><th scope="col" className={th}>μ0 Hc2ρ(0) (T)</th></tr></thead>
          <tbody>{table.rows.map(row => <tr key={row.sample_id} className="border-t border-sage-border"><th scope="row" className={th}><SampleLabel data={data} sampleId={row.sample_id} /></th><td className={td}><Value cell={row.cells.hc2_m_zero_t} /></td><td className={td}><Value cell={row.cells.hc2_rho_zero_t} /></td></tr>)}</tbody>
        </table>
      </ScrollTable>
      <details className="min-w-0 pt-2"><summary className="min-h-11 w-fit cursor-pointer content-center font-medium text-accent-deep">All 15 parameters from 2024 Table 2</summary>
        <div className="min-w-0 space-y-3 pt-3">
          <p className="max-w-3xl text-xs leading-5 text-sage-muted">γel and β include both bcc and hcp contributions. Hc1 uses a GL extrapolation; ξ, λGL and κ are source-derived GL estimates. λGL is a magnetic penetration depth in nm. Vickers hardness uses a 2.94 N load for 10 s.</p>
          <ParameterRows data={data} name="2024 complete superconducting parameters and hardness" columns={table.columns} rows={table.rows} />
          <p className="max-w-3xl text-xs leading-5 text-sage-muted">Original values are retained; unit typography is formatted for reading. Metadata keeps original unit tokens. Parentheses remain uninterpreted uncertainty notation; symbols without printed units retain no unit in the metadata.</p>
        </div>
      </details>
    </section>

    <details className="min-w-0 border-t border-sage-border pt-4"><summary className="min-h-11 w-fit cursor-pointer content-center font-medium text-accent-deep">Phase compositions, lattice parameters and phase fractions</summary>
      <div className="min-w-0 space-y-6 pt-3">
        <p className="max-w-3xl text-sm leading-6 text-sage-muted">Composition units are not printed in these tables. SEM phase volume fractions are separate from superconducting volume fractions. Shared composition values cited across papers do not count as independent experiments.</p>
        <PhaseRows data={data} edition="2023" /><PhaseRows data={data} edition="2024" />
      </div>
    </details>

    <details className="min-w-0 border-t border-sage-border pt-4"><summary className="min-h-11 w-fit cursor-pointer content-center font-medium text-accent-deep">Electronic specific-heat fits</summary>
      <div className="min-w-0 space-y-3 pt-3">
        <p className="max-w-3xl text-sm leading-6 text-sage-muted">Four annealed groups have exponential gap fits and a residual γ term. The heat-jump normalization uses a calorimetry midpoint Tc. The as-cast transition is too broad for the source gap-ratio analysis.</p>
        <ParameterRows data={data} name="2024 electronic specific-heat fit parameters" columns={data.gap_fits.columns} rows={data.gap_fits.rows} />
        <p className="max-w-3xl text-xs leading-5 text-sage-muted">{data.gap_fits.interpretation_scope}</p>
        <PassageLink data={data} sourceId="2024" locator="2024-calorimetry">Read the gap-fit analysis</PassageLink>
        <PassageLink data={data} sourceId="2024" locator="2024-gap-jump">Read the heat-jump analysis</PassageLink>
      </div>
    </details>

    <details className="min-w-0 border-t border-sage-border pt-4"><summary className="min-h-11 w-fit cursor-pointer content-center font-medium text-accent-deep">Sources, methods and downloads</summary>
      <div className="min-w-0 space-y-5 pt-3">
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
          <a className="site-text-link inline-flex min-h-11 items-center" href={nbsctizrAnnealingDownloadPath} download>Download all source values (JSON)</a>
          <a className="site-text-link inline-flex min-h-11 items-center" href={`${nbsctizrAnnealingDownloadPath}.sha256`} download>Download file SHA-256</a>
        </div>
        <p className="max-w-3xl text-xs leading-5 text-sage-muted">The metadata includes 210 source-value cells, 9 explicitly unlisted cells and exact text-window locators. Repeated reports remain separate source cells. Selected catalogue properties and sample associations are unchanged.</p>
        <p className="break-all text-xs text-sage-muted">Metadata SHA-256: <span className="font-mono">{nbsctizrAnnealingSnapshotSha256}</span></p>
        {data.sources.map(source => <section key={source.id} className="min-w-0 space-y-2">
          <h3 className="text-sm font-semibold">{source.title}</h3>
          <a className="site-text-link inline-flex min-h-11 items-center text-sm" href={nbsctizrSourceHref(source.id)!} target="_blank" rel="noopener noreferrer">Read arXiv:{source.edition}</a>
          <p className="break-all text-xs text-sage-muted">Captured PDF SHA-256: <span className="font-mono">{source.pdf_sha256}</span></p>
        </section>)}
        <p className="max-w-3xl text-xs leading-5 text-sage-muted">Current publication status, supplements and equivalence to retained ingestion bytes have not been checked.</p>
        <div className="space-y-4">{data.methods.map(method => <section key={method.id} className="min-w-0 space-y-1">
          <h3 className="text-xs font-semibold text-sage-muted">{method.source_id} source context</h3><p className="max-w-3xl text-sm leading-6">{method.summary}</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1">{method.locator_ids.map(locator => <PassageLink key={locator} data={data} sourceId={method.source_id} locator={locator}>Read source passage</PassageLink>)}</div>
        </section>)}</div>
      </div>
    </details>
  </div>;
}
