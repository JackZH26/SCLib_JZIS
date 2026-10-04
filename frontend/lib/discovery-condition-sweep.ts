/** Local condition proposals. No atomic structures, scientific results or retained batch writes. */
import {
  DESIGN_RESOURCES, designClosed, knownDesignCapabilities, knownDesignPage,
  type DesignBaseline, type DesignCapabilities, type DesignEntry, type ResearchDesign,
} from "./discovery-designs";
import { expressionCanonical, expressionSha } from "./source-expressions";

export const CONDITION_SWEEP_VERSION = "discovery-condition-sweep/1.0.0";
export const CONDITION_SWEEP_MAX_OPTIONS = 8;
export const CONDITION_SWEEP_MAX_SCENARIOS = 64;
export const CONDITION_SWEEP_MAX_MANIFEST_BYTES = 4 * 1024 * 1024;
export type ConditionSweepPressure = { kind: "ambient" | "specified" | "unspecified"; raw_gpa: string | null };
export type ConditionSweepAxes = { pressures: ConditionSweepPressure[]; temperatures_k: Array<string | null> };
type AxisEstimate = { raw_count: number; unique_count: number; collapsed_count: number };
export type ConditionSweepEstimate = {
  raw_cartesian_count: number; unique_cartesian_count: number;
  pressure: AxisEstimate; temperature: AxisEstimate;
  collapsed_reason_codes: Array<"pressure_aliases_collapsed" | "temperature_aliases_collapsed">;
  max_scenarios: 64;
};
export type ConditionSweepInput = { capabilities: DesignCapabilities; entry: DesignEntry; axes: ConditionSweepAxes };
export type ConditionSweepParent = { design_id: string; revision_id: string; revision: number; record_sha256: string };
export type ConditionSweepSourcePins = {
  baseline: DesignBaseline; context_sha256: string; projection_sha256: string;
  event_id: string | null; state_id: string | null; producer_run_id: string | null;
};
export type ConditionSweepScenario = {
  candidate_id: string; candidate_sha256: string;
  conditions: ResearchDesign["target_conditions"]; proposal: ResearchDesign;
};
export type ConditionSweepManifest = {
  version: typeof CONDITION_SWEEP_VERSION; scope: "local_private_condition_sweep";
  actor: { actor_user_id: string; session_version: number; curator_grant_id: string };
  parent: ConditionSweepParent; source_pins: ConditionSweepSourcePins;
  input_canonical_json: string; input_sha256: string; estimate: ConditionSweepEstimate;
  scenarios: ConditionSweepScenario[];
  budget_totals: Array<{ resource: keyof typeof DESIGN_RESOURCES; unit: string; status: "unknown" | "not_aggregated"; total: null }>;
  scientific_acceptance: false; canonical_promotions: 0; ml_training_approved: false;
  public_release: false; calculation_executed: false; database_changed: false;
  batch_saved: false; atomic_sites_generated: false; manifest_sha256: string;
};
export type ConditionSweepErrorCode = "sweep_input_invalid" | "sweep_axes_invalid" | "sweep_pressure_invalid"
  | "sweep_temperature_invalid" | "sweep_decimal_invalid" | "sweep_empty_axis" | "sweep_axis_limit"
  | "sweep_scenario_limit" | "sweep_capability_invalid" | "sweep_parent_invalid" | "sweep_source_unavailable"
  | "sweep_manifest_limit" | "sweep_checksum_unavailable";
export class ConditionSweepError extends Error {
  constructor(readonly code: ConditionSweepErrorCode) { super(code); this.name = "ConditionSweepError"; }
}
function requireSweep(condition: unknown, code: ConditionSweepErrorCode): asserts condition {
  if (!condition) throw new ConditionSweepError(code);
}
function snapshot(value: unknown): unknown {
  try { return structuredClone(value); } catch { throw new ConditionSweepError("sweep_input_invalid"); }
}
/** Exact decimal identity; binary floating point is used only for finite/underflow admission. */
function decimalIdentity(raw: unknown): string {
  requireSweep(typeof raw === "string" && raw.length > 0 && raw.length <= 64, "sweep_decimal_invalid");
  const parts = /^(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(raw);
  requireSweep(parts, "sweep_decimal_invalid");
  const fractional = parts[2] ?? parts[3] ?? "";
  const digits = `${parts[1] ?? ""}${fractional}`.replace(/^0+/, "");
  const rawExponent = BigInt(parts[4] ?? "0") - BigInt(fractional.length);
  // Match the deployed 64-bit Python Decimal constructor used by the existing
  // private design API, including zero spellings that Number accepts regardless
  // of exponent. These are representation bounds, not physical thresholds.
  requireSweep(rawExponent >= -1999999999999999997n && rawExponent <= 999999999999999999n, "sweep_decimal_invalid");
  const admitted = Number(raw);
  requireSweep(Number.isFinite(admitted) && (digits.length === 0 || admitted !== 0), "sweep_decimal_invalid");
  if (!digits.length) return "0e0";
  const coefficient = digits.replace(/0+$/, "");
  const exponent = rawExponent + BigInt(digits.length - coefficient.length);
  return `${coefficient}e${exponent}`;
}
type Option<T> = { key: string; raw: T };
function ordered<T>(options: Map<string, T>): Option<T>[] {
  return Array.from(options, ([key, raw]) => ({ key, raw })).sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
}
function normalizedAxes(value: unknown) {
  requireSweep(designClosed(value, "pressures temperatures_k") && Array.isArray(value.pressures) && Array.isArray(value.temperatures_k), "sweep_axes_invalid");
  const pressureCount = value.pressures.length, temperatureCount = value.temperatures_k.length;
  requireSweep(pressureCount > 0 && temperatureCount > 0, "sweep_empty_axis");
  requireSweep(pressureCount <= CONDITION_SWEEP_MAX_OPTIONS && temperatureCount <= CONDITION_SWEEP_MAX_OPTIONS, "sweep_axis_limit");
  const pressures = new Map<string, ConditionSweepPressure>(), temperatures = new Map<string, string | null>();
  for (const p of value.pressures) {
    requireSweep(designClosed(p, "kind raw_gpa") && ["ambient", "specified", "unspecified"].includes(p.kind as string), "sweep_pressure_invalid");
    const key = p.kind === "specified" ? `specified:${decimalIdentity(p.raw_gpa)}` : p.kind as string;
    requireSweep(p.kind === "specified" || p.raw_gpa === null, "sweep_pressure_invalid");
    if (!pressures.has(key)) pressures.set(key, { kind: p.kind as ConditionSweepPressure["kind"], raw_gpa: p.raw_gpa as string | null });
  }
  for (const t of value.temperatures_k) {
    requireSweep(t === null || typeof t === "string", "sweep_temperature_invalid");
    const key = t === null ? "unknown" : `specified:${decimalIdentity(t)}`;
    if (!temperatures.has(key)) temperatures.set(key, t);
  }
  const uniqueCount = pressures.size * temperatures.size;
  requireSweep(uniqueCount <= CONDITION_SWEEP_MAX_SCENARIOS, "sweep_scenario_limit");
  const count = (raw: number, unique: number): AxisEstimate => ({ raw_count: raw, unique_count: unique, collapsed_count: raw - unique });
  const reasons: ConditionSweepEstimate["collapsed_reason_codes"] = [];
  if (pressures.size !== pressureCount) reasons.push("pressure_aliases_collapsed");
  if (temperatures.size !== temperatureCount) reasons.push("temperature_aliases_collapsed");
  const estimate: ConditionSweepEstimate = {
    raw_cartesian_count: pressureCount * temperatureCount, unique_cartesian_count: uniqueCount,
    pressure: count(pressureCount, pressures.size), temperature: count(temperatureCount, temperatures.size),
    collapsed_reason_codes: reasons, max_scenarios: 64,
  };
  return { pressures: ordered(pressures), temperatures: ordered(temperatures), estimate };
}
/** Synchronous estimate; rejects an invalid axis as a whole, never a silently partial sweep. */
export function estimateConditionSweep(axes: unknown): ConditionSweepEstimate {
  return normalizedAxes(snapshot(axes)).estimate;
}
/**
 * Input hashes retain raw aliases and order. Candidate hashes seal only the exact
 * decimal identities and immutable parent SHA; reordering, aliases or a renewed
 * current session do not change a candidate ID. The first raw alias is displayed.
 * This proves a received snapshot, not live server currentness after this call.
 */
export async function createConditionSweep(input: unknown): Promise<ConditionSweepManifest> {
  const detached = snapshot(input);
  requireSweep(designClosed(detached, "capabilities entry axes"), "sweep_input_invalid");
  const axes = normalizedAxes(detached.axes);
  requireSweep(designClosed(detached.capabilities, "version request_version actor_user_id session_version curator_grant_id can_write baseline_kinds modification_kinds pairing_hypotheses action_kinds decisions budget_resources max_page_size max_operation_bytes scientific_acceptance canonical_promotions ml_training_approved public_release calculation_executed scope"), "sweep_capability_invalid");
  const cap = knownDesignCapabilities(detached.capabilities, detached.capabilities.actor_user_id as string);
  requireSweep(cap, "sweep_capability_invalid");
  let page;
  try {
    // Reuse the exact closed native entry/proof verifier. This envelope is local;
    // it is not asserted to be a page returned by SQL or a fresh authorization.
    page = await knownDesignPage({ version: cap.version, actor_user_id: cap.actor_user_id,
      session_version: cap.session_version, offset: 0, limit: 8, total: 1, entries: [detached.entry],
      scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false,
      public_release: false, calculation_executed: false, scope: "private_owner_research_design" }, cap, 0);
  } catch { throw new ConditionSweepError("sweep_parent_invalid"); }
  requireSweep(page, "sweep_parent_invalid");
  const entry = page.entries[0];
  requireSweep(entry.is_head && entry.status === "proposed", "sweep_parent_invalid");
  requireSweep(entry.eligibility.eligible && entry.projection, "sweep_source_unavailable");
  requireSweep(entry.baseline.kind !== "unanchored", "sweep_source_unavailable");
  const parent: ConditionSweepParent = { design_id: entry.design_id, revision_id: entry.id, revision: entry.revision, record_sha256: entry.record_sha256 };
  const sourcePins: ConditionSweepSourcePins = {
    baseline: structuredClone(entry.baseline), context_sha256: entry.context_sha256, projection_sha256: entry.projection_sha256,
    event_id: entry.projection.event_id, state_id: entry.projection.state_id, producer_run_id: entry.projection.producer_run_id,
  };
  const inputCanonicalJson = expressionCanonical({ version: CONDITION_SWEEP_VERSION, parent, source_pins: sourcePins, axes: detached.axes });
  const scenarios: ConditionSweepScenario[] = [];
  try {
    for (const p of axes.pressures) for (const t of axes.temperatures) {
      const candidateSha = await expressionSha(expressionCanonical({ version: "discovery-condition-sweep-candidate/1.0.0",
        parent_record_sha256: parent.record_sha256, pressure_identity: p.key, temperature_identity: t.key }));
      const conditions = { pressure: structuredClone(p.raw), temperature_k: t.raw };
      const proposal = structuredClone(entry.design);
      proposal.target_conditions = structuredClone(conditions);
      scenarios.push({ candidate_id: `condition-scenario:${candidateSha}`, candidate_sha256: candidateSha, conditions, proposal });
    }
    const body: Omit<ConditionSweepManifest, "manifest_sha256"> = {
      version: CONDITION_SWEEP_VERSION, scope: "local_private_condition_sweep",
      actor: { actor_user_id: cap.actor_user_id, session_version: cap.session_version, curator_grant_id: cap.curator_grant_id },
      parent, source_pins: sourcePins, input_canonical_json: inputCanonicalJson,
      input_sha256: await expressionSha(inputCanonicalJson), estimate: axes.estimate, scenarios,
      budget_totals: entry.design.next_action.budget.map(b => ({ resource: b.resource, unit: b.unit,
        status: b.status === "unknown" ? "unknown" : "not_aggregated", total: null })),
      scientific_acceptance: false, canonical_promotions: 0, ml_training_approved: false,
      public_release: false, calculation_executed: false, database_changed: false,
      batch_saved: false, atomic_sites_generated: false,
    };
    const manifestCanonicalJson = expressionCanonical(body);
    requireSweep(new TextEncoder().encode(manifestCanonicalJson).length <= CONDITION_SWEEP_MAX_MANIFEST_BYTES, "sweep_manifest_limit");
    return { ...body, manifest_sha256: await expressionSha(manifestCanonicalJson) };
  } catch (error) {
    if (error instanceof ConditionSweepError) throw error;
    throw new ConditionSweepError("sweep_checksum_unavailable");
  }
}
