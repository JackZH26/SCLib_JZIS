"use client";

/** Dense catalogue browsing; the displayed Tc and conditions always share a source result. */
import { useEffect, useId, useRef, useState } from "react";
import Link from "@/components/AppLink";
import type { MaterialSemanticField, MaterialSummary, PropertyEvidenceItem } from "@/lib/api";
import { familyLabel } from "@/lib/families";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { AtomicEvidenceDetails, PropertyEvidenceValue } from "@/components/PropertyEvidence";
import { evidenceText, objectValue, propertyOrigin, propertyStatus, propertyValue, selectedProperty, sourceHref } from "@/lib/property-evidence";
import { ScientificAnomalyNotice } from "@/components/ScientificAnomalies";
import { hasMaterialAnomalyReview } from "@/lib/scientific-anomalies";
import { MaterialVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { knownVisibility, SOURCE_SCOPED_VISIBILITY_VERSION, visibilityIsRestricted, visibilityLabel } from "@/lib/material-visibility";
import { MaterialSemanticsPanel } from "@/components/MaterialSemantics";
import { materialSemanticValue, materialSourceCountLabel } from "@/lib/material-semantics";
import { StructureEvidencePanel, StructureEvidenceValue } from "@/components/StructureEvidence";
import { pressureLabel } from "@/lib/pressure-semantics";
import { ScientificMatches } from "@/components/ScientificMatches";
import { materialRowTc, materialTcCriterion, materialTcQuantityKind, type MaterialsTcDisplay } from "@/lib/materials-browser";

const OPTIONAL_COLUMNS = [
  { key: "tc_ambient", label: "Ambient Tc (K)" }, { key: "pairing_symmetry", label: "Pairing" },
  { key: "structure_phase", label: "Phase" }, { key: "is_unconventional", label: "Unconventional" },
  { key: "has_competing_order", label: "Competing order" }, { key: "source_tier", label: "Source tier" },
] as const;
type OptionalColumn = typeof OPTIONAL_COLUMNS[number]["key"];

function locatorAvailable(item: PropertyEvidenceItem | null): boolean {
  const locator = objectValue(objectValue(item?.source).source_locator);
  return ["section", "page", "paragraph", "figure", "table", "row", "column", "line", "chunk_id", "span_id", "start"].some(key => evidenceText(locator[key]));
}
function DisplayTc({ display, material }: { display: MaterialsTcDisplay; material: MaterialSummary }) {
  return <><span className="materials-tc-value">{display.item ? <><span>{propertyValue(display.item, false)}</span><span className="materials-unit"> K</span></> : propertyStatus(material.property_evidence, "tc_max")}</span>
    {display.item && <span className="materials-origin">{propertyOrigin(display.item)}{materialTcQuantityKind(display.item) && <span className="materials-quantity-kind">{materialTcQuantityKind(display.item)}</span>}</span>}
    {display.usesMatch && <span className="materials-matched">Matched result{display.matchCount > 1 ? ` (${display.matchCount} matches)` : ""}</span>}
  </>;
}
function DisplayConditions({ display }: { display: MaterialsTcDisplay }) {
  if (!display.item) return <span className="materials-muted">{display.matched ? "See matching evidence" : "No linked Tc result"}</span>;
  const state = objectValue(display.item.state);
  const conditions = objectValue(display.item.conditions);
  const computed = propertyOrigin(display.item) === "Computed";
  const criterion = materialTcCriterion(evidenceText(conditions.tc_criterion ?? conditions.tc_type));
  const reportedMethod = evidenceText(conditions.method);
  const calculation = evidenceText(conditions.calculation_method) ?? (reportedMethod ? `Reported method: ${reportedMethod}` : null);
  return <><span>{pressureLabel(state.pressure_semantics, typeof state.pressure_gpa === "number" ? state.pressure_gpa : null)}</span><span className="materials-secondary">{computed ? calculation ?? "Calculation method not supplied" : criterion ?? "Criterion not supplied"}</span></>;
}
/** Put decision-relevant source and conditions before the full provenance inventory. */
function CoreTcEvidence({ item }: { item: PropertyEvidenceItem }) {
  const source = objectValue(item.source);
  const state = objectValue(item.state);
  const conditions = objectValue(item.conditions);
  const href = sourceHref(source);
  const sourceLabel = evidenceText(source.paper_id ?? source.doi ?? source.arxiv_id) ?? "Source unavailable";
  const computed = propertyOrigin(item) === "Computed";
  const criterion = evidenceText(conditions.tc_criterion ?? conditions.tc_type);
  const calculation = evidenceText(conditions.calculation_method);
  const reportedMethod = evidenceText(conditions.method);
  const method = computed ? calculation ?? reportedMethod : evidenceText(conditions.calculation_method ?? conditions.measurement_method ?? conditions.method ?? conditions.measurement);
  const methodLabel = computed ? calculation ? "Calculation method" : reportedMethod ? "Reported method" : "Calculation method" : "Method";
  const quantity = objectValue(item.quantity);
  return <dl className="materials-core-evidence" aria-label="Displayed Tc source and conditions">
    <div className="materials-core-source"><dt>Source</dt><dd>{href ? <Link href={href}>{sourceLabel}</Link> : sourceLabel}</dd></div>
    <div><dt>Source year</dt><dd>{evidenceText(source.year) ?? "Not supplied in this record"}</dd></div>
    <div><dt>Pressure</dt><dd>{pressureLabel(state.pressure_semantics, typeof state.pressure_gpa === "number" ? state.pressure_gpa : null)}</dd></div>
    {(!computed || criterion) && <div><dt>{computed ? "Reported Tc criterion" : "Tc criterion"}</dt><dd title={criterion ?? undefined}>{materialTcCriterion(criterion) ?? "Not supplied in this record"}</dd></div>}
    <div><dt>{methodLabel}</dt><dd>{method ?? "Not supplied in this record"}</dd></div>
    <div><dt>Result origin</dt><dd>{propertyOrigin(item)}</dd></div>
    <div><dt>Quantity relation / parser status</dt><dd>{evidenceText(quantity.relation) ?? "Unavailable"} / {evidenceText(quantity.status) ?? "Unavailable"}</dd></div>
  </dl>;
}
function RowWarnings({ material }: { material: MaterialSummary }) {
  const visibility = knownVisibility(material.visibility);
  const review = material.anomaly_review;
  return <div className="materials-row-warnings">
    {visibility?.version === SOURCE_SCOPED_VISIBILITY_VERSION && visibility.source_scope.excluded_records > 0 ? <span className="materials-scope" title={`${visibility.source_scope.eligible_records} of ${visibility.source_scope.total_records} retained records contribute to this view. Excluded records remain subject to Archive access rules.`}>{visibility.source_scope.excluded_records} excluded record{visibility.source_scope.excluded_records === 1 ? "" : "s"}</span> : visibility?.state !== "catalogue" ? <span className="materials-warning">{visibilityLabel(material.visibility).replaceAll(" — ", ": ")}</span> : null}
    {review && (!hasMaterialAnomalyReview(review) || review.needs_review) && <span className="materials-warning">{hasMaterialAnomalyReview(review) ? "Review required" : "Review status unavailable"}</span>}
    {material.needs_review && !review?.needs_review && <span className="materials-warning">Source review pending</span>}
  </div>;
}
function OptionalCell({ column, material }: { column: OptionalColumn; material: MaterialSummary }) {
  if (column === "tc_ambient") {
    const item = selectedProperty(material.property_evidence, "tc_ambient");
    return <span>{item ? propertyValue(item, false) : propertyStatus(material.property_evidence, "tc_ambient")}</span>;
  }
  if (column === "source_tier") return <span title="Source tier is not experimental confirmation">{material.best_credibility_tier ?? "Unknown"}</span>;
  if (column === "structure_phase") return <StructureEvidenceValue evidence={material.structure_evidence} />;
  return <span>{materialSemanticValue(material.material_semantics, column as MaterialSemanticField)}</span>;
}

export function MaterialTable({ rows, resultFiltersActive = false }: { rows: MaterialSummary[]; resultFiltersActive?: boolean }) {
  const visibleRows = rows.filter(row => !visibilityIsRestricted(row.visibility));
  const [columns, setColumns] = useState<OptionalColumn[]>([]);
  const [inspection, setInspection] = useState<MaterialSummary | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!inspection || !dialog.current) return;
    if (!dialog.current.open) {
      if (typeof dialog.current.showModal === "function") dialog.current.showModal();
      else dialog.current.setAttribute("open", "");
    }
  }, [inspection]);
  const close = () => { dialog.current?.close?.(); dialog.current?.removeAttribute("open"); setInspection(null); };
  const inspectedDisplay = inspection ? materialRowTc(inspection, resultFiltersActive) : null;
  if (!visibleRows.length) return <div className="materials-empty" role="status">No materials match these filters. Try widening the Tc or pressure range.</div>;
  return <section aria-label="Material results" className="materials-table-section">
    <div className="materials-table-tools">
      <p>Tc and conditions share one result. <span>Open Evidence for sources and alternatives.</span></p>
      <details className="materials-column-picker"><summary>Scientific columns{columns.length > 0 && <span className="materials-count">{columns.length}</span>}</summary><fieldset>
        <legend>Additional catalogue properties</legend><p>These can describe other results or states.</p>
        {OPTIONAL_COLUMNS.map(column => <label key={column.key}><input type="checkbox" checked={columns.includes(column.key)} onChange={() => setColumns(current => current.includes(column.key) ? current.filter(key => key !== column.key) : [...current, column.key])} />{column.label}</label>)}
      </fieldset></details>
    </div>
    <div className="materials-table-scroll" role="region" aria-label="Scrollable materials table" tabIndex={0}>
      <table className="materials-table">
        <caption className="sr-only">Reported superconducting materials. Default columns show one source-linked Tc result and its conditions; source counts do not establish independent replication.</caption>
        <thead><tr><th scope="col">Formula</th><th scope="col">Family</th><th scope="col">Reported Tc (K)</th><th scope="col">Conditions</th><th scope="col">Source year</th><th scope="col">Sources</th><th scope="col">Evidence status</th>{OPTIONAL_COLUMNS.filter(column => columns.includes(column.key)).map(column => <th scope="col" key={column.key} title={column.key === "source_tier" ? "Source tier is not experimental confirmation" : "Separate catalogue property; may describe another result or state"}>{column.label}</th>)}</tr></thead>
        <tbody>{visibleRows.map(material => {
          const display = materialRowTc(material, resultFiltersActive);
          const year = evidenceText(objectValue(display.item?.source).year);
          const rowFamily = display.matched?.family || material.family;
          return <tr key={material.id}>
            <th scope="row"><Link href={`/materials/${encodeURIComponent(material.id)}`} className="materials-formula" title={material.formula}><FormulaDisplay formula={material.formula} /></Link><RowWarnings material={material} /></th>
            <td title={display.matched?.family ? "Family declared for this matching result" : "Catalogue family classification, not a measured property"}>{rowFamily ? familyLabel(rowFamily) : "Unclassified"}</td>
            <td className="materials-tc-cell"><DisplayTc display={display} material={material} /></td>
            <td className="materials-conditions-cell"><DisplayConditions display={display} /></td>
            <td className="materials-year">{year ?? "Not supplied"}</td>
            <td><button type="button" className="materials-sources-link" onClick={() => setInspection(material)} aria-label={`Sources for ${material.formula}`}>{materialSourceCountLabel(material.material_semantics, material.total_papers)}</button>{material.variant_count > 0 && <span className="materials-secondary">{material.variant_count} variants</span>}</td>
            <td><button type="button" className="materials-evidence-button" onClick={() => setInspection(material)} aria-label={`Evidence for ${material.formula}`}>Evidence</button><span className="materials-secondary">{display.item ? locatorAvailable(display.item) ? "Locator available" : "Locator missing" : "Source unavailable"}</span></td>
            {OPTIONAL_COLUMNS.filter(column => columns.includes(column.key)).map(column => <td key={column.key}><OptionalCell column={column.key} material={material} /></td>)}
          </tr>;
        })}</tbody>
      </table>
    </div>
    <dialog ref={dialog} className="materials-evidence-dialog" aria-labelledby={titleId} onCancel={() => setInspection(null)} onClose={() => setInspection(null)} onClick={event => { if (event.target === event.currentTarget) close(); }}>
      {inspection && inspectedDisplay && <div className="materials-inspection">
        <header><div><h2 id={titleId}><FormulaDisplay formula={inspection.formula} /></h2><p>Source evidence and reported conditions</p></div><button type="button" onClick={close} autoFocus className="materials-dialog-close">Close</button></header>
        <div className="materials-inspection-content">
          <section><h3>{inspectedDisplay.usesMatch ? "Matched Tc result" : "Displayed Tc result"}</h3>
            {inspectedDisplay.item ? <><p className="materials-inspection-value">{propertyValue(inspectedDisplay.item)} <span>{propertyOrigin(inspectedDisplay.item)}</span></p><CoreTcEvidence item={inspectedDisplay.item} /><details className="materials-full-result-context"><summary>Result identity and missing context</summary><p className="materials-inspection-note">Raw criterion tokens, supplied method fields, result and state identifiers, and source locators are available below. Missing context is not inferred from another result.</p><AtomicEvidenceDetails item={inspectedDisplay.item} /></details></> : <p>{propertyStatus(inspection.property_evidence, "tc_max")}. No legacy scalar or filter lower bound is substituted for a source-linked Tc quantity.</p>}
            {inspectedDisplay.usesMatch && <p className="materials-inspection-note">This result matches your filters. It may differ from the catalogue maximum. {inspectedDisplay.matchCount} matching result{inspectedDisplay.matchCount === 1 ? " is" : "s are"} included in this response.</p>}
          </section>
          {resultFiltersActive && <details><summary>Matching result references</summary><ScientificMatches results={inspection.matching_results} scope="material" /></details>}
          <details><summary>Other catalogue selections and result alternatives</summary><p className="materials-inspection-note">Each property has its own source and conditions. These selections are not a joint observation, and unavailable values do not establish absence.</p><div className="materials-inspection-properties"><PropertyEvidenceValue evidence={inspection.property_evidence} field="tc_max" /><PropertyEvidenceValue evidence={inspection.property_evidence} field="tc_ambient" /></div></details>
          <details><summary>Reported classifications</summary><MaterialSemanticsPanel semantics={inspection.material_semantics} /></details>
          <details><summary>Structure and phase evidence</summary><StructureEvidencePanel evidence={inspection.structure_evidence} /></details>
          <details><summary>Catalogue visibility and review policy</summary><MaterialVisibilityNotice visibility={inspection.visibility} /><ScientificAnomalyNotice review={inspection.anomaly_review} /></details>
          <Link className="materials-detail-link" href={`/materials/${encodeURIComponent(inspection.id)}`}>Open full material page</Link>
        </div>
      </div>}
    </dialog>
  </section>;
}
