/** Closed private RPS display wire. Hash checks are not legal authorization. */
export const RIGHTS_VERSION = "rps-rights-preparation/1.0.0";
export const RIGHTS_LICENSES = ["CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"] as const;
type Obj = Record<string, unknown>;
type Authority = { scientific_acceptance: false; ml_training_approved: false; current_authorization_checked: false };
export type RightsAccess = Authority & { version: typeof RIGHTS_VERSION; scope: "rps_structured_bundle";
  actor_user_id: string; actor_grant_id: string; can_read: true; can_prepare: true };
export type RightsDependency = { dependency_id: string; table: string; row_id: string; row_sha256: string };
export type RightsHead = { id: string; record_sha256: string; decision: "allow" | "revoke"; license_code: string; basis_code: string; reason_code: string };
export type RightsPage = Authority & { version: typeof RIGHTS_VERSION; actor_user_id: string; actor_grant_id: string;
  package_id: string; package_record_sha256: string; inventory_sha256: string; dependency_count: number;
  dependencies: RightsDependency[]; next_after: string | null };
export type RightsContext = Authority & { version: typeof RIGHTS_VERSION; actor_user_id: string; actor_grant_id: string;
  package_id: string; package_record_sha256: string; inventory_sha256: string; public_bundle_sha256: string;
  dependency: RightsDependency & { record_sha256: string | null; bytes_sha256: string | null }; head: RightsHead | null };
export type RightsInput = { request_key: string; decision: "allow" | "revoke"; license_code: string; basis_code: string; reason_code: string;
  expected_package_sha256: string; expected_inventory_sha256: string; expected_dependency_row_sha256: string;
  expected_head_id: string | null; expected_head_sha256: string | null; dry_run?: boolean; expected_intent_sha256?: string };
export type RightsIntent = Authority & { version: typeof RIGHTS_VERSION; scope: "rps_structured_bundle";
  package_id: string; package_record_sha256: string; inventory_sha256: string; public_bundle_sha256: string;
  dependency_id: string; dependency_row_sha256: string; actor_user_id: string; actor_grant_id: string;
  request_key: string; decision: "allow" | "revoke"; license_code: string; basis_code: string; reason_code: string;
  expected_head_id: string | null; expected_head_sha256: string | null; rights_bytes_sha256: string };
export type RightsDocument = { version: "rps-distribution-rights/1.0.0"; scope: "rps_structured_bundle"; package_id: string;
  inventory_sha256: string; dependency_id: string; dependency_row_sha256: string; public_bundle_sha256: string;
  license_code: string; basis_code: string; distribution_permitted: true; scientific_acceptance: false; ml_training_approved: false };
export type RightsResult = Authority & { version: typeof RIGHTS_VERSION; dry_run: boolean; committed: false; replayed: boolean;
  intent: RightsIntent; intent_sha256: string; rights_document: RightsDocument; rights_bytes_sha256: string;
  permission: { id: string; record_sha256: string } | null; artifact: { id: string; row_sha256: string; bytes_sha256: string } | null };
export type RightsRecovery = { actorId: string; packageId: string; dependencyId: string; requestKey: string; intentSha256: string };
const authorityKeys = ["scientific_acceptance", "ml_training_approved", "current_authorization_checked"];
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: unknown, expected: string[]): v is Obj => object(v) && Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
export const rightsUuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
export const rightsHash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
export const rightsCode = (v: unknown): v is string => typeof v === "string" && /^[a-z][a-z0-9_]{0,159}$/.test(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 200 && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
const license = (v: unknown) => typeof v === "string" && (RIGHTS_LICENSES as readonly string[]).includes(v);
const decision = (v: unknown) => v === "allow" || v === "revoke";
const requestKey = (v: unknown) => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$/.test(v);
const negative = (v: Obj) => authorityKeys.every(k => v[k] === false);
const nullableHash = (v: unknown) => v === null || rightsHash(v);
const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
function canonical(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (object(v)) return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
  return JSON.stringify(v);
}
export async function rightsDigest(v: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(v));
  if (bytes.length > 65536) throw new Error("Rights response exceeds limits");
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(b => b.toString(16).padStart(2, "0")).join("");
}
function head(v: unknown): boolean {
  return v === null || keys(v, ["id", "record_sha256", "decision", "license_code", "basis_code", "reason_code"])
    && rightsUuid(v.id) && rightsHash(v.record_sha256) && decision(v.decision) && license(v.license_code) && rightsCode(v.basis_code) && rightsCode(v.reason_code);
}
function dependency(v: unknown, detailed = false): boolean {
  return keys(v, ["dependency_id", "table", "row_id", "row_sha256", ...(detailed ? ["record_sha256", "bytes_sha256"] : [])])
    && rightsHash(v.dependency_id) && rightsCode(v.table) && text(v.row_id) && rightsHash(v.row_sha256)
    && (!detailed || nullableHash(v.record_sha256) && nullableHash(v.bytes_sha256));
}
export function knownRightsAccess(v: unknown): RightsAccess | null {
  return keys(v, ["version", "scope", "actor_user_id", "actor_grant_id", "can_read", "can_prepare", ...authorityKeys])
    && v.version === RIGHTS_VERSION && v.scope === "rps_structured_bundle" && rightsUuid(v.actor_user_id) && rightsUuid(v.actor_grant_id)
    && v.can_read === true && v.can_prepare === true && negative(v) ? clone(v) : null;
}
const sameActor = (v: Obj, a: RightsAccess) => v.actor_user_id === a.actor_user_id && v.actor_grant_id === a.actor_grant_id;
export function knownRightsPage(v: unknown, access: RightsAccess, packageId: string, after: string | null = null, inventory?: string): RightsPage | null {
  if (!keys(v, ["version", "actor_user_id", "actor_grant_id", "package_id", "package_record_sha256", "inventory_sha256", "dependency_count", "dependencies", "next_after", ...authorityKeys])
    || v.version !== RIGHTS_VERSION || !sameActor(v, access) || v.package_id !== packageId || !rightsUuid(packageId) || !negative(v)
    || !rightsHash(v.package_record_sha256) || !rightsHash(v.inventory_sha256) || inventory !== undefined && inventory !== v.inventory_sha256
    || typeof v.dependency_count !== "number" || !Number.isSafeInteger(v.dependency_count) || v.dependency_count < 1 || v.dependency_count > 20000
    || !Array.isArray(v.dependencies) || v.dependencies.length > 25 || v.dependencies.length > v.dependency_count
    || !v.dependencies.every(d => dependency(d)) || !nullableHash(v.next_after)) return null;
  const ids = (v.dependencies as RightsDependency[]).map(d => d.dependency_id);
  if (new Set(ids).size !== ids.length || ids.some((id, i) => i > 0 && id <= ids[i - 1] || after !== null && id <= after)
    || v.next_after !== null && (ids.length !== 25 || v.next_after !== ids.at(-1))) return null;
  return clone(v);
}
export function knownRightsContext(v: unknown, access: RightsAccess, page: RightsPage, selected: RightsDependency): RightsContext | null {
  if (!keys(v, ["version", "actor_user_id", "actor_grant_id", "package_id", "package_record_sha256", "inventory_sha256", "public_bundle_sha256", "dependency", "head", ...authorityKeys])
    || v.version !== RIGHTS_VERSION || !sameActor(v, access) || !negative(v) || v.package_id !== page.package_id
    || v.package_record_sha256 !== page.package_record_sha256 || v.inventory_sha256 !== page.inventory_sha256
    || !rightsHash(v.public_bundle_sha256) || !dependency(v.dependency, true) || !head(v.head)) return null;
  if (Object.entries(selected).some(([key, value]) => (v.dependency as Obj)[key] !== value)) return null;
  return clone(v);
}
function knownDocument(v: unknown): v is RightsDocument {
  return keys(v, ["version", "scope", "package_id", "inventory_sha256", "dependency_id", "dependency_row_sha256", "public_bundle_sha256",
    "license_code", "basis_code", "distribution_permitted", "scientific_acceptance", "ml_training_approved"])
    && v.version === "rps-distribution-rights/1.0.0" && v.scope === "rps_structured_bundle" && rightsUuid(v.package_id)
    && [v.inventory_sha256, v.dependency_id, v.dependency_row_sha256, v.public_bundle_sha256].every(rightsHash)
    && license(v.license_code) && rightsCode(v.basis_code) && v.distribution_permitted === true && v.scientific_acceptance === false && v.ml_training_approved === false;
}
export async function knownRightsResult(v: unknown, binding: RightsRecovery & { committed: boolean; request?: RightsInput; grantId?: string; publicBundleSha256?: string }): Promise<RightsResult | null> {
  if (binding.committed && !rightsHash(binding.intentSha256)) return null;
  if (!keys(v, ["version", "dry_run", "committed", "result"]) || v.version !== "research-distribution-operation/1.0.0"
    || v.dry_run !== !binding.committed || v.committed !== binding.committed) return null;
  const r = v.result;
  if (!keys(r, ["version", "dry_run", "committed", "replayed", "intent", "intent_sha256", "rights_document", "rights_bytes_sha256", "permission", "artifact", ...authorityKeys])
    || r.version !== RIGHTS_VERSION || !negative(r) || r.committed !== false || r.dry_run !== !binding.committed || typeof r.replayed !== "boolean"
    || !rightsHash(r.intent_sha256) || !rightsHash(r.rights_bytes_sha256) || !knownDocument(r.rights_document)) return null;
  const i = r.intent;
  if (!keys(i, ["version", "scope", "package_id", "package_record_sha256", "inventory_sha256", "public_bundle_sha256", "dependency_id", "dependency_row_sha256",
    "actor_user_id", "actor_grant_id", "request_key", "decision", "license_code", "basis_code", "reason_code", "expected_head_id", "expected_head_sha256", "rights_bytes_sha256", ...authorityKeys])
    || i.version !== RIGHTS_VERSION || i.scope !== "rps_structured_bundle" || !negative(i) || !rightsUuid(i.package_id) || !rightsUuid(i.actor_user_id) || !rightsUuid(i.actor_grant_id)
    || i.actor_user_id !== binding.actorId || i.package_id !== binding.packageId || i.dependency_id !== binding.dependencyId || i.request_key !== binding.requestKey
    || binding.grantId !== undefined && i.actor_grant_id !== binding.grantId || binding.publicBundleSha256 !== undefined && i.public_bundle_sha256 !== binding.publicBundleSha256
    || !requestKey(i.request_key) || !decision(i.decision) || !license(i.license_code)
    || !rightsCode(i.basis_code) || !rightsCode(i.reason_code) || ![i.package_record_sha256, i.inventory_sha256, i.public_bundle_sha256, i.dependency_id, i.dependency_row_sha256, i.rights_bytes_sha256].every(rightsHash)
    || !(i.expected_head_id === null || rightsUuid(i.expected_head_id)) || !nullableHash(i.expected_head_sha256)
    || (i.expected_head_id === null) !== (i.expected_head_sha256 === null) || i.decision === "revoke" && i.expected_head_id === null) return null;
  const d = r.rights_document;
  if (["package_id", "inventory_sha256", "dependency_id", "dependency_row_sha256", "public_bundle_sha256", "license_code"].some(k => (d as unknown as Obj)[k] !== i[k])
    || i.decision === "allow" && i.basis_code !== d.basis_code || r.rights_bytes_sha256 !== i.rights_bytes_sha256) return null;
  const input = binding.request;
  if (input && (i.package_record_sha256 !== input.expected_package_sha256 || i.inventory_sha256 !== input.expected_inventory_sha256
    || i.dependency_row_sha256 !== input.expected_dependency_row_sha256 || ["request_key", "decision", "license_code", "basis_code", "reason_code", "expected_head_id", "expected_head_sha256"].some(k => i[k] !== (input as unknown as Obj)[k]))) return null;
  if (binding.committed || r.replayed) {
    if (!keys(r.permission, ["id", "record_sha256"]) || !rightsUuid(r.permission.id) || !rightsHash(r.permission.record_sha256)
      || !keys(r.artifact, ["id", "row_sha256", "bytes_sha256"]) || !rightsUuid(r.artifact.id) || !rightsHash(r.artifact.row_sha256) || r.artifact.bytes_sha256 !== r.rights_bytes_sha256) return null;
  } else if (r.permission !== null || r.artifact !== null) return null;
  if (binding.intentSha256 && r.intent_sha256 !== binding.intentSha256) return null;
  if (await rightsDigest(i) !== r.intent_sha256 || await rightsDigest(d) !== r.rights_bytes_sha256) return null;
  return clone(r);
}
