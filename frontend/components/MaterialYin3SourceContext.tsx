import {
  yin3SourceContextHref, yin3SourceContextMetadataPath, yin3SourceContextSnapshotSha256, type Yin3SourceContext,
} from "@/lib/material-yin3-source-context";

type Expression = { raw_value?: string; raw_values?: string[]; raw_unit?: string; raw_lexeme?: string; context?: string; criterion?: string; role?: string; method?: string };
const expressionValue = (value: Expression) => value.raw_lexeme ?? `${value.raw_values?.join(" – ") ?? value.raw_value ?? ""}${value.raw_unit ? " " + value.raw_unit : ""}`;
const methodLabel = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

function SourceLocations({ data, refs }: { data: Yin3SourceContext; refs: string[] }) {
  return <details className="mt-3 min-w-0 text-xs font-normal leading-5 text-sage-muted">
    <summary className="w-fit cursor-pointer text-accent-deep">Source locations</summary>
    <dl className="mt-2 space-y-3">{[...new Set(refs)].map(id => {
      const locator = data.source_locators[id as keyof Yin3SourceContext["source_locators"]];
      const href = locator && yin3SourceContextHref(locator.source_url);
      return locator ? <div key={id}>
        <dt className="font-medium text-sage-ink">{href && <a className="site-text-link" href={href} target="_blank" rel="noopener noreferrer">arXiv:1112.3083v1 · {id}</a>}</dt>
        <dd>Original HTML lines {locator.native_html_lines.start}–{locator.native_html_lines.end} (inclusive); bytes {locator.native_html_utf8_byte_span.start}–{locator.native_html_utf8_byte_span.end} (end exclusive).</dd>
        <dd className="break-all font-mono">Original fragment SHA-256: {locator.native_fragment_sha256}</dd>
      </div> : null;
    })}</dl>
  </details>;
}

export function MaterialYin3SourceContext({ data }: { data: Yin3SourceContext | null }) {
  if (!data) return <p role="status" className="text-sm text-sage-muted">Captured YIn₃ source context is unavailable.</p>;
  const observation = (id: string) => data.observations.find(item => item.id === id)!;
  const expressions = (id: string): Expression[] => observation(id).raw_expressions ?? [];
  const onsets = observation("sample-b-discussion-onsets"), interpretation = observation("author-mechanism-interpretation");
  const rows: [string, string, string, string][] = [
    ...expressions("sample-a-resistivity-context").map(value => ["A", "Resistivity", expressionValue(value), value.criterion === "transition_drop_begins" ? "Approximate drop beginning" : "Completion bound"] as [string, string, string, string]),
    ...expressions("sample-b-resistivity-interval").map(value => ["B", "Resistivity", expressionValue(value), "Printed transition interval, source order"] as [string, string, string, string]),
    ...expressions("sample-b-susceptibility-contexts").map(value => ["B", "Susceptibility", expressionValue(value), value.context?.startsWith("Figure") ? "Figure 1 caption · sharp jump" : value.context?.startsWith("Discussion") ? "Discussion · onset" : value.criterion === "drop_onset" ? "Results · drop onset" : "Results · fully superconducting by"] as [string, string, string, string]),
    ...expressions("sample-b-heat-capacity-method-and-feature").filter(value => value.role === "feature_temperature" || value.criterion === "onset")
      .map(value => ["B", "Heat capacity", expressionValue(value), value.role === "feature_temperature" ? "Results · feature temperature" : "Discussion · onset"] as [string, string, string, string]),
  ];
  return <article className="min-w-0 space-y-6" aria-labelledby="yin3-onsets-heading">
    <section className="min-w-0">
      <h2 id="yin3-onsets-heading" className="text-xl font-semibold">Sample B: method-specific onsets</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-sage-muted">The Discussion reports three onsets for sample B. Measurement and preparation contexts remain separate.</p>
      <table className="mt-3 w-full table-fixed text-left text-sm tabular-nums">
        <caption className="sr-only">Three source-reported onset temperatures for sample B.</caption>
        <thead><tr><th scope="col" className="w-[58%] py-2 pr-4 font-medium">Method</th><th scope="col" className="py-2 font-medium">Reported onset</th></tr></thead>
        <tbody>{expressions(onsets.id).map(value => <tr key={value.method}><th scope="row" className="py-3 pr-4 font-medium">{methodLabel(value.method!)}</th><td className="py-3">{expressionValue(value)}</td></tr>)}</tbody>
      </table>
      <SourceLocations data={data} refs={onsets.source_refs} />
    </section>
    <section className="min-w-0 border-t border-sage-border pt-5" aria-labelledby="yin3-interpretation-heading">
      <h2 id="yin3-interpretation-heading" className="text-base font-semibold">Author interpretation</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6">The authors consider YIn₃ <strong>likely conventional</strong>, with phonon-mediated pairing. The paper’s unconventional examples concern comparator materials.</p>
      <p className="mt-2 text-xs leading-5 text-sage-muted">This is a qualified source interpretation. A binary material classification has not been assigned.</p>
      <SourceLocations data={data} refs={interpretation.source_refs} />
    </section>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Other temperature descriptions in the paper</summary>
      <p className="mt-3 text-xs leading-5 text-sage-muted">Original units, approximate wording and feature roles are retained. Caption, Results and Discussion values have not been reconciled.</p>
      <div className="mt-2 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep" role="region" tabIndex={0} aria-label="YIn3 source temperature descriptions, horizontally scrollable">
        <table className="w-full min-w-[34rem] text-left text-xs tabular-nums">
          <caption className="sr-only">Nine separate source descriptions for samples A and B.</caption>
          <thead><tr>{["Study sample", "Method", "Exact source expression", "Role and context"].map(label => <th className="py-2 pr-4 font-medium" scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(([sample, method, value, role], index) => <tr className="align-top" key={index}><th scope="row" className="py-3 pr-4 font-medium">{sample}</th><td className="py-3 pr-4">{method}</td><td className="py-3 pr-4">{value}</td><td className="py-3">{role}</td></tr>)}</tbody>
        </table>
      </div>
      <SourceLocations data={data} refs={["S3.p3.1", "S3.F3", "S2.F1", "S3.p1.1", "S3.p2.1", "S3.F2", "S3.p5.1"]} />
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Preparation, measurement conditions and indium context</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
        <p>{observation("study-sample-preparation").summary}</p>
        <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">{[
          ...expressions("ac-susceptibility-method").map(value => [value.role === "frequency" ? "Ac frequency" : "Applied ac field", expressionValue(value)]),
          ...expressions("sample-b-heat-capacity-method-and-feature").filter(value => value.role === "method" || value.role === "sample_mass")
            .map(value => [value.role === "method" ? "Heat-capacity method (B)" : "Sample B mass", expressionValue(value)]),
        ].map(([label, value]) => <div key={label}><dt className="font-medium text-sage-ink">{label}</dt><dd>{value}</dd></div>)}</dl>
        <p>{observation("indium-and-susceptibility-caution").summary}</p>
        <SourceLocations data={data} refs={["S2.p1.1", "S2.p2.1", "S3.p3.1", "S3.p1.1", "S3.p2.1", "S3.F2", "S2.F1"]} />
      </div>
    </details>
    <details className="min-w-0 text-sm">
      <summary className="w-fit cursor-pointer text-accent-deep">Catalogue association, provenance and downloads</summary>
      <div className="mt-3 space-y-3 text-xs leading-5 text-sage-muted">
        <p>The saved catalogue selection is 1.2 K, resistivity onset. Sample A is described approximately near 1.2 K; the selected result has no established sample association. The catalogue value is retained separately.</p>
        <p>Legacy pressure has an ambiguous read state. No ambient-pressure assignment is made.</p>
        <p>{data.source_capture_scope}</p>
        <p>Captured on 4 October 2026: arXiv:1112.3083v1. Nine source contexts and twelve locations overlap within one paper; these counts do not establish independent experiments.</p>
        <p className="break-all font-mono">Original HTML SHA-256: {data.source.sha256}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-2"><a className="site-text-link" href={yin3SourceContextMetadataPath} download>Download YIn3 source-context JSON</a><a className="site-text-link" href={`${yin3SourceContextMetadataPath}.sha256`} download>YIn3 source-context SHA-256</a></div>
        <p className="break-all font-mono">Metadata SHA-256: {yin3SourceContextSnapshotSha256}</p>
        <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-md border border-sage-border bg-sage-surface p-3 text-xs leading-5" role="region" tabIndex={0} aria-label="YIn3 source-context metadata JSON">{JSON.stringify(data, null, 2)}</pre>
      </div>
    </details>
  </article>;
}
