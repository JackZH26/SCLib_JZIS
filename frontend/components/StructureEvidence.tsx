import Link from "next/link";
import { objectValue } from "@/lib/property-evidence";

export const STRUCTURE_EVIDENCE_VERSION = "structure-evidence/1.0.0";
const FIELDS = { structure_phase: "Phase", crystal_structure: "Crystal structure", space_group: "Space group" };
type StructureField = keyof typeof FIELDS;
const LIMIT = 20;
function text(value: unknown, limit = 800): string | null { return typeof value === "string" && value.trim() && value.length <= limit ? value : null; }
function count(value: unknown): number | null { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null; }
function reasons(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => !!text(item, 200)).slice(0, 30) : []; }
function known(value: unknown): Record<string, unknown> | null {
  const item = objectValue(value);
  return item.version === STRUCTURE_EVIDENCE_VERSION && item.scientific_acceptance === false && item.coordinate_status === "not_validated" ? item : null;
}
function pendingProposals(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.slice(0, 1000).map(objectValue).filter(item => item.status === "pending" && item.scientific_acceptance === false && item.representation === "text_claim" && Object.hasOwn(FIELDS, String(item.field))) : [];
}

export function StructureEvidenceValue({ evidence, field = "structure_phase" }: { evidence: unknown; field?: StructureField }) {
  const envelope = known(evidence);
  const property = objectValue(objectValue(envelope?.properties)[field]);
  const pending = property.status === "pending" && property.value === null && (count(property.proposal_count) ?? 0) > 0;
  return <span className="block text-xs"><span>{pending ? "Pending source review" : "Unknown"}</span><span className="mt-0.5 block text-[10px] text-slate-500">Text label ≠ coordinate structure</span></span>;
}

/** This view deliberately has no approval action: extraction is not review. */
export function StructureEvidencePanel({ evidence }: { evidence: unknown }) {
  const envelope = known(evidence);
  const coverage = objectValue(envelope?.coverage);
  const proposals = pendingProposals(envelope?.proposals);
  const mentions = Array.isArray(envelope?.unassigned_mentions) ? envelope.unassigned_mentions.slice(0, 1000).map(objectValue).filter(item => item.status === "pending" && item.scientific_acceptance === false && item.association === "unassigned") : [];
  return <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4" aria-label="Structure association proposals">
    <h2 className="text-base font-semibold">Structure and phase · pending evidence review</h2>
    <p className="text-xs text-slate-600">Textual phase, crystal and space-group claims remain proposals until their material, sample/state and source revision are reviewed. Literal text matching is not scientific approval. No validated coordinates or structural descriptors are supplied by this view.</p>
    {!envelope && <p className="text-xs text-amber-900">Compatible structure-evidence metadata is unavailable. Legacy structure flags are not promoted to reviewed properties.</p>}
    {envelope && coverage.assessment_complete !== true && <p className="text-xs text-amber-900">The proposal assessment is incomplete or its completeness is unknown. Do not treat these counts as complete coverage.</p>}
    <dl className="grid gap-3 text-xs sm:grid-cols-3">{Object.entries(FIELDS).map(([field, label]) => <div key={field}><dt className="font-medium">{label}</dt><dd className="mt-1"><StructureEvidenceValue evidence={evidence} field={field as StructureField} /></dd></div>)}</dl>
    <p className="text-xs text-slate-600">Retained proposals: {count(coverage.proposal_count)?.toLocaleString("en-US") ?? "Unknown"} · Unassigned mentions: {count(coverage.unassigned_mention_count)?.toLocaleString("en-US") ?? "Unknown"}. Counts are not independent structures or accepted results.</p>
    {proposals.length > 0 && <details className="text-xs"><summary className="cursor-pointer text-sky-800">Inspect pending structure proposals</summary><ul className="mt-3 space-y-3">{proposals.slice(0, LIMIT).map((proposal, index) => <Proposal key={index} proposal={proposal} />)}</ul></details>}
    {mentions.length > 0 && <details className="text-xs"><summary className="cursor-pointer text-sky-800">Inspect unassigned document mentions</summary><p className="mt-2 text-slate-600">These mentions are not assigned to this material or state.</p><ul className="mt-2 space-y-3">{mentions.slice(0, LIMIT).map((proposal, index) => <Proposal key={index} proposal={proposal} />)}</ul></details>}
    {(coverage.display_truncated === true || proposals.length > LIMIT || mentions.length > LIMIT) && <p className="text-xs text-amber-900">Display is bounded. The full retained source record remains the audit reference.</p>}
    {reasons(envelope?.warnings).length > 0 && <details className="text-xs"><summary className="cursor-pointer">Structure evidence limitations</summary><ul className="mt-2 list-disc pl-4">{reasons(envelope?.warnings).map((reason, index) => <li key={index}>{reason.replaceAll("_", " ")}</li>)}</ul></details>}
  </section>;
}

function Proposal({ proposal }: { proposal: Record<string, unknown> }) {
  const source = objectValue(proposal.source);
  const evidence = objectValue(proposal.evidence);
  const locator = objectValue(evidence.locator);
  const paper = text(source.paper_id, 200);
  return <li className="min-w-0 rounded border border-slate-200 bg-slate-50 p-3">
    <p className="break-words font-medium">{text(proposal.field, 100) ?? "Unassigned mention"}: {text(proposal.value) ?? "Value unavailable"}</p>
    <p className="mt-1">Pending review · {text(proposal.association, 100)?.replaceAll("_", " ") ?? "Unresolved association"}</p>
    <p className="mt-1 break-all">Proposal: {text(proposal.proposal_id, 200) ?? "Unavailable"}</p>
    {paper && <Link className="mt-1 inline-block break-all text-sky-800 underline" href={`/paper/${encodeURIComponent(paper)}`}>{paper}</Link>}
    <p className="mt-1 break-all">Reported source content hash: {text(source.content_sha256, 64) ?? "Unknown"} · publication revision: {text(source.publication_revision, 200) ?? "Unknown"}</p>
    <p className="mt-1 text-amber-900">Source bytes and source revision are not independently rechecked by this page.</p>
    <p className="mt-2 text-slate-600">Source excerpt withheld pending access and redistribution review. Source availability does not establish permission to publish an excerpt.</p>
    <p className="mt-1 break-all">Reported excerpt hash: {text(evidence.text_sha256, 64) ?? "Unknown"}</p>
    <p className="mt-2">Locator: {text(locator.kind, 100) ?? "Unknown"} · {count(locator.start) ?? "?"}–{count(locator.end) ?? "?"}. Assembled-text offsets are not PDF page numbers.</p>
    <Context value={proposal.subject} />
    {reasons(proposal.reason_codes).length > 0 && <p className="mt-2 text-amber-900">{reasons(proposal.reason_codes).map(reason => reason.replaceAll("_", " ")).join("; ")}</p>}
  </li>;
}

function Context({ value }: { value: unknown }) {
  const raw = objectValue(value);
  const safe: Record<string, unknown> = {};
  for (const key of ["formula", "formula_raw", "sample_id", "sample_label", "run_id", "state_id", "structure_id", "doping_type"]) if (text(raw[key], 200)) safe[key] = raw[key];
  for (const key of ["pressure", "doping"]) {
    const quantity = objectValue(raw[key]);
    const fields = Object.fromEntries(["state", "status", "relation", "value", "lower", "upper", "unit", "uncertainty"].filter(name => text(quantity[name], 100) || typeof quantity[name] === "number" && Number.isFinite(quantity[name])).map(name => [name, quantity[name]]));
    if (Object.keys(fields).length) safe[key] = fields;
  }
  return <div className="mt-2"><span className="font-medium">Proposed subject / state: </span>{Object.keys(safe).length ? <pre className="mt-1 whitespace-pre-wrap break-words text-[10px]">{JSON.stringify(safe, null, 2)}</pre> : "Unresolved"}</div>;
}
