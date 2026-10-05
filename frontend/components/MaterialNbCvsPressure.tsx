import Link from "next/link";
import { loadNbCvsPressure, nbCvsPressureDownloadPath, type NbCvsPressure } from "@/lib/material-nb-cvs-pressure";

type Field = NbCvsPressure["fields"][number];
function PressureTable({ data, fields, label }: { data: NbCvsPressure; fields: Field[]; label: string }) {
  return <div className="relative mt-4 max-w-full overflow-x-auto rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label={`${label}, horizontally scrollable`}>
    <table className="w-full min-w-[35rem] table-fixed text-left text-sm tabular-nums">
      <caption className="sr-only">{label}</caption>
      <thead><tr><th className="w-[36%] py-3 pr-3 font-medium" scope="col">Parameter</th>{data.pressure_columns.map(pressure => <th className="w-[16%] py-3 pr-2 font-medium" scope="col" key={pressure.raw_value}>{pressure.raw_value} GPa</th>)}</tr></thead>
      <tbody>{fields.map(field => <tr className="align-top" key={field.id}>
        <th className="py-3 pr-3 font-medium" scope="row"><span>{field.symbol}{field.display_unit ? ` (${field.display_unit})` : ""}</span><span className="mt-1 block text-xs font-normal leading-5 text-sage-muted">{field.label}</span></th>
        {field.cells.map(cell => <td className="py-3 pr-2 font-mono" key={cell.pressure_column_index_0_based}>{cell.state === "source_dash" ? <span className="text-xs text-sage-muted" aria-label="Not listed, source dash">Not listed <span className="sr-only">(source dash)</span></span> : cell.raw_value}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

export function MaterialNbCvsPressure({ snapshot }: { snapshot: NbCvsPressure | null }) {
  const data = snapshot ? loadNbCvsPressure(snapshot) : null;
  if (!data) return <p role="status" className="text-sm text-sage-muted">Captured Nb0.07-CVS pressure readings are unavailable.</p>;
  const source = data.source;
  const href = (id: string) => `${source.html_url}#${id}`;
  return <section className="min-w-0 space-y-6" aria-label="Nb0.07-CVS pressure-series source readings">
    <div className="space-y-2 text-sm leading-6 text-sage-muted">
      <p><span className="font-medium text-sage-ink">Cs(V0.93Nb0.07)3Sb5 · Transverse-field μSR · 10 mT.</span> These are fits to measured data, reported at four applied hydrostatic pressures.</p>
    </div>
    <section className="min-w-0 rounded-lg border border-sage-border bg-white p-4 sm:p-5" aria-labelledby="nb-cvs-parameters">
      <h2 id="nb-cvs-parameters" className="text-xl font-semibold">Gap and penetration-depth parameters</h2>
      <p className="mt-2 text-sm leading-6 text-sage-muted">Tc is a parameter of the gap-structure fit. The separate AC susceptibility measurements used zero-field conditions.</p>
      <PressureTable data={data} fields={data.fields.filter(field => field.role === "source_reported_fit_parameter")} label="Nb0.07-CVS gap-structure fit parameters" />
      <p className="mt-3 text-xs leading-5 text-sage-muted">The table retains λ(T &gt; 0) and λ⁻²(T = 0) as printed. λ denotes London penetration depth. Parenthetical uncertainties are unchanged; unlisted Δ₂ cells are source dashes.</p>
      <div className="mt-4 border-t border-sage-border pt-4">
        <h3 className="text-sm font-semibold">Model used at each pressure</h3>
        <dl className="mt-2 grid grid-cols-1 gap-x-5 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">{data.pressure_columns.map(pressure => <div key={pressure.raw_value}><dt className="font-medium tabular-nums">{pressure.raw_value} GPa</dt><dd className="mt-1 text-xs leading-5 text-sage-muted">{pressure.model}</dd></div>)}</dl>
        <p className="mt-3 text-xs leading-5 text-sage-muted">ω is the phase fraction in this fit, as defined by the authors. It is not a measured superconducting volume fraction.</p>
      </div>
      <details className="mt-4">
        <summary className="w-fit cursor-pointer text-sm text-accent-deep">Inspect 8 fit statistics</summary>
        <PressureTable data={data} fields={data.fields.filter(field => field.role === "source_reported_fit_statistic")} label="Nb0.07-CVS fit statistics" />
        <p className="mt-2 text-xs leading-5 text-sage-muted">χ² and χ²/NDF describe the authors’ fits. They are not SCLib acceptance scores; no threshold or rescaling has been applied.</p>
      </details>
    </section>
    <section className="space-y-2 text-sm leading-6" aria-labelledby="nb-cvs-separate-fit">
      <h2 id="nb-cvs-separate-fit" className="text-lg font-semibold">Keep the ambient prose fit separate</h2>
      <p className="max-w-3xl text-sage-muted">The ambient prose reports Tc = 4.70(3) K, λ = 316(5) nm and Δ = 0.590(5) meV. This is a separate fit from the table’s 0 GPa column.</p>
      <Link className="site-text-link inline-block" href="/materials/source-observations">Compare the original observation windows</Link>
    </section>
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
      <a className="site-text-link" href={href(source.table_locator.element_id)} target="_blank" rel="noopener noreferrer">Open the source table ↗</a>
      <a className="site-text-link" href={`${source.pdf_url}#page=8`} target="_blank" rel="noopener noreferrer">Open PDF page 8 ↗</a>
      <a className="site-text-link" href={nbCvsPressureDownloadPath()} download>Download pressure-series metadata (JSON)</a>
      <a className="site-text-link" href={`${nbCvsPressureDownloadPath()}.sha256`} download>Download SHA-256</a>
    </div>
    <details className="text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Source locators and sample scope</summary>
      <div className="mt-3 space-y-3">
        <p>arXiv:2411.18744v1, captured 5 October 2026. HTML Table 1 and PDF Table I (page 8) were checked for these values and units. Publication status and equivalence to catalogue ingestion remain unverified.</p>
        <p>The paper states a single-crystal default unless otherwise specified. Table 1 has no unique physical specimen identifier. Its pressure labels do not establish an absolute/gauge convention, and 0 GPa is not a conversion of ambient wording.</p>
        <p>The ambient prose and pressure-table fits have unresolved dataset and specimen correspondence. These source readings are unassociated with a selected catalogue result. Independent human review, scientific acceptance and formal property promotion remain separate.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2"><a className="site-text-link" href={href(data.method.conditions_locator.element_id)} target="_blank" rel="noopener noreferrer">Measurement and fit context ↗</a><a className="site-text-link" href={href(data.subject.sample_type_locator.element_id)} target="_blank" rel="noopener noreferrer">Source sample description ↗</a></div>
        <dl className="grid min-w-0 gap-4 sm:grid-cols-2">{data.fields.map(field => <div className="min-w-0" key={field.id}><dt className="font-medium text-sage-ink">{field.symbol}{field.display_unit ? ` (${field.display_unit})` : ""}</dt><dd>Source parameter row {field.source_row_index_1_based}; label <a className="site-text-link" href={href(field.row_label_locator.element_id)} target="_blank" rel="noopener noreferrer">{field.row_label_locator.element_id}</a>. {field.display_unit ? "Unit from the printed row label." : "No unit printed; meaning from the table caption."}</dd></div>)}</dl>
        <p>JSON includes exact cell and row-label HTML character ranges, element IDs and SHA-256 hashes. Offsets count Unicode code points and exclude the end position. Source dashes and uncertainty strings are retained without normalization.</p>
        <p className="break-all font-mono">HTML SHA-256: {source.html_sha256}</p>
        <p className="break-all font-mono">PDF SHA-256: {source.pdf_sha256}</p>
      </div>
    </details>
  </section>;
}
