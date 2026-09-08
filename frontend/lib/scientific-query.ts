/** Closed display guards. Passing one never establishes scientific validity. */
import type {
  BoundScientificQueryResult, RetrievalGeneration, ScientificLookup,
  ScientificQueryInterpretation, ScientificReportQuantity,
} from "@/lib/api";

type Row = Record<string, unknown>;
const sha = /^[0-9a-f]{64}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const code = /^[a-z][a-z0-9_]{0,79}$/;
const origins = ["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"];
const fields = ["tc_kelvin", "pressure_gpa"];
const record = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
function keys(value: unknown, names: string[]): value is Row {
  return record(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
function string(value: unknown, max: number, min = 1): value is string {
  return typeof value === "string" && value.length <= max * 2 && Array.from(value).length >= min && Array.from(value).length <= max;
}
const nullableString = (value: unknown, max: number) => value === null || string(value, max, 0);
const choice = (value: unknown, values: string[]) => typeof value === "string" && values.includes(value);
const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const nullableNumber = (value: unknown) => value === null || number(value);
const integer = (value: unknown, max: number) => number(value) && Number.isInteger(value) && value >= 0 && value <= max;
function list(value: unknown, max: number, validate: (item: unknown) => boolean): value is unknown[] {
  return Array.isArray(value) && value.length <= max && value.every(validate);
}
const codes = (value: unknown, max: number) => list(value, max, item => typeof item === "string" && code.test(item));
function span(value: Row, raw: string) {
  return string(value.raw_text, 2000) && integer(value.start, 2000) && integer(value.end, 2000)
    && (value.end as number) > (value.start as number)
    // The API records Python Unicode-code-point offsets, not UTF-16 offsets.
    && Array.from(raw).slice(value.start as number, value.end as number).join("") === value.raw_text;
}
function bound(value: Row) {
  if (![value.value, value.lower, value.upper].every(nullableNumber)) return false;
  switch (value.relation) {
    case "exact": return number(value.value) && value.lower === null && value.upper === null;
    case "lt": case "le": return number(value.upper) && value.value === null && value.lower === null;
    case "gt": case "ge": return number(value.lower) && value.value === null && value.upper === null;
    case "interval": return number(value.lower) && number(value.upper) && value.value === null && value.lower <= value.upper;
    default: return false;
  }
}

export function knownScientificQuery(input: unknown, expectedRaw?: string): ScientificQueryInterpretation | null {
  if (!keys(input, ["version", "raw_query", "normalized_query", "language", "intent", "status", "requested_fields",
    "formulas", "constraints", "evidence_constraints", "unresolved_clauses", "clarification_questions", "scientific_acceptance"])
      || input.version !== "scientific-query/1.0.0" || input.scientific_acceptance !== false
      || !string(input.raw_query, 2000) || expectedRaw !== undefined && input.raw_query !== expectedRaw
      || !string(input.normalized_query, 4000) || !choice(input.language, ["en", "zh", "mixed"])
      || !choice(input.intent, ["numerical", "mechanism", "mixed", "comparison", "general"])
      || !choice(input.status, ["resolved", "clarification_required"])
      || !list(input.requested_fields, 2, item => choice(item, fields)) || new Set(input.requested_fields).size !== input.requested_fields.length) return null;
  const raw = input.raw_query;
  if (!list(input.formulas, 32, item => {
    if (!keys(item, ["raw_text", "start", "end", "normalization"]) || !span(item, raw)) return false;
    const norm = item.normalization;
    return keys(norm, ["version", "raw_formula", "normalized_formula", "status", "reason_codes"])
      && norm.version === "formula-query/1.0.0" && string(norm.raw_formula, 200) && norm.raw_formula === item.raw_text
      && choice(norm.status, ["normalized", "unresolved"]) && codes(norm.reason_codes, 20)
      && (norm.status === "normalized" ? string(norm.normalized_formula, 200)
        : norm.normalized_formula === null && (norm.reason_codes as unknown[]).length > 0);
  }) || !list(input.constraints, 32, item => keys(item, ["field", "raw_text", "start", "end", "relation", "value", "lower", "upper", "unit", "unit_basis"])
    && span(item, raw) && choice(item.field, fields) && bound(item)
    && [item.value, item.lower, item.upper].every(value => value === null || number(value) && value >= 0)
    && item.unit === (item.field === "tc_kelvin" ? "K" : "GPa")
    && (item.unit_basis === "explicit" || item.unit_basis === "explicit_ambient_reference"
      && item.field === "pressure_gpa" && item.relation === "exact" && item.value === 0))
    || !list(input.evidence_constraints, 32, item => keys(item, ["field", "raw_text", "start", "end", "value"])
      && span(item, raw) && (item.field === "knowledge_origin" ? choice(item.value, origins)
        : item.field === "source_role" ? choice(item.value, ["primary", "cited"])
          : item.field === "experimental_outcome" && choice(item.value, ["positive_reported", "not_detected"])))) return null;
  if (!list(input.unresolved_clauses, 128, item => keys(item, ["raw_text", "start", "end", "reason_code"])
    && span(item, raw) && typeof item.reason_code === "string" && code.test(item.reason_code))
    || !list(input.clarification_questions, 8, item => string(item, 2000))) return null;
  const unresolved = input.unresolved_clauses.length > 0 || input.formulas.some(item =>
    (item as { normalization: { status: string } }).normalization.status !== "normalized");
  if ((input.status === "clarification_required") !== unresolved || (input.clarification_questions.length > 0) !== unresolved) return null;
  return input as unknown as ScientificQueryInterpretation;
}

const quantityKeys = ["status", "relation", "value", "lower", "upper", "uncertainty", "approximate", "unit", "unit_basis", "uncertainty_interpretation"];
function quantity(input: unknown, unit: "K" | "GPa", pressure = false) {
  if (!keys(input, pressure ? [...quantityKeys, "pressure_state"] : quantityKeys)
    || !choice(input.status, ["parsed", "unreported", "invalid"])
    || !choice(input.relation, ["exact", "lt", "le", "gt", "ge", "interval", "unreported"])
    || ![input.value, input.lower, input.upper, input.uncertainty].every(nullableNumber)
    || typeof input.approximate !== "boolean" || input.unit !== unit
    || !choice(input.unit_basis, ["explicit", "field_schema_assumption", "endpoint_units", "unreported", "explicit_ambient_reference"])
    || input.uncertainty_interpretation !== null && input.uncertainty_interpretation !== "unspecified") return false;
  if (pressure && !choice(input.pressure_state, ["explicit_ambient", "reported", "not_reported", "ambiguous"])) return false;
  if (number(input.uncertainty) && input.uncertainty < 0) return false;
  if (input.status === "unreported" && (input.relation !== "unreported"
    || [input.value, input.lower, input.upper, input.uncertainty].some(value => value !== null))) return false;
  if (input.status === "parsed" && (!bound(input) || input.unit_basis === "unreported"
    || [input.value, input.lower, input.upper].some(value => number(value) && value < 0)
    || input.relation !== "exact" && input.uncertainty !== null
    || (input.uncertainty === null) !== (input.uncertainty_interpretation === null))) return false;
  if (!pressure) return input.unit_basis !== "explicit_ambient_reference";
  if (input.pressure_state === "explicit_ambient") return input.status === "parsed" && input.relation === "exact"
    && input.value === 0 && input.approximate === false && input.uncertainty === null;
  return input.pressure_state === "reported" ? input.status === "parsed"
    : input.pressure_state === "not_reported" ? input.status === "unreported" : input.status === "invalid";
}
function result(input: unknown) {
  if (!keys(input, ["version", "result_id", "record_index", "formula", "family", "tc", "pressure", "minimum_temperature",
    "result_classification", "outcome_state", "reported_context", "warning_codes", "scientific_acceptance", "ml_training_eligible", "detection_adequacy_verified"])
    || input.version !== "scientific-query-result/1.0.0" || typeof input.result_id !== "string" || !/^legacy-result:[0-9a-f]{64}$/.test(input.result_id)
    || !integer(input.record_index, 999) || !string(input.formula, 200) || !nullableString(input.family, 160)
    || !quantity(input.tc, "K") || !quantity(input.minimum_temperature, "K") || !quantity(input.pressure, "GPa", true)
    || input.scientific_acceptance !== false || input.ml_training_eligible !== false || input.detection_adequacy_verified !== false
    || !choice(input.outcome_state, ["positive_reported", "not_detected", "unspecified", "unresolved", "conflicted"])
    || !list(input.warning_codes, 40, value => typeof value === "string" && /^[a-z][a-z0-9_]{0,99}$/.test(value))) return false;
  const classification = input.result_classification, context = input.reported_context;
  return keys(classification, ["knowledge_origin", "classification_status", "source_role"])
    && choice(classification.knowledge_origin, origins) && choice(classification.classification_status, ["resolved", "unknown", "conflicted"])
    && choice(classification.source_role, ["primary", "cited", "unknown", "conflicted"])
    && keys(context, ["tc_criterion", "sample_label", "sample_form", "structure_phase", "measurement_method"])
    && Object.values(context).every(value => nullableString(value, 160));
}
function generation(input: unknown): input is RetrievalGeneration {
  return keys(input, ["version", "mode", "generation_id", "activation_event_id", "manifest_sha256"])
    && input.version === "index-read/1.0.0" && input.mode === "generation_snapshot"
    && typeof input.generation_id === "string" && uuid.test(input.generation_id)
    && typeof input.activation_event_id === "string" && uuid.test(input.activation_event_id)
    && typeof input.manifest_sha256 === "string" && sha.test(input.manifest_sha256);
}

export function knownScientificLookup(input: unknown): ScientificLookup | null {
  return keys(input, ["status", "reason_codes", "returned_count", "has_more", "scope", "scientific_acceptance"])
    && choice(input.status, ["not_requested", "completed", "unavailable", "clarification_required"])
    && codes(input.reason_codes, 8) && new Set(input.reason_codes as unknown[]).size === (input.reason_codes as unknown[]).length
    && integer(input.returned_count, 20) && typeof input.has_more === "boolean"
    && input.scope === "declared_generation_derived_extractions" && input.scientific_acceptance === false
    && (input.status === "completed" || input.returned_count === 0 && input.has_more === false)
    && (input.has_more === false || (input.returned_count as number) > 0)
    ? input as unknown as ScientificLookup : null;
}

export function knownScientificResults(input: unknown, lookup: ScientificLookup, pin: unknown,
  query: ScientificQueryInterpretation): BoundScientificQueryResult[] | null {
  if (!Array.isArray(input) || input.length > 20 || input.length !== lookup.returned_count) return null;
  if (lookup.status === "clarification_required" && query.status !== "clarification_required"
    || lookup.status === "unavailable" && query.status !== "resolved") return null;
  if (lookup.status !== "completed") return input.length === 0 ? [] : null;
  if (query.status !== "resolved" || !generation(pin)) return null;
  const valid = input.every(item => {
    if (!keys(item, ["result", "binding"]) || !result(item.result)) return false;
    const binding = item.binding;
    return keys(binding, ["paper_id", "vector_id", "generation_id", "activation_event_id", "manifest_sha256", "content_sha256",
      "evidence_revision_id", "evidence_record_sha256", "parent_result_revision_id", "parent_result_sha256", "association_scope"])
      && string(binding.paper_id, 100) && typeof binding.vector_id === "string"
      && new RegExp(`^ig62_${pin.generation_id!.replaceAll("-", "") }_[0-9a-f]{64}$`).test(binding.vector_id)
      && binding.generation_id === pin.generation_id && binding.activation_event_id === pin.activation_event_id
      && binding.manifest_sha256 === pin.manifest_sha256
      && [binding.content_sha256, binding.evidence_record_sha256, binding.parent_result_sha256].every(value => typeof value === "string" && sha.test(value))
      && [binding.evidence_revision_id, binding.parent_result_revision_id].every(value => typeof value === "string" && uuid.test(value))
      && binding.association_scope === "derived_extraction_not_original_support";
  });
  if (!valid) return null;
  const rows = input as BoundScientificQueryResult[];
  return new Set(rows.map(item => item.binding.parent_result_revision_id)).size === rows.length ? rows : null;
}

const format = (value: number) => value.toLocaleString("en-US", { maximumSignificantDigits: 12 });
export function displayQuantity(value: ScientificReportQuantity): string {
  if (value.status !== "parsed") return value.status === "unreported" ? "Not reported" : "Invalid or unresolved";
  const body = value.relation === "exact" ? format(value.value!)
    : value.relation === "interval" ? `${format(value.lower!)}–${format(value.upper!)}`
      : `${({ lt: "<", le: "≤", gt: ">", ge: "≥" } as Record<string, string>)[value.relation]} ${format((value.lower ?? value.upper)!)}`;
  return `${value.approximate ? "≈ " : ""}${body}${value.uncertainty === null ? "" : ` ± ${format(value.uncertainty)} (interpretation unspecified)`} ${value.unit}`
    + (value.unit_basis === "field_schema_assumption" ? " (unit assumed from field schema)" : "");
}
