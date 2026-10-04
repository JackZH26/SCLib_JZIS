import {
  loadStudyContextBatch, studyContextDownloadPath, studyContextSnapshotSha256, studyContextSourceHref,
  type StudyContextBatch, type StudyContextEntry, type StudyContextField, type StudyContextSource, type StudyContextWindow,
} from "@/lib/material-study-context";

const wording = (value: string) => value.replace(/\s+/g, " ").trim();
function context(batch: StudyContextBatch | null, id: string): StudyContextEntry | null {
  const checked = batch && loadStudyContextBatch(batch);
  return checked?.entries.find(entry => entry.id === id) ?? null;
}
function windowFor(batch: StudyContextBatch, field: StudyContextField): StudyContextWindow {
  return batch.source_windows[field.locator.source_window_id as keyof StudyContextBatch["source_windows"]];
}
function sourceFor(batch: StudyContextBatch, window: StudyContextWindow): StudyContextSource | null {
  const digest = "source_pdf_sha256" in window ? window.source_pdf_sha256 : window.source_sha256;
  return batch.sources.find(source => ("pdf_sha256" in source ? source.pdf_sha256 : source.html_sha256) === digest) ?? null;
}
function fieldDisplay(field: StudyContextField): string {
  if (field.field === "pt_caption_tc_expression") return "23 K";
  if (field.field === "pt_heat_feature_context") return "≈ 20 K";
  return wording(field.raw_value);
}
function sourceLocation(window: StudyContextWindow): string {
  if (typeof window.locator === "string") {
    const id = window.locator.match(/@id='([^']+)'/)?.[1];
    return "HTML element " + (id ?? "not supplied") + (window.locator.endsWith("/figcaption") ? " · figure caption" : "");
  }
  return "PDF page " + window.locator.page + " · " + window.locator.section;
}
function sourceHref(source: StudyContextSource, window: StudyContextWindow): string | null {
  const safe = studyContextSourceHref(source.source_url);
  if (!safe) return null;
  const url = new URL(safe);
  if (typeof window.locator === "string") {
    const id = window.locator.match(/@id='([^']+)'/)?.[1];
    if (id) url.hash = id;
  } else url.hash = "page=" + window.locator.page;
  return url.href;
}
function SourceLocators({ batch, entry }: { batch: StudyContextBatch; entry: StudyContextEntry }) {
  const windows = [...new Set(entry.fields.map(field => field.locator.source_window_id))]
    .map(id => batch.source_windows[id as keyof StudyContextBatch["source_windows"]]);
  return <details className="mt-3 min-w-0 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Exact source locators</summary>
    <div className="mt-3 space-y-4">
      <p>{entry.source_scope}</p>
      {windows.map(window => {
        const source = sourceFor(batch, window), href = source && sourceHref(source, window);
        const sourceHash = source && ("pdf_sha256" in source ? source.pdf_sha256 : source.html_sha256);
        return <div className="min-w-0 space-y-1" key={window.codepoint_start}>
          <p className="font-medium text-sage-ink">{sourceLocation(window)}</p>
          {source && <p>Captured version: {source.revision}</p>}
          {source?.capture_finished_at && <p>Captured on {new Date(source.capture_finished_at).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" })}.</p>}
          {href && <a className="site-text-link inline-block" href={href} target="_blank" rel="noopener noreferrer">Open original source locator ↗</a>}
          {typeof window.locator !== "string" && <p>The PDF URL can return a different version. The source hashes below identify the captured file and text used for these fields.</p>}
          {sourceHash && <p className="break-all font-mono">Original source SHA-256: {sourceHash}</p>}
          <p className="break-all font-mono">Derived text SHA-256: {window.derived_text_sha256}</p>
          <p>Original source window: characters {window.codepoint_start}–{window.codepoint_end} (end exclusive).</p>
          <p>{typeof window.locator === "string" ? "This window range addresses the native HTML; field ranges below address the derived text of its named element." : "Window and field ranges address the frozen PDF-derived text, rather than PDF bytes."}</p>
        </div>;
      })}
      <dl className="space-y-3">{entry.fields.map(field => {
        const locator = field.locator;
        return <div className="min-w-0" key={field.field}>
          <dt className="font-medium text-sage-ink">{field.label}</dt>
          <dd className="mt-1 whitespace-pre-wrap break-words font-mono">Raw literal: {field.raw_value}</dd>
          <dd>Captured characters {locator.char_start}–{locator.char_end} (end exclusive){locator.original_table_column !== null ? " · original column " + locator.original_table_column : ""}{locator.original_table_row !== null ? " · row " + locator.original_table_row : ""}.</dd>
          <dd>{sourceLocation(windowFor(batch, field))} · occurrence {locator.occurrence_in_source_window} of {locator.literal_occurrences_in_source_window} in this source window.</dd>
          <dd className="break-all font-mono">Literal SHA-256: {locator.literal_sha256}</dd>
        </div>;
      })}</dl>
      <p>{entry.display_note}</p>
      <p>These captured source expressions retain pending context status. Current publication equivalence and physical sample or selected-result associations remain unestablished.</p>
    </div>
  </details>;
}

export function StudyContextFields({ batch, contextId }: { batch: StudyContextBatch | null; contextId: string }) {
  const entry = context(batch, contextId);
  if (!batch || !entry) return null;
  return <div className="scroll-mt-24 min-w-0" id={entry.id.replace(/[^a-zA-Z0-9_-]/g, "-")}>
    <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-[minmax(9rem,1fr)_minmax(0,3fr)]">{entry.fields.map(field => <div className="contents" key={field.field}>
      <dt className="text-sage-muted">{field.label}</dt>
      <dd className="min-w-0 break-words tabular-nums">{fieldDisplay(field)}</dd>
    </div>)}</dl>
    <SourceLocators batch={batch} entry={entry} />
  </div>;
}

export function StudyCompositionLocator({ batch, column }: { batch: StudyContextBatch | null; column: 2 | 3 }) {
  const entry = context(batch, "study-context:mo:table-I-column-" + column);
  return batch && entry ? <SourceLocators batch={batch} entry={entry} /> : null;
}

export function StudyPtContexts({ batch }: { batch: StudyContextBatch | null }) {
  const entry = context(batch, "study-context:pt:calorimetry-attribution");
  const composition = context(batch, "study-context:pt:xrd-correspondence");
  if (!batch || !entry || !composition) return null;
  const field = (id: string) => entry.fields.find(value => value.field === id)!;
  return <section className="scroll-mt-24 min-w-0 space-y-3" id="study-context-pt-calorimetry-attribution" aria-labelledby="pt-study-transition-context">
    <h3 className="text-sm font-semibold" id="pt-study-transition-context">Transition methods in the source</h3>
    <div className="max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label="Pt source transition methods, horizontally scrollable">
      <table className="w-full min-w-[29rem] text-left text-sm">
        <caption className="sr-only">Caption Tc attribution and separate calorimetry feature descriptions.</caption>
        <thead><tr>{["Source description", "Reported temperature", "Method and role"].map(label => <th key={label} scope="col" className="py-2 pr-4 font-medium">{label}</th>)}</tr></thead>
        <tbody>
          <tr className="align-top"><th scope="row" className="py-3 pr-4 font-medium">Tc attributed in Figure 4 caption</th><td className="py-3 pr-4 tabular-nums">{fieldDisplay(field("pt_caption_tc_expression"))}</td><td className="py-3">{fieldDisplay(field("pt_caption_tc_methods"))}</td></tr>
          <tr className="align-top"><th scope="row" className="py-3 pr-4 font-medium">Heat-capacity feature · Figure 4 caption</th><td className="py-3 pr-4 tabular-nums">{fieldDisplay(field("pt_heat_feature_context"))}</td><td className="py-3">Feature center in the caption</td></tr>
          <tr className="align-top"><th scope="row" className="py-3 pr-4 font-medium">Heat-capacity shift · discussion</th><td className="py-3 pr-4 tabular-nums">{fieldDisplay(field("pt_heat_anomaly_context"))}</td><td className="py-3">Temperature context in the specific-heat discussion</td></tr>
        </tbody>
      </table>
    </div>
    <p className="text-xs leading-5 text-sage-muted">The calorimetry descriptions remain feature context. The thermal-relaxation method and isoentropic analysis are reported separately below; no distinct calorimetric Tc is assigned here.</p>
    <SourceLocators batch={batch} entry={entry} />
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">XRD composition correspondence</summary>
      <div className="mt-3">
        <StudyContextFields batch={batch} contextId={composition.id} />
        <p className="mt-3 text-xs leading-5 text-sage-muted">The source relates the study composition to its refined composition. Printed uncertainties remain intact; 250 K is the XRD measurement temperature.</p>
      </div>
    </details>
  </section>;
}

export function StudyContextDownloads({ batch }: { batch: StudyContextBatch | null }) {
  const checked = batch && loadStudyContextBatch(batch);
  if (!checked) return null;
  return <details className="min-w-0 text-sm">
    <summary className="w-fit cursor-pointer text-accent-deep">Study context metadata and downloads</summary>
    <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
      <p>Six reading contexts from three captured studies, with 19 literal field projections. These include composition locators for fields already shown; the count does not represent independent experiments.</p>
      <p>Prepared on 4 October 2026. Source contexts retain their captured versions and remain separate from selected catalogue properties.</p>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <a className="site-text-link" href={studyContextDownloadPath} download>Download study context (JSON)</a>
        <a className="site-text-link" href={studyContextDownloadPath + ".sha256"} download>Download study context SHA-256</a>
      </div>
      <p className="break-all font-mono">Metadata SHA-256: {studyContextSnapshotSha256}</p>
      <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} aria-label="Study context metadata JSON">{JSON.stringify(checked, null, 2)}</pre>
    </div>
  </details>;
}
