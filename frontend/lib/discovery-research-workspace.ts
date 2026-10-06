import { researchStateFromCatalogue, type ResearchStateInput } from "@/lib/discovery-research-cycle";
import { prepareResearchModel } from "@/lib/discovery-research-model";
import type { ResearchCatalogue } from "@/lib/discovery-research-catalogue";

/** A self-hash establishes custody; this replay separately establishes the catalogue association. */
export async function verifyWorkspaceState(catalog: ResearchCatalogue, stateId: string, supplied: ResearchStateInput): Promise<void> {
  const selected = structuredClone(supplied), expected = await researchStateFromCatalogue(catalog, stateId);
  for (const key of ["formula", "host_formula", "catalogue_reference", "source_pins", "modifications"] as const) {
    if (JSON.stringify(selected[key]) !== JSON.stringify(expected[key])) throw new Error("The research state does not match the selected catalogue source, composition or modifications.");
  }
  if (selected.relation_to_catalogue === "catalogue_model") {
    if (JSON.stringify(selected) !== JSON.stringify(expected)) throw new Error("Catalogue-model coordinates and conditions must remain unchanged. Declare a derived condition state separately.");
    return;
  }
  if (selected.relation_to_catalogue !== "proposed_conditions") throw new Error("Use an exact catalogue model or its declared condition variant.");
  if (JSON.stringify(selected.structure) === JSON.stringify(expected.structure)) return;
  const replay = await prepareResearchModel(catalog, stateId);
  const generated = { artifact_id: replay.candidateId, version: replay.batch.version, sha256: replay.lineage.generated_cif_sha256 };
  if (JSON.stringify(selected.structure) !== JSON.stringify(generated)) throw new Error("The coordinate artifact differs from the selected state and its reproducible QE model.");
}
