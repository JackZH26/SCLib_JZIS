/** Read retained record fields without joining samples or interpreting source units. */
type Row = Record<string, unknown>;
export type RetainedTextField = { key: string; label: string; value: string };
export type RetainedHc2Reading = {
  value: string;
  displayUnit: "T" | null;
  representation: "api_field_value" | "source_token";
  unitMetadataUnresolved: boolean;
  units: RetainedTextField[];
  context: RetainedTextField[];
};

const missing = new Set(["", "unknown", "none", "null", "n/a", "not_reported", "unspecified"]);
const row = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
/** No object/string coercion, source snippets, or silent clipping of a token. */
export function retainedRecordText(value: unknown, limit = 500): string | null {
  return typeof value === "string" && Array.from(value).length <= limit
    && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value) && !missing.has(value.trim().toLowerCase()) ? value : null;
}
function token(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : retainedRecordText(value);
}
function fields(record: Row, names: [string, string][]): RetainedTextField[] {
  return names.flatMap(([key, label]) => {
    const value = retainedRecordText(record[key]);
    return value === null ? [] : [{ key, label, value }];
  });
}
function unitFields(record: Row, names: [string, string][]): RetainedTextField[] {
  return names.flatMap(([key, label]) => {
    const raw = record[key];
    // Explicit unknown unit tokens remain unresolved instead of becoming absent.
    const value = typeof raw === "string" && raw.trim() && Array.from(raw).length <= 40
      && !/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(raw) ? raw : null;
    return value === null ? [] : [{ key, label, value }];
  });
}

/** Coarse type, definition and lexical criteria remain separate retained fields. */
export function retainedTcCriteria(record: Row): RetainedTextField[] {
  return fields(record, [["tc_type", "Retained Tc type"], ["tc_definition", "Retained Tc definition"],
    ["tc_criterion", "Reported criterion"], ["criterion", "Criterion alias"]]);
}

/** `hc2_tesla` supplies the API field unit, never a measurement/extrapolation role. */
export function retainedHc2(record: Row): RetainedHc2Reading | null {
  const context = fields(record, [["hc2_conditions", "Hc2 conditions"], ["hc2_direction", "Hc2 direction"],
    ["field_orientation", "Field orientation"], ["magnetic_field_orientation", "Magnetic field orientation"]]);
  const values = record.scientific_values;
  if (row(values) && Object.hasOwn(values, "hc2_tesla")) {
    const proposal = values.hc2_tesla;
    // A stored normalized value or stale scalar cannot replace unresolved raw input.
    if (!row(proposal) || !Object.hasOwn(proposal, "raw_value")) return null;
    const value = token(proposal.raw_value);
    if (value === null) return null;
    return { value, displayUnit: null, representation: "source_token",
      unitMetadataUnresolved: ["input_unit", "raw_unit"].some(key => proposal[key] !== null && proposal[key] !== undefined
        && proposal[key] !== "" && !unitFields(proposal, [[key, "unit"]]).length),
      units: unitFields(proposal, [["input_unit", "Stored input unit"], ["raw_unit", "Stored raw unit"]]), context };
  }
  const value = token(record.hc2_tesla);
  if (value === null) return null;
  const units = unitFields(record, [["hc2_tesla_unit", "Stored input unit"]]);
  const sourceUnit = units[0]?.value ?? null;
  const unresolvedUnit = record.hc2_tesla_unit !== null && record.hc2_tesla_unit !== undefined
    && record.hc2_tesla_unit !== "" && sourceUnit === null;
  const scalar = typeof record.hc2_tesla === "number" || /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())
    && Number.isFinite(Number(value));
  const fieldValue = scalar && !unresolvedUnit && (sourceUnit === null || sourceUnit === "T");
  return { value, displayUnit: fieldValue ? "T" : null,
    representation: fieldValue ? "api_field_value" : "source_token",
    unitMetadataUnresolved: unresolvedUnit, units, context };
}
