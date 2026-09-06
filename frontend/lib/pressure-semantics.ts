import { scientificNumber } from "@/lib/result-semantics";

/** Consume server evidence; a legacy zero/null never establishes ambient P. */
export function pressureLabel(metadata: unknown, legacyValue?: number | null): string {
  const p = metadata && typeof metadata === "object" ? metadata as Record<string, unknown> : {};
  const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
  if (p.classifier_version !== "pressure-policy/1.0.0") {
    return number(legacyValue) ? `${scientificNumber(legacyValue)} GPa (unverified)` : "Pressure not reported";
  }
  if (p.pressure_state === "explicit_ambient") return "Explicit ambient";
  if (p.pressure_state === "not_reported") return "Pressure not reported";
  if (p.pressure_state !== "reported") return "Pressure unresolved";
  const prefix = p.approximate ? "≈ " : "";
  if (number(p.pressure_gpa)) {
    const error = number(p.uncertainty_gpa) ? ` ± ${scientificNumber(p.uncertainty_gpa)}` : "";
    return `${prefix}${scientificNumber(p.pressure_gpa)}${error} GPa`;
  }
  if (p.relation === "interval" && number(p.value_lower_gpa) && number(p.value_upper_gpa)) {
    return `${scientificNumber(p.value_lower_gpa)}–${scientificNumber(p.value_upper_gpa)} GPa`;
  }
  if ((p.relation === "lt" || p.relation === "le") && number(p.value_upper_gpa)) {
    return `${p.relation === "lt" ? "<" : "≤"} ${scientificNumber(p.value_upper_gpa)} GPa`;
  }
  if ((p.relation === "gt" || p.relation === "ge") && number(p.value_lower_gpa)) {
    return `${p.relation === "gt" ? ">" : "≥"} ${scientificNumber(p.value_lower_gpa)} GPa`;
  }
  return "Reported pressure; value unresolved";
}
