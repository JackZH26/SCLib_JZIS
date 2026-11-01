/** Public presentation flag; keep source values intact and never clip them. */
export const TC_DISPLAY_MAX_KELVIN = 300;
export type TcDisplayValues = {
  value_kelvin: number | null; value_lower_kelvin: number | null;
  value_upper_kelvin: number | null; value_relation: string;
};
export type TcDisplayPolicy = {
  version: "tc-public-display/1"; maximum_kelvin: 300; exclusion_flag: "tc_above_300k";
};
export function tcDisplayExclusion(row: TcDisplayValues): "tc_above_300k" | null {
  if ([row.value_kelvin, row.value_lower_kelvin, row.value_upper_kelvin].some(value =>
    typeof value === "number" && value > TC_DISPLAY_MAX_KELVIN) ||
    row.value_relation === "gt" && row.value_lower_kelvin === TC_DISPLAY_MAX_KELVIN) return "tc_above_300k";
  return null;
}
