"use client";

import { useState, type ReactNode } from "react";
import { StudyPtContexts } from "@/components/MaterialStudyContext";
import type { StudyContextBatch } from "@/lib/material-study-context";
import { downloadSourceFollowupGroup, groupSourceFollowup, sourceFollowupHref, type SourceFollowupBatch, type SourceFollowupEntry } from "@/lib/material-source-followup";

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
// Readable spacing for captured prose; downloadable source expressions stay unchanged.
const displayWording: Record<string, string> = {
  "Thermal relaxation inQuantumDesignPPMS": "Thermal relaxation in a Quantum Design PPMS",
  "PartialArpressure": "Partial Ar pressure",
  "IsoentropicCp/T vsT construction": "Isoentropic Cp/T versus T construction",
  "For nominal x≥0.5, authors suggest optimum near750°C; temperature not assigned to an individual x=0.6 dataset": "For nominal x ≥ 0.5, the authors suggest an optimum near 750 °C; this temperature is not assigned to an individual x = 0.6 dataset",
  "0.6 (within0.1,0.3,0.6,0.8 study)": "0.6 (within the x = 0.1, 0.3, 0.6 and 0.8 study)",
  "ambient pressure to≈2.6GPa": "Ambient pressure to approximately 2.6 GPa",
  "Resistivity50% of normal-state value": "Resistivity at 50% of the normal-state value",
  "±0.1meV": "±0.1 meV",
  "R(T)50% of normal-state value": "R(T) at 50% of the normal-state value",
  "Linear extrapolation of fitted Hc2(T) slope to0K": "Linear extrapolation of the fitted Hc₂(T) slope to 0 K",
  "Single crystals synthesized in excessFeAs and annealed in inert atmosphere": "Single crystals synthesized in excess FeAs and annealed in an inert atmosphere",
  "Transient terahertz conductivity response/gap-like behavior aboveTc": "Transient terahertz conductivity response and gap-like behavior above Tc",
  "FTIR BrukerVertex88v; quasi-normal-incidence reflectivity; gold evaporation/Kramers–Kronig analysis": "FTIR with a Bruker Vertex 88v; quasi-normal-incidence reflectivity; gold evaporation and Kramers–Kronig analysis",
  "Pump–probe terahertz reflection/electro-optic sampling inZnTe": "Pump–probe terahertz reflection and electro-optic sampling in ZnTe",
  "Mo-1212; nominalMoSr2RCu2O8": "Mo-1212; nominal MoSr₂RCu₂O₈",
  "Authors assign antiferromagnetic order toMo sublattice": "The authors assign antiferromagnetic order to the Mo sublattice",
  "ZFC/FCdc magnetic susceptibility": "ZFC/FC DC magnetic susceptibility",
  "Similar behavior to neighboring heavy-R members reported; no explicitTm field in paragraph": "Similar behavior to neighboring heavy-R members is reported; the paragraph supplies no explicit Tm field",
  "Deduced fromχ′ (real ac susceptibility)": "Deduced from χ′ (real AC susceptibility)",
};
const text = (value: unknown) => typeof value === "string" ? displayWording[value] ?? value : typeof value === "number" ? String(value) : "Not supplied";
const items = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const quantity = (value: unknown): string => {
  const q = object(value), raw = q.raw_value ?? q.value;
  if (raw == null) return "Not supplied";
  const unit = q.unit ?? q.raw_unit;
  const hiddenUnits = ["dimensionless", "fraction", "fractional", "formula_units_per_cell"];
  return `${q.approximate === true ? "≈ " : ""}${text(raw)}${typeof unit === "string" && !hiddenUnits.includes(unit) ? ` ${unit}` : ""}`;
};
const labels: Record<string, string> = {
  calculation_method_and_origin_statement: "Calculation method and reported setting",
  electron_phonon_lambda_source_value: "Electron–phonon coupling λ",
  omega_log_source_value: "Logarithmic phonon frequency ωlog",
  mu_star_source_parameter: "Coulomb pseudopotential μ*",
  source_preparation_description: "Preparation comments · separate database rows",
  source_anneal_temperature_options: "Annealing options and series recommendation",
  susceptibility_transition_definition: "DC and AC susceptibility criteria",
  tc_applied_pressure_context: "Separate pressure experiment",
  meissner_measurement_method_and_conditions: "Database fraction and related probe context",
  source_composition_and_local_x_definition: "Local In concentration",
  hall_carrier_density_and_conditions: "Hall-derived carrier density",
  sample_measurement_context: "Sample and spectroscopy conditions",
  reported_gap_or_pairing_source_claim: "Gap-scale dips and pairing interpretation",
  source_local_Ni_composition_definition: "Local nominal Ni composition",
  source_transition_criterion: "Hc₂ curve criterion",
  hc2_curve_slope_and_model: "Hc₂ slope and extrapolation",
  sample_anneal_conditions: "Cited annealing protocol",
  source_local_composition_definition: "Measured Bi composition and reported Tc",
  reported_short_range_order_claim: "Author interpretation · short-range CDW",
  optical_measurement_temperature_window: "Optical examples and crossover",
  optical_probe_method: "Optical measurement conditions",
  source_rare_earth_member_definition: "Rare-earth member definition",
  reported_magnetic_order_and_temperature: "Magnetic order · Tm member",
  magnetic_probe_method: "Magnetic probes and field limits",
  tm_member_transition_criterion: "Superconducting transition · Tm member",
  listed_atomic_sites: "Listed asymmetric-unit sites",
  declared_symmetry_operations: "Declared symmetry operations",
  reported_hall_symbol: "Captured and original Hall labels",
  cell_formula_units_z: "Formula units per cell · Z",
  source_preparation_and_specific_heat_method: "Growth and calorimetry method",
  source_heating_program: "Growth heating program",
  specific_heat_jump_over_tc: "Specific-heat jump divided by Tc",
  specific_heat_analysis_context: "Heat-capacity construction and assumptions",
  electronic_specific_heat_coefficient_model: "Electronic coefficient · BCS estimate",
};
const roleLabels: Record<string, string> = {
  source_reported_prediction_method: "Computed source report", unresolved_numeric_source_setting: "Numeric setting unavailable",
  database_source_preparation_comment: "Database source comments", source_preparation_options_and_series_recommendation: "Series recommendation",
  source_method_definition_separate_database_values: "Probe definitions and separate database values", separate_source_pressure_experiment_context: "Separate experimental study",
  database_fraction_and_related_primary_method_context: "Database value and related paper context", source_local_composition_definition: "Local source definition",
  source_hall_derived_carrier_density: "Derived from a Hall slope", source_sample_and_probe_metadata: "Source sample and probe report",
  source_probe_interpretation_and_theoretical_pairing_claim: "Author interpretation and theory", source_local_nominal_composition: "Nominal source composition",
  source_curve_definition: "Definition of this source curve", source_curve_derived_slope_and_model_extrapolation: "Curve slope and model extrapolation",
  source_series_protocol_separate_from_individual_sample: "Cited series protocol", source_local_composition_and_probe_statement: "Source composition measurement",
  source_optical_interpretation_claim: "Author optical interpretation", source_figure_measurement_conditions: "Figure-specific conditions",
  source_optical_probe_and_analysis_conditions: "Source probe and analysis conditions", source_explicit_member_definition: "Explicit source member",
  source_member_specific_magnetic_order_report: "Author magnetic-order assignment", source_study_probe_with_member_context: "Study-level probe context",
  source_member_specific_ac_susceptibility_transition_report: "Member-specific susceptibility report", source_reported_refined_atomic_sites: "Listed CIF site metadata",
  source_declared_symmetry_operations: "Declared CIF operations", source_reported_symmetry_label: "Reported CIF labels", source_cell_formula_units: "CIF cell metadata",
  source_preparation_and_measurement_method: "Source preparation and method", source_growth_conditions: "Source growth conditions",
  source_isoentropic_construction_result: "Source analysis · printed unit needs review", source_analysis_definition_and_assumptions: "Analysis definition and assumptions",
  source_BCS_assumption_derived_estimate: "Estimate under BCS and volume assumptions",
};
function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-[minmax(9rem,1fr)_minmax(0,3fr)]">{rows.map(([label, value]) => <div className="contents" key={label}><dt className="text-sage-muted">{label}</dt><dd className="min-w-0 break-words tabular-nums">{value}</dd></div>)}</dl>;
}
function Sites({ value }: { value: unknown }) {
  return <div className="overflow-x-auto" role="region" tabIndex={0} aria-label="Listed FeSe fractional sites"><table className="w-full text-left text-sm tabular-nums"><thead><tr>{["Site", "Element", "x", "y", "z", "Occupancy", "Multiplicity", "Uiso (Å²)"].map(label => <th className="whitespace-nowrap py-2 pr-4 font-medium" scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{items(value).map(item => {
    const site = object(item);return <tr key={text(site.label)}><th className="py-2 pr-4 font-medium" scope="row">{text(site.label)}</th><td className="py-2 pr-4">{text(site.element)}</td>{items(site.fractional_coordinates).map((q, index) => <td className="py-2 pr-4" key={index}>{quantity(q)}</td>)}<td className="py-2 pr-4">{quantity(site.occupancy)}</td><td className="py-2 pr-4">{text(site.source_multiplicity_raw)}</td><td className="py-2 pr-4">{quantity(site.u_iso).replace(/ Å²$/, "")}</td></tr>;
  })}</tbody></table><p className="mt-2 text-xs text-sage-muted">Two listed asymmetric-unit sites. Parenthetical digits and occupancies remain as reported; no accepted defect composition or full coordinate-model validation is established.</p></div>;
}
function Value({ entry }: { entry: SourceFollowupEntry }) {
  const v = object(entry.value), w = entry.source_window;
  const t = (key: string) => text(v[key]), q = (key: string) => quantity(v[key]);
  let rows: [string, ReactNode][];
  if (entry.inspection_status === "source_unavailable") return <p className="text-sm text-sage-muted">No numeric value recovered from accessible sources. This does not establish that the paper omits the setting.</p>;
  switch (entry.field) {
    case "calculation_method_and_origin_statement": rows = [["Method",t("method_statement")],["Origin",t("knowledge_origin")],["Reported Tc setting",`${quantity(w.tc_expression)} at ${quantity(w.tc_expression_pressure)}`],["Stability range",`${items(w.stability_pressure_range_gpa).join("–")} GPa; this is not a Tc measurement window`]];break;
    case "source_preparation_description": return <div className="space-y-3">{items(entry.value).map(item => {const r=object(item);return <Rows key={text(r.source_row_id)} rows={[[`Database row ${text(r.source_row_id)}`,text(r.preparation_raw)],["Reference and year",`${text(r.reference_code)} · ${text(r.publication_year_raw)}`]]} />;})}</div>;
    case "source_anneal_temperature_options": rows=[["Database row 155423",items(v.mdr_row155423_options).map(quantity).join(" or ")],["Related series recommendation",t("primary_series_statement")],["Duration","Not supplied; neither option is assigned to an individual sample"]];break;
    case "susceptibility_transition_definition": rows=[["DC criterion",t("dc_criterion")],["AC criterion",t("ac_criterion")],...items(v.mdr_tcsus_values).map(item=>{const r=object(item);return [`Database row ${text(r.row_id)}`,quantity(r.quantity)] as [string,ReactNode];}),["Row-to-probe association","DC or AC assignment of each database value remains unresolved"]];break;
    case "tc_applied_pressure_context": rows=[["Nominal sample",t("source_sm_x_raw")],["Study pressure extent",t("pressure_extent_raw")],["Resistance temperature extent",`${items(v.resistance_temperature_extent_k).join("–")} K`],["Tc and width criteria",`${t("tc_criterion")}; width from ${items(v.width_criterion_percent).join("–")}%`],["Pressure medium",t("pressure_medium")],["Pressure calibration",t("pressure_calibration")],["Record association","The maximum study pressure is not assigned to a catalogue Tc"]];break;
    case "meissner_measurement_method_and_conditions": rows=[["Database row 155423",`${q("database_row155423_vols_raw")} · unit from the official data guide; the row supplies no unit literal`],["Related paper evaluation",`${q("source_evaluation_temperature")} · dc/ac volume and shielding fractions`],["Related DC field",q("dc_zfc_fc_field")],["Related instruments",`${t("dc_instrument")}; AC: ${t("ac_instrument")}`],["Dataset correspondence","The 80% value is not assigned to a specific DC or AC curve; shielding is not automatically Meissner fraction"]];break;
    case "source_composition_and_local_x_definition": rows=[["Source formula",t("source_formula_variable")],["Local x",q("local_x")],["Composition probe",t("composition_probe")],["Formula substitution",`${t("interpreted_fixed_composition")} · from the supplied local x`]];break;
    case "hall_carrier_density_and_conditions": rows=[["Carrier density",q("carrier_density_raw")],["Method",t("method")],["Geometry",t("geometry")],["Carrier sign",t("carrier_sign_context")],["Hall temperature","Not supplied; the equipment's lower temperature limit is not substituted"]];break;
    case "sample_measurement_context": rows=[["Sample and growth",`${t("sample_form")} · ${t("growth")}`],["Surface",t("surface_plane")],["Spectroscopy",t("spectroscopy")],["AC excitation",q("ac_excitation")],["Separate Hc₂ report",`${q("hc2_source_value")} at ${q("hc2_temperature")}; ${t("hc2_criterion")}`]];break;
    case "reported_gap_or_pairing_source_claim": rows=[["Spectroscopic dip positions",t("dip_positions_raw")],["Gap-scale role",t("gap_role")],["Pairing interpretation",t("pairing_claim")],["Full pairing determination",t("full_pairing_type_determination")]];break;
    case "source_local_Ni_composition_definition": rows=[["Source formula",t("source_formula_variable")],["Nominal local x",q("local_nominal_x")],["Formula substitution",t("interpreted_formula")],["Actual versus nominal",t("actual_vs_nominal_statement")]];break;
    case "source_transition_criterion": rows=[["Curve definition",t("hc2_curve_definition")],["Field direction",text(w.field_direction_raw)]];break;
    case "hc2_curve_slope_and_model": rows=[["Signed slope",q("hc2_slope")],["Hc₂(0) extrapolation",q("linear_extrapolated_hc2_zero_k")],["Model",t("model")],["Curve conditions",`${text(w.field_direction_raw)} · ${text(w.hc2_criterion)}`],["WHH comparison",t("authors_whh_limitation")],["Numeric fit-temperature window","Not supplied"]];break;
    case "sample_anneal_conditions": {const p=object(v.cited_source_series_protocol);rows=[["Present study",t("present_study_statement")],["Cited series protocol",`${quantity(p.temperature)} · ${quantity(p.duration)} · ${text(p.atmosphere)}`],["Cited illustration sample",t("cited_illustration_source_formula")],["Individual x = 0.16 treatment","Protocol correspondence remains unestablished"]];break;}
    case "source_local_composition_definition": rows=[["Local Bi x",`${q("source_local_x")} · reported concentration uncertainty ${t("reported_concentration_uncertainty_raw")}`],["Composition probe",t("composition_probe")],["Reported Tc",q("source_tc")],["Tc criterion","Not supplied in the inspected passages"]];break;
    case "reported_short_range_order_claim": rows=[["Reported interpretation",t("reported_order")],["Stance",t("stance")],["Observed proxy",t("observed_proxy")],["Source window","Immediately above Tc up to approximately 40 K; the source reports a qualitatively different response above approximately 40 K"],["Interpretive crossover",q("interpreted_crossover_temperature")]];break;
    case "optical_measurement_temperature_window": rows=[["Equilibrium example",q("equilibrium_optical_example")],["Transient Drude example",q("transient_drude_example")],["Interpretive crossover",q("interpretive_crossover")],["Window limits","Examples are not continuous sweep endpoints or Tc values"]];break;
    case "optical_probe_method": rows=[["Equilibrium probe",`${t("equilibrium_probe")} · ${items(v.equilibrium_frequency_extent_thz).join("–")} THz`],["Transient probe",`${t("transient_probe")} · ${items(v.transient_probe_frequency_extent_thz).join("–")} THz`],["Doped-sample pump",q("doped_sample_pump_frequency")],["Pulse duration",`${items(v.pulse_duration_extent_fs).join("–")} fs`],["Fluence",q("fluence")]];break;
    case "source_rare_earth_member_definition": rows=[["Member",t("source_rare_earth_member")],["Nominal source system",t("source_system")]];break;
    case "reported_magnetic_order_and_temperature": rows=[["Tm magnetic transition · TN",q("tm_source_tn")],["Order assignment",t("source_order")],["Evidence role",t("order_evidence_role")],["Pressure","Not supplied in this source window"]];break;
    case "magnetic_probe_method": rows=[["Study probes",items(v.study_probes).map(text).join("; ")],["Study temperature extent",`${items(v.study_temperature_extent_k).join("–")} K`],["Tm-specific field","Not supplied; the neighboring Er figure's 30 Oe is not transferred"],["Member context",t("tm_probe_context")]];break;
    case "tm_member_transition_criterion": rows=[["Tm superconducting transition · Tc",q("source_tm_tc")],["Probe criterion",t("source_criterion_raw")],["Threshold","Onset or midpoint threshold not supplied for Tm"],["Granular context",t("granular_context")]];break;
    case "listed_atomic_sites": return <Sites value={entry.value} />;
    case "declared_symmetry_operations": return <div><p className="text-sm">{t("declared_count")} operations declared in the captured CIF; no independent space-group inference.</p><details className="mt-2 text-xs"><summary className="w-fit cursor-pointer text-accent-deep">Inspect all declared operations</summary><ol className="mt-2 grid list-inside list-decimal gap-x-5 gap-y-1 font-mono sm:grid-cols-2">{items(v.operations_raw).map((op,index)=><li key={index}>{text(op)}</li>)}</ol></details></div>;
    case "reported_hall_symbol": rows=[["Captured Hall label",t("hall_symbol_raw")],["COD original Hall label",t("original_cod_hall_raw")]];break;
    case "cell_formula_units_z": rows=[["Z",quantity(entry.value)]];break;
    case "source_preparation_and_specific_heat_method": rows=[["Preparation",t("preparation")],["Specific-heat method",t("specific_heat_method")]];break;
    case "source_heating_program": rows=[["Peak heating",q("peak_heating_temperature")],["Program",t("program")],["Atmosphere",t("atmosphere")],["Pressure and duration","Numeric synthesis pressure and hold duration not supplied"]];break;
    case "specific_heat_jump_over_tc": rows=[["Source expression",`${quantity(entry.value)} · printed unit`],["Unit interpretation","The printed mJ/mol K does not resolve the dimensional unit of ΔCp/Tc; no normalized unit is assigned"],["Source analysis setting",`${quantity(w.source_analysis_temperature)} · zero-field data; ${quantity(w.comparison_field)} comparison`]];break;
    case "specific_heat_analysis_context": rows=[["Construction",t("construction")],["Comparison field",q("comparison_field")],["BCS ratio assumption",q("bcs_ratio_assumption")],["Volume assumption",`${q("superconducting_volume_assumption")} · assumed, not measured`]];break;
    case "electronic_specific_heat_coefficient_model": rows=[["Estimated γ",quantity(entry.value)],["Model assumptions",`BCS ratio ${text(w.bcs_ratio)} and ${text(w.assumed_superconducting_volume_percent)}% superconducting volume; this is not a direct normal-state measurement`]];break;
    default:return null;
  }
  return <Rows rows={rows} />;
}
function href(source: Record<string,unknown>) {
  const safe=sourceFollowupHref(source.source_url);if (!safe)return null;
  const url=new URL(safe), location=object(source.original_html_locator ?? source.locator);
  const id=typeof location.xml_xpath === "string" ? location.xml_xpath.match(/^\/\/\*\[@id='([^']+)'\]$/)?.[1] : null;
  if(id)url.hash=id;else if(typeof location.pdf_page === "number")url.hash=`page=${location.pdf_page}`;
  return url.href;
}
function location(entry: SourceFollowupEntry) {
  const result:string[]=[];
  entry.sources.forEach(source=>{const l=object(source.original_html_locator ?? source.locator);if(typeof l.pdf_page === "number")result.push(`PDF page ${l.pdf_page}`);if(typeof l.xml_xpath === "string")result.push(`HTML ${l.xml_xpath.match(/@id='([^']+)'/)?.[1] ?? "selector"}`);});
  entry.field_locators.forEach(l=>{if(l.source_row_id)result.push(`Database row ${text(l.source_row_id)}${l.column ? ` · ${text(l.column)}` : ""}`);if(l.source_line)result.push(`CIF lines ${text(l.source_line)}–${text(l.source_line_end)}`);if(l.guide_column_number)result.push(`Official guide column ${text(l.guide_column_number)}`);for(const key of ["capture_text_spans","original_normalized_selector_spans","normalized_pdf_page_spans"])items(l[key]).forEach(span=>{const s=object(span);result.push(`Captured characters ${text(s.char_start)}–${text(s.char_end)}`);});});
  return [...new Set(result)];
}
function Locator({ entry }: { entry: SourceFollowupEntry }) {
  return <details className="mt-3 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer text-accent-deep">Source locators and limits</summary><ul className="mt-2 space-y-1">{entry.sources.map((source,index)=>{const link=href(source);return link ? <li key={`source-${index}`}><a className="site-text-link" href={link} target="_blank" rel="noopener noreferrer">Open this field’s original source{entry.sources.length > 1 ? ` ${index+1}` : ""} ↗</a></li> : null;})}{location(entry).map(label=><li key={label}>{label}</li>)}</ul><p className="mt-2 break-all font-mono">Source record ID: {entry.id}</p><ul className="mt-2 list-disc space-y-1 pl-4">{entry.limitations.map(limit=><li key={limit}>{limit}</li>)}</ul></details>;
}
function SourceSnapshots({ entries }: { entries: SourceFollowupEntry[] }) {
  const sources=[...new Map(entries.flatMap(entry=>entry.sources).map(source=>[JSON.stringify(source),source])).values()];
  return <details className="mt-4 text-xs leading-5 text-sage-muted"><summary className="w-fit cursor-pointer text-accent-deep">Source snapshots and locators ({sources.length})</summary><ul className="mt-2 space-y-3">{sources.map((source,index)=>{const link=href(source);return <li key={index}><p className="font-medium">{text(source.paper_id ?? source.capture_id)}</p>{link && <a className="site-text-link" href={link} target="_blank" rel="noopener noreferrer">Open original source locator ↗</a>}<p className="break-all">Captured version: {text(source.source_revision)}</p><p className="break-all font-mono">Content SHA-256: {text(source.content_sha256)}</p>{source.source_url_revision_pinned === false && <p>Current file URL is mutable; the captured bytes are identified by their hash.</p>}{typeof source.attribution === "string" && <p>{source.attribution}</p>}</li>;})}</ul></details>;
}
export function MaterialSourceFollowup({ batch, studyContext }: { batch: SourceFollowupBatch | null; studyContext?: StudyContextBatch | null }) {
  const [failedGroup,setFailedGroup]=useState<string|null>(null);
  if (!batch)return <p role="status" className="text-sm text-sage-muted">Captured source records are unavailable.</p>;
  return <div className="space-y-3">{groupSourceFollowup(batch).map(group=><details id={`followup-${group.id}`} className="scroll-mt-24 rounded-lg border border-sage-border bg-white p-4 sm:p-5" key={group.id}><summary className="cursor-pointer text-base font-semibold"><span>{group.label}</span><span className="ml-3 text-xs font-normal tabular-nums text-sage-muted">{group.entries.length} entries{group.entries.some(e=>e.inspection_status === "source_unavailable") ? " · 3 unavailable numeric settings" : ""}</span></summary><div className="mt-4"><p className="max-w-4xl text-sm leading-6 text-sage-muted">{group.scope}</p>{["sn_in","pt_extra"].includes(group.id) && <p className="mt-2 text-xs text-sage-muted">Measurement pressure is not supplied in the inspected source windows.</p>}{group.id === "fese_cif" && <p className="mt-2 text-xs text-sage-muted">Captured cell temperature: 295 K. Pressure not supplied. This independent reference does not release the historical catalogue hold.</p>}<button className="site-text-link mt-3 text-sm" type="button" onClick={()=>{try{setFailedGroup(downloadSourceFollowupGroup(group.id)?null:group.id);}catch{setFailedGroup(group.id);}}}>Download this source group (JSON)</button>{failedGroup === group.id && <p className="mt-2 text-xs text-sage-muted" role="status">Source-group metadata download is unavailable.</p>}<SourceSnapshots entries={group.entries}/>{group.id === "pt_extra" && studyContext && <StudyPtContexts batch={studyContext} />}<ol className="mt-4 divide-y divide-sage-border">{group.entries.map(entry=><li id={entry.id.replace(/[^a-zA-Z0-9_-]/g,"-")} key={entry.id} className="scroll-mt-24 grid min-w-0 gap-3 py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)] md:gap-8"><div><h3 className="text-sm font-semibold">{labels[entry.field] ?? "Source expression"}</h3><p className="mt-1 text-xs leading-5 text-sage-muted">{roleLabels[entry.source_role]}</p></div><div className="min-w-0"><Value entry={entry}/><Locator entry={entry}/></div></li>)}</ol></div></details>)}</div>;
}
