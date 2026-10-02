import Link from "@/components/AppLink";
import { FamilyFilterField } from "@/components/FamilyFilterField";
import { MaterialsOriginField } from "@/components/MaterialsOriginField";
import { MATERIALS_ADVANCED_KEYS, materialFilterChips, materialsHref, type MaterialsQuery } from "@/lib/materials-browser";

const FIELD_KEYS = new Set(["q", "family", "tc_min", "pressure_max", "knowledge_origin", "experimental_only", "page", "sort", "per_page", ...MATERIALS_ADVANCED_KEYS]);

export function MaterialsFilters({ query, pageSize }: { query: MaterialsQuery; pageSize: number }) {
  const chips = materialFilterChips(query);
  const advancedCount = chips.filter(chip => MATERIALS_ADVANCED_KEYS.includes(chip.key)).length;
  const triSelect = (name: string, label: string) => <label className="materials-field">
    <span>{label}</span>
    <select name={name} defaultValue={query[name] ?? ""}>
      <option value="">Any status</option><option value="true">Reported true</option><option value="false">Qualified reported false</option>
    </select>
  </label>;
  return <section aria-label="Material filters" className="materials-filter-section">
    <form id="materials-filter-form" className="materials-filter-form" method="get" action={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}/materials`}>
      <input type="hidden" name="per_page" value={pageSize} />
      {Object.entries(query).filter(([key, value]) => value && !FIELD_KEYS.has(key)).map(([key, value]) => <input key={key} type="hidden" name={key} value={value} />)}
      <div className="materials-basic-grid">
        <label className="materials-field materials-formula-field"><span id="materials-formula-label">Formula contains</span><input type="search" name="q" maxLength={400} defaultValue={query.q ?? ""} placeholder="e.g. NbN or BiTeCl" aria-labelledby="materials-formula-label" aria-describedby="materials-formula-help" /><small id="materials-formula-help">Case-insensitive text, including subscripts.</small></label>
        <div className="materials-field materials-family-field"><span id="materials-family-label">Family</span><FamilyFilterField key={query.family ?? ""} initial={query.family ?? ""} /></div>
        <label className="materials-field"><span>Tc ≥ (K)</span><input type="number" name="tc_min" min="0" step="any" defaultValue={query.tc_min ?? ""} placeholder="Any Tc" /></label>
        <label className="materials-field"><span>Pressure ≤ (GPa)</span><input type="number" name="pressure_max" min="0" step="any" defaultValue={query.pressure_max ?? ""} placeholder="Any pressure" /></label>
        <label className="materials-field" htmlFor="materials-origin"><span>Result origin</span><MaterialsOriginField key={`${query.knowledge_origin}:${query.experimental_only}`} initial={query.knowledge_origin} observedOnly={query.experimental_only === "true"} /></label>
        <div className="materials-filter-actions"><button type="submit" className="btn-primary">Apply</button><Link href="/materials" className="materials-clear">Clear filters</Link></div>
      </div>
      <details className="materials-advanced">
        <summary>Advanced filters{advancedCount > 0 && <span className="materials-count">{advancedCount} active</span>}</summary>
        <div className="materials-advanced-grid">
          <label className="materials-field"><span>Reported pairing</span><select name="pairing_symmetry" defaultValue={query.pairing_symmetry ?? ""}>
            <option value="">Any pairing</option>{["s-wave", "s±", "d-wave", "p-wave", "chiral", "nodal"].map(value => <option key={value} value={value}>{value}</option>)}
            {query.pairing_symmetry && !["s-wave", "s±", "d-wave", "p-wave", "chiral", "nodal"].includes(query.pairing_symmetry) && <option value={query.pairing_symmetry}>{query.pairing_symmetry}</option>}
          </select></label>
          {triSelect("is_unconventional", "Reported unconventional")}
          {triSelect("has_competing_order", "Reported competing order")}
          <label className="materials-field"><span>Ambient result</span><select name="ambient_sc" defaultValue={query.ambient_sc ?? ""}><option value="">Any</option><option value="true">Explicit ambient + observed Tc</option>{query.ambient_sc === "false" && <option value="false">Saved false filter (unsupported)</option>}</select></label>
          <label className="materials-field"><span>Result source tier</span><select name="min_tier" defaultValue={query.min_tier ?? ""}><option value="">Any tier</option><option value="T1">T1 only</option><option value="T2">T1–T2</option><option value="T3">T1–T3</option></select></label>
          <label className="materials-field"><span>Source links ≥</span><input type="number" name="min_papers" min="1" step="1" defaultValue={query.min_papers ?? ""} placeholder="Any count" /></label>
          <label className="materials-field"><span>Pressure ≥ (GPa)</span><input type="number" name="pressure_min" min="0" step="any" defaultValue={query.pressure_min ?? ""} placeholder="Any pressure" /></label>
          <label className="materials-field"><span>Source role</span><select name="source_role" defaultValue={query.source_role ?? ""}><option value="">Any role</option><option value="primary">Primary report</option><option value="cited">Cited report</option></select></label>
        </div>
        <div className="materials-checkboxes">
          {[['only_aps', 'Only APS data'], ['include_skeletons', 'Include library-only entries'], ['include_unknown_pressure', 'Include unknown pressure'], ['parents_only', 'Parent materials only']].map(([name, label]) => <label key={name}><input type="checkbox" name={name} value="true" defaultChecked={query[name] === "true"} />{label}</label>)}
        </div>
        <div className="materials-phase-status"><label className="materials-field"><span>Reviewed phase filtering</span><input disabled defaultValue={query.structure_phase ?? ""} placeholder="Pending source review" /></label><p>Phase proposals need a reviewed material and state association before filtering.</p></div>
        {query.structure_phase && <input type="hidden" name="structure_phase" value={query.structure_phase} />}
      </details>
    </form>
    {chips.length > 0 && <div className="materials-active-filters" aria-label="Active material filters">{chips.map(chip => <Link key={chip.key} href={materialsHref(query, chip.key === "knowledge_origin" && query.knowledge_origin === "Observed" ? [chip.key, "experimental_only"] : [chip.key])} aria-label={`Remove ${chip.label}`} className="materials-filter-chip">{chip.label}<span aria-hidden="true"> ×</span></Link>)}</div>}
  </section>;
}
