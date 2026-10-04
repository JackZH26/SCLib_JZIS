import {
  computationalNativeOutputHref, computationalNativeOutputMetadataPath,
  computationalNativeOutputSnapshotSha256, computationalNativeOutputSourceSha256,
  type ComputationalNativeOutput,
} from "@/lib/material-computational-native-output";
import { MaterialComputationalInputContext } from "@/components/MaterialComputationalInputContext";
import { type ComputationalInputContext } from "@/lib/material-computational-input-context";

function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = computationalNativeOutputHref(url);
  return href ? <a href={href} className="site-text-link" target="_blank" rel="noopener noreferrer">{children}</a> : null;
}

function inputContextLabel(sourceContext: string): string {
  if (sourceContext === "./incar[1]") return "INCAR";
  const groups = [...sourceContext.matchAll(/\[@name='([^']+)'\]/g)].map(match => match[1]);
  const group = groups.at(-1);
  return group ? `Parameters · ${group.charAt(0).toUpperCase()}${group.slice(1)}` : "Parameters";
}

function CoordinateTable({ title, labels, rows, regionName }: { title: string; labels: string[]; rows: string[][]; regionName: string }) {
  return <div className="min-w-0">
    <h4 className="text-sm font-medium">{title}</h4>
    <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" tabIndex={0} role="region" aria-label={regionName}>
      <table className="w-full min-w-[19rem] text-right text-xs tabular-nums">
        <caption className="sr-only">{title}: exact source coordinate lexemes.</caption>
        <thead><tr><th scope="col" className="py-2 pr-3 text-left">{regionName.startsWith("Lattice") ? "Vector" : "Site"}</th>{["x", "y", "z"].map(axis => <th scope="col" className="px-2 py-2 font-medium" key={axis}>{axis}</th>)}</tr></thead>
        <tbody>{rows.map((values, index) => <tr key={index}>
          <th scope="row" className="py-2 pr-3 text-left font-medium">{labels[index]}</th>
          {values.map((value, coordinate) => <td key={coordinate} className="px-2 py-2 font-mono">{value}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}

export function MaterialComputationalNativeOutput({ data, additionalInputContext }: { data: ComputationalNativeOutput | null; additionalInputContext?: ComputationalInputContext | null }) {
  if (!data) return <p role="status" className="text-sm text-sage-muted">Complete native output metadata is unavailable.</p>;
  const geometry = data.reported_final_geometry;
  const inputs = [
    ...data.native_inputs.map(input => ({ ...input, raw_lexeme: input.raw_scalar_lexeme, role: null as string | null, text_content_sha256: null as string | null })),
    ...(additionalInputContext?.native_inputs ?? []),
  ];
  const tagCount = new Set(inputs.map(input => input.native_tag)).size;
  return <section className="min-w-0 space-y-4" aria-labelledby="nomad-final-structure-heading">
    <div className="space-y-2">
      <h3 id="nomad-final-structure-heading" className="text-base font-semibold">Reported final structure</h3>
      <p className="text-sm leading-6">Complete native XML with three calculation blocks and three reported sites. Finalpos coordinates match the last calculation.</p>
      <p className="text-xs leading-5 text-sage-muted">Convergence has not been independently assessed. Experimental sample and material-state associations remain unresolved.</p>
    </div>
    <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
      <CoordinateTable title="Basis (Å, documented convention)" labels={["a₁", "a₂", "a₃"]} rows={geometry.basis_raw_lexemes} regionName="Lattice basis, horizontally scrollable" />
      <CoordinateTable title="Positions (fractional/direct)" labels={geometry.atom_labels_in_source_order.map((label, index) => `${index + 1} · ${label}`)} rows={geometry.positions_raw_lexemes} regionName="Reported atomic positions, horizontally scrollable" />
    </div>
    <p className="text-xs leading-5 text-sage-muted">Units follow the <SourceLink url="https://vasp.at/wiki/Vasprun.xml">current VASP format documentation</SourceLink>. The captured basis and positions have no explicit XML unit attributes; the original VASP 5.3.2 documentation edition was not checked. Historical archive units retain their earlier unresolved status.</p>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Full-source input settings ({tagCount} tags)</summary>
      <p className="mt-3 text-xs leading-5 text-sage-muted">{inputs.length} source occurrences from one computed entry retain their exact values and separate contexts. PSTRESS is a model input; its value does not assign a Tc measurement pressure.</p>
      {additionalInputContext === null && <p role="status" className="mt-2 text-xs text-sage-muted">Additional input-context metadata is unavailable. The earlier complete-source settings remain available below.</p>}
      <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" tabIndex={0} role="region" aria-label="Full native input contexts, horizontally scrollable">
        <table className="w-full min-w-[29rem] text-left text-xs">
          <caption className="sr-only">{tagCount} reported native input tags and {inputs.length} source occurrences; repeated tags remain separate contexts.</caption>
          <thead><tr>{["Tag", "Exact value", "Source context"].map(label => <th key={label} scope="col" className="py-2 pr-4 font-medium">{label}</th>)}</tr></thead>
          <tbody>{inputs.map(input => <tr className="align-top" key={input.source_xpath}>
            <th scope="row" className="py-2 pr-4 font-mono font-medium">{input.native_tag}</th>
            <td className="whitespace-pre-wrap break-words py-2 pr-4 font-mono">{input.raw_lexeme}</td>
            <td className="py-2"><span>{inputContextLabel(input.source_context)}</span><details className="mt-1"><summary className="w-fit cursor-pointer text-accent-deep">XML source path</summary><p className="mt-1 break-all font-mono">{input.source_xpath}</p><p className="mt-1">XML type: {input.declared_xml_type ?? "Not declared"}.</p>{input.role && <p className="mt-2 leading-5 text-sage-muted">{input.role}</p>}{input.text_content_sha256 && <p className="mt-2 break-all font-mono">Element text SHA-256: {input.text_content_sha256}</p>}</details></td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-5 text-sage-muted">ENCUT was not observed in the complete captured XML. ENMAX remains a separate tag; no default cutoff is supplied.</p>
      {additionalInputContext && <div className="mt-5"><MaterialComputationalInputContext data={additionalInputContext} /></div>}
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Parameter differences and energy channels</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
        <p>ISTART is 1 in INCAR and 0 in electronic-startup parameters. NELM is 60 in electronic convergence and 1 in response functions.</p>
        {additionalInputContext && <p>ICHARG is 1 in both INCAR and electronic-startup parameters. The captured packet does not establish original restart-file identities or resolve the ISTART context difference.</p>}
        <p>Ionic-summary and last-electronic energy channels remain separate. A corrected final energy and a convergence conclusion have not been assigned.</p>
        {(["last_ionic", "last_electronic"] as const).map(channel => <div className="min-w-0" key={channel}>
          <h4 className="font-medium text-sage-ink">{channel === "last_ionic" ? "Last ionic summary" : "Last electronic iteration"}</h4>
          <dl className="mt-2 space-y-2">{data.native_energy_channels[channel].map(field => <div key={field.source_xpath}>
            <dt className="font-mono">{field.native_tag}</dt><dd className="font-mono">{field.raw_scalar_lexeme}</dd><dd className="break-all font-mono text-[11px]">{field.source_xpath}</dd>
          </div>)}</dl>
        </div>)}
      </div>
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Complete-source provenance and metadata</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
        <p>Captured on 2 October 2026: 3,835,451 bytes, HTTP EOF observed, full XML parsed. The first 2 MiB exactly match the earlier captured prefix.</p>
        <p>Indexed entry metadata agreed before and after the download. Its 2021 processing timestamp differs from the earlier archive projection's 2023 timestamp; the historical archive hash was not reverified.</p>
        <SourceLink url="https://nomad-lab.eu/prod/v1/api/v1/entries/0dTJ0oCkwgt1xEV8EcXKIV8k9Zjq/raw/vasprun.xml">Original native XML at NOMAD</SourceLink>
        <p className="break-all font-mono">Complete native source SHA-256: {computationalNativeOutputSourceSha256}</p>
        <p>This is additional source metadata for the same independent computed entry. Potential-file identity, numerical convergence, experiment correspondence, Tc and EPC remain unresolved.</p>
        <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} role="region" aria-label="Complete native output metadata JSON">{JSON.stringify(data, null, 2)}</pre>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          <a href={computationalNativeOutputMetadataPath} className="site-text-link" download>Download complete-source JSON</a>
          <a href={`${computationalNativeOutputMetadataPath}.sha256`} className="site-text-link" download>Complete-source SHA-256</a>
        </div>
        <p className="break-all font-mono">Metadata resource SHA-256: {computationalNativeOutputSnapshotSha256}</p>
      </div>
    </details>
  </section>;
}
