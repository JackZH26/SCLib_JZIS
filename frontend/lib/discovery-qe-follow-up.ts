import { prepareQeInput, type QeSettings } from "@/lib/discovery-qe-input";
import { QE_RESULT_VERSION, type QeResultContext } from "@/lib/discovery-qe-result";
import { coordinateSha256 } from "@/lib/discovery-site-candidates";

export const QE_FOLLOW_UP_VERSION = "discovery-qe-follow-up/1.0.0";
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const fail = (message: string): never => { throw new Error(message); };

export function canPrepareQeFollowUp(context: QeResultContext): boolean {
  return context.reading.report.input_kind === "execution"
    && context.reading.report.settings.calculation === "scf";
}

/** Continue from the original, fixed candidate. No wavefunction restart or relaxed-geometry import. */
export async function prepareQeFollowUp(input: QeResultContext, settings: QeSettings, rationale: string) {
  const context = structuredClone(input), requested = structuredClone(settings);
  const note = rationale.trim();
  if (!note || Array.from(note).length > 2000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(note)) {
    fail("Describe why you are preparing this follow-up, using 1 to 2,000 characters.");
  }
  if (!canPrepareQeFollowUp(context)) fail("Follow-up preparation currently uses original fixed-geometry SCF inputs. Relaxation output needs an explicit final-coordinate model first.");
  const { reading, preparation } = context, previous = preparation.prepared;
  const report = reading.report;
  if (report.version !== QE_RESULT_VERSION || reading.json !== JSON.stringify(report, null, 2) + "\n"
    || await coordinateSha256(reading.json) !== reading.sha256) fail("The prior reading changed. Read the original files again.");
  const reconstructed = await prepareQeInput(preparation.batch, previous.manifest.candidate.id, previous.manifest.settings, preparation.pseudos);
  if (!same(previous, reconstructed)) fail("The original preparation changed. Read the original files again.");
  const manifest = reconstructed.manifest;
  if (report.preparation_id !== manifest.id || report.candidate_id !== manifest.candidate.id
    || report.candidate_cif_sha256 !== manifest.candidate.cif_sha256 || report.parent_id !== manifest.parent_id
    || !same(report.composition, manifest.candidate.composition) || !same(report.source_reference, manifest.source_reference)
    || !same(report.settings, manifest.settings) || !same(report.pseudopotentials, manifest.pseudopotentials)
    || report.files.filter(file => file.role === "manifest").length !== 1
    || report.files.find(file => file.role === "manifest")?.sha256 !== reconstructed.sha256
    || report.files.filter(file => file.role === "input").length !== 1
    || report.files.find(file => file.role === "input")?.sha256 !== manifest.files.execution.sha256) {
    fail("The reading does not belong to this original preparation.");
  }
  const prepared = await prepareQeInput(preparation.batch, manifest.candidate.id, requested, preparation.pseudos);
  const changes = (Object.keys(manifest.settings) as (keyof QeSettings)[])
    .filter(key => !same(manifest.settings[key], prepared.manifest.settings[key]))
    .map(key => ({ field: key, before: manifest.settings[key], after: prepared.manifest.settings[key] }));
  const record = {
    version: QE_FOLLOW_UP_VERSION,
    relation: changes.length ? "changed_settings" : "repeat_preparation",
    researcher_rationale: note,
    previous_reading: { sha256: reading.sha256, filename: reading.filename, report },
    previous_preparation: { sha256: reconstructed.sha256, filename: reconstructed.filename },
    next_preparation: { sha256: prepared.sha256, filename: prepared.filename, manifest: prepared.manifest },
    settings_changes: changes,
    geometry: { basis: "original_prepared_candidate", candidate_id: manifest.candidate.id, cif_sha256: manifest.candidate.cif_sha256 },
    scope: {
      next_run_executed: false, wavefunction_restart: false, relaxed_coordinates_imported: false,
      previous_results_inherited: false, cross_run_comparability_established: false,
      execution_authenticated: false, stable_host_validated: false, tc_calculated: false,
      scientific_acceptance: false, database_write: false,
    },
  };
  const json = JSON.stringify(record, null, 2) + "\n", sha256 = await coordinateSha256(json);
  return { prepared, lineage: { record, json, sha256, filename: `sclib-qe-follow-up-${sha256.slice(0, 16)}.json` } };
}
export type QeFollowUp = Awaited<ReturnType<typeof prepareQeFollowUp>>;
