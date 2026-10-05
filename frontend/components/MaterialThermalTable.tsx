import { loadThermalTable, thermalTableDownloadPath, type ThermalTable } from "@/lib/material-thermal-table";

const fields = [
  { id: "electronic_specific_heat_coefficient_source_value", label: "Electronic specific-heat coefficient, γ", symbol: "γ", unit: "mJ/mol-at./K²" },
  { id: "debye_temperature_source_value", label: "Debye temperature, ΘD", symbol: "ΘD", unit: "K" },
];

export function MaterialThermalTable({ snapshot }: { snapshot: ThermalTable | null }) {
  const table = snapshot ? loadThermalTable(snapshot) : null;
  if (!table) return <p role="status" className="text-sm text-sage-muted">Captured heat-capacity table readings are unavailable.</p>;
  const formulas = Array.from(new Set(table.readings.map(reading => reading.formula_as_printed)));
  const source = table.source;
  const pdfHref = `${source.source_url}#page=${source.pdf_page_1_based}`;
  return <section id="mo-thermal-table" aria-labelledby="mo-thermal-heading" className="min-w-0 scroll-mt-24 rounded-lg border border-sage-border bg-white p-4 sm:p-5">
    <h2 id="mo-thermal-heading" className="text-xl font-semibold">Mo borophosphide: heat-capacity analysis</h2>
    <p className="mt-2 text-sm leading-6 text-sage-muted">4 source readings for 2 printed compositions, from Table II on PDF page 5.</p>
    <div className="mt-4 max-w-full overflow-x-auto rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label="Mo Table II thermal readings, horizontally scrollable">
      <table className="w-full min-w-[15rem] table-fixed text-left text-sm tabular-nums">
        <caption className="sr-only">Table II heat-capacity readings under their exact printed composition headers.</caption>
        <thead><tr><th scope="col" className="w-[40%] py-3 pr-2 font-medium">Composition</th>{fields.map((field, index) => <th scope="col" aria-label={`${field.label}, ${field.unit}`} className={`${index === 0 ? "w-[36%] pr-2" : "w-[24%]"} py-3 font-medium`} key={field.id}><span className="hidden sm:block">{field.label}</span><span className="sm:hidden">{field.symbol}</span><span className="mt-1 block break-words text-xs font-normal text-sage-muted">{field.unit}</span></th>)}</tr></thead>
        <tbody>{formulas.map(formula => <tr key={formula} className="align-top"><th scope="row" className="py-3 pr-2 text-xs font-medium sm:text-sm">{formula}</th>{fields.map(field => {
          const reading = table.readings.find(item => item.field_id === field.id && item.formula_as_printed === formula)!;
          return <td key={field.id} className="py-3 pr-2 text-lg font-semibold">{reading.raw_value}</td>;
        })}</tr>)}</tbody>
      </table>
    </div>
    <p className="mt-2 text-xs leading-5 text-sage-muted sm:hidden">γ: electronic specific-heat coefficient.<br />ΘD: Debye temperature.</p>
    <p className="mt-3 max-w-3xl text-xs leading-5 text-sage-muted">The γ unit is per mole of atoms. These cells supply no uncertainty or pressure. Catalogue and Table I sample associations remain unresolved.</p>
    <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
      <a className="site-text-link" href={pdfHref} target="_blank" rel="noopener noreferrer">Open Table II in the paper ↗</a>
      <a className="site-text-link" href={thermalTableDownloadPath()} download>Download thermal readings (JSON)</a>
      <a className="site-text-link" href={`${thermalTableDownloadPath()}.sha256`} download>Download thermal SHA-256</a>
    </div>
    <details className="mt-4 text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Thermal field locators and source scope</summary>
      <div className="mt-3 space-y-4">
        <p>Table II prints Mo5P1.1B1.9; Table I uses a different first nominal composition, Mo5P0.9B2.1. Matching these samples or assigning either table to a catalogue result requires a separate association review. The cited Mo5SiB2 and W5SiB2 comparison columns are excluded.</p>
        <p>Values and row units are transcribed without numerical conversion. Parenthetical uncertainties from nearby prose are not assigned to these table cells.</p>
        <dl className="grid min-w-0 gap-4 sm:grid-cols-2">{table.readings.map(reading => <div className="min-w-0" key={reading.id}>
          <dt className="font-medium text-sage-ink">{reading.formula_as_printed}: {reading.field_cue}</dt>
          <dd className="mt-1 space-y-1">
            <p>Raw reading: {reading.raw_value} {reading.raw_unit}</p>
            <p>Original column {reading.column_index_0_based + 1}; data row {reading.row_index_0_based + 1}, excluding the composition header.</p>
            <p>Row label: <span className="whitespace-pre-wrap">{reading.raw_row_label}</span></p>
            <p>Value characters {reading.spans_in_table_text.value.char_start}-{reading.spans_in_table_text.value.char_end}; unit characters {reading.spans_in_table_text.unit.char_start}-{reading.spans_in_table_text.unit.char_end}, within the captured table text.</p>
          </dd>
        </div>)}</dl>
        <p>Offsets use zero-based Unicode code points with an exclusive end. The table occupies characters {source.table_span_in_full_text.char_start}-{source.table_span_in_full_text.char_end} in the retained text. Downloads include value, unit, field cue, composition, row-label and caption hashes.</p>
        <p>Captured 2 October 2026. The current PDF URL may return different bytes. Publication-version equivalence and independent human review remain unverified.</p>
        <p className="break-all font-mono">Captured PDF SHA-256: {source.pdf_sha256}</p>
        <p className="break-all font-mono">Captured full-text SHA-256: {source.full_text_sha256}</p>
        <p className="break-all font-mono">Captured table SHA-256: {source.table_text_sha256}</p>
      </div>
    </details>
  </section>;
}
