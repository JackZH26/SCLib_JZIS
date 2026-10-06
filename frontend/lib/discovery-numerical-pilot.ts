/** Public projection of independently checked pilot artifacts; no private paths or file contents. */
export type NumericalPilotFailure = "not_captured" | "not_executed" | "native_xml_missing" | "native_read_rejected"
  | "initialization_rejected" | "execution_failed" | "timed_out" | "scf_not_converged" | "incomplete";

export type NumericalPilotPoint = {
  mesh: number[];
  status: "scf_reported_converged" | "scf_not_converged" | "incomplete" | "not_read";
  comparison_eligible: boolean;
  initialization_status: "initialization_only" | "not_read";
  exit_code: number | null;
  timed_out: boolean | null;
  elapsed_wall_seconds: { initialization: number | null; execution: number | null };
  energy_hartree_per_cell: number | null;
  scf_error_hartree_per_cell: number | null;
  scf_iterations: number | null;
  file_hashes: {
    input: string | null; preparation_manifest: string | null; xml: string | null; stdout: string | null;
    initialization_xml: string | null; initialization_stdout: string | null; execution_receipt: string | null; reading: string | null;
  };
  failure_code: NumericalPilotFailure | null;
};

export type NumericalPilotCaseExport = { sha256: string; download_url: string | null };
export type NumericalPilotState = {
  catalogue_state_id: string;
  catalogue_group_id: string;
  strain_percent: number;
  source: { provider: "COD"; record_id: string; revision: string; cif_sha256: string; cif_url: string };
  original_cif_sha256: string[];
  generated_cif_sha256: string;
  generated_candidate_id: string;
  coordinate_model_equivalent: true;
  points: NumericalPilotPoint[];
  assessment: "sampled_window_within_tolerance" | "sampled_window_outside_tolerance" | "scf_precision_insufficient" | "not_assessed";
  comparison_sha256: string | null;
  comparison_download_url?: string | null;
  energy_spread_hartree_per_atom: number | null;
  maximum_scf_error_hartree_per_atom: number | null;
  decision: { outcome: "continue" | "redirect"; next_direction: "refine_method"; decision_sha256: string; return_sha256: string } | null;
  case_exports: { prepared: NumericalPilotCaseExport | null; returned: NumericalPilotCaseExport | null; decided: NumericalPilotCaseExport | null; child: NumericalPilotCaseExport | null };
  elapsed_wall_seconds: number | null;
};

export type DiscoveryNumericalPilotSummary = {
  schema_version: "discovery-qe-pilot-compact-summary/1.0.0";
  pilot_id: string;
  catalogue_version: string;
  formula: string;
  host_formula: string;
  model_status: "unrelaxed";
  atom_count: number;
  protocol: {
    plan_sha256: string;
    axis: "mesh";
    mesh_set: number[][];
    tolerance_hartree_per_atom: number;
    spread_operator: string;
    scf_precision_operator: string;
    required_points: number;
    comparison_grouping: string;
    cutoffs_ry: { wavefunction: number; density: number };
    smearing: { kind: string; width_ry: number; physical_temperature_k: null };
    conditions: { charge: number; nspin: 1; pressure_gpa: null; temperature_k: null };
    engine: string;
    functional: string;
    pseudopotential_type: string;
  };
  reader_summary_sha256: string;
  runtime_pw_sha256: string;
  execution_finished_sha256: string;
  elapsed_wall_seconds: number;
  execution_capture_status: "execution_files_captured" | "partial_or_failed";
  pseudopotentials: { element: string; sha256: string }[];
  states: NumericalPilotState[];
  interpretation: string;
  authority: {
    formal_scientific_approval: false; human_scientific_review: null; rps_release: false;
    rps_score: null; rank: null; public_release: false; properties_inherited: false;
  };
};
