import Link from "next/link";
import {
  loadNativePaperContexts, nativePaperContextDownloadPath, nativePaperContextSnapshotSha256,
  nativePaperContextSourceHref, type NativePaperContextBatch, type NativePaperContext,
} from "@/lib/material-native-paper-context";

function SourceDetails({ context, batch }: { context: NativePaperContext; batch: NativePaperContextBatch }) {
  const source = batch.sources.find(source => source.id === context.source_id)!;
  const locators = batch.locators.filter(locator => context.rows.some(row => row.locator_ids.includes(locator.id))
    || context.additional_locator_ids.includes(locator.id));
  return <details className="mt-4 min-w-0 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Source and attribution details</summary>
    <div className="mt-3 space-y-3">
      <p>{context.attribution_note}</p>
      <p>Captured edition: {source.revision}. {source.review_scope}</p>
      <a className="site-text-link inline-block" href={nativePaperContextSourceHref(source.id)!} target="_blank" rel="noopener noreferrer">Open captured paper edition ↗</a>
      <p>{source.bibliographic_note}</p>
      <p className="break-all font-mono">Original PDF SHA-256: {source.pdf_sha256}</p>
      <p className="break-all font-mono">Derived text SHA-256: {source.derived_text_sha256}</p>
      <dl className="space-y-3">{locators.map(locator => <div className="min-w-0" key={locator.id}>
        <dt className="font-medium text-sage-ink">{locator.label}</dt>
        <dd>PDF page {locator.pages_one_based.join(", ")} · captured characters {locator.char_start}–{locator.char_end} (end exclusive).</dd>
        <dd><a className="site-text-link inline-block" href={nativePaperContextSourceHref(source.id, locator.pages_one_based[0])!} target="_blank" rel="noopener noreferrer">Open source page ↗</a></dd>
        <dd className="break-all font-mono">Window SHA-256: {locator.window_sha256}</dd>
      </div>)}</dl>
      <p>Character ranges address the frozen PDF-derived text. Summaries above are paraphrases, not retained literal extractions. Current download bytes may differ from the captured hashes.</p>
    </div>
  </details>;
}

export function MaterialNativePaperContexts({ batch }: { batch: NativePaperContextBatch | null }) {
  const checked = batch && loadNativePaperContexts(batch);
  if (!checked) return <p className="text-sm text-sage-muted" role="status">Captured paper contexts are unavailable. The materials catalogue remains available.</p>;
  return <div className="min-w-0 divide-y divide-sage-border">{checked.contexts.map(context => <section className="scroll-mt-24 min-w-0 space-y-4 py-6 first:pt-0" id={context.id} key={context.id} aria-labelledby={context.id + "-heading"}>
    <h2 className="break-words text-xl font-semibold" id={context.id + "-heading"}>{context.title}</h2>
    <p className="max-w-3xl text-sm leading-6 text-sage-muted">{context.subject}</p>
    <dl className="grid min-w-0 gap-x-6 gap-y-3 text-sm sm:grid-cols-[minmax(9rem,1fr)_minmax(0,3fr)]">{context.rows.map(row => <div className="contents" key={row.label}>
      <dt className="text-sage-muted">{row.label}</dt>
      <dd className="min-w-0 max-w-3xl break-words leading-6">{row.summary}</dd>
    </div>)}</dl>
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
      <Link className="site-text-link" href={"/materials/" + encodeURIComponent(context.material_id)}>Open catalogue entry</Link>
      <a className="site-text-link" href={nativePaperContextSourceHref(context.source_id)!} target="_blank" rel="noopener noreferrer">Read original paper ↗</a>
    </div>
    <SourceDetails context={context} batch={checked} />
  </section>)}</div>;
}

export function NativePaperContextDownloads({ batch }: { batch: NativePaperContextBatch | null }) {
  const checked = batch && loadNativePaperContexts(batch);
  if (!checked) return null;
  return <details className="min-w-0 text-sm">
    <summary className="w-fit cursor-pointer text-accent-deep">Paper context metadata and downloads</summary>
    <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
      <p>Prepared on 4 October 2026. These source summaries establish no physical sample, state or selected-result association and make no canonical field updates.</p>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <a className="site-text-link" href={nativePaperContextDownloadPath} download>Download paper contexts (JSON)</a>
        <a className="site-text-link" href={nativePaperContextDownloadPath + ".sha256"} download>Download paper context SHA-256</a>
      </div>
      <p className="break-all font-mono">Metadata SHA-256: {nativePaperContextSnapshotSha256}</p>
      <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} aria-label="Paper context metadata JSON">{JSON.stringify(checked, null, 2)}</pre>
    </div>
  </details>;
}
