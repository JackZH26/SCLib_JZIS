/** Owner-private native-file returns. Receipt integrity is not authenticated execution. */
import { designClosed, designHash, designId, designObject, designText, type DesignCapabilities, type DesignEligibility, type DesignEntry, type ResearchDesign } from "./discovery-designs";
import { feedbackDesignPin, knownFeedbackDesignPin, type FeedbackDesignPin } from "./discovery-feedback";
import { expressionCanonical, expressionSha, parseExpressionJson } from "./source-expressions";

export const CALCULATION_VERSION = "discovery-calculation-return/1.0.0";
export const CALCULATION_REQUEST_VERSION = "discovery-calculation-operation/1.0.0";
export const CALCULATION_PARSER_VERSION = "qe-pw-native-preflight/1.0.0";
export const CALCULATION_AUTHORITY = { scientific_acceptance: false, ml_training_approved: false, public_release: false, execution_authenticated: false, candidate_source_association_verified: false, canonical_promotions: 0 } as const;
export const CALCULATION_LIMITS = { input: 1048576, file: 8388608, package: 84934656 } as const;
type Authority = typeof CALCULATION_AUTHORITY;
export type CalculationFile = { role: "input" | "xml" | "stdout" | "upf"; name: string; sha256: string; size_bytes: number };
export type CalculationRequest = { version: typeof CALCULATION_REQUEST_VERSION; request_key: string; design: FeedbackDesignPin; files: CalculationFile[]; association: "researcher_linked_unverified"; findings: string; decision: "continue" | "stop" | "redirect"; reason: string; unknowns: string[] };
export type CalculationUpload = { request: CalculationRequest; files_base64: string[] };
export type CalculationCapabilities = Authority & { version: string; request_version: string; actor_user_id: string; session_version: number; curator_grant_id: string; parser_version: string; action_kinds: ["calculation"]; baseline_kinds: string[]; max_package_bytes: number; max_file_bytes: number; max_input_bytes: number; max_files: 11; max_page_size: 8 };
export type CalculationContext = Authority & { version: string; design: FeedbackDesignPin; eligibility: DesignEligibility; next_action: ResearchDesign["next_action"]; association: "researcher_linked_unverified" };
export type CalculationReceipt = Authority & { version: string; receipt_id: string; receipt_sha256: string; request_sha256: string; preview_sha256: string; request_key: string; design: FeedbackDesignPin; report_sha256: string; report_version: string; request_canonical_json: string; preview_canonical_json: string; receipt_canonical_json: string; replayed: boolean; dry_run: boolean; private_ledger_written: boolean };
/** No file names, raw bytes, findings, quantities or notes survive a private-view clear. */
export type CalculationRecovery = { actorId: string; requestKey: string; requestSha: string; previewSha: string; receiptSha: string; receiptId: string; reportSha: string; design: FeedbackDesignPin };
export type CalculationEntry = { receipt: CalculationReceipt; request: CalculationRequest; eligibility: DesignEligibility };
export type CalculationPage = { entries: CalculationEntry[]; offset: number; total: number; limit: 8; design_id: string };
export type CalculationQuantity = { value: number; raw: string; unit: string; xml_path: string };
export type CalculationReport = Record<string, unknown> & { version: string; status: string; engine: { name: string; version: string }; observations: { total_energy: CalculationQuantity | null; fermi_energy: CalculationQuantity | null; valence_electrons: CalculationQuantity | null }; convergence: { electronic_reported: boolean; ionic_reported: boolean | null; scf_steps: number; basis_sampling_convergence_established: false } };
export type CalculationReading = CalculationEntry & { report: CalculationReport | null; reportText: string | null };
const AUTH = Object.keys(CALCULATION_AUTHORITY).join(" ");
const RECEIPT = `version receipt_id receipt_sha256 request_sha256 preview_sha256 request_key design report_sha256 report_version request_canonical_json preview_canonical_json receipt_canonical_json replayed dry_run private_ledger_written ${AUTH}`;
const key = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v);
const count = (v: unknown, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
function same(a: unknown, b: unknown): boolean {
  let nodes = 0;
  function equal(left: unknown, right: unknown, depth: number): boolean {
    if (++nodes > 40000 || depth > 20) return false;
    if (left === right && (left === null || typeof left !== "object")) return left === null || typeof left === "string" || typeof left === "boolean" || typeof left === "number" && Number.isFinite(left);
    if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((v, i) => equal(v, right[i], depth + 1));
    if (!designObject(left) || !designObject(right)) return false;
    const keys = Object.keys(left); return keys.length === Object.keys(right).length && keys.every(k => Object.hasOwn(right, k) && equal(left[k], right[k], depth + 1));
  }
  return equal(a, b, 0);
}
const authority = (v: Record<string, unknown>) => Object.entries(CALCULATION_AUTHORITY).every(([k, val]) => v[k] === val);
function eligibility(v: unknown): v is DesignEligibility { return designClosed(v, "eligible reason_codes") && typeof v.eligible === "boolean" && Array.isArray(v.reason_codes) && v.reason_codes.length <= 32 && v.reason_codes.every(r => typeof r === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(r)) && new Set(v.reason_codes).size === v.reason_codes.length && v.eligible === (v.reason_codes.length === 0); }
function file(v: unknown): v is CalculationFile { return designClosed(v, "role name sha256 size_bytes") && ["input", "xml", "stdout", "upf"].includes(String(v.role)) && typeof v.name === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(v.name) && !v.name.includes("..") && designHash(v.sha256) && count(v.size_bytes, v.role === "input" ? CALCULATION_LIMITS.input : CALCULATION_LIMITS.file) && v.size_bytes > 0; }
export function knownCalculationRequest(v: unknown): v is CalculationRequest {
  if (!designClosed(v, "version request_key design files association findings decision reason unknowns") || v.version !== CALCULATION_REQUEST_VERSION || !key(v.request_key) || !knownFeedbackDesignPin(v.design) || v.association !== "researcher_linked_unverified" || !designText(v.findings, 4000) || !designText(v.reason, 2000) || !["continue", "stop", "redirect"].includes(String(v.decision)) || !Array.isArray(v.unknowns) || v.unknowns.length > 16 || !v.unknowns.every(s => designText(s, 1000)) || new Set(v.unknowns).size !== v.unknowns.length || !Array.isArray(v.files) || v.files.length < 4 || v.files.length > 11 || !v.files.every(file)) return false;
  const fs = v.files, ids = fs.map(f => `${f.role}:${f.name}`);
  return new Set(ids).size === ids.length && same(ids, [...ids].sort()) && ["input", "xml", "stdout"].every(role => fs.filter(f => f.role === role).length === 1) && fs.some(f => f.role === "upf") && fs.reduce((n, f) => n + f.size_bytes, 0) <= CALCULATION_LIMITS.package && new TextEncoder().encode(expressionCanonical(v)).length <= 32768;
}
export function knownCalculationRecovery(v: unknown): v is CalculationRecovery { return designClosed(v, "actorId requestKey requestSha previewSha receiptSha receiptId reportSha design") && designId(v.actorId) && key(v.requestKey) && [v.requestSha, v.previewSha, v.receiptSha, v.reportSha].every(designHash) && designId(v.receiptId) && knownFeedbackDesignPin(v.design); }
export function knownCalculationCapabilities(value: unknown, design: DesignCapabilities): CalculationCapabilities | null {
  const v = structuredClone(value);
  if (!designClosed(v, `version request_version actor_user_id session_version curator_grant_id parser_version action_kinds baseline_kinds max_package_bytes max_file_bytes max_input_bytes max_files max_page_size ${AUTH}`) || !authority(v) || v.version !== CALCULATION_VERSION || v.request_version !== CALCULATION_REQUEST_VERSION || v.parser_version !== CALCULATION_PARSER_VERSION || v.actor_user_id !== design.actor_user_id || v.curator_grant_id !== design.curator_grant_id || v.session_version !== design.session_version || !same(v.action_kinds, ["calculation"]) || !same(v.baseline_kinds, ["unanchored", "retained_result", "native_property"]) || v.max_files !== 11 || v.max_page_size !== 8 || v.max_package_bytes !== CALCULATION_LIMITS.package || v.max_file_bytes !== CALCULATION_LIMITS.file || v.max_input_bytes !== CALCULATION_LIMITS.input) return null;
  return v as CalculationCapabilities;
}
export async function knownCalculationContext(value: unknown, entry: DesignEntry): Promise<CalculationContext | null> {
  const v = structuredClone(value), e = structuredClone(entry), pin = await feedbackDesignPin(e);
  if (!designClosed(v, `version design eligibility next_action association ${AUTH}`) || !authority(v) || v.version !== CALCULATION_VERSION || !pin || !same(v.design, pin) || !same(v.next_action, e.design.next_action) || !eligibility(v.eligibility) || v.association !== "researcher_linked_unverified") return null;
  return v as CalculationContext;
}
async function proof(text: unknown, hash: unknown, limit = 262144) {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > limit || !designHash(hash) || await expressionSha(text) !== hash) return null;
  try { const v = parseExpressionJson(text); return designObject(v) && expressionCanonical(v) === text ? v : null; } catch { return null; }
}
type Expectation = Pick<CalculationRecovery, "actorId" | "requestKey" | "requestSha" | "design"> & Partial<CalculationRecovery>;
export async function knownCalculationReceipt(value: unknown, cap: CalculationCapabilities, expected: Expectation, mode: "preview" | "commit" | "outcome" | "history"): Promise<CalculationEntry | null> {
  const v = structuredClone(value), c = structuredClone(cap), exp = structuredClone(expected);
  if (!designClosed(v, RECEIPT) || !authority(v) || v.version !== CALCULATION_VERSION || !designId(v.receipt_id) || ![v.receipt_sha256, v.request_sha256, v.preview_sha256, v.report_sha256].every(designHash) || v.report_version !== CALCULATION_PARSER_VERSION || !knownFeedbackDesignPin(v.design) || !same(v.design, exp.design) || v.request_key !== exp.requestKey || v.request_sha256 !== exp.requestSha || c.actor_user_id !== exp.actorId || typeof v.replayed !== "boolean" || typeof v.dry_run !== "boolean" || typeof v.private_ledger_written !== "boolean") return null;
  if (mode === "preview" ? v.dry_run !== !v.replayed || v.private_ledger_written !== v.replayed : v.dry_run || !v.private_ledger_written) return null;
  if (mode === "outcome" && !v.replayed || mode === "history" && v.replayed) return null;
  for (const [k, field] of [["previewSha", "preview_sha256"], ["receiptSha", "receipt_sha256"], ["receiptId", "receipt_id"], ["reportSha", "report_sha256"]] as const) if (exp[k] !== undefined && exp[k] !== v[field]) return null;
  const req = await proof(v.request_canonical_json, v.request_sha256, 32768), preview = await proof(v.preview_canonical_json, v.preview_sha256), receipt = await proof(v.receipt_canonical_json, v.receipt_sha256);
  if (!knownCalculationRequest(req) || !same(req.design, v.design) || req.request_key !== v.request_key || !designClosed(preview, "version receipt_id actor request_sha256 report_sha256 report_version design") || !designClosed(preview.actor, "actor_user_id actor_grant_id actor_session_version") || !designClosed(receipt, "id actor_user_id actor_grant_id actor_session_version design_revision_id design_ref request_key request_json request_sha256 files report_version report_sha256 preview_json preview_sha256")) return null;
  const actor = preview.actor;
  if (actor.actor_user_id !== c.actor_user_id || !designId(actor.actor_grant_id) || !count(actor.actor_session_version) || (!v.replayed && (mode === "preview" || mode === "commit") && (actor.actor_grant_id !== c.curator_grant_id || actor.actor_session_version !== c.session_version))) return null;
  if (!same(preview, { version: CALCULATION_VERSION, receipt_id: v.receipt_id, actor, request_sha256: v.request_sha256, report_sha256: v.report_sha256, report_version: CALCULATION_PARSER_VERSION, design: v.design }) || !same(receipt, { id: v.receipt_id, ...actor, design_revision_id: v.design.revision_id, design_ref: v.design, request_key: v.request_key, request_json: v.request_canonical_json, request_sha256: v.request_sha256, files: req.files, report_version: CALCULATION_PARSER_VERSION, report_sha256: v.report_sha256, preview_json: v.preview_canonical_json, preview_sha256: v.preview_sha256 })) return null;
  return { receipt: v as CalculationReceipt, request: req, eligibility: { eligible: false, reason_codes: ["current_scope_not_loaded"] } };
}
function quantity(v: unknown, unit: string): v is CalculationQuantity | null {
  if (v === null) return true;
  return designClosed(v, "value raw unit xml_path") && typeof v.value === "number" && Number.isFinite(v.value) && typeof v.raw === "string" && v.raw.length <= 200 && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$/.test(v.raw) && Number(v.raw.replace(/[dD]/, "e")) === v.value && v.unit === unit && typeof v.xml_path === "string" && v.xml_path.startsWith("output/");
}
/** Hash the backend's original decimal tokens; do not rewrite Python's 1.0 as JavaScript's 1. */
async function report(value: unknown, text: unknown, receipt: CalculationReceipt, request: CalculationRequest): Promise<CalculationReport | null> {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > 262144 || await expressionSha(text) !== receipt.report_sha256) return null;
  const r = parseExpressionJson(text, false);
  if (!same(r, value) || !designClosed(r, "version files input pseudopotentials expected_valence_electrons status engine convergence observations consistency interpretation scientific_scope authority") || r.version !== CALCULATION_PARSER_VERSION || !designObject(r.authority) || !same(r.authority, { execution_authenticated: false, pseudopotential_execution_bytes_attested: false, candidate_source_association_verified: false, scientific_acceptance: false, ml_training_approved: false, database_write: false, public_release: false }) || !same(r.scientific_scope, { target_temperature_k: null, target_pressure_gpa: null, stable_host_validated: false, phonons_calculated: false, tc_calculated: false }) || !["initialization_only", "incomplete", "scf_not_converged", "ionic_not_converged", "relaxation_reported_converged", "scf_reported_converged"].includes(String(r.status))) return null;
  if (!Array.isArray(r.files) || r.files.length !== request.files.length) return null;
  const inventory = request.files.map(f => f.role === "upf" ? { role: "pseudopotential", filename: f.name, size_bytes: f.size_bytes, sha256: f.sha256 } : { role: f.role, size_bytes: f.size_bytes, sha256: f.sha256 });
  if (!r.files.every(f => inventory.some(expected => same(f, expected))) || new Set(r.files.map(f => expressionCanonical(f))).size !== inventory.length) return null;
  const o = r.observations, c = r.convergence, e = r.engine;
  if (!designClosed(o, "total_energy fermi_energy valence_electrons forces stress final_atoms") || !quantity(o.total_energy, "Hartree/cell") || !quantity(o.fermi_energy, "Hartree") || !quantity(o.valence_electrons, "electrons/cell") || !designClosed(c, "electronic_reported scf_steps scf_error_hartree electronic_threshold_hartree ionic_reported ionic_steps basis_sampling_convergence_established") || typeof c.electronic_reported !== "boolean" || !count(c.scf_steps) || !(c.ionic_reported === null || typeof c.ionic_reported === "boolean") || c.basis_sampling_convergence_established !== false || !designClosed(e, "name version xml_format xml_units reported_exit_status nprocs nthreads") || e.name !== "PWSCF" || e.version !== "7.5" || e.xml_format !== "QEXSD 25.05.21" || e.xml_units !== "Hartree atomic units") return null;
  if (r.status === "initialization_only" && (c.electronic_reported || c.scf_steps !== 0 || Object.values(o).some(v => v !== null))) return null;
  return r as CalculationReport;
}
export async function knownCalculationPreview(value: unknown, cap: CalculationCapabilities, expected: Expectation) {
  const v = structuredClone(value);
  if (!designObject(v)) return null;
  const { report: r, report_canonical_json: text, ...receipt } = v;
  const checked = await knownCalculationReceipt(receipt, cap, expected, "preview");
  if (!checked) return null;
  if (checked.receipt.replayed) return r === undefined && text === undefined ? { ...checked, report: null, reportText: null } : null;
  const parsed = await report(r, text, checked.receipt, checked.request);
  return parsed ? { ...checked, eligibility: { eligible: true, reason_codes: [] }, report: parsed, reportText: text as string } : null;
}
export async function knownCalculationPage(value: unknown, cap: CalculationCapabilities, designId: string, offset: number): Promise<CalculationPage | null> {
  const v = structuredClone(value);
  if (!designClosed(v, `version design_id offset limit total entries ${AUTH}`) || !authority(v) || v.version !== CALCULATION_VERSION || v.design_id !== designId || v.offset !== offset || v.limit !== 8 || !count(v.total) || !Array.isArray(v.entries) || v.entries.length !== Math.min(8, Math.max(0, v.total - offset))) return null;
  const entries: CalculationEntry[] = [];
  for (const e of v.entries) {
    if (!designClosed(e, "receipt eligibility") || !eligibility(e.eligibility) || !designObject(e.receipt) || !knownFeedbackDesignPin(e.receipt.design) || e.receipt.design.design_id !== designId) return null;
    const checked = await knownCalculationReceipt(e.receipt, cap, { actorId: cap.actor_user_id, requestKey: String(e.receipt.request_key), requestSha: String(e.receipt.request_sha256), design: e.receipt.design }, "history");
    if (!checked || entries.some(item => item.receipt.receipt_id === checked.receipt.receipt_id)) return null;
    entries.push({ ...checked, eligibility: e.eligibility });
  }
  return { entries, offset, limit: 8, total: v.total, design_id: designId };
}
export async function knownCalculationReading(value: unknown, cap: CalculationCapabilities, selected: CalculationEntry): Promise<CalculationReading | null> {
  const v = structuredClone(value), s = structuredClone(selected);
  if (!designClosed(v, `receipt eligibility report report_canonical_json ${AUTH}`) || !authority(v) || !eligibility(v.eligibility)) return null;
  const checked = await knownCalculationReceipt(v.receipt, cap, calculationRecovery(s.receipt, cap.actor_user_id), "history");
  if (!checked) return null;
  if (!v.eligibility.eligible) return v.report === null && v.report_canonical_json === null ? { ...checked, eligibility: v.eligibility, report: null, reportText: null } : null;
  const parsed = await report(v.report, v.report_canonical_json, checked.receipt, checked.request);
  return parsed ? { ...checked, eligibility: v.eligibility, report: parsed, reportText: v.report_canonical_json as string } : null;
}
export function calculationRecovery(r: CalculationReceipt, actorId: string): CalculationRecovery { return { actorId, requestKey: r.request_key, requestSha: r.request_sha256, previewSha: r.preview_sha256, receiptSha: r.receipt_sha256, receiptId: r.receipt_id, reportSha: r.report_sha256, design: structuredClone(r.design) }; }
export async function calculationByteSha(bytes: Uint8Array): Promise<string> { return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes)))).map(n => n.toString(16).padStart(2, "0")).join(""); }
export async function prepareCalculationUpload(request: Omit<CalculationRequest, "files">, sources: { role: CalculationFile["role"]; file: File }[]): Promise<CalculationUpload> {
  const sorted = [...sources].sort((a, b) => `${a.role}:${a.file.name}` < `${b.role}:${b.file.name}` ? -1 : 1);
  const files = sorted.map(s => ({ role: s.role, name: s.file.name, size_bytes: s.file.size, sha256: "0".repeat(64) }));
  if (!knownCalculationRequest({ ...request, files })) throw new Error("Choose one input, XML and stdout file, plus 1–8 distinct UPFs. Use safe file names and the stated size limits; complete findings and decision fields.");
  const encoded: string[] = [];
  for (let i = 0; i < sorted.length; i++) {
    const bytes = new Uint8Array(await sorted[i].file.arrayBuffer());
    if (bytes.length !== files[i].size_bytes) throw new Error("A selected file changed during reading. Select it again.");
    files[i].sha256 = await calculationByteSha(bytes);
    let binary = ""; for (let j = 0; j < bytes.length; j += 32768) binary += String.fromCharCode(...bytes.subarray(j, j + 32768));
    encoded.push(btoa(binary));
  }
  return { request: { ...structuredClone(request), files }, files_base64: encoded };
}
