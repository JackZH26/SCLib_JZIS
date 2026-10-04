import { Fragment } from "react";
import Link from "next/link";
import { ORGANIC_FILE, ORGANIC_PAGE_SIZE, ORGANIC_ROUTE, organicAssetPath, organicCell, organicCode, organicHref, organicLabel,
  organicPropertyFields, organicQuery, organicSnapshot, organicStructures, type OrganicParams, type OrganicRow } from "@/lib/mdr-organic";

const control = "mt-1 min-h-11 w-full min-w-0 rounded-md border border-sage-border bg-white px-3 py-2 text-sm";
const cellClass = "px-3 py-3 align-top";
const fmt = (value: number) => value.toLocaleString("en-US");
function RawValue({ row, field }: { row: OrganicRow; field: string }) {
  const value = organicCell(row, field);
  return <span className="tabular-nums">{value || <span aria-label="Not supplied">—</span>}{value && field === "pcrit" ? " GPa" : ""}</span>;
}

export function OrganicReferenceBrowser({ params }: { params: OrganicParams }) {
  const data = organicSnapshot();
  const { rows, errors, filters, pages } = organicQuery(params);
  const pageRows = rows.slice(filters.page * ORGANIC_PAGE_SIZE, (filters.page + 1) * ORGANIC_PAGE_SIZE);
  const before = filters.page * ORGANIC_PAGE_SIZE;
  const download = organicAssetPath(ORGANIC_FILE);
  const pageInvalid = filters.page >= pages;
  return <div className="min-w-0 space-y-5">
    <form key={JSON.stringify(filters)} method="get" action={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${ORGANIC_ROUTE}`} aria-label="Filter Organic source rows" className="grid min-w-0 items-end gap-4 rounded-lg border border-sage-border bg-white p-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
      <label className="min-w-0 text-sm">Names, remarks or reference<input name="q" maxLength={128} defaultValue={filters.q} className={control} placeholder="e.g. TMTSF, deuterated or PR05403760" /></label>
      <label className="min-w-0 text-sm">Source structure label<select name="structure" defaultValue={filters.structure} className={control}><option value="">All labels</option>{filters.structure && !organicStructures().includes(filters.structure) && <option value={filters.structure}>{filters.structure} (unknown)</option>}{organicStructures().map(value => <option value={value} key={value}>{value}</option>)}</select></label>
      <label className="min-w-0 text-sm">Has source field<select name="field" defaultValue={filters.field} className={control}><option value="">Any field</option>{filters.field && !organicPropertyFields.includes(filters.field) && <option value={filters.field}>{filters.field} (unknown)</option>}{organicPropertyFields.map(key => <option key={key} value={key}>{organicLabel(key)}</option>)}</select></label>
      <div className="flex min-h-11 items-center gap-4"><button type="submit" className="btn-primary">Apply</button><Link href={ORGANIC_ROUTE} className="site-text-link">Clear</Link></div>
    </form>
    <p className="max-w-4xl text-xs leading-5 text-sage-muted">Search uses original source text. Rows remain separate references; catalogue sample associations are unestablished.</p>
    {errors.length > 0 && <p role="alert" className="rounded-md border border-red-200 bg-white p-3 text-sm text-red-800">{errors.join(" ")} Clear the filters to recover.</p>}
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><p role="status"><strong>{fmt(rows.length)}</strong> matching source rows{!errors.length && pageRows.length > 0 ? ` · ${fmt(before + 1)}–${fmt(before + pageRows.length)} shown` : ""}{filters.row ? ` · row ${filters.row}` : ""}</p>{!errors.length && <a href={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${organicHref(filters, 0, true)}`} download className="site-text-link">Download all matching rows (JSON)</a>}</div>
    <p className="max-w-4xl text-sm leading-6 text-sage-muted">Only <code>pcrit</code> explicitly supplies GPa; the other numeric columns lack unit fields. Tc, maximum Tc and non-SC limits stay separate. A dash means no supplied value.</p>
    {!errors.length && pageInvalid && <p role="alert" className="text-sm">This page is outside the current results. <Link className="site-text-link" href={organicHref(filters)}>Return to the first page</Link>.</p>}
    {!errors.length && !rows.length && <p className="border-y border-sage-border py-8 text-sm">No source rows match these filters in version 240322. Try a source spelling or clear the filters.</p>}
    {pageRows.length > 0 && <div role="region" aria-label="Scrollable Organic reference table" tabIndex={0} className="min-w-0 overflow-x-auto rounded-lg border border-sage-border bg-white">
      <table className="w-full min-w-[760px] text-left text-sm"><caption className="sr-only">Organic source rows with separate transition and pressure columns; raw units are not inferred</caption>
        <thead className="border-b border-sage-border bg-sage-surface text-xs text-sage-muted"><tr>{["Source material", "Transition values (raw)", "Pressure context", "Reference / method"].map(label => <th scope="col" className={cellClass} key={label}>{label}</th>)}</tr></thead>
        <tbody>{pageRows.map(row => <Fragment key={row.id}>
          <tr id={`organic-row-${row.id}`} className="scroll-mt-24 border-t border-sage-border">
            <th scope="row" className={`${cellClass} max-w-sm font-medium`}><span className="break-words">{organicCell(row, "fullname")}</span><span className="mt-1 block text-xs font-normal text-sage-muted">Row {row.id} · {organicCell(row, "str") || "Structure label not supplied"}</span>{organicCell(row, "isoel") && <span className="mt-1 block text-xs font-normal">Isotope element: {organicCell(row, "isoel")}</span>}{organicCell(row, "sample") && <span className="mt-1 block text-xs font-normal">Sample label: {organicCell(row, "sample")}</span>}</th>
            <td className={`${cellClass} min-w-44`}><dl className="space-y-1">{[["tc", "Tc"], ["tcmax", "Maximum Tc"], ["tcn", "Non-SC test limit"]].filter(([field]) => organicCell(row, field)).map(([field, label]) => <div key={field} className="flex justify-between gap-4"><dt className="text-xs text-sage-muted">{label}</dt><dd><RawValue row={row} field={field} /></dd></div>)}</dl>{!["tc", "tcmax", "tcn"].some(field => organicCell(row, field)) && <span aria-label="No transition value supplied">—</span>}</td>
            <td className={`${cellClass} min-w-44`}><dl className="space-y-1">{organicCell(row, "pcrit") && <div className="flex justify-between gap-4"><dt className="text-xs text-sage-muted">Critical pressure, pcrit</dt><dd className="whitespace-nowrap"><RawValue row={row} field="pcrit" /></dd></div>}{organicCell(row, "pmax") && <div className="flex justify-between gap-4"><dt className="text-xs text-sage-muted">At maximum Tc, pmax (raw)</dt><dd><RawValue row={row} field="pmax" /></dd></div>}</dl>{!["pcrit", "pmax"].some(field => organicCell(row, field)) && <span aria-label="No pressure value supplied">—</span>}</td>
            <td className={`${cellClass} min-w-40`}><p>{organicCell(row, "year")} · {organicCell(row, "refno")}</p><p className="mt-1 text-xs text-sage-muted">{organicCell(row, "tcmeth") ? organicCode("tcmeth", organicCell(row, "tcmeth")) : "Method —"}</p></td>
          </tr>
          <tr><td colSpan={4} className="px-3 pb-3"><details className="min-w-0"><summary className="w-fit max-w-[calc(100vw-5rem)] cursor-pointer py-1 text-xs font-medium text-accent-deep md:max-w-none">Inspect row {row.id}: properties, remarks and source</summary><div className="mt-3 min-w-0 max-w-[calc(100vw-5rem)] space-y-4 md:max-w-none">
            <div className="max-w-4xl space-y-2 text-sm leading-6"><p className="font-medium">{organicCell(row, "title") || "Title not supplied"}</p><p>{organicCell(row, "journal")}</p>{organicCell(row, "commt") && <p><strong className="font-medium">Source remark: </strong>{organicCell(row, "commt")}</p>}{organicCell(row, "comments") && <p><strong className="font-medium">Additional comment: </strong>{organicCell(row, "comments")}</p>}</div>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3"><div><dt className="text-xs text-sage-muted">Common name (raw)</dt><dd>{organicCell(row, "name") || "Not supplied"}</dd></div><div><dt className="text-xs text-sage-muted">Sample form</dt><dd>{organicCode("shape", organicCell(row, "shape"))}</dd></div>{organicPropertyFields.filter(key => !["tc", "tcmax", "pcrit", "pmax", "tcn", "tcmeth", "isoel"].includes(key) && organicCell(row, key)).map(key => <div key={key}><dt className="text-xs text-sage-muted">{organicLabel(key)}{key === "gapmeth" ? "" : " (raw)"}</dt><dd>{key === "gapmeth" ? organicCode(key, organicCell(row, key)) : organicCell(row, key)}</dd></div>)}</dl>
            <div className="flex flex-wrap gap-4 text-xs"><Link className="site-text-link" href={organicHref({ q: "", structure: "", field: "", page: 0, row: row.id })}>Link to this source row</Link><a className="site-text-link" href={data.source.url}>Original NIMS table</a><a className="site-text-link" href={`${data.source.guide_url}#page=9`}>Field guide, page 9</a></div>
            <details className="min-w-0 text-xs"><summary className="w-fit cursor-pointer text-accent-deep">All 49 original cells and provenance</summary><div className="mt-3 space-y-3"><p>Original physical lines {row.line_start}–{row.line_end}; blank cells are preserved. Linked figure/table filenames are source metadata; their files have not been inspected here.</p><p>Row SHA-256: <code className="break-all">{row.sha256}</code></p><dl className="grid gap-x-8 gap-y-2 sm:grid-cols-2">{data.columns.map((field, index) => <div key={field} className="min-w-0"><dt className="text-sage-muted">{data.source_labels[index]} · <code>{field}</code></dt><dd className="whitespace-pre-wrap break-words">{row.values[index] || <span aria-label="Empty source cell">—</span>}</dd></div>)}</dl></div></details>
          </div></details></td></tr>
        </Fragment>)}</tbody>
      </table>
    </div>}
    {!errors.length && rows.length > 0 && !pageInvalid && <nav aria-label="Organic reference pages" className="flex flex-wrap items-center gap-5 text-sm">{filters.page > 0 && <Link className="site-text-link inline-flex min-h-11 items-center" href={organicHref(filters, filters.page - 1)}>Previous</Link>}<span>Page {fmt(filters.page + 1)} of {fmt(pages)}</span>{filters.page + 1 < pages && <Link className="site-text-link inline-flex min-h-11 items-center" href={organicHref(filters, filters.page + 1)}>Next</Link>}{filters.page + 1 < pages && <Link className="site-text-link inline-flex min-h-11 items-center" href={organicHref(filters, pages - 1)}>Last page</Link>}</nav>}
    <details className="min-w-0 border-t border-sage-border pt-4 text-xs leading-6 text-sage-muted"><summary className="w-fit cursor-pointer font-medium text-accent-deep">Dataset coverage, units and downloads</summary><div className="mt-3 min-w-0 space-y-3">
      <p>{data.attribution} <a className="site-text-link" href={data.dataset_url}>Dataset version</a> · <a className="site-text-link" href={data.license_url}>CC BY 4.0</a>.</p>
      <p>568 nonempty source rows, 49 original columns. One all-empty trailing row is excluded and recorded in the manifest. Source row counts are not material or independent-experiment counts. Publication status and catalogue sample/phase associations have not been checked.</p>
      <p>{data.interpretation.tc} {data.interpretation.tcmax} {data.interpretation.tcn}</p>
      <p>Numeric cells are not converted or assigned absent units. Comments can contain additional conditions or units and remain source text. Guide code labels are provided for sample form and measurement methods; raw codes remain available.</p>
      <div className="flex flex-wrap gap-4"><a className="site-text-link" href={download} download>Full reference JSON</a><a className="site-text-link" href={`${download}.sha256`} download>JSON SHA-256</a><a className="site-text-link" href={organicAssetPath("240322_MDR_Organic.txt")} download>Original table bytes</a></div>
      <p>Source file SHA-256: <code className="break-all">{data.source.sha256}</code></p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">{organicPropertyFields.map(field => <div key={field}><dt>{organicLabel(field)}</dt><dd>{fmt(data.coverage[field as keyof typeof data.coverage])} nonempty rows</dd></div>)}</dl>
    </div></details>
  </div>;
}
