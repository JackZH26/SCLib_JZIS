import Link from "@/components/AppLink";
import { listAdmittedTcResults } from "@/lib/api";
import { MaterialsDownloads } from "@/components/MaterialsDownloads";
import type { MaterialsSearchParams } from "@/lib/materials-browser";
import { admittedPressureLabel, admittedTcLabel, tcCriteria, type AdmittedTcPage } from "@/lib/materials-vnext";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { LatexText } from "@/components/LatexText";
import { materialFamilies } from "@/lib/material-families";

const reported = (text: string | null) => text && !["unresolved", "unspecified", "unknown"].includes(text);

// Preserve the source expression; only select the matching display renderer.
function ReportedFormula({ formula }: { formula: string }) {
  return /[$\\_^]/.test(formula)
    ? <span role="math" aria-label={formula}><LatexText math>{formula}</LatexText></span>
    : <FormulaDisplay formula={formula} />;
}

export function MaterialsVNextResults({ data }: { data: AdmittedTcPage }) {
  if (!data.items.length) return <p className="materials-empty" role="status">No reported results match these filters.</p>;
  return <div className="materials-table-scroll" role="region" aria-label="Reported superconducting transition results" tabIndex={0}>
    <table className="materials-table materials-vnext-table">
      <thead><tr><th scope="col">Material &amp; sample</th><th scope="col">Tc</th><th scope="col">Criterion &amp; method</th><th scope="col">Measurement conditions</th><th scope="col">Source &amp; review</th></tr></thead>
      <tbody>{data.items.map(row => <tr key={row.id}>
        <td><Link className="site-text-link" href={`/materials/${encodeURIComponent(row.material_id)}`}><strong><ReportedFormula formula={row.formula} /></strong></Link>
          <p className="materials-vnext-family">{materialFamilies[row.family ?? "unclassified"] ?? "Unclassified"}</p>
          {row.sample_label && <p className="materials-vnext-secondary"><LatexText>{row.sample_label}</LatexText></p>}
          {reported(row.sample_form) && <p className="materials-vnext-secondary"><LatexText>{row.sample_form!}</LatexText></p>}
          {row.substrate && <p className="materials-vnext-secondary">Substrate: <LatexText>{row.substrate}</LatexText></p>}
        </td>
        <td className="materials-vnext-tc">{admittedTcLabel(row)}</td>
        <td>{row.criterion === "unspecified" && row.criterion_raw ? "Criterion not classified" : (tcCriteria[row.criterion] ?? row.criterion)}
          {row.criterion_raw && <p className="materials-vnext-secondary">Reported criterion: <LatexText>{row.criterion_raw}</LatexText></p>}
          <p className="materials-vnext-secondary"><LatexText>{row.method_raw ?? (row.method === "unspecified" ? "Method not specified" : row.method.replaceAll("_", " "))}</LatexText></p></td>
        <td><LatexText>{admittedPressureLabel(row)}</LatexText>{row.measurement_context && (row.measurement_context.length > 240
          ? <details className="materials-vnext-evidence"><summary>Read measurement context</summary><p><LatexText>{row.measurement_context}</LatexText></p></details>
          : <p className="materials-vnext-secondary"><LatexText>{row.measurement_context}</LatexText></p>)}</td>
        <td><a className="site-text-link" href={row.source_url} target="_blank" rel="noreferrer">{row.paper_id.replace("arxiv:", "arXiv ")}</a>
          <p className="materials-vnext-review">{row.review.per_record_checked ? "Model source checked" : "Batch sample passed"}</p>
          <details className="materials-vnext-evidence"><summary>Evidence &amp; context</summary>
            <p><LatexText>{row.paper_title}</LatexText></p><p>Source version: {row.source_versions.join(", ") || "Not supplied"}</p>
            <p>Tc as written: <LatexText math>{row.quantity.raw}</LatexText></p>
            {row.compositions.map((c, i) => <p key={i}>Reported composition: <ReportedFormula formula={c.formula} />{c.basis === "unresolved" ? " · basis not resolved" : ` · ${c.basis}`}</p>)}
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

export async function MaterialsVNext({ searchParams, materialId }: { searchParams: MaterialsSearchParams; materialId?: string }) {
  const scalar = (key: string) => typeof searchParams[key] === "string" ? searchParams[key] as string : "";
  const q = scalar("q"), pressure = scalar("pressure"), criterion = scalar("criterion"), family = scalar("family");
  const pageValue = scalar("page"); const page = /^\d+$/.test(pageValue) ? Number(pageValue) : 0;
  const invalid = Object.keys(searchParams).some(key => !["q", "pressure", "criterion", "family", "page"].includes(key))
    || Object.values(searchParams).some(Array.isArray) || Boolean(pageValue && !/^\d+$/.test(pageValue)) || !Number.isSafeInteger(page) || page > 1000000
    || Boolean(pressure && !["explicit_ambient", "nonambient", "unknown"].includes(pressure))
    || Boolean(family && !Object.hasOwn(materialFamilies, family))
    || Boolean(criterion && !Object.hasOwn(tcCriteria, criterion)) || q.length > 200;
  const data = invalid ? null : await listAdmittedTcResults({ q, pressure, criterion, ...(family ? {family} : {}), offset: page * 50, limit: 50, ...(materialId ? {material_id: materialId} : {}) }).catch(() => null);
  const totalPages = data ? Math.ceil(data.total / data.limit) : 0;
  const route = materialId ? `/materials/${encodeURIComponent(materialId)}` : "/materials";
  const href = (next: number) => {
    const query = new URLSearchParams({ page: String(next) });
    for (const [key, value] of Object.entries({ q, pressure, criterion, family })) if (value) query.set(key, value);
    return `${route}?${query}`;
  };
  return <main className="materials-browser">
    <header className="materials-heading">{materialId && <Link className="site-text-link" href="/materials">Browse all materials</Link>}<h1>{materialId ? (data?.items[0] ? <ReportedFormula formula={data.items[0].formula} /> : "Material results") : "Materials"}</h1><p>{materialId ? "Reported superconducting transitions for this material entry, with their samples, conditions, and original sources." : "Explore reported superconducting transitions, their measurement conditions, and original sources."}</p></header>
    <p className="materials-vnext-note">Admission requires at least 90% correct results in a random batch sample or an individual check against the original paper. Checks are performed by models; errors and missing results may remain.</p>
    <section className="materials-filter-section" aria-label="Filter reported results"><form key={JSON.stringify([materialId, q, pressure, criterion, family])} className="materials-filter-form materials-vnext-filters" action={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${route}`} method="get">
      <label className="materials-field"><span>Material or arXiv ID</span><input name="q" defaultValue={q} placeholder="e.g. FeSe or 2301.04984" maxLength={200} /></label>
      <label className="materials-field"><span>Material family</span><select name="family" defaultValue={family}><option value="">All families</option>{Object.entries(materialFamilies).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="materials-field"><span>Pressure</span><select name="pressure" defaultValue={pressure}>
        <option value="">All pressures</option><option value="explicit_ambient">Explicit ambient</option><option value="nonambient">Reported nonambient</option><option value="unknown">Not classified / not reported</option>
      </select></label>
      <label className="materials-field"><span>Tc criterion</span><select name="criterion" defaultValue={criterion}><option value="">All criteria</option>{Object.entries(tcCriteria).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="materials-filter-actions"><button className="btn-primary" type="submit">Apply filters</button><Link className="materials-clear" href={route}>Clear</Link></div>
    </form><details className="materials-family-guide"><summary>About material families</summary><p>Families group reported compositions and established material hosts for browsing. They do not determine pairing mechanisms, crystal structures, or sample stoichiometry. Unresolved notation is marked Unclassified.</p></details></section>
    {data ? <><p className="materials-vnext-note"><strong>{data.total.toLocaleString("en-US")}</strong> reported {data.total === 1 ? "result" : "results"} from <strong>{data.paper_count.toLocaleString("en-US")}</strong> {data.paper_count === 1 ? "paper" : "papers"} · {data.material_count.toLocaleString("en-US")} material {data.material_count === 1 ? "entry" : "entries"}, counted separately by paper. Each row retains its own sample, criterion and conditions.</p>
      {totalPages > 0 && page >= totalPages ? <p className="materials-empty">This page is outside the available results.</p> : <MaterialsVNextResults data={data} />}
      {totalPages > 0 && <nav className="materials-vnext-pagination" aria-label="Results pagination">{page >= totalPages ? <Link href={href(0)}>Return to first page</Link> : <>{page > 0 && <Link href={href(page - 1)}>Previous</Link>}<span aria-label={`Page ${page + 1} of ${totalPages}`}>Page {(page + 1).toLocaleString("en-US")} / {totalPages.toLocaleString("en-US")}</span>{data.offset + data.items.length < data.total && <Link href={href(page + 1)}>Next</Link>}</>}</nav>}
    </> : <p role="alert" className="materials-error">{invalid ? "Invalid filters. Choose a supported family, pressure and criterion, or clear the filters." : "Reported results could not be loaded. Reload the page to try again."}</p>}
    {!invalid && !materialId && <MaterialsDownloads />}
  </main>;
}
