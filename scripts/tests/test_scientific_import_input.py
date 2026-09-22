"""Offline, synthetic input compiler tests; no executed or approved calculation."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from services import scientific_import_input as compiler  # noqa: E402
from services.research_release_manifest import canonical, digest  # noqa: E402


def arguments():
    leaves = [("input", "synthetic.in", b" &input\n asr='simple', flfrc='synthetic.fc', flfrq='synthetic.freq'\n /\n 1\n 0 0 0\n"),
              ("frequency", "synthetic.freq", b" &plot nbnd=3,nks=1 /\n 0 0 0\n -1.0000 0.0000 2.0000\n")]
    fc = b"1 1 2 10.5 0 0 0 0 0\n1 'Al' 24590.76\n1 1 0 0 0\nF\n1 1 1\n"
    fc += b"".join(f"{i} {j} 1 1\n1 1 1 -0.01\n".encode() for i in range(1, 4) for j in range(1, 4))
    manifest = {"version": "scientific-program-package/1.0.0", "adapter_id": "qe-matdyn-flfrq",
        "files": [{"role": role, "logical_name": name, "sha256": compiler.sha(data), "size_bytes": len(data)}
                  for role, name, data in leaves],
        "context": {"material_formula": "Al", "material_id": None, "geometry_scope": "bulk_3d",
                    "source_url": None, "source_revision": None, "license_spdx": None},
        "declarations": {"review_status": "unreviewed", "execution_attested": False, "ml_training_approved": False}}
    return {"manifest": manifest, "artifact_bytes": {compiler.sha(data): data for _, _, data in leaves},
        "expected_manifest_sha256": digest(manifest), "context": {"version": compiler.CONTEXT_VERSION,
            "material_id": "synthetic-Al", "expected_material_row_sha256": "a" * 64,
            "force_constants": {"logical_name": "synthetic.fc", "sha256": compiler.sha(fc), "size_bytes": len(fc)}},
        "force_constants_bytes": fc}


def test_real_compiler_keeps_raw_bytes_coordinates_cost_scope_and_no_authority():
    args = arguments()
    package = compiler.prepare_input(**args)
    prepared = compiler.compile_input(package)
    assert compiler.verify_prepared(prepared) is prepared
    assert package.package_key == compiler.sha(package.request_bytes)
    assert prepared.report["status"] == "pending_context_and_review"
    assert prepared.report["reason_codes"] == []
    assert prepared.report["coordinate_sha256"] == compiler.sha(prepared.coordinate_bytes)
    assert prepared.report["actual_calculation_costs"] is None
    assert prepared.report["cost_scope"] == "parser_worker_only"
    assert prepared.import_cpu_ms >= 0 and prepared.import_wall_ms >= 0
    assert set(prepared.report["authority"].values()) == {False}
    assert prepared.report["coverage"]["scientifically_accepted_properties"] == 0
    assert prepared.report["coverage"]["ml_admitted_properties"] == 0
    retained = {data for _, _, _, data in package.sources}
    assert retained >= {*args["artifact_bytes"].values(), args["force_constants_bytes"], canonical(args["manifest"])}


def test_caller_mutation_cannot_change_captured_input_or_returned_reports():
    args = arguments()
    package = compiler.prepare_input(**args)
    before = package.request_bytes, package.sources
    args["context"]["material_id"] = "mutated"
    args["manifest"]["context"]["material_formula"] = "Cu"
    args["artifact_bytes"].clear()
    package.request["context"]["material_id"] = "mutated"
    assert (package.request_bytes, package.sources) == before
    prepared = compiler.compile_input(package)
    prepared.report["authority"]["ml_training_approved"] = True
    assert prepared.report["authority"]["ml_training_approved"] is False


@pytest.mark.parametrize("field,value", [("request_bytes", b"{}"), ("sources", ()), ("signature", b"invalid")])
def test_input_tamper_cannot_cross_compiler(field, value):
    package = replace(compiler.prepare_input(**arguments()), **{field: value})
    with pytest.raises(compiler.ScientificImportError, match="input_capture_changed"):
        compiler.compile_input(package)


@pytest.mark.parametrize("field,value", [("report_bytes", b"{}"), ("coordinate_bytes", b"{}"),
    ("import_wall_ms", -1), ("import_cpu_ms", 999999999), ("signature", b"invalid")])
def test_prepared_tamper_cannot_cross_writer_boundary(field, value):
    prepared = compiler.compile_input(compiler.prepare_input(**arguments()))
    with pytest.raises(compiler.ScientificImportError, match="parser_result_changed"):
        compiler.verify_prepared(replace(prepared, **{field: value}))


@pytest.mark.parametrize("field,value", [("version", "future"), ("material_id", ""), ("material_id", "x\n"),
    ("material_id", "x" * 101), ("expected_material_row_sha256", None), ("expected_material_row_sha256", "f" * 63)])
def test_context_requires_independent_material_pin_and_closed_fields(field, value):
    args = arguments()
    args["context"][field] = value
    with pytest.raises(ValueError):
        compiler.prepare_input(**args)


@pytest.mark.parametrize("key", ["actor_user_id", "actor_grant_id", "review_status", "pressure_gpa", "coordinates"])
def test_request_cannot_smuggle_authority_or_physical_context(key):
    args = arguments()
    args["context"][key] = "injected"
    with pytest.raises(compiler.ScientificImportError, match="import_context_fields"):
        compiler.prepare_input(**args)


@pytest.mark.parametrize("field,value", [("logical_name", "../synthetic.fc"), ("logical_name", "https://x/x.fc"),
    ("sha256", "b" * 64), ("size_bytes", True), ("size_bytes", 8388609)])
def test_force_constant_sidecar_requires_safe_name_and_exact_actual_bytes(field, value):
    args = arguments()
    args["context"]["force_constants"][field] = value
    with pytest.raises(ValueError):
        compiler.prepare_input(**args)


@pytest.mark.parametrize("kind", ["absent", "bad_bytes", "wrong_name", "wrong_formula", "nonbulk", "malformed_frequency"])
def test_missing_or_incompatible_science_remains_in_denominator_as_quarantine(kind):
    args = arguments()
    if kind == "absent":
        args["context"]["force_constants"] = args["force_constants_bytes"] = None
    elif kind == "bad_bytes":
        args["force_constants_bytes"] = b"malformed native format"
        args["context"]["force_constants"].update(sha256=compiler.sha(args["force_constants_bytes"]),
                                               size_bytes=len(args["force_constants_bytes"]))
    elif kind == "wrong_name":
        args["context"]["force_constants"]["logical_name"] = "another.fc"
    elif kind == "wrong_formula":
        args["manifest"]["context"]["material_formula"] = "Cu"
    elif kind == "nonbulk":
        args["manifest"]["context"]["geometry_scope"] = "other"
    else:
        entry = args["manifest"]["files"][1]
        del args["artifact_bytes"][entry["sha256"]]
        raw = b"malformed frequency format"
        entry.update(sha256=compiler.sha(raw), size_bytes=len(raw))
        args["artifact_bytes"][entry["sha256"]] = raw
    args["expected_manifest_sha256"] = digest(args["manifest"])
    prepared = compiler.compile_input(compiler.prepare_input(**args))
    assert prepared.report["status"] == "quarantined"
    assert prepared.report["reason_codes"]
    assert prepared.report["coverage"]["source_packages_seen"] == 1
    assert set(prepared.report["authority"].values()) == {False}


def test_code_change_between_capture_and_compile_is_not_silent(monkeypatch):
    package = compiler.prepare_input(**arguments())
    changed = deepcopy(compiler.compiler_inventory())
    changed["api/services/scientific_import_input.py"] = "0" * 64
    monkeypatch.setattr(compiler, "compiler_inventory", lambda: changed)
    with pytest.raises(compiler.ScientificImportError, match="import_compiler_changed"):
        compiler.compile_input(package)


@pytest.mark.parametrize("kind", ["parsed", "wrong_name", "nonbulk", "malformed"])
def test_installed_runtime_matches_frozen_cli_scientific_decisions(kind):
    from services.scientific_program_import import build_preflight
    args = arguments()
    if kind == "wrong_name":
        args["manifest"]["files"][1]["logical_name"] = "another.freq"
    elif kind == "nonbulk":
        args["manifest"]["context"]["geometry_scope"] = "other"
    elif kind == "malformed":
        entry = args["manifest"]["files"][1]
        del args["artifact_bytes"][entry["sha256"]]
        raw = b"malformed"
        entry.update(sha256=compiler.sha(raw), size_bytes=len(raw))
        args["artifact_bytes"][entry["sha256"]] = raw
    manifest = args["manifest"]
    kwargs = {"artifact_bytes": args["artifact_bytes"], "expected_manifest_sha256": digest(manifest)}
    old = build_preflight(manifest, **kwargs)
    installed = compiler.runtime_preflight(manifest, **kwargs)
    for key in set(old) - {"version", "source_code_sha256"}:
        assert installed[key] == old[key], key
    assert installed["version"] == "scientific-import-native-preflight/1.0.0"


def test_api_only_installation_without_repository_scripts_compiles_real_bytes(tmp_path):
    deployed = tmp_path / "installed-api"
    inventory = compiler.compiler_inventory()
    for name in (*inventory, "api/services/_composition/__init__.py"):
        target = deployed / name.removeprefix("api/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert not (deployed / "api").exists() and not (deployed / "scripts").exists()
    args = arguments()
    args["artifact_bytes"] = {key: value.hex() for key, value in args["artifact_bytes"].items()}
    args["force_constants_bytes"] = args["force_constants_bytes"].hex()
    program = """import sys,json
sys.path.insert(0,sys.argv[1])
from services.scientific_import_input import prepare_input,compile_input,compiler_inventory
args=json.loads(sys.stdin.read())
args['artifact_bytes']={key:bytes.fromhex(value) for key,value in args['artifact_bytes'].items()}
args['force_constants_bytes']=bytes.fromhex(args['force_constants_bytes'])
result=compile_input(prepare_input(**args))
assert result.report['status']=='pending_context_and_review'
print(json.dumps(compiler_inventory(),sort_keys=True))
"""
    result = subprocess.run([sys.executable, "-I", "-c", program, str(deployed)], cwd=tmp_path,
                            input=json.dumps(args), text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == inventory
