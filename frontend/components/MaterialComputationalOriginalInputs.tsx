import {
  computationalOriginalInputsHref, computationalOriginalInputsMetadataPath, computationalOriginalInputsSnapshotSha256,
  type ComputationalOriginalInputs, type OriginalInputLine,
} from "@/lib/material-computational-original-inputs";

function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = computationalOriginalInputsHref(url);
  return href ? <a className="site-text-link" href={href} target="_blank" rel="noopener noreferrer">{children}</a> : null;
}
function LineLocator({ line }: { line: OriginalInputLine }) {
  return <details className="mt-1 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Source line {line.line}</summary>
    <p className="mt-2">Original line bytes {line.byte_start_inclusive}–{line.byte_end_exclusive} (end exclusive, including the line ending).</p>
    <p className="mt-1 break-all font-mono">Line SHA-256: {line.line_sha256}</p>
  </details>;
}
function GeometryRows({ title, rows, labels, name }: { title: string; rows: ComputationalOriginalInputs["poscar"]["basis_rows"]; labels: string[]; name: string }) {
  return <div className="min-w-0">
    <h4 className="text-sm font-medium">{title}</h4>
    <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label={name}>
      <table className="w-full min-w-[24rem] text-right text-xs tabular-nums">
        <caption className="sr-only">{title}, using the original POSCAR numeric lexemes.</caption>
        <thead><tr><th scope="col" className="py-2 pr-3 text-left">Input row</th>{["x", "y", "z"].map(axis => <th scope="col" className="px-2 py-2 font-medium" key={axis}>{axis}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.source_line.line} className="align-top">
          <th scope="row" className="py-2 pr-3 text-left font-medium">{labels[index]}<LineLocator line={row.source_line} /></th>
          {row.raw_lexeme.split(/\s+/).map((token, axis) => <td className="px-2 py-2 font-mono" key={axis}>{token}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}

export function MaterialComputationalOriginalInputs({ data }: { data: ComputationalOriginalInputs | null }) {
  if (!data) return <p role="status" className="text-sm text-sage-muted">Original input-file metadata is unavailable.</p>;
  const pos = data.poscar, mesh = data.kpoints;
  const summaries: Record<string, string> = {
    INCAR: "19 original control assignments", POSCAR: "B / Cr labels · 2 / 1 ions · direct input positions",
    KPOINTS: `Gamma · ${mesh.mesh_lexemes.join(" × ")}`,
  };
  return <section className="min-w-0 space-y-3 border-t border-sage-border pt-5" aria-labelledby="nomad-original-inputs-heading">
    <h3 id="nomad-original-inputs-heading" className="text-base font-semibold">Original input files</h3>
    <p className="text-xs leading-5 text-sage-muted">Three auxiliary files recovered from the same NOMAD entry directory on 4 October 2026. Directory membership and source agreement do not establish every effective runtime control.</p>
    <dl className="grid gap-x-5 gap-y-3 text-sm sm:grid-cols-[minmax(7rem,1fr)_minmax(0,4fr)]">{data.source_files.map(file => <div className="contents" key={file.name}>
      <dt className="font-mono font-medium"><SourceLink url={file.source_url}>{file.name}</SourceLink></dt>
      <dd className="min-w-0 break-words">{summaries[file.name]}<span className="ml-2 text-xs text-sage-muted">{file.source_bytes} bytes</span></dd>
    </div>)}</dl>
    <p className="text-xs leading-5 text-amber-800">LORBIT differs between the original INCAR and XML. Its effective runtime value remains unresolved.</p>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Read original input values</summary>
      <div className="mt-3 space-y-5">
        <div className="min-w-0">
          <h4 className="text-sm font-medium">INCAR controls</h4>
          <p className="mt-2 text-xs leading-5 text-sage-muted">Values retain the original file spelling and repetition syntax. Units and effective runtime roles have not been assigned here.</p>
          <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label="Original INCAR controls, horizontally scrollable">
            <table className="w-full min-w-[29rem] text-left text-xs">
              <caption className="sr-only">19 original INCAR assignments, with separate frozen XML source contexts.</caption>
              <thead><tr>{["Original tag", "Exact original value", "Source and XML comparison"].map(label => <th className="py-2 pr-4 font-medium" scope="col" key={label}>{label}</th>)}</tr></thead>
              <tbody>{data.incar_controls.map(control => <tr key={control.tag} className="align-top">
                <th scope="row" className="py-2 pr-4 font-mono font-medium">{control.tag}</th>
                <td className="whitespace-pre-wrap break-words py-2 pr-4 font-mono">{control.raw_value_lexeme}</td>
                <td className="py-2"><LineLocator line={control.source_line} /><details className="mt-1"><summary className="w-fit cursor-pointer text-accent-deep">Frozen XML contexts</summary>
                  {control.frozen_xml_occurrences.length ? <dl className="mt-2 space-y-3">{control.frozen_xml_occurrences.map(context => <div key={context.xpath}>
                    <dt className="break-all font-mono">{context.xpath}</dt><dd className="whitespace-pre-wrap break-words font-mono">{context.raw_text}</dd><dd>XML type: {context.native_type_attribute ?? "Not declared"}.</dd>
                  </div>)}</dl> : <p className="mt-2">No same-name element was observed in the complete frozen XML.</p>}
                </details></td>
              </tr>)}</tbody>
            </table>
          </div>
        </div>
        <div className="min-w-0 space-y-3">
          <h4 className="text-sm font-medium">POSCAR input structure</h4>
          <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-3">{[["Scale", pos.scale], ["Species-name line", pos.species_names], ["Ions per species", pos.ions_per_species]].map(([label, value]) => {
            const item = value as typeof pos.scale;
            return <div key={label as string}><dt className="text-sage-muted">{label as string}</dt><dd className="font-mono">{item.raw_lexeme}<LineLocator line={item.source_line} /></dd></div>;
          })}</dl>
          <p className="text-xs leading-5 text-sage-muted">Species labels follow lines 6 and 7; the header comment is not used. Runtime species and potential-file identity have not been validated.</p>
          <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-2">
            <GeometryRows title="Input basis (source lexemes)" rows={pos.basis_rows} labels={["a₁", "a₂", "a₃"]} name="Original input basis, horizontally scrollable" />
            <GeometryRows title="Input positions (direct)" rows={pos.position_rows} labels={pos.source_species_labels_in_order.map((label, index) => `${index + 1} · ${label}`)} name="Original input positions, horizontally scrollable" />
          </div>
          <p className="text-xs leading-5 text-sage-muted">Written numeric values agree with XML initialpos; their precision differs. The input basis differs from the reported final structure above. Current POSCAR conventions use the scale with basis components in Å and direct positions as fractional; the historical documentation edition remains unverified.</p>
        </div>
        <div className="min-w-0">
          <h4 className="text-sm font-medium">KPOINTS source lines</h4>
          <dl className="mt-2 grid gap-x-5 gap-y-2 text-xs sm:grid-cols-2">{[["Generation control", mesh.number_line], ["Centering", mesh.generation_mode], ["Mesh subdivisions", mesh.mesh], ["Shift", mesh.shift]].map(([label, value]) => {
            const item = value as typeof mesh.mesh;
            return <div key={label as string}><dt className="text-sage-muted">{label as string}</dt><dd className="font-mono">{item.raw_lexeme}<LineLocator line={item.source_line} /></dd></div>;
          })}</dl>
          <p className="mt-2 text-xs leading-5 text-sage-muted">The subdivisions agree numerically with frozen XML generation inputs. Effective irreducible sampling and mesh convergence have not been assessed.</p>
        </div>
      </div>
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Original input and XML differences</summary>
      <dl className="mt-3 space-y-4 text-xs leading-5">{data.source_differences.map(item => <div key={item.id}>
        <dt className="font-mono font-medium">{item.id}</dt><dd>Original INCAR line {item.original_line}: <code>{item.original_input}</code></dd><dd className="whitespace-pre-wrap break-words">XML contexts: {item.XML_values.join(" / ")}</dd><dd className="mt-1 text-sage-muted">{item.interpretation}</dd>
      </div>)}</dl>
      <dl className="mt-4 space-y-3 text-xs leading-5 text-sage-muted">{data.interpretation_limits.map(item => <div key={item.id}><dt className="font-medium text-sage-ink">{item.id === "restart_and_potential" ? "Remaining reproduction evidence" : item.id}</dt><dd>{item.evidence}</dd></div>)}</dl>
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Input-file provenance and downloads</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
        <p>Three recovered files and 19 original control assignments belong to one computed entry. They overlap the XML inputs and add no independent experiments or formal catalogue properties.</p>
        <p>{data.snapshot_scope}</p><p>{data.locator_convention}</p>
        <dl className="space-y-3">{data.source_files.map(file => <div key={file.name}><dt className="font-mono font-medium text-sage-ink">{file.name}</dt><dd className="break-all font-mono">{file.provider_path}</dd><dd className="break-all font-mono">Original file SHA-256: {file.source_sha256}</dd></div>)}</dl>
        <p>NOMAD reports the entry published, unembargoed and licensed {data.entry_capture.license_as_reported}. This download contains selected source values and provenance; complete original file bodies are available through the provider links.</p>
        <p>{data.provider_inventory.capture_scope} <SourceLink url={data.provider_inventory.source_url}>Open provider directory metadata</SourceLink></p>
        <p>{data.file_relationship_scope.scope} <SourceLink url={data.file_relationship_scope.documentation_url}>NOMAD file relationships</SourceLink></p>
        <dl className="space-y-3">{data.format_annotations.map(annotation => <div key={annotation.file}><dt className="font-medium text-sage-ink"><SourceLink url={annotation.url}>Current {annotation.file} format</SourceLink> · observed revision {annotation.observed_revision_id}</dt><dd>{annotation.documented_convention}</dd><dd>{annotation.role}</dd></div>)}</dl>
        <div className="flex flex-wrap gap-x-4 gap-y-2"><a className="site-text-link" href={computationalOriginalInputsMetadataPath} download>Download original-input metadata JSON</a><a className="site-text-link" href={`${computationalOriginalInputsMetadataPath}.sha256`} download>Original-input metadata SHA-256</a></div>
        <p className="break-all font-mono">Metadata SHA-256: {computationalOriginalInputsSnapshotSha256}</p>
        <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" role="region" tabIndex={0} aria-label="Original input-file metadata JSON">{JSON.stringify(data, null, 2)}</pre>
      </div>
    </details>
  </section>;
}
