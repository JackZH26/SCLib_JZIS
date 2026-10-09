"""Bounded, sequential CHGNet single points on an immutable structure bundle.

Without --execute, only bundle bytes and structure schema are checked. Execution
requires a pinned prepared runtime and an externally limited Linux service. No
relaxation, training, chemistry ranking, formation energy, Tc or RPS is produced.
Every worker loads exact checkpoint bytes with weights_only=True on CPU.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

JOB_SECONDS = 180
GLOBAL_SECONDS = 7100
THREADS = 4
MEMORY_BYTES = 12 * 2**30
MAX_INPUT = 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_RUNTIME_FILE = 512 * 1024 * 1024
CHECKPOINT = "lib/python3.12/site-packages/chgnet/pretrained/0.3.0/chgnet_0.3.0_e29f68s314m37.pth.tar"
WHEEL_SHA = "c5231eac9348cb1a2dac27077d3e836a1f6dc324da8aa16b28139c5e3c5da1d6"
LIFECYCLE_SHA = "c94de42a7c81cb4a6e3ea957cbc01360041342c0c84b617df63db7bf8d9b46de"
HASH = re.compile(r"[a-f0-9]{64}\Z")
ROLES = {"proposal", "baseline_control", "exploratory_control", "ordering_variant", "strain_control"}
CONDITIONS = {"pressure_gpa": None, "temperature_k": None, "charge_state": None, "magnetic_state": None}
AUTHORITY = {"scientific_acceptance": False, "training_performed": False, "relaxation_performed": False,
             "formation_energy_calculated": False, "hull_calculated": False, "tc_calculated": False,
             "bandwidth_calculated": False, "carrier_density_calculated": False,
             "high_potential": None, "rps_score": None, "rank": None}
VERSION = "discovery-chgnet-single-point/1.0.0"


class BatchError(ValueError):
    """Closed error codes; no native payload or credentials in errors."""


def require(condition, code):
    if not condition:
        raise BatchError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, "duplicate_json_key")
        out[key] = value
    return out


def _bad_float(_):
    raise BatchError("nonfinite_json")


def decode(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_bad_float)
    except (ValueError, UnicodeError, RecursionError):
        raise BatchError("invalid_json") from None


def pretty(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def relative(value):
    require(type(value) is str and len(value) <= 512 and value and not value.startswith("/"), "unsafe_path")
    parts = value.split("/")
    require(all(p not in ("", ".", "..") for p in parts) and "\\" not in value and "\0" not in value, "unsafe_path")
    return parts


def read_bounded(root, path, *, expected=None, size=None, maximum=MAX_INPUT, allow_empty=False):
    """Use one regular-file fd, including traversal via non-symlink dir fds."""
    fds = []
    try:
        parts = relative(path)
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
        fds.append(fd)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and (0 if allow_empty else 1) <= before.st_size <= maximum, "file_type_or_size")
        chunks, remaining = [], before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(signature(before) == signature(after) and len(data) == before.st_size, "file_changed_during_read")
        require(size is None or (type(size) is int and len(data) == size), "file_size_mismatch")
        require(expected is None or (type(expected) is str and HASH.fullmatch(expected) and sha(data) == expected), "file_hash_mismatch")
        return data
    except OSError:
        raise BatchError("file_unavailable_or_unsafe") from None
    finally:
        for fd in reversed(fds):
            os.close(fd)


def pinned(root, pin, maximum=MAX_INPUT, *, allow_empty=False):
    require(type(pin) is dict and {"path", "sha256", "bytes"} <= set(pin), "file_pin_missing")
    return read_bounded(root, pin["path"], expected=pin["sha256"], size=pin["bytes"], maximum=maximum,
                        allow_empty=allow_empty)


def _lifecycle():
    raw = read_bounded(Path(__file__).parent, "run_discovery_qe_pilot.py", expected=LIFECYCLE_SHA)
    namespace = {"__name__": "frozen_qe_lifecycle", "__file__": "run_discovery_qe_pilot.py"}
    exec(compile(raw, "run_discovery_qe_pilot.py", "exec"), namespace)
    return namespace


_helpers = _lifecycle()
execute_before_deadline = _helpers["execute_before_deadline"]
atomic_new = _helpers["atomic_new"]
RESERVE_SECONDS = _helpers["TERM_GRACE_SECONDS"] + _helpers["KILL_REAP_SECONDS"]


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def matrix(value, n, m):
    return type(value) is list and len(value) == n and all(type(row) is list and len(row) == m
          and all(finite(x) for x in row) for row in value)


def determinant(m):
    return (m[0][0] * (m[1][1]*m[2][2]-m[1][2]*m[2][1])
            - m[0][1] * (m[1][0]*m[2][2]-m[1][2]*m[2][0])
            + m[0][2] * (m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def validate_input(value):
    keys = {"schema_version", "state_id", "role", "parent_id", "source_id", "source_sha256", "structure_sha256",
            "source_snapshot_sha256", "conditions", "lattice_matrix_angstrom", "species", "fractional_coordinates",
            "occupancy", "composition", "periodic", "cell", "original_atom_ids"}
    require(type(value) is dict and set(value) == keys, "structure_input_fields")
    require(value["schema_version"] == "discovery-chgnet-structure-input/1.0.0", "structure_input_version")
    require(value["role"] in ROLES and value["conditions"] == CONDITIONS and value["periodic"] is True, "structure_condition_or_role")
    for key in ["state_id", "parent_id", "source_id"]:
        require(type(value[key]) is str and re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", value[key]), "structure_identity")
    for key in ["source_sha256", "structure_sha256", "source_snapshot_sha256"]:
        require(type(value[key]) is str and HASH.fullmatch(value[key]), "structure_hash")
    species = value["species"]
    require(type(species) is list and 1 <= len(species) <= 96 and all(type(s) is str and re.fullmatch(r"[A-Z][a-z]?", s) for s in species), "species_or_atom_bound")
    n = len(species)
    require(matrix(value["fractional_coordinates"], n, 3) and all(0 <= f < 1 for row in value["fractional_coordinates"] for f in row), "fractional_coordinates")
    require(type(value["occupancy"]) is list and len(value["occupancy"]) == n
            and all(type(x) in (int, float) and x == 1 for x in value["occupancy"]), "occupancy")
    require(type(value["composition"]) is dict and all(type(x) is int for x in value["composition"].values())
            and value["composition"] == dict(Counter(species)), "composition")
    require(type(value["original_atom_ids"]) is list and len(value["original_atom_ids"]) == n
            and all(type(x) is str and 0 < len(x) <= 160 for x in value["original_atom_ids"])
            and len(set(value["original_atom_ids"])) == n, "atom_identity")
    lattice = value["lattice_matrix_angstrom"]
    require(matrix(lattice, 3, 3) and determinant(lattice) > 1e-8, "lattice")
    require(type(value["cell"]) is dict and set(value["cell"]) == {"a", "b", "c", "alpha", "beta", "gamma"}
            and all(finite(x) and x > 0 for x in value["cell"].values()), "cell")
    lengths = [math.sqrt(sum(x*x for x in row)) for row in lattice]
    for key, actual in zip(["a", "b", "c"], lengths):
        require(math.isclose(value["cell"][key], actual, rel_tol=1e-9, abs_tol=1e-9), "cell_lattice_mismatch")
    for key, (i, j) in zip(["alpha", "beta", "gamma"], [(1, 2), (0, 2), (0, 1)]):
        cosine = sum(x*y for x, y in zip(lattice[i], lattice[j])) / lengths[i] / lengths[j]
        angle = math.degrees(math.acos(max(-1, min(1, cosine))))
        require(math.isclose(value["cell"][key], angle, abs_tol=1e-8), "cell_lattice_mismatch")
    return value


def load_bundle(bundle, expected):
    raw = read_bounded(bundle, "batch-manifest.json", expected=expected, maximum=MAX_MANIFEST)
    manifest = decode(raw)
    require(manifest.get("schema_version") == "discovery-high-throughput-batch/1.0.0", "batch_version")
    rows = manifest.get("inputs")
    require(type(rows) is list and 1 <= len(rows) <= 200, "batch_input_bound")
    if "selection" in manifest:
        selection = manifest["selection"]
        require(type(selection) is dict and set(selection) == {"kind", "source_manifest", "state_ids"}
                and selection["kind"] == "smoke_subset", "subset_selection_fields")
        original = decode(pinned(bundle, selection["source_manifest"], MAX_MANIFEST))
        require(original.get("schema_version") == "discovery-high-throughput-batch/1.0.0"
                and "selection" not in original and type(original.get("inputs")) is list
                and len(original["inputs"]) <= 200 and len(rows) <= 3, "subset_original_manifest")
        require(selection["state_ids"] == [r.get("state_id") for r in rows]
                and all(sum(candidate == row for candidate in original["inputs"]) == 1 for row in rows), "subset_input_not_exact_original")
    records, ids, paths = [], set(), set()
    for row in rows:
        require(type(row) is dict and set(row) == {"state_id", "recipe_id", "role", "path", "sha256", "bytes", "cif"}, "batch_input_fields")
        require(type(row["recipe_id"]) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", row["recipe_id"]), "recipe_id")
        require(row["state_id"] not in ids and row["path"] not in paths, "duplicate_input_identity")
        ids.add(row["state_id"]); paths.add(row["path"])
        source = pinned(bundle, row)
        data = validate_input(decode(source))
        cif = pinned(bundle, row["cif"])
        require(data["state_id"] == row["state_id"] and data["role"] == row["role"]
                and data["structure_sha256"] == sha(cif), "input_identity_or_cif_mismatch")
        records.append({"entry": row, "data": data, "input_bytes": source, "cif_bytes": cif})
    return manifest, raw, records


def runtime_inventory(prefix, manifest_sha, checkpoint_sha):
    require(type(checkpoint_sha) is str and HASH.fullmatch(checkpoint_sha), "checkpoint_pin_required")
    raw = read_bounded(prefix, "runtime-artifact-manifest.json", expected=manifest_sha, maximum=MAX_MANIFEST)
    value = decode(raw)
    require(value.get("schema_version") == "discovery-chgnet-runtime/1.0.0"
            and value.get("prefix") == str(prefix) and value.get("official_wheel_sha256") == WHEEL_SHA, "runtime_identity")
    versions = value.get("versions", {})
    require(versions.get("chgnet") == "0.4.2" and versions.get("torch") == "2.10.0+cpu"
            and re.fullmatch(r"3\.12\.\d+", versions.get("python", "")) and type(versions.get("pymatgen")) is str, "runtime_versions")
    require(value.get("python", {}).get("path") == "bin/python3.12", "runtime_python_path")
    pinned(prefix, value["python"], MAX_RUNTIME_FILE)
    checkpoint = value.get("checkpoint", {})
    require(checkpoint.get("path") == CHECKPOINT and checkpoint.get("sha256") == checkpoint_sha, "checkpoint_identity")
    checkpoint_bytes = pinned(prefix, checkpoint, MAX_RUNTIME_FILE)
    rows = value.get("files")
    require(type(rows) is list and 1 <= len(rows) <= 512, "runtime_inventory_bound")
    names = set()
    require(all(type(r) is dict and type(r.get("bytes")) is int and r["bytes"] >= 0 for r in rows)
            and sum(r["bytes"] for r in rows) <= 512 * 1024 * 1024, "runtime_inventory_total_size")
    for row in rows:
        require(row["path"].startswith("lib/python3.12/site-packages/chgnet/") and row["path"] not in names, "runtime_inventory_path")
        names.add(row["path"])
        # The official wheel includes an empty data/__init__.py. Empty pinned
        # Python modules are valid; weights, binaries and other artifacts are not.
        allow_empty = row["bytes"] == 0 and row["path"].endswith(".py")
        pinned(prefix, row, MAX_RUNTIME_FILE, allow_empty=allow_empty)
    require(CHECKPOINT in names and "lib/python3.12/site-packages/chgnet/model/model.py" in names, "runtime_inventory_incomplete")
    # Detect omitted or newly added importable CHGNet modules, including native extensions.
    installed = prefix / "lib/python3.12/site-packages/chgnet"
    actual = {str(p.relative_to(prefix)) for p in installed.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts
              and (p.suffix in {".py", ".so"} or "pretrained" in p.parts)}
    require(actual <= names, "runtime_code_not_in_inventory")
    return value, raw, checkpoint_bytes


def enforce_cgroup():
    require(sys.platform == "linux", "linux_resource_service_required")
    lines = Path("/proc/self/cgroup").read_text().splitlines()
    require(len(lines) == 1 and lines[0].startswith("0::/"), "cgroup_v2_required")
    group = lines[0][3:].lstrip("/")
    require(re.search(r"(?:^|/)sclib-chgnet-[a-z0-9-]{1,100}\.service$", group), "named_resource_service_required")
    root = Path("/sys/fs/cgroup") / group
    cpu = (root / "cpu.max").read_text().split()
    memory = (root / "memory.max").read_text().strip()
    require(len(cpu) == 2 and all(x.isdigit() for x in cpu) and 0 < int(cpu[0]) <= 4 * int(cpu[1])
            and int(cpu[1]) > 0 and memory.isdigit() and 0 < int(memory) <= MEMORY_BYTES, "resource_limits_missing_or_excessive")
    return {"cpu_max": cpu, "memory_max_bytes": int(memory)}


def match_cif(data, structure):
    """Metric + exact species/periodic-coordinate multiset, independent of row order."""
    require(len(structure) == len(data["species"]) and structure.is_ordered, "cif_atom_count_or_disorder")
    matrix_b = structure.lattice.matrix.tolist()
    require(matrix(matrix_b, 3, 3), "cif_lattice")
    metric = lambda m: [[sum(a*b for a, b in zip(x, y)) for y in m] for x in m]
    a, b = metric(data["lattice_matrix_angstrom"]), metric(matrix_b)
    require(all(math.isclose(a[i][j], b[i][j], rel_tol=1e-8, abs_tol=1e-8) for i in range(3) for j in range(3)), "cif_lattice_mismatch")
    remaining = list(structure)
    for element, xyz in zip(data["species"], data["fractional_coordinates"]):
        matches = [i for i, site in enumerate(remaining) if str(site.specie) == element
                   and all(abs((float(a)-float(b)+0.5) % 1 - 0.5) <= 1e-7 for a,b in zip(site.frac_coords, xyz))]
        require(len(matches) == 1, "cif_species_coordinates_mismatch_or_duplicate")
        remaining.pop(matches[0])
    require(not remaining, "cif_unmatched_atoms")


def normalize_prediction(output, atom_count, volume):
    """Preserve CHGNet eV/atom directly; only shape/finite checks and norms."""
    require(type(output) is dict and all(k in output for k in ["e", "f", "s", "m"]), "prediction_missing_fields")
    scalar = output["e"].item() if hasattr(output["e"], "item") else output["e"]
    convert = lambda x: x.tolist() if hasattr(x, "tolist") else x
    force, stress, moment = [convert(output[k]) for k in ["f", "s", "m"]]
    require(finite(scalar) and matrix(force, atom_count, 3) and matrix(stress, 3, 3)
            and type(moment) is list and len(moment) == atom_count and all(finite(x) for x in moment)
            and finite(volume) and volume > 0, "prediction_shape_or_nonfinite")
    max_force = max(math.sqrt(sum(x*x for x in v)) for v in force)
    require(finite(max_force), "prediction_derived_nonfinite")
    return {"energy": {"value": scalar, "unit": "eV/atom", "normalization": "native_intensive_no_extra_division"},
            "forces": {"values": force, "unit": "eV/angstrom", "layout": "input atom order, xyz",
                       "frame": "Cartesian frame of input lattice_matrix_angstrom"},
            "stress": {"values": stress, "unit": "GPa", "layout": "native 3x3 tensor",
                       "frame": "Cartesian frame of input lattice_matrix_angstrom"},
            "magnetic_moments": {"values": moment, "unit": "mu_B/atom", "scope": "Nonnegative predicted site moment magnitudes; not signed spin orientation or measured magnetic order"},
            "max_force": {"value": max_force, "unit": "eV/angstrom"},
            "volume": {"value": volume, "unit": "angstrom^3"}}


def calculate(data, cif_bytes, prefix, runtime, checkpoint_bytes):
    import importlib.metadata
    import torch
    from chgnet.model.model import CHGNet
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifParser
    for name in ["chgnet", "torch", "pymatgen"]:
        require(importlib.metadata.version(name) == runtime["versions"][name], "imported_distribution_version")
    import chgnet.model.model as chgnet_module
    require(Path(chgnet_module.__file__).resolve() == prefix / "lib/python3.12/site-packages/chgnet/model/model.py"
            and Path(torch.__file__).resolve().is_relative_to(prefix), "imported_module_outside_runtime")
    require(sys.version.split()[0] == runtime["versions"]["python"] and Path(sys.executable).resolve() == prefix / "bin/python3.12", "worker_interpreter_identity")
    torch.set_num_threads(THREADS)
    torch.set_num_interop_threads(1)
    parser = CifParser.from_str(cif_bytes.decode("utf-8"), occupancy_tolerance=1.0, site_tolerance=1e-8, frac_tolerance=0)
    structures = parser.parse_structures(primitive=False, check_occu=True)
    require(len(structures) == 1, "cif_single_structure_required")
    match_cif(data, structures[0])
    structure = Structure(Lattice(data["lattice_matrix_angstrom"]), data["species"], data["fractional_coordinates"], coords_are_cartesian=False)
    state = torch.load(io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=True)
    require(type(state) is dict and "model" in state, "checkpoint_model_missing")
    model = CHGNet.from_dict(state["model"], mlp_out_bias=False, version="0.3.0").to("cpu")
    require(model.is_intensive is True and all(p.device.type == "cpu" for p in model.parameters()), "model_intensive_cpu_required")
    model.eval()  # Do not use no_grad: forces/stress require autograd.
    output = model.predict_structure(structure, task="efsm")
    return normalize_prediction(output, len(data["species"]), float(structure.volume))


def context(data, input_sha, cif_sha, manifest_sha, runtime_sha, checkpoint_sha, script_sha):
    return {"state_id": data["state_id"], "role": data["role"], "parent_id": data["parent_id"],
            "source_id": data["source_id"], "source_sha256": data["source_sha256"],
            "source_snapshot_sha256": data["source_snapshot_sha256"], "structure_sha256": cif_sha,
            "input_sha256": input_sha, "batch_manifest_sha256": manifest_sha,
            "runtime_manifest_sha256": runtime_sha, "checkpoint_sha256": checkpoint_sha,
            "runner_sha256": script_sha, "lifecycle_sha256": LIFECYCLE_SHA,
            "method": {"name": "CHGNet", "package_version": "0.4.2", "checkpoint_version": "0.3.0",
                       "device": "cpu", "threads": THREADS, "operation": "single_point", "mlp_out_bias": False},
            "conditions": data["conditions"], "original_atom_ids": data["original_atom_ids"]}


def worker(args):
    import resource
    enforce_cgroup()
    resource.setrlimit(resource.RLIMIT_FSIZE, (8*1024*1024, 8*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (JOB_SECONDS*THREADS, JOB_SECONDS*THREADS))
    job = args.worker_request.parent.resolve(strict=True)
    request = decode(read_bounded(job, args.worker_request.name, expected=args.worker_request_sha256))
    require(set(request) == {"context", "input", "cif", "runtime_prefix"}, "worker_request_fields")
    require(request["runtime_prefix"] == str(args.runtime_prefix), "worker_runtime_path")
    current_script = read_bounded(Path(__file__).parent, Path(__file__).name)
    require(sha(current_script) == request["context"]["runner_sha256"], "worker_script_changed")
    raw = pinned(job, request["input"]); data = validate_input(decode(raw)); cif = pinned(job, request["cif"])
    require(context(data, sha(raw), sha(cif), request["context"]["batch_manifest_sha256"], args.runtime_manifest_sha256,
                    args.checkpoint_sha256, sha(current_script)) == request["context"], "worker_context_mismatch")
    runtime, _, checkpoint = runtime_inventory(args.runtime_prefix, args.runtime_manifest_sha256, args.checkpoint_sha256)
    t0 = time.monotonic()
    result = calculate(data, cif, args.runtime_prefix, runtime, checkpoint)
    # Runtime code/weights must remain fixed throughout imports and calculation.
    runtime_inventory(args.runtime_prefix, args.runtime_manifest_sha256, args.checkpoint_sha256)
    atomic_new(job / "result.json", {"schema_version": VERSION, "status": "single_point_completed",
               "binding": request["context"], "prediction": result, "compute_wall_seconds": time.monotonic()-t0,
               "authority": AUTHORITY, "interpretation": "Pretrained atomistic-model outputs; no thermodynamic reference energies or superconductivity inference."})


def write_bytes_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)


def run_batch(args, records, manifest_raw, start):
    limits = enforce_cgroup()
    runtime, runtime_raw, _ = runtime_inventory(args.runtime_prefix, args.runtime_manifest_sha256, args.checkpoint_sha256)
    script = read_bounded(Path(__file__).parent, Path(__file__).name)
    helper = read_bounded(Path(__file__).parent, "run_discovery_qe_pilot.py", expected=LIFECYCLE_SHA)
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_bytes_new(args.output / "runner.py", script)
    write_bytes_new(args.output / "run_discovery_qe_pilot.py", helper)
    write_bytes_new(args.output / "batch-manifest.json", manifest_raw)
    write_bytes_new(args.output / "runtime-artifact-manifest.json", runtime_raw)
    (args.output / "jobs").mkdir(mode=0o700)
    common = {"schema_version": "discovery-chgnet-batch-execution/1.0.0", "started_at_utc": stamp(),
              "manifest_sha256": sha(manifest_raw), "runtime_manifest_sha256": sha(runtime_raw),
              "runner_sha256": sha(script), "lifecycle_sha256": LIFECYCLE_SHA,
              "checkpoint_sha256": args.checkpoint_sha256, "limits": limits,
              "per_job_seconds": JOB_SECONDS, "global_seconds": GLOBAL_SECONDS,
              "term_grace_seconds": _helpers["TERM_GRACE_SECONDS"], "kill_reap_seconds": _helpers["KILL_REAP_SECONDS"],
              "authority": AUTHORITY, "input_count": len(records)}
    atomic_new(args.output / "started.json", common)
    receipts, succeeded, stop_reason = [], 0, None
    # A clean environment prevents inherited Python paths, GPU selection and user caches.
    env = {"PATH": str(args.runtime_prefix / "bin") + ":/usr/bin:/bin",
           "XDG_CACHE_HOME": str(args.output / "cache"),
           "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
           "NUMEXPR_NUM_THREADS": "4", "CUDA_VISIBLE_DEVICES": "", "MPLCONFIGDIR": str(args.output / "mpl-cache")}
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    try:
        for index, record in enumerate(records):
            if start + GLOBAL_SECONDS - time.monotonic() <= RESERVE_SECONDS:
                stop_reason = "global_budget_exhausted"; break
            begun = time.monotonic(); deadline = min(start + GLOBAL_SECONDS, begun + JOB_SECONDS)
            job = args.output / "jobs" / f"{index:03d}-{record['entry']['recipe_id']}"
            job.mkdir(mode=0o700)
            receipt = {"state_id": record["data"]["state_id"], "role": record["data"]["role"], "job_started_at_utc": stamp(),
                       "status": "failed", "process": None, "result": None, "worker_log": None, "reason_code": None}
            write_bytes_new(job / "input.json", record["input_bytes"]); write_bytes_new(job / "input.cif", record["cif_bytes"])
            binding = context(record["data"], sha(record["input_bytes"]), sha(record["cif_bytes"]), sha(manifest_raw),
                              sha(runtime_raw), args.checkpoint_sha256, sha(script))
            request = {"context": binding, "runtime_prefix": str(args.runtime_prefix),
                       "input": {"path": "input.json", "bytes": len(record["input_bytes"]), "sha256": sha(record["input_bytes"])},
                       "cif": {"path": "input.cif", "bytes": len(record["cif_bytes"]), "sha256": sha(record["cif_bytes"])}}
            request_raw = pretty(request); write_bytes_new(job / "request.json", request_raw)
            try:
                argv = [str(args.runtime_prefix / runtime["python"]["path"]), "-I", str(args.output / "runner.py"),
                        "--execute", "--worker-request", str(job / "request.json"), "--worker-request-sha256", sha(request_raw),
                        "--runtime-prefix", str(args.runtime_prefix), "--runtime-manifest-sha256", sha(runtime_raw),
                        "--checkpoint-sha256", args.checkpoint_sha256]
                with (job / "worker.log").open("xb") as log:
                    outcome = execute_before_deadline(argv, cwd=job, stdout=log, env=env, deadline=deadline)
                receipt["process"] = outcome
                if outcome is None or outcome["process_reaped"]:
                    log_raw = read_bounded(job, "worker.log", maximum=8*1024*1024, allow_empty=True)
                    receipt["worker_log"] = {"path": str((job/"worker.log").relative_to(args.output)), "bytes": len(log_raw), "sha256": sha(log_raw)}
                if outcome is None:
                    receipt["reason_code"] = "insufficient_remaining_job_budget"
                elif not outcome["process_reaped"]:
                    receipt["reason_code"] = "process_not_reaped"; stop_reason = "process_not_reaped"
                elif outcome["exit_code"] != 0 or outcome["timed_out"]:
                    receipt["reason_code"] = "worker_failed_or_timed_out"
                else:
                    raw = read_bounded(job, "result.json")
                    result = decode(raw)
                    require(result.get("schema_version") == VERSION and result.get("status") == "single_point_completed"
                            and result.get("binding") == binding and result.get("authority") == AUTHORITY, "result_context_or_scope")
                    p = result["prediction"]
                    require(finite(p["volume"]["value"]) and math.isclose(p["volume"]["value"], determinant(record["data"]["lattice_matrix_angstrom"]), rel_tol=1e-10, abs_tol=1e-10), "result_volume_mismatch")
                    expected = normalize_prediction({"e": p["energy"]["value"], "f": p["forces"]["values"],
                               "s": p["stress"]["values"], "m": p["magnetic_moments"]["values"]}, len(record["data"]["species"]), p["volume"]["value"])
                    require(expected == p, "result_shape_units_or_normalization")
                    require(time.monotonic() <= deadline, "job_deadline_exceeded")
                    receipt["result"] = {"path": str((job / "result.json").relative_to(args.output)), "bytes": len(raw), "sha256": sha(raw)}
                    receipt["status"] = "single_point_completed"; succeeded += 1
            except Exception as error:
                receipt["reason_code"] = str(error) if isinstance(error, BatchError) else type(error).__name__
            receipt.update({"binding": binding, "job_wall_seconds": time.monotonic()-begun,
                            "job_deadline_exceeded": time.monotonic() > deadline, "job_finished_at_utc": stamp()})
            if receipt["job_deadline_exceeded"] and receipt["status"] == "single_point_completed":
                receipt["status"] = "failed"; receipt["reason_code"] = "job_deadline_exceeded"; succeeded -= 1
            atomic_new(job / "receipt.json", receipt)
            receipt_raw = read_bounded(job, "receipt.json")
            receipts.append({"state_id": receipt["state_id"], "status": receipt["status"], "receipt_sha256": sha(receipt_raw),
                             "path": str((job / "receipt.json").relative_to(args.output))})
            print(json.dumps({"job_index": index, "status": receipt["status"], "reason_code": receipt["reason_code"]}), flush=True)
            if stop_reason:
                break
    except Exception as error:
        stop_reason = str(error) if isinstance(error, BatchError) else type(error).__name__
    complete = succeeded == len(records) and time.monotonic()-start <= GLOBAL_SECONDS and not stop_reason
    atomic_new(args.output / "finished.json", {**common, "finished_at_utc": stamp(), "wall_seconds": time.monotonic()-start,
               "status": "complete_single_points" if complete else "partial_or_failed", "successful_jobs": succeeded,
               "jobs": receipts, "unstarted_jobs": len(records)-len(receipts), "stop_reason": stop_reason})
    return 0 if complete else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--runtime-prefix", type=Path, required=True)
    parser.add_argument("--runtime-manifest-sha256")
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-request-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    os.umask(0o077)
    start = time.monotonic()
    try:
        args.runtime_prefix = args.runtime_prefix.absolute()
        if args.execute:
            require(type(args.runtime_manifest_sha256) is str and HASH.fullmatch(args.runtime_manifest_sha256), "runtime_manifest_pin_required")
        if args.worker_request:
            require(args.execute and args.worker_request_sha256 and not args.bundle and not args.output, "invalid_worker_invocation")
            worker(args); return 0
        require(args.bundle is not None and args.output is not None and args.manifest_sha256 is not None, "batch_arguments_required")
        manifest, raw, records = load_bundle(args.bundle.absolute(), args.manifest_sha256)
        if not args.execute:
            print(json.dumps({"status": "selected_inputs_verified_not_executed", "inputs": len(records),
                              "unselected_artifacts_validated": False,
                              "manifest_sha256": sha(raw), "runtime_checked": False, "model_imported": False})); return 0
        args.output = args.output.absolute()
        return run_batch(args, records, raw, start)
    except Exception as error:
        print(json.dumps({"status": "rejected", "reason_code": str(error) if isinstance(error, BatchError) else type(error).__name__}), flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
