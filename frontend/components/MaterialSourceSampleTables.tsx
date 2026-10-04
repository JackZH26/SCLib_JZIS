import type { ReactNode } from "react";
import {
  loadSourceSampleTables, sourceSampleTableCell, sourceSampleTableHref,
  sourceSampleTablesDownloadPath, sourceSampleTablesSha256,
  type SourceSampleCell, type SourceSampleTable, type SourceSampleTables,
} from "@/lib/material-source-sample-tables";

const headers: Record<string, ReactNode> = {
  nominal_x: <>Nominal <i>x</i></>, EDX_Fe: "EDX Fe", EDX_Te: "EDX Te", EDX_Se: "EDX Se",
  C: "C (emu K/mol)", theta: "θ (K)", mu_eff: <>μ<sub>eff</sub> (μ<sub>B</sub>)</>,
  C_II: <>C<sub>II</sub> (emu K/mol)</>, theta_II: <>θ<sub>II</sub> (K)</>,
};
function Cell({ cell }: { cell: SourceSampleCell }) {
  if (cell.display_state === "source_blank") return <span className="text-xs text-sage-muted">Blank in source</span>;
  if (cell.display_state === "source_dash") return <span title="Printed dash in source">{cell.raw_value}</span>;
  return <>{cell.raw_value}</>;
}
function SourceTable({ table, name, caption, minimumWidth }: { table: SourceSampleTable; name: string; caption: string; minimumWidth: string }) {
  return <div role="region" aria-label={name + ", horizontally scrollable"} tabIndex={0}
    className="min-w-0 max-w-full overflow-x-auto rounded-lg border border-sage-border bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
    <table className={"w-full text-left text-sm " + minimumWidth}>
      <caption className="border-b border-sage-border px-4 py-3 text-left text-xs leading-5 text-sage-muted">{caption}</caption>
      <thead className="border-b border-sage-border bg-sage-surface text-xs text-sage-muted"><tr>{table.columns.map(column => <th key={column} scope="col" className="px-4 py-3 font-medium">{headers[column]}</th>)}</tr></thead>
      <tbody className="divide-y divide-sage-border">{table.rows.map(row => <tr key={row.source_row}>{table.columns.map((column, index) => index === 0
        ? <th key={column} scope="row" className="px-4 py-3 font-medium tabular-nums"><Cell cell={sourceSampleTableCell(row, column)} /></th>
        : <td key={column} className="px-4 py-3 align-top tabular-nums"><Cell cell={sourceSampleTableCell(row, column)} /></td>)}</tr>)}</tbody>
    </table>
  </div>;
}

export function MaterialSourceSampleTables({ data }: { data: SourceSampleTables | null }) {
  const checked = data && loadSourceSampleTables(data);
  if (!checked) return <p className="text-sm text-sage-muted" role="status">The captured sample tables are unavailable. The materials catalogue remains available.</p>;
  return <div className="min-w-0 space-y-8">
    <section className="min-w-0 space-y-4" aria-labelledby="fete-composition-heading">
      <h2 className="text-xl font-semibold" id="fete-composition-heading">Nominal and measured composition</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">The EDX columns preserve the reported Fe, Te and Se coefficients, including excess Fe. Nominal x describes preparation; it differs from measured Se content.</p>
      <SourceTable table={checked.composition_table} name="FeTeSe nominal and EDX composition" minimumWidth="min-w-[28rem]"
        caption="Table I composition rows, in their original order. Coefficients are retained as printed." />
    </section>
    <section className="min-w-0 space-y-4" aria-labelledby="fete-fit-heading">
      <h2 className="text-xl font-semibold" id="fete-fit-heading">Curie–Weiss fit parameters</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">θ is a Weiss fit temperature; μeff is a fit-derived effective moment. These parameters do not establish ordering temperatures or ordered moments.</p>
      <ul className="max-w-3xl space-y-2 text-sm leading-6 text-sage-muted">
        <li>100–300 K: measured x = 0 and 0.05 (nominal x = 0 and 0.10); C, θ and μeff.</li>
        <li>20–50 K: measured x = 0.12, 0.20, 0.28 and 0.33; CII and θII. The authors tentatively attribute this term to Fe(II), for approximate subtraction.</li>
      </ul>
      <SourceTable table={checked.fit_parameter_table} name="FeTeSe Curie–Weiss fit parameters" minimumWidth="min-w-[48rem]"
        caption="Susceptibility-fit parameters from the same Table I rows. Original units and missing-cell marks are preserved." />
      <p className="text-xs leading-5 text-sage-muted">Blank in source = an empty printed cell; - = a printed dash. Neither is a zero.</p>
    </section>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Source, scope and downloads</summary>
      <div className="mt-4 space-y-4 text-xs leading-5 text-sage-muted">
        <p>Captured edition: {checked.source.edition}, Table I on page 4. The six rows belong to this source. Physical sample, state and selected catalogue result associations remain unestablished; publisher and retained-ingestion edition equivalence is unresolved.</p>
        <p>Printed coefficients and fit parameters retain their source roles and units. No canonical field, scientific acceptance or ML approval is added by this reference.</p>
        <dl className="space-y-3">{checked.locators.map(locator => <div className="min-w-0" key={locator.id}>
          <dt className="font-medium text-sage-ink">{locator.id === checked.composition_table.source_locator_id ? "Table I rows and headings" : locator.id.includes("low-temperature") ? "20–50 K fit and Fe(II) interpretation" : "100–300 K fit range"}</dt>
          <dd>PDF page {locator.page} · captured characters {locator.char_start}–{locator.char_end}, end exclusive.</dd>
          <dd><a className="site-text-link" href={sourceSampleTableHref(locator.page)!} target="_blank" rel="noopener noreferrer">Read this passage on PDF page {locator.page} ↗</a></dd>
          <dd className="break-all font-mono">Window SHA-256: {locator.window_sha256}</dd>
        </div>)}</dl>
        <p className="break-all font-mono">Original PDF SHA-256: {checked.source.pdf_sha256}</p>
        <p className="break-all font-mono">Derived text SHA-256: {checked.source.derived_text_sha256}</p>
        <p>Character ranges refer to the frozen PDF-derived text. A current paper download can have different bytes.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          <a className="site-text-link" href={sourceSampleTablesDownloadPath} download>Download sample tables (JSON)</a>
          <a className="site-text-link" href={sourceSampleTablesDownloadPath + ".sha256"} download>Download sample table SHA-256</a>
        </div>
        <p className="break-all font-mono">Reference JSON SHA-256: {sourceSampleTablesSha256}</p>
        <pre role="region" className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} aria-label="Source sample table metadata JSON">{JSON.stringify(checked, null, 2)}</pre>
      </div>
    </details>
  </div>;
}
