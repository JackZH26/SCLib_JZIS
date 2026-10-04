import {
  archiveReferenceField, archiveReferenceRole, archiveReferenceValue, computationalReferenceHref,
  computationalReferenceMetadataPath, computationalReferenceSnapshotSha256,
  type ArchiveReferenceField, type ComputationalReference, type NativeReferenceInput, type NativeTagDocumentationAnnotation,
} from "@/lib/material-computational-reference";
import { type ComputationalNativeOutput } from "@/lib/material-computational-native-output";
import { type ComputationalInputContext } from "@/lib/material-computational-input-context";
import { MaterialComputationalNativeOutput } from "@/components/MaterialComputationalNativeOutput";

const sourceDate = (value: string) => new Date(value).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" });
function PublicSourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = computationalReferenceHref(url);
  return href ? <a href={href} className="site-text-link" target="_blank" rel="noopener noreferrer">{children}</a> : null;
}
function ArchiveLocator({ field }: { field: ArchiveReferenceField | null }) {
  if (!field) return null;
  return <details className="mt-1 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Archive field source</summary>
    <dl className="mt-2 space-y-1 break-words">
      <div><dt className="inline font-medium">Role: </dt><dd className="inline">{archiveReferenceRole[field.role]}</dd></div>
      <div><dt className="inline font-medium">Original archive pointer: </dt><dd className="inline break-all font-mono">{field.original_archive_pointer}</dd></div>
      <div><dt className="inline font-medium">Projection {field.response_number} pointer: </dt><dd className="inline break-all font-mono">{field.response_pointer}</dd></div>
      <div><dt className="inline font-medium">Response SHA-256: </dt><dd className="inline break-all font-mono">{field.response_sha256}</dd></div>
    </dl>
    {field.limitation && <p className="mt-2">{field.limitation}</p>}
  </details>;
}
function NativeLocator({ field, unitSourceUrl, annotation }: { field: NativeReferenceInput; unitSourceUrl?: string; annotation?: NativeTagDocumentationAnnotation }) {
  return <details className="mt-1 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Native input source</summary>
    <p className="mt-2">Input metadata in the incomplete source prefix. Present in {field.source_blocks_reported.join(" and ")}.</p>
    <p className="mt-2">{annotation?.limitation ?? inputNotes[field.native_tag]}</p>
    {unitSourceUrl && <div className="mt-2"><PublicSourceLink url={unitSourceUrl}>Official EDIFF unit definition</PublicSourceLink></div>}
    {annotation && <div className="mt-2 space-y-1">
      <p>Documented native-tag definition: {annotation.documented_meaning}{annotation.documented_unit ? `; unit ${annotation.documented_unit}` : ""}.</p>
      <PublicSourceLink url={annotation.source.url}>Official {field.native_tag} tag definition</PublicSourceLink>
      <p>Observed revision ID {annotation.source.observed_revision_id}. Capture kind: rendered page text; original HTML response hash not established.</p>
      <p className="break-all font-mono">Rendered page text capture SHA-256: {annotation.source.page_text_capture_sha256}</p>
    </div>}
    <dl className="mt-2 space-y-2">{field.occurrences.map(occurrence => <div key={occurrence.source_block}>
      <dt className="font-medium">{occurrence.source_block}</dt>
      <dd>Scalar bytes {occurrence.scalar_byte_span_zero_based_half_open.join("-")}; UTF-8 characters {occurrence.scalar_utf8_character_span_zero_based_half_open.join("-")} (end exclusive).</dd>
      <dd>Original XML type: {occurrence.declared_xml_type ?? "Not declared; decimal lexeme retained as a string"}.</dd>
      <dd className="break-all font-mono">Literal element SHA-256: {occurrence.literal_element_sha256}</dd>
    </div>)}</dl>
  </details>;
}

function ArchiveSummary({ data }: { data: ComputationalReference }) {
  const field = (id: string) => archiveReferenceField(data, id);
  const grid = field("k_mesh_grid")!;
  const gridValue = Array.isArray(grid.raw_value) ? grid.raw_value.join(" × ") : archiveReferenceValue(grid);
  const rows: [string, string, ArchiveReferenceField | null][] = [
    ["Software", `${archiveReferenceValue(field("program_name"))} 5.3.2`, field("program_version")],
    ["Electronic method", "DFT, PBE (GGA_C_PBE + GGA_X_PBE)", field("xc_functional_name")],
    ["Reported k mesh", `${archiveReferenceValue(field("k_mesh_sampling_method"))}, ${gridValue}`, grid],
    ["Reported mesh points", archiveReferenceValue(field("k_mesh_n_points")), field("k_mesh_n_points")],
    ["Basis and core treatment", `${archiveReferenceValue(field("basis_set_type"))}; ${archiveReferenceValue(field("core_electron_treatment"))}`, field("basis_set_type")],
    ["Source workflow", `Cell-shape optimization (${archiveReferenceValue(field("workflow_type"))}), ${archiveReferenceValue(field("workflow_optimization_steps"))} reported steps`, field("workflow_type")],
  ];
  return <section className="min-w-0" aria-labelledby="nomad-method-heading">
    <h3 id="nomad-method-heading" className="text-base font-semibold">Reported archive method</h3>
    <table className="mt-3 w-full table-fixed text-left text-sm">
      <caption className="sr-only">Selected archive metadata for one independent calculated B2Cr entry.</caption>
      <tbody>{rows.map(([label, value, source]) => <tr className="align-top" key={label}>
        <th scope="row" className="w-[35%] py-3 pr-4 font-medium">{label}</th>
        <td className="min-w-0 break-words py-3">{value}<ArchiveLocator field={source} /></td>
      </tr>)}</tbody>
    </table>
    <p className="mt-2 text-xs leading-5 text-sage-muted">Mesh and workflow flags are reported metadata. Independent numerical convergence and a validated final geometry have not been established.</p>
    <details className="mt-3 text-xs leading-5 text-sage-muted">
      <summary className="w-fit cursor-pointer text-accent-deep">Input and output structure references</summary>
      <p className="mt-2">Workflow input system 0 and calculation-linked output system 2 differ. Workflow result calculation 2 references method 0 and system 2.</p>
      <p className="mt-2">Projection 2 compacts the selected original system 2 to response array index 0. Original archive indices are preserved in the field pointers. Raw coordinate arrays remain unit-unresolved source metadata.</p>
      <p className="mt-2 break-all font-mono">Input: {data.reference.calculation_bindings.workflow_input_structure_ref}<br />Calculation: {data.reference.calculation_bindings.workflow_result_ref}<br />Output: {data.reference.calculation_bindings.system_ref}</p>
    </details>
  </section>;
}

const inputNotes: Record<string, string> = {
  EDIFF: "Native SCF stopping parameter. Its eV unit is documented for this native tag; legacy archive units remain unresolved.",
  ISPIN: "Original input integer. It does not establish magnetic order or a measured magnetic state.",
  LSORBIT: "Original logical F; no magnetic-order or experimental interpretation is assigned.",
  LNONCOLLINEAR: "Original logical F, preserved separately from the DOS flag.",
  ISMEAR: "Original input code. A smearing-method interpretation was not established in the checked documentation scope.",
  SIGMA: "Original decimal input. Its physical unit is unresolved in this checked scope; it is not a measured temperature.",
  PSTRESS: "Original model input with unresolved unit. This is not a Tc measurement pressure or a 0 GPa assignment.",
  ENAUG: "Original decimal input with unresolved unit. It does not assign a unit to the archive cutoff values.",
};
function NativeInputs({ data, completeSourceAvailable = false }: { data: ComputationalReference; completeSourceAvailable?: boolean }) {
  return <section className="min-w-0" aria-labelledby="nomad-native-heading">
    <h3 id="nomad-native-heading" className="text-base font-semibold">{completeSourceAvailable ? "Earlier prefix input settings" : "Original input settings, partial source"}</h3>
    <p className="mt-2 text-xs leading-5 text-sage-muted">{completeSourceAvailable
      ? "This earlier snapshot checked INCAR and parameters inside a 2 MiB prefix. The separate complete-source projection above retains additional contexts; the earlier metadata bytes remain unchanged."
      : "Only complete INCAR and parameters subtrees inside a 2 MiB prefix were checked. The whole XML is incomplete; the final calculation was not inspected."}</p>
    <div className="mt-3 max-w-full overflow-x-auto rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" tabIndex={0} role="region" aria-label="Native VASP input settings, horizontally scrollable">
      <table className="w-full min-w-[24rem] text-left text-sm tabular-nums">
        <caption className="sr-only">Eight literal native input tags with exact source precision, units and interpretation boundaries.</caption>
        <thead><tr>{["Native tag", "Exact source value", "Type / unit / definition"].map(label => <th key={label} scope="col" className="py-2 pr-4 font-medium">{label}</th>)}</tr></thead>
        <tbody>{data.native_inputs.map(field => {
          const annotation = data.native_tag_documentation_annotations.find(item => item.native_tag === field.native_tag);
          const unit = annotation?.documented_unit ?? field.unit;
          const declaredType = field.occurrences[0]?.declared_xml_type;
          const typeCue = declaredType === "int" ? "Integer code" : declaredType === "logical" ? "Logical flag" : null;
          return <tr key={field.native_tag} className="align-top">
          <th scope="row" className="w-[25%] py-3 pr-4 font-mono font-medium">{field.native_tag}</th>
          <td className="w-[45%] py-3 pr-4"><span className="font-mono font-medium">{field.raw_scalar_lexeme}</span>{field.native_tag === "PSTRESS" && <span className="mt-1 block text-xs text-sage-muted">Model input, not Tc pressure</span>}<NativeLocator field={field} annotation={annotation} unitSourceUrl={field.native_tag === "EDIFF" ? data.native_EDIFF_unit_source.url : undefined} /></td>
          <td className="py-3 text-xs leading-5 text-sage-muted">{unit ?? typeCue ?? "Unit unresolved"}{annotation && !unit && <span className="mt-1 block">{annotation.documented_meaning}</span>}{(annotation || field.unit) && <span className="mt-1 block">Native-tag documentation</span>}</td>
        </tr>;
        })}</tbody>
      </table>
    </div>
    <p className="mt-3 text-xs leading-5 text-sage-muted">Documented tag units and definitions annotate the original inputs. They do not establish legacy archive units or a historical VASP 5.3.2 documentation edition.</p>
    <p className="mt-3 text-xs leading-5 text-sage-muted"><strong>ENCUT:</strong> not found in the two complete checked blocks. No default, alternate cutoff or absence elsewhere is inferred.</p>
    <p className="mt-2 text-xs leading-5 text-sage-muted"><strong>DOS spin flag:</strong> normalized archive DOS metadata reports <span className="font-mono">true</span>. This is separate from native <span className="font-mono">ISPIN 2</span> and does not establish input settings on its own or physical magnetic order.</p>
  </section>;
}

function PotentialLabels({ data }: { data: ComputationalReference }) {
  return <section className="min-w-0" aria-labelledby="nomad-potential-heading">
    <h3 id="nomad-potential-heading" className="text-base font-semibold">Native potential labels</h3>
    <table className="mt-3 w-full table-fixed text-left text-sm">
      <caption className="sr-only">Two native atomtypes dataset labels, with no potential file identity claim.</caption>
      <thead><tr><th scope="col" className="w-[30%] py-2 pr-3 font-medium">Element</th><th scope="col" className="py-2 font-medium">Original label and date string</th></tr></thead>
      <tbody>{data.native_potential_labels.map(row => <tr key={row.element_label} className="align-top"><th scope="row" className="py-3 pr-3 font-medium">{row.element_label}</th><td className="break-words py-3 font-mono text-xs">{row.dataset_label_literal}</td></tr>)}</tbody>
    </table>
    <p className="mt-2 text-xs leading-5 text-sage-muted">Atomtypes report 2 B and 1 Cr. Dataset labels and valence lexemes are input metadata; POTCAR bytes, hashes, license and availability remain unestablished. These labels do not prove reproduction.</p>
  </section>;
}

function SourceProvenance({ data, completeSourceAvailable = false }: { data: ComputationalReference; completeSourceAvailable?: boolean }) {
  const origin = data.reference.source_origin;
  return <details className="min-w-0 text-xs leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">{completeSourceAvailable ? "Earlier archive and prefix provenance" : "Source identity, capture and remaining units"}</summary>
    <div className="mt-3 space-y-3">
      <dl className="space-y-1">
        <div><dt className="inline font-medium">Entry: </dt><dd className="inline break-all font-mono">{data.reference.entry_id}</dd></div>
        <div><dt className="inline font-medium">Upload: </dt><dd className="inline break-all font-mono">{data.reference.upload_id}</dd></div>
        <div><dt className="inline font-medium">Entry hash reported by NOMAD: </dt><dd className="inline break-all font-mono">{origin.entry_hash}</dd></div>
        <div><dt className="inline font-medium">Original mainfile locator: </dt><dd className="inline break-all font-mono">{origin.mainfile}</dd></div>
        <div><dt className="inline font-medium">Software build: </dt><dd className="inline break-words">{data.software_consistency.archive_program_version_raw}</dd></div>
        <div><dt className="inline font-medium">NOMAD processing version: </dt><dd className="inline break-words">{origin.nomad_processing_version}</dd></div>
        <div><dt className="inline font-medium">Reported last processing: </dt><dd className="inline">{sourceDate(origin.last_processing_time)}</dd></div>
      </dl>
      <p>Captured on {sourceDate(data.native_source.requested_at_utc)}. Selected entry metadata and the entry hash agreed before and after the archive projections. This does not establish an atomic snapshot across projections, historical-summary byte equivalence or current download equivalence.</p>
      <p>NOMAD reported the entry published, unembargoed and licensed {origin.license_reported_by_entry}. This page contains selected metadata only; original raw archive, XML and documentation bodies are not redistributed.</p>
      <p className="break-all font-mono">Incomplete native prefix SHA-256: {data.native_source.source_prefix_sha256}</p>
      <dl className="space-y-2">{["basis_cutoff_valence", "basis_cutoff_augmentation", "scf_energy_change_threshold"].map(id => {
        const field = archiveReferenceField(data, id)!;
        return <div key={id}><dt className="font-medium">{id.replaceAll("_", " ")}</dt><dd className="font-mono">{archiveReferenceValue(field)} (unit unresolved)</dd><dd><ArchiveLocator field={field} /></dd></div>;
      })}</dl>
      <p>The native generator version/build/platform matches the archive software version after declared whitespace joining. Its date/time strings establish no timezone, publication time or successful completion.</p>
      <p>The additional SIGMA, ENAUG, PSTRESS and ISMEAR definitions were captured as rendered page text. Original HTML response hashes were not established; four direct revision requests returned 403. These annotations do not prove historical edition correspondence or effective run parameter use.</p>
    </div>
  </details>;
}

export function MaterialComputationalReference({ data, nativeOutput, additionalInputContext }: { data: ComputationalReference | null; nativeOutput?: ComputationalNativeOutput | null; additionalInputContext?: ComputationalInputContext | null }) {
  if (!data) return <p role="status" className="text-sm text-sage-muted">Captured computational reference metadata is unavailable.</p>;
  return <article className="min-w-0 space-y-6 rounded-lg border border-sage-border bg-white p-4 sm:p-5" aria-labelledby="crb2-computed-heading">
    <div className="space-y-2">
      <h2 id="crb2-computed-heading" className="text-xl font-semibold">CrB₂: independent computed reference</h2>
      <p className="max-w-4xl text-sm leading-6 text-sage-muted">NOMAD composition B2Cr. This is one independent computed entry, with no selected superconducting result, physical sample or material-state association.</p>
      <PublicSourceLink url={data.reference.entry_url}>Open NOMAD entry</PublicSourceLink>
    </div>
    {nativeOutput !== undefined && <MaterialComputationalNativeOutput data={nativeOutput} additionalInputContext={additionalInputContext} />}
    <ArchiveSummary data={data} />
    {nativeOutput ? <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Earlier prefix input snapshot</summary>
      <div className="mt-3"><NativeInputs data={data} completeSourceAvailable /></div>
    </details> : <NativeInputs data={data} />}
    <PotentialLabels data={data} />
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">{nativeOutput ? "Earlier snapshot gaps and current limits" : "Missing fields and checked scope"}</summary>
      {nativeOutput && <p className="mt-3 text-xs leading-5 text-sage-muted">The entries below describe the earlier archive and 2 MiB prefix captures. Complete-source geometry and input contexts are shown above; the earlier metadata remains a separate historical snapshot.</p>}
      <dl className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">{data.unresolved.map(item => <div key={item.field}><dt className="font-semibold">{item.field}</dt><dd>{item.reason}</dd></div>)}</dl>
      <p className="mt-3 text-xs leading-5 text-sage-muted">Native spin/occupation inputs supplement the earlier archive-only absence checks. Their source scopes remain separate. No new calculation, canonical promotion, scientific acceptance or ML training approval is granted.</p>
    </details>
    <SourceProvenance data={data} completeSourceAvailable={Boolean(nativeOutput)} />
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">{nativeOutput ? "Earlier reference metadata (JSON)" : "View computational reference metadata (JSON)"}</summary>
      <p className="mt-2 text-xs leading-5 text-sage-muted">Archive fields, native input settings and potential-label rows overlap. They are evidence groups for one entry, not counts of distinct properties or independent experiments. Raw coordinate arrays are unvalidated, unit-unresolved archive metadata.</p>
      <pre className="mt-3 max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" tabIndex={0} role="region" aria-label="Computational reference metadata JSON">{JSON.stringify(data, null, 2)}</pre>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs">
        <a href={computationalReferenceMetadataPath} className="site-text-link">Static metadata JSON resource</a>
        <a href={`${computationalReferenceMetadataPath}.sha256`} className="site-text-link" download>Download SHA-256</a>
      </div>
      <p className="mt-2 break-all font-mono text-xs text-sage-muted">Static resource SHA-256: {computationalReferenceSnapshotSha256}</p>
    </details>
  </article>;
}
