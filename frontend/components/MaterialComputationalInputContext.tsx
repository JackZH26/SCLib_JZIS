import {
  computationalInputContextHref, computationalInputContextMetadataPath,
  computationalInputContextSnapshotSha256, type ComputationalInputContext,
} from "@/lib/material-computational-input-context";

function DocumentationLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = computationalInputContextHref(url);
  return href ? <a href={href} className="site-text-link" target="_blank" rel="noopener noreferrer">{children}</a> : null;
}

export function MaterialComputationalInputContext({ data }: { data: ComputationalInputContext }) {
  return <div className="min-w-0 space-y-4">
    <section className="min-w-0" aria-labelledby="nomad-spin-input-heading">
      <h4 id="nomad-spin-input-heading" className="text-sm font-medium">MAGMOM input by source atom order</h4>
      <p className="mt-2 text-xs leading-5 text-sage-muted">These are input components, with no physical unit declared in the captured XML. Their restart-dependent role remains unresolved; final or ordered moments have not been assigned.</p>
      <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" tabIndex={0} role="region" aria-label="Spin input atom order, horizontally scrollable">
        <table className="w-full min-w-[24rem] text-left text-xs">
          <caption className="sr-only">Three MAGMOM input components, matched only to the captured XML atom order.</caption>
          <thead><tr>{["Source index (0-based)", "Element", "Exact input component"].map(label => <th scope="col" key={label} className="py-2 pr-4 font-medium">{label}</th>)}</tr></thead>
          <tbody>{data.spin_components.map(site => <tr key={site.zero_based_index} className="align-top">
            <th scope="row" className="py-2 pr-4 font-medium">{site.zero_based_index}</th>
            <td className="py-2 pr-4">{site.source_element_label}<details className="mt-1"><summary className="w-fit cursor-pointer text-accent-deep">Atom label source</summary><p className="mt-1 break-all font-mono">{site.atom_label_source_xpath}</p></details></td>
            <td className="py-2 font-mono">{site.raw_input_lexeme}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
    <p className="text-xs leading-5 text-sage-muted">The native GGA string <code className="font-mono">--</code> remains uninterpreted. The archive’s PBE method label is a separate source report.</p>
    <details className="min-w-0 text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Tag definitions in current VASP documentation</summary>
      <p className="mt-3">Current definitions clarify input roles. They do not establish the original VASP 5.3.2 edition, native units, effective runtime settings or convergence.</p>
      <dl className="mt-3 space-y-4">{data.documentation_annotations.map(annotation => <div key={annotation.native_tag}>
        <dt className="font-mono font-medium text-sage-ink">{annotation.native_tag}</dt>
        <dd>{annotation.documented_meaning}. {annotation.limitation}</dd>
        <dd className="mt-1 flex flex-wrap gap-x-4 gap-y-1"><DocumentationLink url={annotation.source.url}>Official {annotation.native_tag} definition</DocumentationLink><DocumentationLink url={annotation.source.revision_url}>Observed revision {annotation.source.observed_revision_id}</DocumentationLink></dd>
      </div>)}</dl>
      <p className="mt-3">Documentation was captured as rendered web-tool text. Grouped capture hashes in the metadata do not represent original HTML bytes.</p>
    </details>
    <details className="min-w-0 text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Reproduction evidence still to recover</summary>
      <dl className="mt-3 space-y-3">{data.reproduction_limits.map(item => <div key={item.id}>
        <dt className="font-medium text-sage-ink">{({ potential_identity: "Potential-file identity", original_input_and_restart_context: "Original inputs and restart context", cutoff_and_version_units: "Cutoff and version-specific definitions", convergence_and_result_mapping: "Convergence and energy mapping" } as Record<string, string>)[item.id]}</dt>
        <dd>{item.evidence}</dd><dd className="mt-1">{item.boundary}</dd>
      </div>)}</dl>
    </details>
    <details className="min-w-0 text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Additional input-context metadata and downloads</summary>
      <p className="mt-3">Eight additional tags and ten source occurrences belong to the same computed entry. They add no formal material properties or independent experiments. The earlier complete-source download retains its original bytes.</p>
      <pre className="mt-3 max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} role="region" aria-label="Additional input-context metadata JSON">{JSON.stringify(data, null, 2)}</pre>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2"><a href={computationalInputContextMetadataPath} className="site-text-link" download>Download additional input-context JSON</a><a href={`${computationalInputContextMetadataPath}.sha256`} className="site-text-link" download>Additional input-context SHA-256</a></div>
      <p className="mt-2 break-all font-mono">Metadata resource SHA-256: {computationalInputContextSnapshotSha256}</p>
    </details>
  </div>;
}
