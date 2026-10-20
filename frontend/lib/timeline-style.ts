/**
 * A restrained qualitative palette for the dense Tc chart. Inspired by
 * Nature's figure guidance on clear keys and avoiding decorative colour:
 * https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/
 * These are SCLib colours, not an official journal palette. Family names in
 * tooltips and the table remain essential; colour alone is not an identifier.
 */
const FAMILY_COLOURS: Record<string, string> = {
  cuprate: "#58758C",
  iron_based: "#A89065",
  nickelate: "#638D91",
  hydride: "#AC756B",
  mgb2: "#738E7A",
  heavy_fermion: "#837B99",
  fulleride: "#A18091",
  elemental: "#667078",
  conventional: "#8B9188",
  mixed: "#6B746F",
};

export const timelineFamilyColour = (family: string) => FAMILY_COLOURS[family] ?? "#747A80";

// Bounded marker growth leaves dense data readable. Never move, round or repel
// coordinates to fit symbols: nearby Tc values are allowed to overlap visually.
export const timelineMarkerDiameter = (members: number) =>
  Math.min(10, 8 + Math.log2(Math.max(1, members)) * .5);
