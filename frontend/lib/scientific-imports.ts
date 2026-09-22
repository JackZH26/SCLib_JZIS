/** Bounded local byte preparation and an allowlisted private receipt projection.
 * No scientific program is executed, fetched, repaired or approved here.
 */
type Obj = Record<string, unknown>;
export const IMPORT_LIMITS = { manifest: 65536, files: 16, file: 4 * 1024 * 1024,
  package: 8 * 1024 * 1024, force: 8 * 1024 * 1024, request: 24 * 1024 * 1024, response: 8 * 1024 * 1024 };
const authorityKeys = ["scientific_accepted", "ml_training_approved", "public_release", "execution_attested", "source_time_verified", "redistribution_authorized"];
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: unknown, names: string[]): v is Obj => object(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k));
export const importHash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const wellFormed = (v: string) => !/[\uD800-\uDFFF]/u.test(v);
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && v.length <= max && !/[\u0000-\u001f\u007f]/.test(v) && wellFormed(v);
export const importMaterialId = (v: unknown): v is string => text(v, 100) && v.trim() === v;
export const importLogicalName = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(v) && !v.includes("..");
const requestKey = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v);
const negative = (v: unknown) => keys(v, authorityKeys) && authorityKeys.every(k => v[k] === false);
const copy = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
export class ImportInputError extends Error {}
function requireInput(condition: unknown, message: string): asserts condition { if (!condition) throw new ImportInputError(message); }

export type ImportAccess = { version: string; actor_user_id: string; actor_grant_id: string; can_read: true; can_import: true; compiler_sha256: string; authority: Record<string, false> };
export type ImportBinding = { material_id: string; material_row_sha256: string; material_formula: string };
export type ImportFileEntry = { role: "input" | "frequency" | "license" | "provenance"; logical_name: string; sha256: string; size_bytes: number };
export type ImportManifest = { version: "scientific-program-package/1.0.0"; adapter_id: "qe-matdyn-flfrq"; files: ImportFileEntry[];
  context: { material_formula: string | null; material_id: string | null; geometry_scope: "bulk_3d" | "other" | "unknown"; source_url: string | null; source_revision: string | null; license_spdx: string | null };
  declarations: { review_status: "unreviewed"; execution_attested: false; ml_training_approved: false } };
export type ImportContext = { version: "scientific-import-context/1.0.0"; material_id: string; expected_material_row_sha256: string;
  force_constants: { logical_name: string; sha256: string; size_bytes: number } | null };
export type ImportRequest = { request_key: string; dry_run: boolean; manifest: ImportManifest; expected_manifest_sha256: string;
  artifact_bytes_base64: Record<string, string>; context: ImportContext; force_constants_bytes_base64: string | null; expected_request_sha256: string };
export type ImportRecovery = { actorId: string; requestKey: string; requestSha256: string };
export type ImportReceipt = { attemptId: string; packageId: string; requestSha256: string; actorGrantId: string;
  status: "success_pending" | "quarantined" | "failed" | "outcome_unknown"; outcomeId: string | null; reportSha256: string | null;
  reasons: string[]; rowIds: { run: string; state: string; structure: string; event: string; property: string } | null;
  costs: { import_wall_ms: number | null; import_cpu_ms: number | null } | null; replayed: boolean };

export function knownImportAccess(v: unknown): ImportAccess | null {
  return keys(v, ["version", "actor_user_id", "actor_grant_id", "can_read", "can_import", "compiler_sha256", "authority"])
    && v.version === "scientific-import-capabilities/1.0.0" && uuid(v.actor_user_id) && uuid(v.actor_grant_id)
    && v.can_read === true && v.can_import === true && importHash(v.compiler_sha256) && negative(v.authority) ? copy(v) : null;
}
export function knownImportBinding(v: unknown, materialId: string): ImportBinding | null {
  return keys(v, ["material_id", "material_row_sha256", "material_formula"]) && v.material_id === materialId
    && importMaterialId(materialId) && importHash(v.material_row_sha256) && text(v.material_formula, 1000) ? copy(v) : null;
}
export function knownImportManifest(v: unknown): ImportManifest | null {
  if (!keys(v, ["version", "adapter_id", "files", "context", "declarations"]) || v.version !== "scientific-program-package/1.0.0"
    || v.adapter_id !== "qe-matdyn-flfrq" || !keys(v.declarations, ["review_status", "execution_attested", "ml_training_approved"])
    || v.declarations.review_status !== "unreviewed" || v.declarations.execution_attested !== false || v.declarations.ml_training_approved !== false
    || !keys(v.context, ["material_formula", "material_id", "geometry_scope", "source_url", "source_revision", "license_spdx"])
    || !["bulk_3d", "other", "unknown"].includes(v.context.geometry_scope as string)) return null;
  for (const [field, limit] of [["material_formula", 200], ["material_id", 100], ["source_url", 2048], ["source_revision", 160], ["license_spdx", 120]] as const) {
    if (v.context[field] !== null && !text(v.context[field], limit)) return null;
  }
  if (v.context.source_url !== null) {
    try { const url = new URL(v.context.source_url as string); if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null; } catch { return null; }
  }
  if (!Array.isArray(v.files) || v.files.length < 2 || v.files.length > IMPORT_LIMITS.files) return null;
  const names = new Set<string>(), sizes = new Map<string, number>();
  for (const f of v.files) {
    if (!keys(f, ["role", "logical_name", "sha256", "size_bytes"]) || !["input", "frequency", "license", "provenance"].includes(f.role as string)
      || !importLogicalName(f.logical_name) || names.has(f.logical_name) || !importHash(f.sha256) || !integer(f.size_bytes, 1, IMPORT_LIMITS.file)
      || sizes.has(f.sha256) && sizes.get(f.sha256) !== f.size_bytes) return null;
    names.add(f.logical_name); sizes.set(f.sha256, f.size_bytes);
  }
  if (v.files.filter(f => f.role === "input").length !== 1 || v.files.filter(f => f.role === "frequency").length !== 1) return null;
  return copy(v);
}

/** Only the closed manifest/context/package (integer-only JSON) use this codec.
 * Never apply it to floating-point native reports or SQL row projections.
 */
export function importCanonical(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.map(importCanonical).join(",") + "]";
  if (object(v)) return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + importCanonical(v[k])).join(",") + "}";
  requireInput(v === null || typeof v === "boolean" || typeof v === "string" && wellFormed(v) || integer(v), "Unsupported canonical metadata value.");
  return JSON.stringify(v);
}
const encoded = (v: unknown) => new TextEncoder().encode(importCanonical(v));
export async function importBytesHash(bytes: Uint8Array): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(b => b.toString(16).padStart(2, "0")).join("");
}
export const importDigest = (v: unknown) => importBytesHash(encoded(v));
async function readFile(file: File, limit: number): Promise<Uint8Array> {
  requireInput(integer(file.size, 1, limit), "A selected file is empty or exceeds its byte limit.");
  const value = new Uint8Array(await file.arrayBuffer());
  requireInput(value.byteLength === file.size && value.byteLength <= limit, "Selected file bytes changed.");
  return value;
}
export async function readImportManifest(file: File, expectedSha256: string): Promise<ImportManifest> {
  requireInput(importHash(expectedSha256), "Enter the independently supplied manifest SHA-256.");
  const raw = await readFile(file, IMPORT_LIMITS.manifest);
  let parsed: unknown;
  try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw)); } catch { throw new ImportInputError("Select a canonical UTF-8 JSON manifest."); }
  const manifest = knownImportManifest(parsed);
  requireInput(manifest, "Manifest fields are outside the supported unreviewed QE package contract.");
  const bytes = encoded(manifest);
  requireInput(bytes.length === raw.length && bytes.every((b, i) => b === raw[i]), "Manifest must be exact canonical UTF-8 JSON: no BOM, duplicate keys, whitespace or trailing newline. It is not repaired automatically.");
  requireInput(await importBytesHash(raw) === expectedSha256, "Manifest does not match the independent SHA-256.");
  const unique = new Map(manifest.files.map(f => [f.sha256, f.size_bytes]));
  requireInput(bytes.length + [...unique.values()].reduce((a, b) => a + b, 0) <= IMPORT_LIMITS.package, "Manifest and original source bytes exceed the 8 MiB package limit.");
  return manifest;
}
function base64(bytes: Uint8Array): string {
  let value = "";
  for (let start = 0; start < bytes.length; start += 32768) value += String.fromCharCode(...bytes.subarray(start, start + 32768));
  return btoa(value);
}
export async function prepareImportRequest(options: { manifest: ImportManifest; manifestSha256: string; binding: ImportBinding;
  files: Record<string, File>; forceFile: File | null; forceName: string; forceSha256: string; compilerSha256: string; requestKey: string }): Promise<ImportRequest> {
  // Capture caller-owned metadata before the first asynchronous byte/hash read.
  options = { ...options, manifest: copy(options.manifest), binding: copy(options.binding), files: { ...options.files } };
  const { manifest, binding, files, forceFile } = options;
  requireInput(knownImportManifest(manifest) && knownImportBinding(binding, binding.material_id) && importHash(options.compilerSha256) && requestKey(options.requestKey), "The local import context is invalid.");
  requireInput(importHash(options.manifestSha256) && await importDigest(manifest) === options.manifestSha256, "The selected manifest changed.");
  requireInput(Object.keys(files).length === manifest.files.length && manifest.files.every(f => Object.hasOwn(files, f.logical_name)), "Select exactly one source file for every logical inventory entry.");
  // Check the complete physical selection before reading any large file.
  for (const entry of manifest.files) requireInput(files[entry.logical_name].size === entry.size_bytes, "A source file size does not match its manifest entry.");
  const unique = new Map(manifest.files.map(f => [f.sha256, f.size_bytes]));
  requireInput(encoded(manifest).length + [...unique.values()].reduce((a, b) => a + b, 0) <= IMPORT_LIMITS.package, "Original package exceeds 8 MiB.");
  requireInput(forceFile ? integer(forceFile.size, 1, IMPORT_LIMITS.force) && importLogicalName(options.forceName) && importHash(options.forceSha256)
    : options.forceName === "" && options.forceSha256 === "", "Pair the optional force-constant file with its logical name and independent SHA-256, or leave all three empty.");
  const context: ImportContext = { version: "scientific-import-context/1.0.0", material_id: binding.material_id,
    expected_material_row_sha256: binding.material_row_sha256, force_constants: forceFile ? { logical_name: options.forceName, sha256: options.forceSha256, size_bytes: forceFile.size } : null };
  const artifacts: Record<string, string> = {};
  for (const entry of manifest.files) {
    const bytes = await readFile(files[entry.logical_name], IMPORT_LIMITS.file);
    requireInput(await importBytesHash(bytes) === entry.sha256, "A source file does not match its manifest SHA-256.");
    if (!Object.hasOwn(artifacts, entry.sha256)) artifacts[entry.sha256] = base64(bytes);
  }
  let forceBytes: string | null = null;
  if (forceFile) {
    const bytes = await readFile(forceFile, IMPORT_LIMITS.force);
    requireInput(await importBytesHash(bytes) === options.forceSha256, "Force-constant bytes do not match the independent SHA-256.");
    forceBytes = base64(bytes);
  }
  const contextSha = await importDigest(context);
  const inventory = manifest.files.map(f => ({ ...f, logical_name: "package/" + f.logical_name }));
  const augmented: { role: string; logical_name: string; sha256: string; size_bytes: number }[] = [...inventory,
    { role: "manifest", logical_name: "import/package.json", sha256: options.manifestSha256, size_bytes: encoded(manifest).length },
    { role: "context", logical_name: "import/context.json", sha256: contextSha, size_bytes: encoded(context).length }];
  if (context.force_constants) augmented.push({ role: "force_constants", ...context.force_constants, logical_name: "force_constants/" + context.force_constants.logical_name });
  const pin = await importDigest({ version: "scientific-pending-import/1.0.0", manifest_sha256: options.manifestSha256,
    context_sha256: contextSha, compiler_sha256: options.compilerSha256, manifest, context, files: augmented });
  const body: ImportRequest = { request_key: options.requestKey, dry_run: true, manifest: copy(manifest), expected_manifest_sha256: options.manifestSha256,
    artifact_bytes_base64: artifacts, context, force_constants_bytes_base64: forceBytes, expected_request_sha256: pin };
  requireInput(new TextEncoder().encode(JSON.stringify(body)).length <= IMPORT_LIMITS.request, "Encoded request exceeds 24 MiB; no upload was sent.");
  return body;
}

/** Validate a bounded envelope, then discard unrendered native report contents.
 * report_sha256 is a server receipt identifier, not a client-verified report hash.
 */
export function knownImportReceipt(value: unknown, binding: { requestSha256: string; mode: "preview" | "commit" | "outcome"; grantId?: string }): ImportReceipt | null {
  let v = value;
  if (!importHash(binding.requestSha256)) return null;
  if (binding.mode !== "outcome") {
    const preview = binding.mode === "preview";
    if (!keys(v, ["version", "dry_run", "committed", "result"]) || v.version !== "scientific-import-operation/1.0.0" || v.dry_run !== preview || v.committed !== !preview) return null;
    v = v.result;
  }
  if (!keys(v, ["attempt_id", "package_id", "request_sha256", "actor_grant_id", "status", "outcome_id", "report_sha256", "report", "row_ids", "costs", "replayed", "authority"])
    || !uuid(v.attempt_id) || !uuid(v.package_id) || !uuid(v.actor_grant_id) || v.request_sha256 !== binding.requestSha256
    || binding.grantId !== undefined && v.actor_grant_id !== binding.grantId || !negative(v.authority) || typeof v.replayed !== "boolean"
    || binding.mode === "outcome" && v.replayed !== true
    || !["success_pending", "quarantined", "failed", "outcome_unknown"].includes(v.status as string)) return null;
  const unknown = v.status === "outcome_unknown";
  let reasons: string[] = [], costs: ImportReceipt["costs"] = null;
  if (unknown) {
    if (binding.mode === "preview" || [v.outcome_id, v.report_sha256, v.report, v.row_ids, v.costs].some(x => x !== null)) return null;
  } else {
    if (!uuid(v.outcome_id) || !importHash(v.report_sha256)) return null;
    const r = v.report, failed = v.status === "failed";
    if (!keys(r, ["version", "status", "reason_codes", "cost_scope", "actual_calculation_costs", "authority", ...(!failed ? ["request_sha256", "preflight", "force_constants", "coordinate_sha256", "coverage", "limitations"] : [])])
      || r.version !== "scientific-pending-import-report/1.0.0" || r.status !== v.status || !negative(r.authority)
      || r.cost_scope !== "parser_worker_only" || r.actual_calculation_costs !== null || !Array.isArray(r.reason_codes) || r.reason_codes.length > 256
      || !r.reason_codes.every(code => typeof code === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(code)) || new Set(r.reason_codes).size !== r.reason_codes.length
      || v.status === "success_pending" && r.reason_codes.length !== 0 || v.status !== "success_pending" && r.reason_codes.length === 0) return null;
    if (!failed) {
      const p = r.preflight, coverage = r.coverage;
      if (r.request_sha256 !== binding.requestSha256 || !(r.coordinate_sha256 === null || importHash(r.coordinate_sha256))
        || !keys(p, ["version", "status", "reason_codes", "package_sha256", "adapter_id", "source_code_sha256", "inventory", "context_declarations", "parse_result", "coverage", "unresolved_gates", "costs", "authority"])
        || p.version !== "scientific-import-native-preflight/1.0.0" || p.adapter_id !== "qe-matdyn-flfrq" || !["parsed", "quarantined"].includes(p.status as string)
        || !importHash(p.package_sha256) || !keys(p.authority, [...authorityKeys, "database_changed", "material_binding_verified"])
        || Object.values(p.authority).some(flag => flag !== false)
        || !keys(coverage, ["source_packages_seen", "parsed_candidates", "scientifically_accepted_properties", "ml_admitted_properties"])
        || coverage.source_packages_seen !== 1 || !integer(coverage.parsed_candidates, 0, 1) || coverage.scientifically_accepted_properties !== 0 || coverage.ml_admitted_properties !== 0
        || !Array.isArray(r.limitations) || r.limitations.length > 32 || !r.limitations.every(code => typeof code === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(code))) return null;
      if (v.status === "success_pending" && (!importHash(r.coordinate_sha256) || p.status !== "parsed" || coverage.parsed_candidates !== 1
        || !object(r.force_constants) || r.force_constants.status !== "parsed" || r.force_constants.coordinate_sha256 !== r.coordinate_sha256)) return null;
    }
    const c = v.costs;
    if (!keys(c, ["cost_scope", "import_wall_ms", "import_cpu_ms", "calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost"])
      || c.cost_scope !== "parser_worker_only" || ![c.import_wall_ms, c.import_cpu_ms].every(n => n === null || integer(n))
      || [c.calculation_cpu_seconds, c.calculation_wall_seconds, c.calculation_monetary_cost].some(n => n !== null)) return null;
    costs = { import_wall_ms: c.import_wall_ms as number | null, import_cpu_ms: c.import_cpu_ms as number | null };
    reasons = [...r.reason_codes] as string[];
  }
  if (v.status === "success_pending") {
    if (!keys(v.row_ids, ["run", "state", "structure", "event", "property"]) || !Object.values(v.row_ids).every(uuid)) return null;
  } else if (v.row_ids !== null) return null;
  return { attemptId: v.attempt_id, packageId: v.package_id, requestSha256: binding.requestSha256, actorGrantId: v.actor_grant_id,
    status: v.status as ImportReceipt["status"], outcomeId: v.outcome_id as string | null, reportSha256: v.report_sha256 as string | null,
    reasons, rowIds: copy(v.row_ids), costs, replayed: v.replayed };
}
