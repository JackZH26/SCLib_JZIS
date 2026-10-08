"""Freeze existing real-file M4 calibration inputs; never run or enqueue a solver."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

SOURCE_MANIFEST_SHA256 = "af978e9f847a77913a32b19f09910b67d42c8d185943b25c5e1f8ffd9277f838"
STATE_ID = "reference-control:supercell:3e7b6416dccf8a84904856faa1737f85d02304b98af8ca16ed8e44b0db2e5dcc"
MESHES = ((4, 4, 6), (6, 6, 10), (8, 8, 12))
UPF_PINS = {
    "B.pbe-n-kjpaw_psl.1.0.0.UPF": "4a41b06dfc361efde113fc033a06b9103e6d09df58f6f167c44b47e5ed082135",
    "Mg.pbe-spnl-kjpaw_psl.1.0.0.UPF": "c6420b82107b1fe96a798a0232093dacb0e0917dbb49bccbff5f845525b2810a",
}
OUTPUT_RULES = [
    {"name": "stdout.txt", "max_bytes": 8 * 1024**2},
    {"name": "stderr.txt", "max_bytes": 1024**2},
    {"name": "data-file-schema.xml", "max_bytes": 8 * 1024**2},
    {"name": "execution.json", "max_bytes": 128 * 1024},
]


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")) or "\\" in value:
        raise ValueError("Expected a normalized relative artifact path")
    return path


def read_regular(root: Path, relative: str) -> bytes:
    path = safe_relative(relative)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink artifacts or parent directories are forbidden")
    if not current.is_file():
        raise ValueError("Artifact must be a regular file")
    descriptor = os.open(current, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def read_pinned(root: Path, pin: dict) -> bytes:
    content = read_regular(root, pin["path"])
    if len(content) != pin["bytes"] or sha256(content) != pin["sha256"]:
        raise ValueError(f"Pinned artifact changed: {pin['path']}")
    return content


def protocol() -> dict:
    return {
        "schema_version": "sclib-m4-calibration-plan/1",
        "status": "prepared_not_run",
        "runtime_id": "qe-7.5-770a0b2-arm64",
        "runtime_attestation_required": True,
        "source_bundle_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "material": "Mg4B8",
        "parent_formula": "MgB2",
        "state_id": STATE_ID,
        "atom_count": 12,
        "expected_upf_valence_electrons": 64,
        "strain_percent": 0,
        "meshes": [list(mesh) for mesh in MESHES],
        "settings": {"ecutwfc_ry": 60, "ecutrho_ry": 480, "smearing": "mv", "degauss_ry": 0.02,
                     "conv_thr_ry": 1e-10, "electron_maxstep": 100, "mixing_beta": 0.3,
                     "engine_max_seconds": 600, "charge": 0, "nspin": 1, "spin_orbit": False,
                     "restart_mode": "from_scratch", "geometry": "fixed"},
        "execution_controls": {
            "max_concurrent_heavy_jobs": 1, "max_attempts": 1,
            "threads_per_rank": 1, "blas_threads": 1,
            "memory_bytes_per_job": 12 * 1024**3,
            "minimum_available_memory_bytes_before_launch": 24 * 1024**3,
            "minimum_free_disk_bytes_before_launch": 20 * 1024**3,
            "node_disk_floor_also_required": True,
            "memory_enforcement": "Worker process-tree RSS watchdog; this is not an OS hard memory cgroup on macOS. Record sampling interval and observed peak, and retain any overshoot.",
            "cpu_enforcement": "MPI ranks plus single-thread settings; not a claim of macOS hard CPU quota or CPU affinity.",
        },
        "stages": [
            {"id": "first_closed_loop", "sequence": [
                {"payload": "k4x4x6-initialize", "ranks": 2, "wall_seconds": 180},
                {"payload": "k4x4x6-scf", "ranks": 2, "wall_seconds": 900}],
             "maximum_reserved_core_seconds": 2160,
             "release_condition": "Node native acceptance, pinned runtime and process-tree controls verified; release only one job at a time."},
            {"id": "rank_calibration", "sequence": [
                {"payload": "k4x4x6-scf", "ranks": 1, "wall_seconds": 900},
                {"payload": "k4x4x6-scf", "ranks": 4, "wall_seconds": 900}],
             "maximum_additional_reserved_core_seconds": 4500,
             "release_condition": "First SCF has complete native output and independently checked SCF convergence; retain the first 2-rank reading as the reference."},
            {"id": "finite_mesh_window", "sequence": [
                {"payload": "k4x4x6-scf", "ranks": None, "wall_seconds": 900},
                {"payload": "k6x6x10-scf", "ranks": None, "wall_seconds": 900},
                {"payload": "k8x8x12-scf", "ranks": None, "wall_seconds": 900}],
             "maximum_additional_reserved_core_seconds": 10800,
             "rank_upper_bound": 4,
             "reuse_rule": "The exact selected-rank coarse result from calibration may be reused with its immutable receipt and hashes; do not re-label it as a new execution.",
             "release_condition": "Rank comparison passes. Operator chooses one tested rank count, confirms measured cost and reserves the explicit remaining budget. Future initializations need separate envelopes and count toward the cap."},
        ],
        "rank_comparison": {
            "ranks": [1, 2, 4], "reference_ranks": 2,
            "same_input_upf_runtime_required": True,
            "all_native_scf_converged_required": True,
            "energy_range_tolerance_hartree_per_atom": 1e-7,
            "max_scf_error_strictly_below_hartree_per_atom": 1e-7,
            "maximum_force_component_difference_hartree_per_bohr": 1e-5,
            "maximum_stress_component_difference_hartree_per_bohr3": 1e-6,
            "force_stress_scope": "Reproducibility across rank counts only; not geometry or force/stress convergence.",
            "missing_nonfinite_or_unmatched_output": "incomplete; never pass",
            "performance_measurement": "One observation per rank count; report elapsed time, core-seconds, RSS sampling and limits. A noisy timing result is not a reliable speedup claim.",
            "selection": "Among passing configurations prefer measured lower wall time within the agreed core-second and memory envelope; if timing differences are ambiguous prefer 2 ranks, not an invented speedup."},
        "mesh_comparison": {
            "all_three_native_scf_converged_required": True,
            "energy_window_tolerance_hartree_per_atom": 1e-4,
            "max_scf_error_strictly_below_hartree_per_atom": 1e-4,
            "formula": "(max(E_Hartree_per_cell) - min(E_Hartree_per_cell)) / 12",
            "scope": "Finite sampled energy sensitivity only. Cutoff, smearing, target-observable convergence and the infinite-mesh limit remain unestablished."},
        "stop_rules": [
            "Initialization is not an SCF result. Its success cannot pass the SCF or mesh gate.",
            "Transport acceptance, exit code 0 and JOB DONE alone do not establish electronic convergence.",
            "Stop the dependent stage on hash/runtime mismatch, resource breach, missing output, non-convergence or a failed comparison. Retain raw outputs and receipts.",
            "If the unchanged 600-second engine limit stops a job, retain that attempt and freeze a new version before changing max_seconds; never edit the queued deck.",
            "No automatic solver retry, tolerance relaxation, zero-filled measurements or replacement of failed evidence.",
        ],
        "historical_vps_reference": {
            "material": "Mg7AlB16", "atom_count": 24, "date": "2026-10-06",
            "electronic_scf_converged": 9, "executions": 9, "meshes": [[2, 2, 2], [4, 4, 4], [6, 6, 6]],
            "energy_windows_hartree_per_atom": [0.0006334572564270502, 0.0007494048434040224, 0.0008587643862464726],
            "finite_mesh_windows_passed": 0, "predeclared_tolerance_hartree_per_atom": 1e-4,
            "comparison_scope": "Different composition, cell and meshes; historical numerical caution, not a cross-platform energy reference or a Mini speed baseline."},
        "authority": {"auto_enqueue": False, "queue_authorization": False, "calculation_executed": False,
                      "budget_status": "bounded staged proposal; actual release and reservation are separate",
                      "full_36_input_campaign_budget": None, "scientific_publication_authority": False,
                      "new_material_discovery": False, "tc_calculated": False, "assigned_pressure_gpa": None},
    }


def build(source: Path, output: Path, summary: Path) -> dict:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source must be an existing non-symlink directory")
    if output.exists() or output.is_symlink() or summary.exists() or summary.is_symlink():
        raise ValueError("Output bundle and summary must be new; preparations are immutable")
    raw_manifest = read_regular(source, "bundle-manifest.json")
    if sha256(raw_manifest) != SOURCE_MANIFEST_SHA256:
        raise ValueError("Unexpected source bundle manifest")
    original = json.loads(raw_manifest)
    pins = {}
    for pin in original["files"]:
        safe_relative(pin["path"])
        if pin["path"] in pins:
            raise ValueError("Duplicate source artifact path")
        pins[pin["path"]] = pin
        read_pinned(source, pin)  # Validate the entire frozen source bundle.
    selected = [j for j in original["jobs"] if j["role"] == "parent" and j["strain_percent"] == 0]
    if len(selected) != 3 or {tuple(j["mesh"]) for j in selected} != set(MESHES):
        raise ValueError("Expected exactly the three frozen zero-strain parent meshes")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".m4-calibration-", dir=output.parent))
    written = []

    def save(relative: str, content: bytes) -> dict:
        target = staging / str(safe_relative(relative))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as handle:
            os.chmod(target, 0o600)
            handle.write(content)
        pin = {"path": relative, "sha256": sha256(content), "bytes": len(content)}
        written.append(pin)
        return pin

    try:
        plan = protocol()
        save("source/bundle-manifest.json", raw_manifest)
        save("source/parent-plus0.cif", read_pinned(source, pins["states/parent-plus0.cif"]))
        payloads = []
        for job in selected:
            if job["state_id"] != STATE_ID or job["composition"] != {"B": 8, "Mg": 4} or job["expected_valence_electrons"] != 64:
                raise ValueError("Unexpected parent state or valence identity")
            manifest_data = read_pinned(source, job["preparation_manifest"])
            manifest = json.loads(manifest_data)
            upfs = manifest["pseudopotentials"]
            if {u["filename"]: u["sha256"] for u in upfs} != UPF_PINS:
                raise ValueError("Parent UPF identity differs")
            mesh_tag = "k" + "x".join(map(str, job["mesh"]))
            for phase, role in (("initialize", "initialization"), ("scf", "execution")):
                payload_name = f"{mesh_tag}-{phase}"
                prefix_path = f"payloads/{payload_name}"
                filename = manifest["files"][role]["filename"]
                input_data = read_pinned(source, pins[f"{job['directory']}/{filename}"])
                if sha256(input_data) != manifest["files"][role]["sha256"]:
                    raise ValueError("Native deck differs from original preparation manifest")
                match = re.findall(rb"(?m)^\s*prefix\s*=\s*'([^']+)'\s*,?\s*$", input_data)
                if len(match) != 1:
                    raise ValueError("Expected exactly one original prefix")
                manifest_name = Path(job["preparation_manifest"]["path"]).name
                native = {"schema_version": "sclib-native-qe/1", "input_name": filename,
                          "source_manifest_name": manifest_name, "prefix": match[0].decode("ascii"),
                          "pseudo_names": sorted(UPF_PINS)}
                entries = [save(f"{prefix_path}/native.json", encoded(native)),
                           save(f"{prefix_path}/{filename}", input_data),
                           save(f"{prefix_path}/{manifest_name}", manifest_data)]
                for upf in upfs:
                    upf_data = read_pinned(source, pins[f"{job['directory']}/pseudo/{upf['filename']}"])
                    if sha256(upf_data) != upf["sha256"] or len(upf_data) != upf["byte_length"]:
                        raise ValueError("UPF differs from preparation manifest")
                    entries.append(save(f"{prefix_path}/{upf['filename']}", upf_data))
                payloads.append({"id": payload_name, "kind": f"qe_{phase}", "mesh": job["mesh"],
                                 "directory": prefix_path, "input_artifacts": [
                                     {"name": Path(pin["path"]).name, "sha256": pin["sha256"], "bytes": pin["bytes"]}
                                     for pin in entries], "output_rules": OUTPUT_RULES,
                                 "status": "prepared_not_run"})
        plan["payloads"] = payloads
        plan_pin = save("calibration-plan.json", encoded(plan))
        manifest_pin = save("bundle-manifest.json", encoded({
            "schema_version": "sclib-m4-calibration-bundle/1", "plan": plan_pin,
            "source_bundle_manifest_sha256": SOURCE_MANIFEST_SHA256, "files": list(written),
            "calculation_executed": False, "queueable": False}))
        save("SHA256SUMS", ("\n".join(f"{p['sha256']}  {p['path']}" for p in written) + "\n").encode())
        os.rename(staging, output)
        projection = {**plan, "bundle_manifest_sha256": manifest_pin["sha256"],
                      "calibration_plan_sha256": plan_pin["sha256"], "artifact_files_prepared": len(written),
                      "sha256sum_entries": len(written) - 1}
        summary.parent.mkdir(parents=True, exist_ok=True)
        with summary.open("xb") as handle:
            handle.write(encoded(projection))
        return {"bundle_manifest_sha256": manifest_pin["sha256"], "calibration_plan_sha256": plan_pin["sha256"],
                "payloads": len(payloads), "files": len(written), "calculation_executed": False}
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.summary), sort_keys=True))


if __name__ == "__main__":
    main()
