export type FamilyOption = {
  slug: string;
  label: string;
  color: string;
};

export const FAMILY_OPTIONS: FamilyOption[] = [
  { slug: "cuprate",       label: "Cuprate",       color: "#2563eb" },
  { slug: "iron_based",    label: "Iron-based",    color: "#ca8a04" },
  { slug: "nickelate",     label: "Nickelate",     color: "#0891b2" },
  { slug: "hydride",       label: "Hydride",       color: "#dc2626" },
  { slug: "mgb2",          label: "MgB₂",          color: "#059669" },
  { slug: "heavy_fermion", label: "Heavy fermion", color: "#7c3aed" },
  { slug: "fulleride",     label: "Fulleride",     color: "#db2777" },
  { slug: "elemental",     label: "元素超导体",       color: "#3f3f46" },
  { slug: "conventional",  label: "Conventional",  color: "#64748b" },
];

export const FAMILY_LABEL: Record<string, string> = Object.fromEntries(
  FAMILY_OPTIONS.map((o) => [o.slug, o.label]),
);

export const FAMILY_COLORS: Record<string, string> = Object.fromEntries(
  FAMILY_OPTIONS.map((o) => [o.slug, o.color]),
);

export function familyLabel(slug: string | null | undefined): string {
  if (!slug) return "—";
  return FAMILY_LABEL[slug] ?? slug;
}
