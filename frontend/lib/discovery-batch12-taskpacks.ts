import { generateCombinedCandidates, prepareCombinedReferenceControl, type CombinedCandidate } from "@/lib/discovery-combined-candidates";
import { supercellModel } from "@/lib/discovery-site-candidates";

/** A small factorial calibration design, not a superconductivity prediction. */
export async function buildBatch12TaskPacks() {
  const model = supercellModel("cod-1526507", [2, 2, 1]);
  const mg = model.atoms.find(atom => atom.element === "Mg")!;
  const b = model.atoms.find(atom => atom.element === "B")!;
  const batch = await generateCombinedCandidates({ referenceId: model.reference.id, repeats: model.repeats, strain: "-2,0,2",
    sites: [{ targetId: mg.id, replacements: "Al", vacancy: false, unchanged: true },
      { targetId: b.id, replacements: "C", vacancy: false, unchanged: true }] });
  const control = await prepareCombinedReferenceControl(batch);
  const states = [control, ...batch.candidates].map((candidate: CombinedCandidate) => ({
    id: candidate.id, role: candidate.composition.Al ? candidate.composition.C ? "al_c" : "al_only" : candidate.composition.C ? "c_only" : "parent",
    strain_percent: candidate.strain_percent, candidate,
  })).sort((a, b) => a.role.localeCompare(b.role, "en") || a.strain_percent - b.strain_percent);
  const studies = [
    { id: "mgb2-al-paired", question: "What changes under one ordered Mg-site Al substitution at matched lattice and numerical settings?",
      roles: ["parent", "al_only"], nominal_composition: "Mg3AlB8", sublattice_fraction: "1/4 Mg sites replaced",
      prior: "Al substitution in MgB2 is known and can suppress Tc. Extra nominal electrons are not a carrier-density or Tc gain.",
      prior_url: "https://doi.org/10.1103/PhysRevB.71.144512" },
    { id: "mgb2-c-paired", question: "What changes under one ordered B-site C substitution at matched lattice and numerical settings?",
      roles: ["parent", "c_only"], nominal_composition: "Mg4B7C", sublattice_fraction: "1/8 B sites replaced",
      prior: "C substitution is known; alloy disorder, strain and nominal electron count are coupled. This ordered cell does not model a disordered experimental sample.",
      prior_url: "https://doi.org/10.1103/PhysRevB.64.134513" },
    { id: "mgb2-al-c-factorial", question: "Is the joint response nonadditive after matching geometry and comparing both single substitutions?",
      roles: ["parent", "al_only", "c_only", "al_c"], nominal_composition: "Mg3AlB7C", sublattice_fraction: "1/4 Mg and 1/8 B sites replaced",
      prior: "Al/C codoping is known. The exact ordered model is a controlled research input, with novelty unresolved until structure-aware prior-art review.",
      prior_url: "https://doi.org/10.1016/j.physc.2025.1354776" },
  ].map(study => ({ ...study, state_ids: states.filter(s => study.roles.includes(s.role)).map(s => s.id),
    execution_status: "prepared_not_run", novelty_credit: false, superconductivity_claim: false,
    stop_rule: "Retain failed or incomplete calculations. Do not rank an observable until its own matched-state convergence test passes.",
  }));
  return { schema_version: "discovery-factorial-calibration/1.0.0", batch, states, studies,
    scope: { source: "COD 1526507 pinned coordinates", construction: "Explicit ordered 12-atom cells; no symmetry-unique or dilute-defect claim",
      charge: 0, nspin: 1, spin_orbit: false, assigned_pressure_gpa: null, assigned_temperature_k: null,
      strain: "Uniform linear lattice perturbation, not a measured pressure or equilibrium volume",
      geometry_route: "Constructed perturbations; causal benefit untested", bandwidth_route: "Active-orbital bandwidth unmeasured",
      carrier_route: "Mobile carrier density unmeasured; UPF valence count is bookkeeping only",
      source_phase_experiment_association: "unestablished", new_material_discovery: false, formal_RPS: null },
    protocol: { stage: "fixed-geometry numerical calibration before relaxation or physics interpretation",
      meshes: [[4, 4, 6], [6, 6, 10], [8, 8, 12]], ecutwfc_ry: 60, ecutrho_ry: 480, degauss_ry: 0.02,
      sampled_energy_tolerance_ha_per_atom: 1e-4,
      pass_rule: "For each identical state: all three SCFs converge, max SCF error/atom < 1e-4 Ha and (max E - min E)/12 <= 1e-4 Ha. Finite sampled mesh sensitivity only; cutoff/smearing convergence remains separate.",
      comparison: "Never rank absolute total energies across different compositions. Later use matched observables or a mass-balanced reaction with declared chemical potentials.",
      factorial: "For a common converged observable Y at a matched strain, interaction = Y(Al+C) - Y(Al) - Y(C) + Y(parent). Record numerical uncertainty before interpretation.",
      subsequent_stages: ["cutoff and smearing sensitivity for the declared observable", "fixed-cell relaxation with force and stress readback",
        "explicit active-orbital model and band/DOS sampling before bandwidth claims", "Fermi-surface or transport model with units before carrier claims",
        "competing structures, magnetism and phonons before stability/pairing follow-up"],
      execution_budget: null, auto_enqueue: false, machine_readiness_required: true },
  };
}
