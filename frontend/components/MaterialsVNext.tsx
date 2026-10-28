import Link from "@/components/AppLink";
import { getMaterialsDataset, listAdmittedTcResults, materialsDatasetDownloadUrl } from "@/lib/api";
import type { MaterialsSearchParams } from "@/lib/materials-browser";
import { admittedPressureLabel, admittedTcLabel, tcCriteria, type AdmittedTcPage, type MaterialsDataset } from "@/lib/materials-vnext";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { LatexText } from "@/components/LatexText";

const reported = (text: string | null) => text && !["unresolved", "unspecified", "unknown"].includes(text);

// Preserve the source expression; only select the matching display renderer.
function ReportedFormula({ formula }: { formula: string }) {
  return /\$[^$]+\$/.test(formula)
    ? <span role="math" aria-label={formula}><LatexText>{formula}</LatexText></span>
    : <FormulaDisplay formula={formula} />;
}

export function MaterialsVNextResults({ data }: { data: AdmittedTcPage }) {
  if (!data.items.length) return <p className="materials-empty" role="status">No reported results match these filters.</p>;
  return <div className="materials-table-scroll" role="region" aria-label="Reported superconducting transition results" tabIndex={0}>
    <table className="materials-table materials-vnext-table">
      <thead><tr><th scope="col">Material &amp; sample</th><th scope="col">Tc</th><th scope="col">Criterion &amp; method</th><th scope="col">Measurement conditions</th><th scope="col">Source &amp; review</th></tr></thead>
      <tbody>{data.items.map(row => <tr key={row.id}>
        <td><Link className="site-text-link" href={`/materials/${encodeURIComponent(row.material_id)}`}><strong><ReportedFormula formula={row.formula} /></strong></Link>
          {row.sample_label && <p className="materials-vnext-secondary">{row.sample_label}</p>}
          {reported(row.sample_form) && <p className="materials-vnext-secondary">{row.sample_form}</p>}
          {row.substrate && <p className="materials-vnext-secondary">Substrate: {row.substrate}</p>}
        </td>
        <td className="materials-vnext-tc">{admittedTcLabel(row)}</td>
        <td>{row.criterion === "unspecified" && row.criterion_raw ? "Criterion not classified" : (tcCriteria[row.criterion] ?? row.criterion)}
          {row.criterion_raw && <p className="materials-vnext-secondary">Reported criterion: <code>{row.criterion_raw}</code></p>}
          <p className="materials-vnext-secondary">{row.method_raw ?? (row.method === "unspecified" ? "Method not specified" : row.method.replaceAll("_", " "))}</p></td>
        <td>{admittedPressureLabel(row)}{row.measurement_context && (row.measurement_context.length > 240
          ? <details className="materials-vnext-evidence"><summary>Read measurement context</summary><p>{row.measurement_context}</p></details>
          : <p className="materials-vnext-secondary">{row.measurement_context}</p>)}</td>
        <td><a className="site-text-link" href={row.source_url} target="_blank" rel="noreferrer">{row.paper_id.replace("arxiv:", "arXiv ")}</a>
          <p className="materials-vnext-review">{row.review.per_record_checked ? "Model source checked" : "Batch sample passed"}</p>
          <details className="materials-vnext-evidence"><summary>Evidence &amp; context</summary>
            <p>{row.paper_title}</p><p>Source version: {row.source_versions.join(", ") || "Not supplied"}</p>
            <p>Tc as written: <code>{row.quantity.raw}</code></p>
            {row.compositions.map((c, i) => <p key={i}>Reported composition: <code>{c.formula}</code>{c.basis === "unresolved" ? " · basis not resolved" : ` · ${c.basis}`}</p>)}
            <ul>{Array.from(new Map(row.evidence.map(e => [e.locator, e])).values()).map(e => <li key={e.locator}>
              <a className="site-text-link" href={`${row.source_url}${e.page ? `#page=${e.page}` : ""}`} target="_blank" rel="noreferrer">{e.page ? `Read source, page ${e.page}` : "Read original source"}</a>
              {!e.page && <span> · {e.locator}</span>}
            </li>)}</ul>
            <p>{row.review.per_record_checked ? "This result received a model check against its original source." : "This result belongs to a passing sampled batch; it has not been checked individually."} Independent domain review is pending.</p>
          </details>
        </td>
      </tr>)}</tbody>
    </table>
  </div>;
}

export function MaterialsDatasetDownloads({ dataset }: { dataset: MaterialsDataset | null }) {
  return <section className="materials-dataset-downloads" aria-labelledby="materials-downloads-heading">
    <h2 id="materials-downloads-heading">Download dataset</h2>
    {dataset ? <>
      <p>Full dataset snapshot · {dataset.files.results.rows.toLocaleString("en-US")} results from {dataset.paper_count.toLocaleString("en-US")} papers. Page filters do not change these downloads.</p>
      <ul>{(["results", "evidence", "training"] as const).map(kind => <li key={kind}>
        <a className="site-text-link" href={materialsDatasetDownloadUrl(dataset.version, kind)}>
          {kind === "results" ? "Results CSV" : kind === "evidence" ? "Evidence CSV" : "Training CSV"}
        </a> · {dataset.files[kind].rows.toLocaleString("en-US")} rows
      </li>)}</ul>
      <p>Updated {new Date(dataset.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })} · Version <code title={dataset.version}>{dataset.version.slice(0, 12)}</code></p>
      <details><summary>Scope and training guidance</summary>
        <p>{dataset.source_scope}</p><p>{dataset.training_policy}</p><p>{dataset.grouping_policy}</p>
        <p>Use only feature columns as model inputs. Review and provenance columns describe the data. Unknown pressure and publication status remain unknown.</p>
        <p>Join the results and evidence files by record_id. Downloads include quality status and source versions; batch sampling is not individual expert review.</p>
      </details>
    </> : <p>Downloads will be available after the latest dataset update is prepared.</p>}
  </section>;
}

export async function MaterialsVNext({ searchParams, materialId }: { searchParams: MaterialsSearchParams; materialId?: string }) {
  const scalar = (key: string) => typeof searchParams[key] === "string" ? searchParams[key] as string : "";
  const q = scalar("q"), pressure = scalar("pressure"), criterion = scalar("criterion");
  const pageValue = scalar("page"); const page = /^\d+$/.test(pageValue) ? Number(pageValue) : 0;
  const invalid = Object.keys(searchParams).some(key => !["q", "pressure", "criterion", "page"].includes(key))
    || Object.values(searchParams).some(Array.isArray) || Boolean(pageValue && !/^\d+$/.test(pageValue)) || !Number.isSafeInteger(page) || page > 1000000
    || Boolean(pressure && !["explicit_ambient", "nonambient", "unknown"].includes(pressure))
    || Boolean(criterion && !Object.hasOwn(tcCriteria, criterion)) || q.length > 200;
  const [data, dataset] = await Promise.all([
    invalid ? null : listAdmittedTcResults({ q, pressure, criterion, offset: page * 50, limit: 50, ...(materialId ? {material_id: materialId} : {}) }).catch(() => null),
    !invalid && !materialId ? getMaterialsDataset().catch(() => null) : null,
  ]);
  const route = materialId ? `/materials/${encodeURIComponent(materialId)}` : "/materials";
  const href = (next: number) => {
    const query = new URLSearchParams({ page: String(next) });
    for (const [key, value] of Object.entries({ q, pressure, criterion })) if (value) query.set(key, value);
    return `${route}?${query}`;
  };
  return <main className="materials-browser">
    <header className="materials-heading">{materialId && <Link className="site-text-link" href="/materials">Browse all materials</Link>}<h1>{materialId ? (data?.items[0] ? <ReportedFormula formula={data.items[0].formula} /> : "Material results") : "Materials"}</h1><p>{materialId ? "Reported superconducting transitions for this material entry, with their samples, conditions, and original sources." : "Explore reported superconducting transitions, their measurement conditions, and original sources."}</p></header>
    <p className="materials-vnext-note">Dataset preview · Admission uses a 90% source-check threshold or an individual check against the original paper. Full-corpus processing is in progress.</p>
    <section className="materials-filter-section" aria-label="Filter reported results"><form key={JSON.stringify([materialId, q, pressure, criterion])} className="materials-filter-form materials-vnext-filters" action={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${route}`} method="get">
      <label className="materials-field"><span>Material or arXiv ID</span><input name="q" defaultValue={q} placeholder="e.g. FeSe or 2301.04984" maxLength={200} /></label>
      <label className="materials-field"><span>Pressure</span><select name="pressure" defaultValue={pressure}>
        <option value="">All pressures</option><option value="explicit_ambient">Explicit ambient</option><option value="nonambient">Reported nonambient</option><option value="unknown">Not classified / not reported</option>
      </select></label>
      <label className="materials-field"><span>Tc criterion</span><select name="criterion" defaultValue={criterion}><option value="">All criteria</option>{Object.entries(tcCriteria).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="materials-filter-actions"><button className="btn-primary" type="submit">Apply filters</button><Link className="materials-clear" href={route}>Clear</Link></div>
    </form></section>
    {data ? <><p className="materials-vnext-note"><strong>{data.total.toLocaleString("en-US")}</strong> reported {data.total === 1 ? "result" : "results"} from <strong>{data.paper_count.toLocaleString("en-US")}</strong> {data.paper_count === 1 ? "paper" : "papers"} · {data.material_count.toLocaleString("en-US")} material {data.material_count === 1 ? "entry" : "entries"}, counted separately by paper. Each row retains its own sample, criterion and conditions.</p>
      <MaterialsVNextResults data={data} />
      <nav className="materials-vnext-pagination" aria-label="Results pagination">{page > 0 && <Link href={href(page - 1)}>Previous</Link>}<span>Page {(page + 1).toLocaleString("en-US")}</span>{data.offset + data.items.length < data.total && <Link href={href(page + 1)}>Next</Link>}</nav>
    </> : <p role="alert" className="materials-error">{invalid ? "Invalid filters. Choose a supported pressure and criterion, or clear the filters." : "Reported results could not be loaded. Reload the page to try again."}</p>}
    {!invalid && !materialId && <MaterialsDatasetDownloads dataset={dataset} />}
  </main>;
}
