import type { QeJointReading } from "@/lib/discovery-qe-joint-refinement";

const number = (value: number) => value.toLocaleString("en-US", { maximumSignificantDigits: 10, notation: value !== 0 && Math.abs(value) < 0.0001 ? "scientific" : "standard" });
const labels = {
  incomplete_grid: "Some mesh–smearing combinations are missing",
  insufficient_axis_samples: "Add at least three meshes and three smearing widths",
  scf_precision_insufficient: "Tighten electronic convergence before assessing this window",
  sampled_window_within_tolerance: "Joint sampled energy window is within your tolerance",
  sampled_window_outside_tolerance: "Joint sampled energy window exceeds your tolerance",
};
export function DiscoveryQeJointResult({ result }: { result: QeJointReading }) {
  const report = result.report, window = report.sampled_window;
  return <div className="min-w-0 space-y-4">
    <h3 className="text-lg font-semibold">{labels[window.assessment]}</h3>
    <p className="text-sm text-sage-muted">{report.coverage.supplied} of {report.coverage.expected} combinations supplied across the parameter values in this study. Missing cells are not estimated.</p>
    <div tabIndex={0} role="region" aria-label="Scrollable mesh and smearing energy grid" className="relative max-w-full overflow-x-auto rounded border border-sage-border bg-white">
      <table className="w-full min-w-[600px] text-left text-sm tabular-nums">
        <caption className="p-3 text-left text-xs text-sage-muted">Native QE energy (Hartree/cell), including the chosen smearing contribution. Columns give smearing width in Ry; rows give the k-point mesh.</caption>
        <thead className="bg-sage-surface"><tr><th scope="col" className="px-3 py-3">k mesh</th>{report.axes.smearing_widths_ry.map(width => <th key={width} scope="col" className="px-3 py-3">{number(width)} Ry</th>)}</tr></thead>
        <tbody>{report.axes.meshes.map((mesh, row) => <tr key={mesh.join("-")} className="border-t border-sage-border"><th scope="row" className="whitespace-nowrap px-3 py-3 font-medium">{mesh.join(" × ")}</th>{report.axes.smearing_widths_ry.map((width, col) => {
          const cell = report.cells[row * report.axes.smearing_widths_ry.length + col];
          return <td key={width} className="whitespace-nowrap px-3 py-3">{cell.energy_hartree_per_cell === null ? <span className="text-sage-muted">Not calculated</span> : number(cell.energy_hartree_per_cell)}</td>;
        })}</tr>)}</tbody>
      </table>
    </div>
    <dl className="grid min-w-0 gap-4 sm:grid-cols-2">{[
      ["Finest 3 meshes × smallest 3 widths: energy range", window.energy_range_hartree_per_atom],
      ["Largest reported SCF error in that window", window.maximum_reported_scf_error_hartree_per_atom],
      ["Smallest-three-width range at the finest mesh", report.smallest_three_width_range_at_finest_mesh_hartree_per_atom],
    ].map(([label, value]) => <div key={String(label)} className="min-w-0"><dt className="text-sm text-sage-muted">{label}</dt><dd className="mt-1 break-words font-medium tabular-nums">{typeof value === "number" ? `${number(value)} Hartree/atom` : "Insufficient coverage"}</dd></div>)}</dl>
    <details className="min-w-0 text-sm"><summary className="cursor-pointer font-medium">Mesh sensitivity at each smearing width</summary><dl className="mt-3 space-y-2">{report.mesh_sensitivity_by_width.map(row => <div key={row.smearing_width_ry} className="flex flex-wrap justify-between gap-x-5 gap-y-1"><dt>{number(row.smearing_width_ry)} Ry</dt><dd>{row.energy_range_hartree_per_atom === null ? `${row.mesh_count} of 3 finest meshes available` : `${number(row.energy_range_hartree_per_atom)} Hartree/atom`}</dd></div>)}</dl></details>
    <p className="max-w-3xl text-sm leading-6">The joint assessment needs a complete grid with at least three values on each axis. It checks the energy range across the finest three supplied meshes and smallest three widths. A finite window within tolerance does not prove the dense-mesh or zero-smearing limit. No extrapolation or entropy correction is applied; numerical broadening does not assign an experimental temperature.</p>
  </div>;
}
