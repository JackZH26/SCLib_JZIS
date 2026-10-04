import type { NomadElectronicReferences } from "@/lib/api";

export const NOMAD_GAP_SCHEMA = "https://github.com/FAIRmat-NFDI/nomad/blob/2b16820bdf83f57437c906addae3faf955ca4acf/nomad/datamodel/metainfo/simulation/calculation.py#L794-L820";
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

export function validNomadElectronic(value: unknown): value is NomadElectronicReferences {
  if (!object(value) || value.version !== "nomad-electronic-references/1.0.0"
    || value.scope !== "task_electronic_band_gaps_not_superconducting_gaps" || value.unit_schema_url !== NOMAD_GAP_SCHEMA
    || !["reported", "not_supplied", "requires_review"].includes(String(value.status))
    || !Array.isArray(value.band_gaps) || value.band_gaps.length > 16) return false;
  if (value.status !== "reported") return value.band_gaps.length === 0;
  if (!value.band_gaps.length) return false;
  const groups = new Map<string, number>();
  return value.band_gaps.every(row => {
    if (!object(row) || !["dos_electronic", "band_structure_electronic"].includes(String(row.source_kind))
      || !Number.isInteger(row.group_index) || Number(row.group_index) < 0 || Number(row.group_index) > 3
      || row.spin_channel_index !== null && (!Number.isInteger(row.spin_channel_index) || Number(row.spin_channel_index) < 0 || Number(row.spin_channel_index) > 255)
      || row.spin_polarized !== null && typeof row.spin_polarized !== "boolean"
      || row.gap_type !== null && !["direct", "indirect"].includes(String(row.gap_type))
      || !finite(row.value_j) || row.value_j < 0 || !finite(row.value_ev) || row.value_ev < 0) return false;
    const expected = row.value_j / 1.602176634e-19;
    if (!Number.isFinite(expected) || (expected === 0 ? row.value_ev !== 0 : Math.abs(row.value_ev / expected - 1) > 1e-12)) return false;
    const key = `${row.source_kind}:${row.group_index}`;
    groups.set(key, (groups.get(key) ?? 0) + 1);
    return groups.get(key)! <= 2;
  });
}

export const electronicGapLabel = (kind: string) => kind === "dos_electronic" ? "DOS" : "Band structure";
export const electronicGapNumber = (value: number) => value.toLocaleString("en-US", { maximumSignificantDigits: 6 });
