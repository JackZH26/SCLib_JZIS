"use client";

import { useEffect, useRef, useState } from "react";
import { ResearchPriorityRow } from "@/components/ResearchPriorityBoard";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import {
  getRpsPage, getRpsReleases, PHYSICAL_DIMENSIONS, rpsBundleDownloadUrl, verifyRpsCatalog, verifyRpsPage,
  type RpsCatalog, type RpsRelease, type RpsRow,
} from "@/lib/research-priority";

type Group = "discovery" | "mechanism" | "controls";
type Candidate = { materialId: string; primary: RpsRow; actions: RpsRow[] };
const groups: [Group, string][] = [["discovery", "Research candidates"], ["mechanism", "Mechanism studies"], ["controls", "References / controls"]];
const score = (value: number | null) => value === null ? "Unranked" : value.toLocaleString("en-US");
const controlRoles = new Set(["reference_anchor", "benchmark_control", "negative_control"]);
const roles = new Set([...controlRoles, "mechanism_anchor", "new_candidate", "conditional_candidate"]);
const identifier = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9_.:-]{1,120}$/.test(value);
const groupOf = (row: RpsRow): Group => controlRoles.has(row.role) ? "controls" : row.role === "mechanism_anchor" ? "mechanism" : "discovery";
const byPriority = (left: RpsRow, right: RpsRow) => left.result.score_display === null
  ? right.result.score_display === null ? 0 : 1
  : right.result.score_display === null ? -1 : right.result.score_display - left.result.score_display;

/** Display grouping of one complete frozen release. This does not select a scientific representative. */
export function groupResearchCandidates(rows: readonly RpsRow[], group: Group): Candidate[] {
  const materialGroups = new Map<string, RpsRow[]>();
  for (const row of rows) {
    if (groupOf(row) !== group) continue;
    const actions = materialGroups.get(row.material_id) ?? [];
    actions.push(row); materialGroups.set(row.material_id, actions);
  }
  return [...materialGroups].map(([materialId, actions]) => {
    const ordered = [...actions].sort(byPriority);
    return { materialId, primary: ordered[0], actions: ordered };
  }).sort((a, b) => byPriority(a.primary, b.primary));
}

/** Never group a partial assessment page: another page can contain the same material or a better action. */
export async function readCompleteCandidateRelease(release: RpsRelease, signal: AbortSignal): Promise<RpsRow[]> {
  // The existing public-bundle contract permits at most 1,000 assessments.
  if (!Number.isSafeInteger(release.total) || release.total < 0 || release.total > 1000) throw new Error("Unsupported release size");
  const rows: RpsRow[] = [];
  const identities = new Map<string, [string, string]>();
  let policy: string | undefined;
  do {
    if (signal.aborted) throw new Error("Cancelled release read");
    const page = await getRpsPage(release.id, rows.length, "all", signal);
    if (signal.aborted) throw new Error("Cancelled release read");
    verifyRpsPage(page, release, rows.length, rows, "all");
    if (page.total !== release.total || page.limit !== 24 || page.items.length !== Math.min(24, release.total - rows.length)
      || policy !== undefined && page.policy_hash !== policy) throw new Error("Incomplete or changed release");
    policy = page.policy_hash;
    for (const row of page.items) {
      if (![row.id, row.material_id, row.state_id, row.action_id].every(identifier)
        || typeof row.formula !== "string" || !row.formula.trim() || typeof row.family !== "string" || !row.family.trim()
        || typeof row.state_summary !== "string" || typeof row.action_summary !== "string"
        || !roles.has(row.role) || row.result.policy_version !== "RPS-v1.2"
        || row.result.rank_group !== (row.role === "mechanism_anchor" ? "mechanism" : "discovery")
        || controlRoles.has(row.role) && row.result.score_display !== null) throw new Error("Invalid material or action identity");
      const previous = identities.get(row.material_id);
      if (previous && (previous[0] !== row.formula || previous[1] !== row.family)) throw new Error("Conflicting material identity");
      identities.set(row.material_id, [row.formula, row.family]);
    }
    rows.push(...structuredClone(page.items));
    if (!page.has_more) break;
  } while (rows.length < release.total);
  if (rows.length !== release.total) throw new Error("Incomplete release");
  return rows;
}

export function ResearchCandidateBoard({ compactEmpty = false }: { compactEmpty?: boolean }) {
  const [catalog, setCatalog] = useState<RpsCatalog | null>(null);
  const [selected, setSelected] = useState("");
  const [rows, setRows] = useState<RpsRow[]>([]);
  const [group, setGroup] = useState<Group>("discovery");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"catalog" | "choose" | "loading" | "ready" | "empty" | "error">("catalog");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);

  const reset = () => {
    generation.current++; active.current?.abort(); setSelected(""); setRows([]); setCatalog(null);
    setStatus("catalog"); setError(""); setRefresh(value => value + 1);
  };
  const select = (value: string) => {
    generation.current++; active.current?.abort(); setRows([]); setError(""); setSelected(value);
    setStatus(value ? "loading" : "choose");
  };
  useEffect(() => {
    const current = ++generation.current, controller = new AbortController(); active.current = controller;
    getRpsReleases(controller.signal).then(value => {
      if (current !== generation.current) return;
      const checked = verifyRpsCatalog(value); setCatalog(checked);
      if (checked.status === "unavailable") {
        setStatus("error"); setError("Configured research releases could not be verified. No candidate scores are shown.");
      } else setStatus(checked.items.length ? "choose" : "empty");
    }).catch(() => {
      if (current !== generation.current) return;
      setStatus("error"); setError("The research publication service could not be verified. This is not an empty release.");
    });
    return () => { generation.current++; controller.abort(); };
  }, [refresh]);

  const release = catalog?.items.find(item => item.id === selected);
  useEffect(() => {
    if (!release) return;
    const current = ++generation.current, controller = new AbortController(); active.current = controller;
    const timer = setTimeout(() => controller.abort(), 60_000);
    readCompleteCandidateRelease(release, controller.signal).then(result => {
      if (current !== generation.current) return;
      setRows(result); setStatus("ready");
    }).catch(() => {
      if (current !== generation.current) return;
      setRows([]); setStatus("error"); setError("The complete selected release could not be verified. A partial candidate ranking is not shown; refresh releases to retry.");
    }).finally(() => clearTimeout(timer));
    return () => { generation.current++; controller.abort(); clearTimeout(timer); };
  }, [release]);

  const candidates = groupResearchCandidates(rows, group);
  const search = query.trim().toLowerCase();
  const visible = candidates.filter(item => [item.primary.formula, item.primary.family, item.materialId].some(value => value.toLowerCase().includes(search)));
  const bundle = release ? rpsBundleDownloadUrl(release) : null;
  if (compactEmpty && status === "empty") return <p role="status" className="text-sm text-sage-muted">No published research-priority assessments. Structure proposals below remain unranked.</p>;
  if (compactEmpty && !catalog?.items.length) return status === "error"
    ? <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <p role="alert">{error}</p><button type="button" onClick={reset} className="min-h-11 rounded-lg border border-red-200 bg-white px-3">Refresh releases</button>
    </div>
    : <p role="status" className="text-sm text-sage-muted">Checking published research priorities…</p>;
  return <section className="min-w-0 space-y-3" aria-labelledby="research-candidates-heading">
    <h2 id="research-candidates-heading" className="text-xl font-semibold">Research candidates</h2>
    <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end">
      <label className="min-w-0 text-sm font-medium">Published release
        <select className="mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3" value={selected} disabled={!catalog?.items.length} onChange={event => select(event.target.value)}>
          <option value="">Choose a published release</option>
          {catalog?.items.map(item => <option key={item.id} value={item.id}>{item.id} · {item.campaign_id}</option>)}
        </select>
      </label>
      <label className="min-w-0 text-sm font-medium">Find a material
        <input className="mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3" type="search" value={query} placeholder="Formula, family or ID" onChange={event => setQuery(event.target.value)} />
      </label>
      <label className="min-w-0 text-sm font-medium">Research role
        <select className="mt-1 block min-h-11 w-full min-w-0 rounded-lg border border-sage-border bg-white px-3" value={group} onChange={event => setGroup(event.target.value as Group)}>
          {groups.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <button type="button" onClick={reset} className="min-h-11 whitespace-nowrap rounded-lg border border-sage-border bg-white px-3 text-sm">Refresh releases</button>
    </div>
    <div className="flex flex-wrap items-start gap-x-5 gap-y-2 text-sm text-sage-muted">
      <p>RPS-v1.2 · Research priority, not a superconductivity probability.</p>
      <details className="min-w-0 max-w-3xl"><summary className="cursor-pointer">How rows are ranked</summary>
        <div className="mt-2 space-y-2 leading-6">
          <p>One row per material ID in the selected release and role. Its score, state and next action belong to its highest-priority published action; expand the row for every action in this role. Ties keep frozen order and unranked actions follow scored actions. This display does not choose a scientifically preferred state.</p>
          <p>RPS = 1,000 + 90 × (0.50 P + 0.30 G + 0.20 A). P uses six conservative evidence dimensions, G measures decision gain, and A uses readiness and affordability. Compare only within this campaign, budget and policy. Missing physical evidence stays unknown; unresolved action requirements can prevent a score.</p>
          <p>Policy-based research priority; empirical calibration pending. Publication does not establish superconductivity or scientific acceptance of every property.</p>
        </div>
      </details>
      {release && <details className="min-w-0 max-w-3xl"><summary className="cursor-pointer">Release and sources</summary>
        <div className="mt-2 space-y-2 break-words [overflow-wrap:anywhere]">
          <p>{release.objective}</p><p>Campaign {release.campaign_id} · {release.campaign_version} · Evidence cutoff {release.evidence_cutoff}</p>
          <p>Manifest SHA-256: <code>{release.manifest_sha256}</code></p>
          {bundle ? <a href={bundle} className="site-text-link">Download pinned public verification bundle</a> : <p>The public verification bundle is not available for download.</p>}
          <p>Publication is checked by the service at request time. Download integrity and reproducible scoring do not certify the science.</p>
        </div>
      </details>}
    </div>
    {status === "catalog" && <p role="status" className="py-6 text-sm text-sage-muted">Loading published research releases…</p>}
    {status === "choose" && <p className="py-6 text-sm text-sage-muted">Choose a release to compare research candidates within one campaign.</p>}
    {status === "loading" && <p role="status" className="py-6 text-sm text-sage-muted">Checking all actions in this release before grouping materials…</p>}
    {status === "empty" && <div className="rounded-xl border border-dashed border-sage-border p-5">
      <h3 className="font-semibold">No research candidate release published yet</h3>
      <p className="mt-2 max-w-3xl text-sm text-sage-muted">Candidates appear here after their defined states, next actions, evidence, resource estimates and disclosure review are published. Host references and calculation tools remain available below.</p>
    </div>}
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
    {catalog?.status === "degraded" && <p role="status" className="text-sm text-amber-950">Some configured releases or verification bundles are unavailable. Only checked releases can be selected.</p>}
    {status === "ready" && release && <>
      <p className="text-sm text-sage-muted">{visible.length} / {candidates.length} materials in this role · {rows.length} published actions in this release</p>
      <div className="max-w-full overflow-x-auto rounded-xl border border-sage-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" tabIndex={0} role="region" aria-label="Research candidates table, scroll horizontally for all columns">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <caption className="sr-only">Research candidates by highest-priority published action within the selected release and role.</caption>
          <thead className="bg-sage-surface text-sage-muted"><tr>
            <th scope="col" className="p-3">Material</th><th scope="col" aria-sort="descending" className="p-3">Research priority <span className="block font-normal">RPS ↓</span></th>
            <th scope="col" className="p-3">Family</th><th scope="col" className="p-3">State</th><th scope="col" className="p-3">Next action</th>
          </tr></thead>
          <tbody>{visible.map(candidate => <CandidateRow key={`${release.manifest_sha256}:${group}:${candidate.materialId}`} candidate={candidate} release={release} />)}</tbody>
        </table>
      </div>
      {!visible.length && <p className="text-sm text-sage-muted">No materials match this role and search in the selected release.</p>}
    </>}
  </section>;
}

function CandidateRow({ candidate, release }: { candidate: Candidate; release: RpsRelease }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const row = candidate.primary, detailsId = `candidate-${candidate.materialId}`;
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <>
    <tr className="border-t border-sage-border bg-white align-top">
      <th scope="row" className="w-48 max-w-60 p-3 font-normal"><button ref={trigger} type="button" aria-label={row.formula} onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls={open ? detailsId : undefined} className="min-h-8 break-words text-left font-semibold text-accent underline decoration-dotted underline-offset-4 [overflow-wrap:anywhere]"><FormulaDisplay formula={row.formula} /></button>
        {candidate.actions.length > 1 && <p className="text-xs text-sage-muted">{candidate.actions.length} actions</p>}</th>
      <td className="whitespace-nowrap p-3"><strong className="tabular-nums">{score(row.result.score_display)}</strong>{row.result.score_display === null && <p className="text-xs text-sage-muted">{row.result.eligibility.replaceAll("_", " ")}</p>}</td>
      <td className="max-w-40 break-words p-3">{row.family}</td>
      <td className="max-w-64 p-3"><p className="line-clamp-2 break-words">{row.state_summary}</p></td>
      <td className="max-w-80 p-3"><p className="line-clamp-2 break-words">{row.action_summary}</p></td>
    </tr>
    {open && <tr id={detailsId} className="border-t border-sage-border bg-sage-surface"><td colSpan={5} className="p-4">
      <div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold">Published states and next actions</h3><p className="mt-1 text-xs text-sage-muted">Material ID: {candidate.materialId}. Each action retains its own score, state, evidence and original assessment rank.</p></div>
        <button type="button" className="min-h-9 rounded-lg border border-sage-border bg-white px-3 text-sm" onClick={close}>Close</button></div>
      <div className="mt-3 max-w-full overflow-x-auto" tabIndex={0} role="region" aria-label={`Actions for ${row.formula}, scroll horizontally for all columns`}>
        <table className="w-full min-w-[1060px] border-collapse text-left text-sm"><caption className="sr-only">All published actions for this material in the selected role. Open an action for evidence and resource details.</caption>
          <thead className="text-xs text-sage-muted"><tr><th scope="col" className="p-3">Original rank / RPS</th><th scope="col" className="p-3">Material · state · next action</th>
            {PHYSICAL_DIMENSIONS.map(([key, label]) => <th key={key} scope="col" className="p-3">{label}</th>)}<th scope="col" className="p-3">Assessed weight</th></tr></thead>
          <tbody>{candidate.actions.map(action => <ResearchPriorityRow key={action.id} row={action} release={release} />)}</tbody>
        </table>
      </div>
    </td></tr>}
  </>;
}
