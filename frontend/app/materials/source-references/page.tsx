import type { Metadata } from "next";
import Link from "next/link";
import pilot from "@/public/research-pilots/materials-source-references-2026-10-02.json";
import { absoluteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Materials source reference pilot",
  description: "Inspect source-specific CrB2 paper findings and independent crystallographic references, with conditions, provenance and downloadable metadata. Catalogue associations remain pending.",
  alternates: { canonical: absoluteUrl("/materials/source-references") },
};

const download = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-source-references-2026-10-02.json`;

export default function MaterialsSourceReferencesPage() {
  return <main className="min-w-0 space-y-8">
    <header className="space-y-3">
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm"><Link className="site-text-link" href="/materials">Materials catalogue</Link><Link className="site-text-link" href="/materials/source-observations">Additional source observations</Link></div>
      <h1 className="text-3xl font-semibold tracking-tight">Source reference pilot</h1>
      <p className="text-sm"><Link className="site-text-link inline-flex min-h-11 items-center" href="/materials/source-references/organic">Explore 568 NIMS Organic source rows</Link></p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Seven CrB₂ paper items and three independent crystallographic references, with conditions and original file hashes. Sample and state matching remains pending; current publication status has not been checked.</p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <span className="text-sage-muted">Prepared {pilot.prepared_on}</span>
        <a className="site-text-link" href={download} download>Download reference metadata (JSON)</a>
        <a className="site-text-link" href={`${download}.sha256`} download>Download SHA-256</a>
      </div>
    </header>

    <section aria-labelledby="paper-items-title" className="space-y-3">
      <h2 id="paper-items-title" className="text-xl font-semibold">CrB₂ · paper findings</h2>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted"><a className="site-text-link" href={pilot.paper_source.url}>{pilot.paper_source.title}</a>. Source-specific reports and derived quantities are kept separate below.</p>
      <ol className="divide-y divide-sage-border border-y border-sage-border">
        {pilot.paper_findings.map(item => <li id={item.id} key={item.id} className="scroll-mt-24 grid min-w-0 gap-3 py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:gap-8">
          <div><h3 className="text-sm font-semibold">{item.label}</h3><p className="mt-1 text-xs leading-5 text-sage-muted">{item.origin}</p></div>
          <div className="min-w-0 space-y-2">
            <p className="text-base font-medium tabular-nums">{item.display_value}</p>
            <p className="text-sm leading-6 text-sage-muted">{item.scope}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">{item.pages.map(page => <a key={page} className="site-text-link" href={`${pilot.paper_source.url}#page=${page}`}>PDF page {page}</a>)}{item.depends_on.map(id => <a key={id} className="site-text-link" href={`#${id}`}>Related: {pilot.paper_findings.find(other => other.id === id)?.label ?? id}</a>)}</div>
            <details className="text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer text-accent-deep">Scope and association</summary><p className="mt-2">{item.unresolved}</p></details>
          </div>
        </li>)}
      </ol>
    </section>

    <section aria-labelledby="cif-title" className="space-y-3">
      <h2 id="cif-title" className="text-xl font-semibold">Independent crystallographic references</h2>
      <p className="text-sm"><Link className="site-text-link inline-flex min-h-11 items-center" href="/discovery/structures">Inspect atomic coordinates and try a lattice proposal</Link></p>
      <p className="max-w-3xl text-sm leading-6 text-sage-muted">Conditions below belong to each CIF. They do not supply the pressure or temperature of a superconducting transition, or establish that a catalogue result used this structure.</p>
      <p className="max-w-3xl text-xs leading-5 text-sage-muted">MgB₂ and FeSe were in the disputed or archive catalogue partition in the checked historical snapshot. These independent COD references do not establish catalogue associations or release held records.</p>
      <div className="divide-y divide-sage-border border-y border-sage-border">
        {pilot.structure_references.map(item => <article id={item.id} key={item.id} className="scroll-mt-24 grid min-w-0 gap-3 py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:gap-8" aria-labelledby={`${item.id}-title`}>
          <div><h3 id={`${item.id}-title`} className="text-base font-semibold">{item.formula}</h3><p className="mt-1 text-xs text-sage-muted">COD {item.cod_id} · source year {item.source.year}</p></div>
          <div className="min-w-0 space-y-3">
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-sage-muted">Declared space group</dt><dd className="mt-1">{item.declared_space_group} · {item.declared_space_group_number}</dd></div>
              <div><dt className="text-xs text-sage-muted">Structure conditions</dt><dd className="mt-1">{item.temperature_k == null ? "Temperature not supplied" : `${item.temperature_k} K`} · {item.pressure_gpa == null ? "Pressure not supplied" : `${item.pressure_gpa} GPa`}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs text-sage-muted">Lattice lengths (Å)</dt><dd className="mt-1 tabular-nums">a = {item.lattice.a.raw} · b = {item.lattice.b.raw} · c = {item.lattice.c.raw}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs text-sage-muted">Lattice angles (degrees)</dt><dd className="mt-1 tabular-nums">α = {item.lattice.alpha.raw} · β = {item.lattice.beta.raw} · γ = {item.lattice.gamma.raw}</dd></div>
              {item.Fe_site_occupancy && <div className="sm:col-span-2"><dt className="text-xs text-sage-muted">Refined Fe occupancy</dt><dd className="mt-1">{item.Fe_site_occupancy.raw} · standard uncertainty {item.Fe_site_occupancy.standard_uncertainty}. This alone does not establish a physical vacancy concentration.</dd></div>}
            </dl>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm"><a className="site-text-link" href={item.source.entry_url}>COD entry</a><a className="site-text-link" href={item.source.cif_url}>{item.source.download_is_mutable_current_file ? "Current CIF download" : "CIF revision download"}</a>{item.source.doi && <a className="site-text-link" href={`https://doi.org/${item.source.doi}`}>Source publication</a>}</div>
            <details className="min-w-0 text-xs leading-5 text-sage-muted">
              <summary className="w-fit cursor-pointer text-accent-deep">File provenance and inspection</summary>
              <p className="mt-2">Captured {item.source.captured_at_utc} · header revision {item.source.captured_revision} · {item.source.bytes.toLocaleString("en-US")} bytes.</p>
              <p className="mt-2">SHA-256: <code className="break-all">{item.source.file_sha256}</code></p>
              <p className="mt-2">AI-assisted checks parsed the CIF and inspected listed sites, declared symmetry operations and lattice metrics. Independent space-group inference, checkCIF and refinement were not performed.</p>
              <ul className="mt-2 list-disc space-y-1 pl-4">{item.limitations.map(text => <li key={text}>{text}</li>)}</ul>
              <p className="mt-2">{item.source.bibliography.authors}. {item.source.bibliography.title}. {item.source.bibliography.journal} ({item.source.year}). COD data: <a className="site-text-link" href={item.source.license_url}>{item.source.license}</a>.</p>
            </details>
          </div>
        </article>)}
      </div>
    </section>

    <details className="border-t border-sage-border pt-4 text-sm leading-6 text-sage-muted">
      <summary className="w-fit cursor-pointer font-medium text-accent-deep">Inspection scope and use</summary>
      <div className="mt-3 max-w-3xl space-y-3">
        <p>These source items are independent of selected catalogue properties. Associations remain pending; no scientific approval, canonical promotion or training permission is granted by this pilot. The current publication status and source lifecycle of each work have not been established here.</p>
        <p>The checked historical catalogue snapshot ({pilot.boundary.eligibility_snapshot.site_version}, {pilot.boundary.eligibility_snapshot.dataset_version}) placed MgB₂ and FeSe in disputed or archive scope. Their independent COD metadata here does not create a catalogue entry, restore a held record or establish a sample association. Current eligibility must be checked separately.</p>
        <p>The PDF was requested as {pilot.paper_source.requested_arxiv_version}; publication revision remains unverified. Captured PDF SHA-256: <code className="break-all">{pilot.paper_source.pdf_sha256}</code>. Page anchors in the JSON use characters in the captured text extraction, rather than PDF geometry.</p>
        <p>The JSON provides factual metadata and original-source links. Original PDF and CIF files are available from their providers. A current download URL may return different bytes; compare it with the recorded hash.</p>
      </div>
    </details>
  </main>;
}
