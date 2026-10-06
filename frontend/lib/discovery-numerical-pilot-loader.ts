import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import type { ResearchCatalogue } from "@/lib/discovery-research-catalogue";
import type { DiscoveryNumericalPilotSummary } from "@/lib/discovery-numerical-pilot";
import { importResearchCase, RESEARCH_AXES, type ResearchCase } from "@/lib/discovery-research-cycle";
import { prepareResearchModel } from "@/lib/discovery-research-model";
import { compareQeReadings, type QeConvergenceReading } from "@/lib/discovery-qe-convergence";
import { verifyWorkspaceState } from "@/lib/discovery-research-workspace";

const digest = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const hash = /^[a-f0-9]{64}$/;
function check(condition: unknown): asserts condition { if (!condition) throw new Error("The retained numerical pilot could not be verified."); }

/** Only a frozen, root-reviewed projection can supply public numerical observations. */
export async function getDiscoveryNumericalPilot(catalog: ResearchCatalogue): Promise<DiscoveryNumericalPilotSummary> {
  const directory = join(process.cwd(), "public/research-pilots");
  const file = readFileSync(join(directory, "discovery-qe-pilot-2026-10-06.json"));
  const pins = JSON.parse(readFileSync(join(directory, "discovery-qe-pilot-2026-10-06.pins.json"), "utf8"));
  check(pins.schema_version === "discovery-qe-pilot-public-pins/1.0.0" && hash.test(pins.summary_sha256) && digest(file) === pins.summary_sha256);
  const summary = JSON.parse(file.toString("utf8")) as DiscoveryNumericalPilotSummary;
  check(summary.schema_version === "discovery-qe-pilot-compact-summary/1.0.0" && summary.catalogue_version === catalog.version
    && summary.protocol.plan_sha256 === pins.plan_sha256 && summary.reader_summary_sha256 === pins.reader_summary_sha256
    && summary.model_status === "unrelaxed" && summary.states.length === 3 && summary.formula === "Mg7AlB16" && summary.atom_count === 24
    && summary.protocol.axis === "mesh" && summary.protocol.tolerance_hartree_per_atom === 1e-4
    && summary.protocol.conditions.pressure_gpa === null && summary.protocol.conditions.temperature_k === null);
  const authority = { formal_scientific_approval: false, human_scientific_review: null,
    rps_release: false, rps_score: null, rank: null, public_release: false, properties_inherited: false };
  check(Object.keys(summary.authority).length === Object.keys(authority).length
    && Object.entries(authority).every(([key, value]) => summary.authority[key as keyof typeof authority] === value));
  const seen = new Set<string>();
  for (const state of summary.states) {
    const original = catalog.states.find(s => s.id === state.catalogue_state_id);
    check(original && !seen.has(original.id) && original.group_id === state.catalogue_group_id && original.formula === summary.formula
      && original.strain_micro_percent / 1e6 === state.strain_percent && state.coordinate_model_equivalent === true);
    seen.add(original.id);
    const occurrenceHashes = original.occurrence_ids.map(id => catalog.occurrences.find(o => o.id === id)!.cif_sha256).sort();
    check(JSON.stringify([...state.original_cif_sha256].sort()) === JSON.stringify(occurrenceHashes));
    const parent = catalog.parents.find(p => p.id === original.parent_id)!;
    const source = catalog.sources.find(s => s.id === parent.source_id)!;
    const group = catalog.groups.find(g => g.id === original.group_id);
    check(group && group.source_id === source.id && summary.host_formula === group.host_formula && summary.host_formula === source.formula);
    check(state.source.cif_sha256 === source.cif_sha256 && state.source.record_id === source.record_id && state.source.revision === String(source.revision)
      && state.source.provider === source.provider && state.source.cif_url === source.cif_url);
    check(state.points.length === 3 && JSON.stringify(state.points.map(p => p.mesh)) === JSON.stringify(summary.protocol.mesh_set));
    const model = await prepareResearchModel(catalog, original.id);
    check(state.generated_cif_sha256 === model.lineage.generated_cif_sha256 && state.generated_candidate_id === model.candidateId);
    check(typeof state.comparison_download_url === "string" && /^\/research-pilots\/[A-Za-z0-9_/-]+\.json$/.test(state.comparison_download_url));
    const comparisonPath = resolve(process.cwd(), "public", state.comparison_download_url.slice(1));
    check(comparisonPath.startsWith(resolve(directory) + sep));
    const comparisonBytes = readFileSync(comparisonPath);
    check(digest(comparisonBytes) === state.comparison_sha256);
    const comparison = JSON.parse(comparisonBytes.toString("utf8")) as QeConvergenceReading["report"];
    const replayed = await compareQeReadings(comparison.readings.map(reading => ({ ...reading,
      json: JSON.stringify(reading.report, null, 2) + "\n" })), "mesh", summary.protocol.tolerance_hartree_per_atom);
    check(replayed.sha256 === state.comparison_sha256 && comparison.candidate_cif_sha256 === state.generated_cif_sha256
      && comparison.candidate_id === state.generated_candidate_id && comparison.atom_count === summary.atom_count
      && comparison.sampled_window.assessment === state.assessment
      && comparison.sampled_window.energy_spread_hartree_per_atom === state.energy_spread_hartree_per_atom
      && comparison.sampled_window.maximum_reported_scf_error_hartree_per_atom === state.maximum_scf_error_hartree_per_atom);
    check(comparison.points.length === state.points.length && comparison.points.every((point, i) =>
      point.reading_sha256 === state.points[i].file_hashes.reading && JSON.stringify(point.parameter) === JSON.stringify(state.points[i].mesh)
      && point.energy_hartree_per_cell === state.points[i].energy_hartree_per_cell
      && Math.abs(point.scf_error_hartree_per_atom - state.points[i].scf_error_hartree_per_cell! / summary.atom_count) < 1e-15));
    check(summary.protocol.required_points === comparison.sampled_window.point_count
      && summary.protocol.required_points === state.points.length && summary.protocol.smearing.physical_temperature_k === null);
    for (const point of state.points) {
      const reading = comparison.readings.find(r => r.sha256 === point.file_hashes.reading);
      check(reading);
      const report = reading.report, settings = report.settings, protocol = summary.protocol;
      check(protocol.engine === `${report.engine.name} ${report.engine.version}`
        && protocol.cutoffs_ry.wavefunction === settings.ecutwfc && protocol.cutoffs_ry.density === settings.ecutrho
        && protocol.smearing.kind === settings.smearing && protocol.smearing.width_ry === settings.degauss
        && protocol.conditions.charge === settings.charge && protocol.conditions.nspin === settings.nspin
        && point.scf_iterations === report.convergence.scf_steps);
      check(report.pseudopotentials.length > 0 && summary.pseudopotentials.length === report.pseudopotentials.length
        && new Set(summary.pseudopotentials.map(p => p.element)).size === summary.pseudopotentials.length
        && report.pseudopotentials.every(p => p.functional === protocol.functional && p.pseudo_type === protocol.pseudopotential_type
          && summary.pseudopotentials.some(pin => pin.element === p.element && pin.sha256 === p.sha256)));
      // These four artifacts are pinned by the native reading itself. Runtime,
      // initialization and elapsed-time custody remains in the operator receipts.
      for (const [role, field] of [["manifest", "preparation_manifest"], ["input", "input"], ["xml", "xml"], ["stdout", "stdout"]] as const) {
        const captured = report.files.filter(file => file.role === role);
        check(captured.length === 1 && captured[0].sha256 === point.file_hashes[field]);
      }
    }
    const stages: Record<string, ResearchCase> = {};
    check(Object.keys(state.case_exports).sort().join(" ") === "child decided prepared returned");
    for (const [stage, exported] of Object.entries(state.case_exports)) {
      check(exported && hash.test(exported.sha256) && typeof exported.download_url === "string"
        && /^\/research-pilots\/[A-Za-z0-9_/-]+\.json$/.test(exported.download_url));
      const path = resolve(process.cwd(), "public", exported.download_url.slice(1));
      check(path.startsWith(resolve(directory) + sep));
      const bytes = readFileSync(path); check(digest(bytes) === exported.sha256);
      const record = await importResearchCase(bytes.toString("utf8"));
      check(record.definition.state.catalogue_reference?.catalog_state_id === state.catalogue_state_id
        && record.definition.state.structure?.sha256 === state.generated_cif_sha256);
      await verifyWorkspaceState(catalog, state.catalogue_state_id, record.definition.state);
      check(RESEARCH_AXES.every(axis => record.definition.evidence[axis].status === "unknown" && record.definition.evidence[axis].readings.length === 0));
      stages[stage] = record;
    }
    const { prepared, returned, decided, child } = stages;
    check(prepared && returned && decided && child && prepared.returns.length === 0 && prepared.decision === null
      && returned.returns.length === 1 && returned.decision === null && decided.returns.length === 1 && decided.decision !== null
      && child.returns.length === 0 && child.decision === null);
    check(prepared.binding.definition_sha256 === returned.binding.definition_sha256
      && returned.binding.definition_sha256 === decided.binding.definition_sha256
      && prepared.definition.action.numerical_protocol?.kind === summary.protocol.axis
      && prepared.definition.action.numerical_protocol.tolerance_hartree_per_atom === summary.protocol.tolerance_hartree_per_atom);
    const retained = returned.returns[0];
    check(retained.kind === "qe_sampled_study" && retained.numerical_assessment === state.assessment
      && retained.artifacts[0].sha256 === state.comparison_sha256
      && retained.return_sha256 === decided.returns[0].return_sha256
      && decided.decision!.return_sha256 === retained.return_sha256
      && state.decision?.return_sha256 === retained.return_sha256
      && state.decision.decision_sha256 === decided.decision!.decision_sha256
      && state.decision.outcome === decided.decision!.decision && state.decision.next_direction === decided.decision!.next_direction
      && child.parent?.case_id === decided.binding.case_id && child.parent.decision_sha256 === decided.decision!.decision_sha256
      && child.parent.properties_inherited === false);
    check(state.points.every(point => point.comparison_eligible && point.status === "scf_reported_converged"
      && point.exit_code === 0 && point.timed_out === false && point.initialization_status === "initialization_only"
      && Number.isFinite(point.energy_hartree_per_cell) && Number.isFinite(point.scf_error_hartree_per_cell)
      && hash.test(point.file_hashes.reading!) && prepared.definition.action.input_artifacts.some(pin => pin.sha256 === point.file_hashes.reading)));
    const range = (Math.max(...state.points.map(p => p.energy_hartree_per_cell!)) - Math.min(...state.points.map(p => p.energy_hartree_per_cell!))) / summary.atom_count;
    const error = Math.max(...state.points.map(p => p.scf_error_hartree_per_cell!)) / summary.atom_count;
    check(state.energy_spread_hartree_per_atom !== null && Math.abs(range - state.energy_spread_hartree_per_atom) < 1e-12
      && state.maximum_scf_error_hartree_per_atom !== null && Math.abs(error - state.maximum_scf_error_hartree_per_atom) < 1e-15);
    const expectedAssessment = error >= summary.protocol.tolerance_hartree_per_atom ? "scf_precision_insufficient"
      : range <= summary.protocol.tolerance_hartree_per_atom ? "sampled_window_within_tolerance" : "sampled_window_outside_tolerance";
    check(state.assessment === expectedAssessment);
  }
  return summary;
}
