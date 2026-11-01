export type NerTimelinePoint = {
  id: string; material_id: string; paper_id: string; formula: string; family: string;
  date: string; date_basis: "paper_submission" | "arxiv_identifier_month"; date_precision: "day" | "month";
  value_kelvin: number | null; value_lower_kelvin: number | null; value_upper_kelvin: number | null;
  value_relation: "exact" | "interval" | "lt" | "le" | "gt" | "ge";
  approximate: boolean; criterion: string; pressure_gpa: number | null;
  pressure_regime: "explicit_ambient" | "nonambient" | "unknown";
};
export type NerTimelineData = {
  dataset: "materials-production90/1"; points: NerTimelinePoint[];
  total_results: number; total_materials: number; total_papers: number;
  plotted_results: number; omitted_without_date: number; omitted_invalid_quantity: number;
  sampled: boolean; families: Record<string, number>; date_min: string | null; date_max: string | null;
};

// Stable across the home module, independent page and every date/pressure view.
export const timelineFamilies: Record<string, { label: string; color: string; shape: string; glyph: string }> = Object.fromEntries([
  ["cuprate","Cuprate","#C34A3E","circle","●"], ["iron_based","Iron-based","#386CA5","square","■"],
  ["hydride","Hydride","#27846E","diamond","◆"], ["nickelate","Nickelate","#BB8B2F","star","★"],
  ["heavy_fermion","Heavy fermion","#86599B","triangle","▲"], ["chalcogenide","Chalcogenide","#499CB7","wye","Y"],
  ["mgb2","MgB₂","#CE7B42","square","■"], ["kagome","Kagome","#87933F","diamond","◆"],
  ["intermetallic","Intermetallic","#568A83","circle","●"], ["elemental","Elemental","#424F5B","cross","✚"],
  ["nitride","Nitride","#537BB9","triangle","▲"], ["oxide","Oxide","#A2755B","diamond","◆"],
  ["pnictide","Pnictide","#A76693","square","■"], ["boride","Boride","#657F48","triangle","▲"],
  ["bis2_layered","BiS₂-layered","#835F8B","wye","Y"], ["heterostructure","Heterostructure","#AC6366","star","★"],
  ["carbide","Carbide","#9B8137","cross","✚"], ["ruthenate","Ruthenate","#A0446A","diamond","◆"],
  ["borocarbide","Borocarbide","#6F8EA5","square","■"], ["bismuthate","Bismuthate","#C89B72","triangle","▲"],
  ["carbon","Carbon","#424F5B","star","★"], ["organic","Organic","#81905E","circle","●"],
  ["fulleride","Fulleride","#86599B","square","■"], ["other_compound","Other compound","#A2755B","cross","✚"],
  ["unclassified","Unclassified","#90989F","open","○"],
].map(([key,label,color,shape,glyph]) => [key,{label,color,shape,glyph}]));

/** Month precision is centred in that calendar month, never jittered by record ID. */
export function timelineDate(point: Pick<NerTimelinePoint,"date"|"date_precision">): number {
  if (point.date_precision === "month") {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(point.date)) return NaN;
    const [year,month] = point.date.split("-").map(Number);
    return (Date.UTC(year,month-1,1)+Date.UTC(year,month,1))/2;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(point.date)) return NaN;
  const value=Date.parse(point.date+"T00:00:00Z");
  return Number.isFinite(value) && new Date(value).toISOString().slice(0,10)===point.date ? value : NaN;
}

export function timelineValue(point: NerTimelinePoint): number {
  return point.value_relation==="exact" ? point.value_kelvin! : (point.value_lower_kelvin ?? point.value_upper_kelvin)!;
}
export function timelineTc(point: NerTimelinePoint): string {
  const n=(v:number|null)=>v?.toLocaleString("en-US",{maximumFractionDigits:6}) ?? "";
  const approx=point.approximate ? "≈ " : "";
  if(point.value_relation==="exact")return approx+n(point.value_kelvin)+" K";
  if(point.value_relation==="interval")return approx+n(point.value_lower_kelvin)+"–"+n(point.value_upper_kelvin)+" K";
  const sign={lt:"<",le:"≤",gt:">",ge:"≥"}[point.value_relation];
  return sign+" "+approx+n(point.value_lower_kelvin??point.value_upper_kelvin)+" K";
}
export function timelinePressure(point: NerTimelinePoint): string {
  if(point.pressure_gpa!==null)return point.pressure_gpa.toLocaleString("en-US")+" GPa";
  return point.pressure_regime==="explicit_ambient" ? "Ambient pressure" :
    point.pressure_regime==="nonambient" ? "Nonambient; pressure not stated" : "Pressure not stated";
}
