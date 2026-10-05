import { loadPressureTableSubject, pressureTableSubjectPath, pressureTableSourceHref, pressureTableSubjectEntries,
  type PressureTableBatch, type PressureTableEntry, type PressureTableSource, type SourceQuantity } from "@/lib/material-pressure-table-sources";
import { StudyCompositionLocator, StudyContextFields } from "@/components/MaterialStudyContext";
import { loadStudyContextBatch, type StudyContextBatch } from "@/lib/material-study-context";

const wording = (value: string) => value.replace(/\s+/g, " ").trim();
// Spacing is presentation only. The raw source strings and unresolved numeric values remain unchanged in metadata.
const quantity = (value: SourceQuantity) => `${wording(value.raw_value)}${value.raw_unit ? ` ${value.raw_unit}` : ""}`;
const condition = (entry: PressureTableEntry, field: string) => entry.conditions.find(value => value.field_id === field)?.value;
const fieldId = (entry: PressureTableEntry) => entry.id.replace(/[^a-zA-Z0-9_-]/g, "-");
function SourceSnapshot({ source }: { source: PressureTableSource }) {
  return <details className="mt-4 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Source snapshot and publication version</summary>
    <div className="mt-2 space-y-2">
      <p>{source.paper_id}. Captured {new Date(source.captured_at_utc).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" })}.</p>
      <p>{source.source_revision}</p>
      {source.pdf_internal_date_raw && <p>PDF internal date: {source.pdf_internal_date_raw}. Official arXiv v1 submission: {source.official_arxiv_v1_submission_date}. Their correspondence remains unresolved.</p>}
      {!source.pdf_internal_date_raw && <p>Official arXiv v1 submission: {source.official_arxiv_v1_submission_date}. The captured PDF has not been established as identical to the current publisher or arXiv file.</p>}
      <a href={pressureTableSourceHref(source.source_url)!} className="site-text-link" target="_blank" rel="noopener noreferrer">Open paper PDF ↗</a>
      <p>Current URLs may return different bytes. Source currentness and original-fulltext redistribution rights remain unresolved.</p>
      <p className="break-all font-mono">Captured PDF SHA-256: {source.parent_pdf_sha256}</p>
      <p className="break-all font-mono">Captured text SHA-256: {source.source_content_sha256}</p>
      <p className="break-all font-mono">Prepared package SHA-256: {source.prepared_package_file_sha256}</p>
    </div>
  </details>;
}
function Locator({ entry, source }: { entry: PressureTableEntry; source: PressureTableSource }) {
  const location = entry.locator;
  const spans = entry.field_spans.value_spans as { start: number; end: number; sha256: string }[];
  return <details className="mt-2 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Field locator</summary>
    <div className="mt-2 space-y-1">
      <a className="site-text-link" href={pressureTableSourceHref(source.source_url, location.page)!} target="_blank" rel="noopener noreferrer">Open field’s PDF page ↗</a>
      <p>PDF page {location.page}{location.table ? `, ${location.table}` : ""}{location.column !== null ? `, original column ${location.column}` : ""}{location.row !== null ? `, row ${location.row}` : ""}.</p>
      {spans.map(span => <p key={`${span.start}:${span.end}`}>Captured characters {span.start}-{span.end} (end exclusive).</p>)}
      <p className="break-all">Source window: {entry.window.id}</p>
      <p className="break-all font-mono">Expression key: {entry.expression_key}</p>
      {entry.value.status === "unit_requires_review" && <p>Numeric normalization pending. No bare float or interpreted uncertainty is assigned.</p>}
      <p>Metadata downloads include the exact subject, condition, window, unit and value spans with their token hashes.</p>
    </div>
  </details>;
}
function SubjectReference({ subjectId, label }: { subjectId: string; label: string }) {
  const metadata = loadPressureTableSubject(subjectId);
  const href = pressureTableSubjectPath(subjectId);
  return metadata && href ? <details className="min-w-0 text-sm">
    <summary className="w-fit cursor-pointer text-accent-deep">{label}</summary>
    <p className="mt-2 text-xs leading-5 text-sage-muted">Six source expressions with their original locators and pending status. This view preserves the static resource's data.</p>
    <pre className="mt-3 max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} aria-label={`${label}: six source expressions`}>{JSON.stringify(metadata, null, 2)}</pre>
    <a className="site-text-link mt-2 inline-block text-xs" href={href}>Static JSON resource</a>
  </details>
    : <p role="status" className="text-xs text-sage-muted">Source-subject metadata is unavailable.</p>;
}
function BiTeCl({ batch, studyContext }: { batch: PressureTableBatch; studyContext?: StudyContextBatch | null }) {
  const entries = pressureTableSubjectEntries(batch, "bitecl"), source = batch.sources[0];
  const [tc, pressure, sample, instrument, captionLow, captionHigh] = entries;
  return <section aria-labelledby="bitecl-heading" className="min-w-0 rounded-lg border border-sage-border bg-white p-4 sm:p-5">
    <h2 id="bitecl-heading" className="scroll-mt-24 text-xl font-semibold">BiTeCl: separate pressure windows</h2>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">The main-text Tc report and the Figure 2 curve criteria have distinct source windows.</p>
    <div className="mt-4 grid gap-5 md:grid-cols-2">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">Main-text highest Tc report</h3>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          {[tc, pressure].map(entry => <div key={entry.id} id={fieldId(entry)} className="min-w-0"><dt className="text-xs text-sage-muted">{entry.field_id === "tc_kelvin" ? "Reported Tc" : "Reported pressure"}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{quantity(entry.value)}</dd><Locator entry={entry} source={source} /></div>)}
        </dl>
        <p className="mt-3 text-xs leading-5 text-sage-muted">Tc criterion not supplied in this source window. The pressure string is retained; its numeric normalization remains pending.</p>
      </div>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">Figure 2 caption criteria</h3>
        <dl className="mt-3 space-y-3">{[captionLow, captionHigh].map(entry => <div key={entry.id} id={fieldId(entry)}><dt className="text-xs text-sage-muted">Caption pressure {quantity(condition(entry, "pressure_gpa")!)}</dt><dd className="mt-1 text-sm">{wording(condition(entry, "criterion_statement")!.raw_value)}</dd><Locator entry={entry} source={source} /></div>)}</dl>
        <p className="mt-3 text-xs leading-5 text-sage-muted">The caption criterion is not assigned to the 7 K report at 15 GPa.</p>
      </div>
    </div>
    <div className="mt-5 rounded-md border border-sage-border bg-sage-surface p-3 text-sm leading-6" role="note" aria-label="Unresolved Figure 2 pressure-label conflict">
      <p className="font-semibold">Pressure-label conflict: unresolved</p>
      <p>Figure 2’s inset legend prints {batch.source_label_conflict.inset_legend_pressure_raw}; its caption and main text report {batch.source_label_conflict.caption_and_main_text_pressure_raw}. The caption is transcribed as written. A common physical pressure has not been established.</p>
    </div>
    <details className="mt-4 text-sm"><summary className="w-fit cursor-pointer text-accent-deep">Sample and transport method</summary>
      <dl className="mt-3 space-y-3">{[sample, instrument].map(entry => <div key={entry.id} id={fieldId(entry)}><dt className="text-xs text-sage-muted">{entry.field_id === "sample_form_statement" ? "Reported sample form" : "Reported instrument and probes"}</dt><dd className="mt-1">{quantity(entry.value)}</dd><Locator entry={entry} source={source} /></div>)}</dl>
      {studyContext ? <div className="mt-4 space-y-5"><StudyContextFields batch={studyContext} contextId="study-context:bi:transport" /><StudyContextFields batch={studyContext} contextId="study-context:bi:raman" /></div> : <p className="mt-3 text-xs leading-5 text-sage-muted">Room-temperature pressure calibration is separate from the superconducting measurement temperature.</p>}
    </details>
    <div className="mt-4"><SubjectReference subjectId="bitecl" label="View BiTeCl source subject (JSON)" /></div>
    <SourceSnapshot source={source} />
  </section>;
}
function MoTable({ batch, studyContext }: { batch: PressureTableBatch; studyContext?: StudyContextBatch | null }) {
  const left = pressureTableSubjectEntries(batch, "mo_nominal_column_2"), right = pressureTableSubjectEntries(batch, "mo_nominal_column_3"), source = batch.sources[1];
  const labels = ["Tc: zero resistivity", "Tc: χ′ diamagnetic onset", "Lattice a", "Lattice c", "Reported space group", "Reported sample form"];
  return <section aria-labelledby="mo-table-heading" className="min-w-0 rounded-lg border border-sage-border bg-white p-4 sm:p-5">
    <h2 id="mo-table-heading" className="scroll-mt-24 text-xl font-semibold">Mo borophosphide: two original table columns</h2>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">The two nominal samples share a reported refined composition, while their Tc criteria and lattice values remain distinct.</p>
    <div className="mt-4 max-w-full overflow-x-auto rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label="Mo Table I comparison, horizontally scrollable">
      <table className="w-full min-w-[40rem] text-left text-sm tabular-nums">
        <caption className="sr-only">Table I original columns 2 and 3, preserving separate nominal samples and source-reported uncertainty notation.</caption>
        <thead><tr><th scope="col" className="w-[30%] py-3 pr-4 font-medium">Reported field</th>{[left, right].map((entries, index) => <th scope="col" className="w-[35%] py-3 pr-5 font-medium" key={index}><span className="block">Nominal {entries[0].subject.sample_label}</span><span className="mt-1 block text-xs font-normal text-sage-muted">Original Table I column {index + 2}</span><span className="mt-2 block text-xs font-normal">Refined {entries[0].subject.formula}</span>{studyContext && <StudyCompositionLocator batch={studyContext} column={index === 0 ? 2 : 3} />}</th>)}</tr></thead>
        <tbody>{labels.map((label, index) => <tr className="align-top" key={label}><th scope="row" className="py-4 pr-4 font-medium">{label}<span className="mt-1 block text-xs font-normal text-sage-muted">{index < 2 ? "Tc pressure not supplied" : index < 5 ? "Room-temperature powder XRD" : "Study-level preparation"}</span></th>{[left[index], right[index]].map(entry => <td id={fieldId(entry)} className="py-4 pr-5" key={entry.id}><span className="font-medium">{quantity(entry.value)}</span><Locator entry={entry} source={source} /></td>)}</tr>)}</tbody>
      </table>
    </div>
    <p className="mt-3 max-w-4xl text-xs leading-5 text-sage-muted">Parenthetical digits and the printed angstrom units are preserved. All eight Tc/lattice quantities await numeric and uncertainty normalization. Room-temperature XRD conditions are not Tc conditions; missing Tc pressure is not treated as ambient.</p>
    <p className="mt-2 max-w-4xl text-xs leading-5 text-sage-muted">The third, more P-rich table column is a separate sample and is excluded from this comparison.</p>
    <div className="mt-4 grid min-w-0 gap-4 md:grid-cols-2"><SubjectReference subjectId="mo_nominal_column_2" label="View original column 2 (JSON)" /><SubjectReference subjectId="mo_nominal_column_3" label="View original column 3 (JSON)" /></div>
    <SourceSnapshot source={source} />
  </section>;
}
export function MaterialPressureTableSources({ batch, studyContext }: { batch: PressureTableBatch | null; studyContext?: StudyContextBatch | null }) {
  if (!batch) return <p role="status" className="text-sm text-sage-muted">Captured pressure and table records are unavailable.</p>;
  const checkedContext = studyContext ? loadStudyContextBatch(studyContext) : null;
  return <div className="min-w-0 space-y-5">
    <p className="max-w-4xl text-xs leading-5 text-sage-muted">These pending field expressions are source records, not a count of independent experiments. Catalogue result, sample and state associations remain unestablished. No scientific acceptance or ML training approval is granted.</p>
    <BiTeCl batch={batch} studyContext={checkedContext} />
    <MoTable batch={batch} studyContext={checkedContext} />
  </div>;
}
