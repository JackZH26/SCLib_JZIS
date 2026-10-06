"""Fake-compute lifecycle and structural counterexamples; never installs/runs ML."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_discovery_chgnet_batch as batch  # noqa: E402


def structure():
    return {"schema_version": "discovery-chgnet-structure-input/1.0.0", "state_id": "state:one", "role": "proposal",
            "parent_id": "parent:one", "source_id": "cod-test", "source_sha256": "1"*64,
            "structure_sha256": "2"*64, "source_snapshot_sha256": "3"*64, "conditions": dict(batch.CONDITIONS),
            "lattice_matrix_angstrom": [[3., 0., 0.], [0., 3., 0.], [0., 0., 3.]],
            "species": ["Mg", "B"], "fractional_coordinates": [[0., 0., 0.], [.5, .5, .5]],
            "occupancy": [1, 1], "composition": {"Mg": 1, "B": 1}, "periodic": True,
            "cell": {"a": 3., "b": 3., "c": 3., "alpha": 90., "beta": 90., "gamma": 90.},
            "original_atom_ids": ["site1", "site2"]}


def prediction():
    return {"e": -6.0, "f": [[3., 4., 0.], [0., 0., 0.]], "s": [[1., 0., 0.], [0., 2., 0.], [0., 0., 3.]], "m": [0., .2]}


def bundle(tmp_path, count=2):
    root = tmp_path / "bundle"; root.mkdir()
    rows = []
    for i in range(count):
        data = structure(); data["state_id"] = f"state:{i}"
        cif = b"data_test\n"; data["structure_sha256"] = batch.sha(cif)
        raw = batch.pretty(data)
        (root / f"{i}.json").write_bytes(raw); (root / f"{i}.cif").write_bytes(cif)
        rows.append({"state_id": data["state_id"], "recipe_id": f"recipe-{i}", "role": "proposal", "path": f"{i}.json",
                     "bytes": len(raw), "sha256": batch.sha(raw), "cif": {"path": f"{i}.cif", "bytes": len(cif), "sha256": batch.sha(cif)}})
    raw = batch.pretty({"schema_version": "discovery-high-throughput-batch/1.0.0", "inputs": rows})
    (root / "batch-manifest.json").write_bytes(raw)
    return root, batch.sha(raw)


def test_dry_run_never_imports_or_computes_or_creates_output(tmp_path, monkeypatch, capsys):
    root, digest = bundle(tmp_path)
    monkeypatch.setattr(batch, "runtime_inventory", lambda *a: pytest.fail("dry run imported runtime"))
    monkeypatch.setattr(batch, "run_batch", lambda *a: pytest.fail("dry run computed"))
    output = tmp_path / "new"
    rc = batch.main(["--bundle", str(root), "--manifest-sha256", digest, "--runtime-prefix", "/not-installed",
                     "--checkpoint-sha256", "a"*64, "--output", str(output)])
    assert rc == 0 and not output.exists()
    assert json.loads(capsys.readouterr().out)["model_imported"] is False


@pytest.mark.parametrize("change,reason", [
    ("atoms", "species_or_atom_bound"), ("occupancy", "occupancy"), ("nonfinite", "lattice"),
    ("left_handed", "lattice"), ("formula", "composition"), ("duplicate_ids", "atom_identity"),
    ("pressure", "structure_condition_or_role"), ("cell", "cell_lattice_mismatch"),
    ("fraction", "fractional_coordinates"), ("extra", "structure_input_fields"),
])
def test_input_counterexamples(change, reason):
    data = structure()
    if change == "atoms": data["species"] *= 49
    elif change == "occupancy": data["occupancy"][0] = .5
    elif change == "nonfinite": data["lattice_matrix_angstrom"][0][0] = math.nan
    elif change == "left_handed": data["lattice_matrix_angstrom"][0][0] = -3
    elif change == "formula": data["composition"]["Mg"] = 2
    elif change == "duplicate_ids": data["original_atom_ids"] = ["site1", "site1"]
    elif change == "pressure": data["conditions"]["pressure_gpa"] = 0
    elif change == "cell": data["cell"]["alpha"] = 80
    elif change == "fraction": data["fractional_coordinates"][0][0] = 1.1
    elif change == "extra": data["claimed_tc"] = 300
    with pytest.raises(batch.BatchError, match=reason): batch.validate_input(data)


def test_manifest_rejects_rebound_cif_and_duplicate_state(tmp_path):
    root, digest = bundle(tmp_path)
    _, raw, _ = batch.load_bundle(root, digest)
    m = json.loads(raw); m["inputs"][1]["state_id"] = m["inputs"][0]["state_id"]
    raw = batch.pretty(m); (root / "batch-manifest.json").write_bytes(raw)
    with pytest.raises(batch.BatchError, match="duplicate_input_identity"): batch.load_bundle(root, batch.sha(raw))
    m["inputs"][1]["state_id"] = "state:1"
    (root / "0.cif").write_bytes(b"replacement")
    m["inputs"][0]["cif"].update(bytes=11, sha256=batch.sha(b"replacement"))
    raw = batch.pretty(m); (root / "batch-manifest.json").write_bytes(raw)
    with pytest.raises(batch.BatchError, match="input_identity_or_cif_mismatch"): batch.load_bundle(root, batch.sha(raw))


def test_energy_is_native_per_atom_no_second_division():
    result = batch.normalize_prediction(prediction(), 2, 27.)
    assert result["energy"]["value"] == -6.0
    assert result["max_force"]["value"] == 5.0
    assert result["forces"]["values"] == prediction()["f"]
    assert result["magnetic_moments"]["values"] == [0., .2]
    assert result["forces"]["frame"] == result["stress"]["frame"] == "Cartesian frame of input lattice_matrix_angstrom"
    assert "not signed spin orientation" in result["magnetic_moments"]["scope"]


@pytest.mark.parametrize("key,value", [("e", float("inf")), ("f", [[0., 0., 0.]]),
                                         ("s", [1., 2., 3.]), ("m", [[0.], [.2]])])
def test_native_prediction_shapes_and_finite_values(key, value):
    p = prediction(); p[key] = value
    with pytest.raises(batch.BatchError, match="prediction_shape_or_nonfinite"):
        batch.normalize_prediction(p, 2, 27.)


class Array(list):
    def tolist(self): return list(self)


class Site:
    def __init__(self, specie, coords): self.specie = specie; self.frac_coords = coords


class Parsed(list):
    def __init__(self, sites, matrix=None):
        super().__init__(sites)
        self.is_ordered = True
        self.lattice = types.SimpleNamespace(matrix=Array(matrix or [[3.,0.,0.], [0.,3.,0.], [0.,0.,3.]]))


def test_independent_cif_allows_rotation_order_and_periodic_coordinates():
    p = Parsed([Site("B", [-.5, .5, .5]), Site("Mg", [1., 0., 0.])], [[0.,3.,0.], [-3.,0.,0.], [0.,0.,3.]])
    batch.match_cif(structure(), p)


@pytest.mark.parametrize("change", ["species", "position", "lattice", "disorder", "extra"])
def test_independent_cif_rejects_unmatched_atom_or_cell(change):
    p = Parsed([Site("Mg", [0.,0.,0.]), Site("B", [.5,.5,.5])])
    if change == "species": p[0].specie = "Al"
    elif change == "position": p[0].frac_coords = [.1,0.,0.]
    elif change == "lattice": p.lattice.matrix[0][0] = 3.1
    elif change == "disorder": p.is_ordered = False
    elif change == "extra": p.append(Site("B", [.1,.1,.1]))
    with pytest.raises(batch.BatchError): batch.match_cif(structure(), p)


def setup_run(tmp_path, monkeypatch, count=2):
    source, digest = bundle(tmp_path, count)
    _, raw, records = batch.load_bundle(source, digest)
    args = argparse.Namespace(runtime_prefix=tmp_path / "runtime", runtime_manifest_sha256="a"*64,
                             checkpoint_sha256="b"*64, output=tmp_path / "results")
    runtime = {"python": {"path": "bin/python3.12"}}
    monkeypatch.setattr(batch, "runtime_inventory", lambda *a: (runtime, b'{"prepared":"fake_for_test"}', b"fake"))
    monkeypatch.setattr(batch, "enforce_cgroup", lambda: {"cpu_max": ["400000","100000"], "memory_max_bytes": 12*2**30})
    return args, records, raw


def write_fake_result(job):
    request = json.loads((job / "request.json").read_text())
    batch.atomic_new(job / "result.json", {"schema_version": batch.VERSION, "status": "single_point_completed",
        "binding": request["context"], "prediction": batch.normalize_prediction(prediction(), 2, 27.),
        "authority": batch.AUTHORITY, "compute_wall_seconds": .1})


def test_sequential_partial_failure_no_retry_preserves_input_receipts(tmp_path, monkeypatch):
    args, records, raw = setup_run(tmp_path, monkeypatch)
    calls = []
    def fake(argv, *, cwd, stdout, env, deadline):
        calls.append(cwd)
        assert "-I" in argv and "--execute" in argv
        assert env["OMP_NUM_THREADS"] == "4" and "PYTHONPATH" not in env
        assert env.get("HOME") == os.environ.get("HOME")
        assert env["XDG_CACHE_HOME"] == str(args.output / "cache")
        assert env["MPLCONFIGDIR"] == str(args.output / "mpl-cache")
        stdout.write(b"bounded fake log\n")
        if len(calls) == 1:
            write_fake_result(cwd)
            return {"exit_code": 0, "timed_out": False, "process_reaped": True}
        return {"exit_code": 3, "timed_out": False, "process_reaped": True}
    monkeypatch.setattr(batch, "execute_before_deadline", fake)
    assert batch.run_batch(args, records, raw, batch.time.monotonic()) == 1
    assert len(calls) == 2
    final = json.loads((args.output / "finished.json").read_text())
    assert final["successful_jobs"] == 1 and final["unstarted_jobs"] == 0
    assert final["status"] == "partial_or_failed" and final["authority"] == batch.AUTHORITY
    for job in calls:
        assert (job / "receipt.json").is_file() and (job / "input.json").is_file() and (job / "input.cif").is_file()


@pytest.mark.parametrize("outcome", [None, {"exit_code": -15, "timed_out": True, "process_reaped": True},
                                     {"exit_code": None, "timed_out": True, "process_reaped": False}])
def test_timeout_does_not_admit_even_if_result_exists(tmp_path, monkeypatch, outcome):
    args, records, raw = setup_run(tmp_path, monkeypatch)
    calls = []
    def fake(argv, *, cwd, **kwargs):
        calls.append(cwd); write_fake_result(cwd); return outcome
    monkeypatch.setattr(batch, "execute_before_deadline", fake)
    assert batch.run_batch(args, records, raw, batch.time.monotonic()) == 1
    final = json.loads((args.output / "finished.json").read_text())
    assert final["successful_jobs"] == 0
    if outcome and not outcome["process_reaped"]:
        assert len(calls) == 1 and final["stop_reason"] == "process_not_reaped"


def test_global_budget_reserves_termination_and_does_not_start_worker(tmp_path, monkeypatch):
    args, records, raw = setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(batch.time, "monotonic", lambda: 100.)
    monkeypatch.setattr(batch, "execute_before_deadline", lambda *a, **k: pytest.fail("no budget to start"))
    assert batch.run_batch(args, records, raw, 100. - batch.GLOBAL_SECONDS + batch.RESERVE_SECONDS) == 1
    final = json.loads((args.output / "finished.json").read_text())
    assert final["unstarted_jobs"] == 2 and final["stop_reason"] == "global_budget_exhausted"


def test_job_deadline_includes_result_readback_and_marks_late_result_failed(tmp_path, monkeypatch):
    args, records, raw = setup_run(tmp_path, monkeypatch, count=1)
    now = [100.]
    monkeypatch.setattr(batch.time, "monotonic", lambda: now[0])
    def fake(argv, *, cwd, deadline, **kwargs):
        write_fake_result(cwd); now[0] = deadline + .01
        return {"exit_code": 0, "timed_out": False, "process_reaped": True}
    monkeypatch.setattr(batch, "execute_before_deadline", fake)
    assert batch.run_batch(args, records, raw, 100.) == 1
    final = json.loads((args.output / "finished.json").read_text())
    assert final["successful_jobs"] == 0
    receipt = json.loads((args.output / final["jobs"][0]["path"]).read_text())
    assert receipt["job_deadline_exceeded"] and receipt["reason_code"] == "job_deadline_exceeded"


def test_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    args, records, raw = setup_run(tmp_path, monkeypatch)
    args.output.mkdir(); marker = args.output / "mine"; marker.write_bytes(b"retained")
    monkeypatch.setattr(batch, "execute_before_deadline", lambda *a, **k: pytest.fail("output must be new"))
    with pytest.raises(FileExistsError): batch.run_batch(args, records, raw, batch.time.monotonic())
    assert marker.read_bytes() == b"retained"


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../b", "a//b"])
def test_read_path_escape(tmp_path, path):
    with pytest.raises(batch.BatchError, match="unsafe_path"): batch.read_bounded(tmp_path, path)


def test_symlink_and_file_changes_rejected(tmp_path, monkeypatch):
    p = tmp_path / "data"; p.write_bytes(b"old")
    (tmp_path / "link").symlink_to(p)
    with pytest.raises(batch.BatchError, match="file_unavailable_or_unsafe"): batch.read_bounded(tmp_path, "link")
    oldread = os.read
    def mutate(fd, size): p.write_bytes(b"new-longer"); return oldread(fd, size)
    monkeypatch.setattr(os, "read", mutate)
    with pytest.raises(batch.BatchError, match="file_changed_during_read"): batch.read_bounded(tmp_path, "data")


def test_worker_cannot_bypass_execute_flag(tmp_path, capsys):
    rc = batch.main(["--worker-request", str(tmp_path / "request"), "--worker-request-sha256", "a"*64,
                    "--runtime-prefix", str(tmp_path), "--checkpoint-sha256", "b"*64])
    assert rc == 2
    assert json.loads(capsys.readouterr().out)["reason_code"] == "invalid_worker_invocation"


def test_torch_load_is_exact_bytes_weights_only_cpu_and_no_extra_energy_division(tmp_path, monkeypatch):
    prefix = tmp_path / "runtime"
    calls = {}
    torch = types.ModuleType("torch"); torch.__file__ = str(prefix / "lib/python3.12/site-packages/torch/__init__.py")
    torch.set_num_threads = lambda n: calls.update(threads=n)
    torch.set_num_interop_threads = lambda n: calls.update(interop=n)
    def load(stream, **kwargs):
        calls.update(checkpoint=stream.read(), torch_load=kwargs); return {"model": {"original": "state"}}
    torch.load = load
    class Model:
        is_intensive = True
        @classmethod
        def from_dict(cls, state, **kwargs): calls.update(state=state, from_dict=kwargs); return cls()
        def to(self, device): calls["device"] = device; return self
        def parameters(self): return [types.SimpleNamespace(device=types.SimpleNamespace(type="cpu"))]
        def eval(self): calls["eval"] = True
        def predict_structure(self, structure, **kwargs): calls["prediction"] = kwargs; return prediction()
    chgnet = types.ModuleType("chgnet"); chgnet.__path__ = []
    modelpkg = types.ModuleType("chgnet.model"); modelpkg.__path__ = []
    mod = types.ModuleType("chgnet.model.model"); mod.CHGNet = Model
    mod.__file__ = str(prefix / "lib/python3.12/site-packages/chgnet/model/model.py")
    chgnet.model = modelpkg; modelpkg.model = mod
    core = types.ModuleType("pymatgen.core"); core.Lattice = lambda m: m
    core.Structure = lambda *a, **k: types.SimpleNamespace(volume=27.)
    cif = types.ModuleType("pymatgen.io.cif")
    parsed = Parsed([Site("Mg", [0,0,0]), Site("B", [.5,.5,.5])])
    class Parser:
        @classmethod
        def from_str(cls, source, **kwargs): calls["cif_source"] = source; return cls()
        def parse_structures(self, **kwargs): return [parsed]
    cif.CifParser = Parser
    for name, modl in {"torch": torch, "chgnet": chgnet, "chgnet.model": modelpkg, "chgnet.model.model": mod,
                       "pymatgen.core": core, "pymatgen.io.cif": cif}.items(): monkeypatch.setitem(sys.modules, name, modl)
    import importlib.metadata
    versions = {"python": sys.version.split()[0], "torch": "2.10.0+cpu", "chgnet": "0.4.2", "pymatgen": "test"}
    monkeypatch.setattr(importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(sys, "executable", str(prefix / "bin/python3.12"))
    output = batch.calculate(structure(), b"actual selected CIF bytes", prefix, {"versions": versions}, b"exact pinned checkpoint bytes")
    assert calls["torch_load"] == {"map_location": "cpu", "weights_only": True}
    assert calls["from_dict"] == {"mlp_out_bias": False, "version": "0.3.0"}
    assert calls["device"] == "cpu" and calls["threads"] == 4 and calls["prediction"] == {"task": "efsm"}
    assert calls["checkpoint"] == b"exact pinned checkpoint bytes" and output["energy"]["value"] == -6.


def test_explicit_smoke_subset_replays_exact_original_entries(tmp_path):
    root, _ = bundle(tmp_path, count=4)
    original = (root / "batch-manifest.json").read_bytes()
    (root / "original-batch-manifest.json").write_bytes(original)
    manifest = json.loads(original)
    manifest["inputs"] = manifest["inputs"][:2]
    manifest["selection"] = {"kind": "smoke_subset", "source_manifest": {"path": "original-batch-manifest.json",
        "bytes": len(original), "sha256": batch.sha(original)}, "state_ids": ["state:0", "state:1"]}
    raw = batch.pretty(manifest); (root / "batch-manifest.json").write_bytes(raw)
    assert len(batch.load_bundle(root, batch.sha(raw))[2]) == 2
    manifest["inputs"][0]["recipe_id"] = "changed-independent-recipe"
    raw = batch.pretty(manifest); (root / "batch-manifest.json").write_bytes(raw)
    with pytest.raises(batch.BatchError, match="subset_input_not_exact_original"): batch.load_bundle(root, batch.sha(raw))


def fake_runtime(tmp_path):
    root = tmp_path / "runtime"; root.mkdir()
    files = [("bin/python3.12", b"fake interpreter"), (batch.CHECKPOINT, b"fake weights"),
             ("lib/python3.12/site-packages/chgnet/model/model.py", b"fake model source")]
    pins = []
    for name, raw in files:
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        pins.append({"path": name, "bytes": len(raw), "sha256": batch.sha(raw)})
    manifest = {"schema_version": "discovery-chgnet-runtime/1.0.0", "prefix": str(root), "official_wheel_sha256": batch.WHEEL_SHA,
                "python": pins[0], "checkpoint": pins[1], "files": pins[1:],
                "versions": {"python": "3.12.14", "chgnet": "0.4.2", "torch": "2.10.0+cpu", "pymatgen": "test"}}
    raw = batch.pretty(manifest); (root / "runtime-artifact-manifest.json").write_bytes(raw)
    return root, manifest, batch.sha(raw), pins[1]["sha256"]


def test_runtime_checkpoint_code_and_external_manifest_are_bound(tmp_path):
    root, manifest, digest, checkpoint = fake_runtime(tmp_path)
    assert batch.runtime_inventory(root, digest, checkpoint)[2] == b"fake weights"
    (root / "lib/python3.12/site-packages/chgnet/extra.py").write_bytes(b"unlisted new code")
    with pytest.raises(batch.BatchError, match="runtime_code_not_in_inventory"): batch.runtime_inventory(root, digest, checkpoint)
    (root / "lib/python3.12/site-packages/chgnet/extra.py").unlink()
    (root / batch.CHECKPOINT).write_bytes(b"tampered")
    with pytest.raises(batch.BatchError, match="file_size_mismatch"): batch.runtime_inventory(root, digest, checkpoint)


def test_official_empty_python_package_module_is_pinned_and_allowed(tmp_path):
    root, manifest, _, checkpoint = fake_runtime(tmp_path)
    name = "lib/python3.12/site-packages/chgnet/data/__init__.py"
    path = root / name; path.parent.mkdir(parents=True); path.write_bytes(b"")
    manifest["files"].append({"path": name, "bytes": 0, "sha256": batch.sha(b"")})
    raw = batch.pretty(manifest); (root / "runtime-artifact-manifest.json").write_bytes(raw)
    assert batch.runtime_inventory(root, batch.sha(raw), checkpoint)[2] == b"fake weights"
    path.write_bytes(b"changed module")
    with pytest.raises(batch.BatchError, match="file_size_mismatch"):
        batch.runtime_inventory(root, batch.sha(raw), checkpoint)


@pytest.mark.parametrize("name", [batch.CHECKPOINT, "lib/python3.12/site-packages/chgnet/empty.so"])
def test_empty_weights_or_native_extension_remain_rejected(tmp_path, name):
    root, manifest, _, checkpoint = fake_runtime(tmp_path)
    path = root / name; path.write_bytes(b"")
    if name == batch.CHECKPOINT:
        manifest["checkpoint"].update(bytes=0, sha256=batch.sha(b""))
        checkpoint = batch.sha(b"")
    else:
        manifest["files"].append({"path": name, "bytes": 0, "sha256": batch.sha(b"")})
    raw = batch.pretty(manifest); (root / "runtime-artifact-manifest.json").write_bytes(raw)
    with pytest.raises(batch.BatchError, match="file_type_or_size"):
        batch.runtime_inventory(root, batch.sha(raw), checkpoint)


@pytest.mark.parametrize("cpu,memory", [("max 100000", "12884901888"), ("500000 100000", "12884901888"),
                                          ("400000 100000", "max"), ("400000 100000", "12884901889")])
def test_actual_resource_envelope_must_be_bounded(monkeypatch, cpu, memory):
    monkeypatch.setattr(sys, "platform", "linux")
    def read(path, **kwargs):
        name = str(path)
        if name == "/proc/self/cgroup": return "0::/system.slice/sclib-chgnet-smoke.service\n"
        if name.endswith("/cpu.max"): return cpu
        if name.endswith("/memory.max"): return memory
        raise AssertionError(name)
    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(batch.BatchError, match="resource_limits_missing_or_excessive"): batch.enforce_cgroup()


def test_finite_components_cannot_emit_overflowed_force_norm():
    p = prediction(); p["f"][0][0] = 1e308
    with pytest.raises(batch.BatchError, match="prediction_derived_nonfinite"):
        batch.normalize_prediction(p, 2, 27.)
