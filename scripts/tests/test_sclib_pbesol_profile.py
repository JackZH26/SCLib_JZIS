"""Offline binding tests. Synthetic UPFs never constitute runtime/science evidence."""

import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_sclib_pbesol_preparation as prep
from sclib_compute import pbesol_profile as profile
from sclib_compute.contracts import FilePin, canonical
from sclib_compute.native_contract import NativeInput, validate_deck, validate_inputs
from test_build_sclib_pbesol_preparation import source_text

REAL_LOAD_TRUST = profile._load_trust
REAL_LOAD_PROFILE = prep.load_profile
CONTEXTS = [(sid, phase) for sid in profile.CONTEXT_IDS for phase in ("initialize", "scf")]


def file_pin(name, data):
    return {"name": name, "sha256": prep.sha256(data), "bytes": len(data)}


def context_files(root, sid, phase):
    directory = root / "prepared" / sid / phase
    manifest = (directory / "preparation-manifest.json").read_bytes()
    m = json.loads(manifest)
    files = {"preparation.json": manifest, "source.in": (root / m["source_file"]["path"]).read_bytes(),
             "input.in": (directory / "input.in").read_bytes(), "delta.json": (directory / "delta.json").read_bytes()}
    files.update({p["filename"]: (directory / "pseudo" / p["filename"]).read_bytes() for p in m["pseudopotentials"]})
    return files


def context_pin(sid, phase, files):
    return {"source_id": sid, "phase": phase,
            **{field: file_pin(name, files[name]) for field, name in (
                ("preparation_manifest", "preparation.json"), ("source_deck", "source.in"),
                ("derived_deck", "input.in"), ("line_delta", "delta.json"))},
            "geometry_sha256": json.loads(files["preparation.json"])["geometry"]["source_sha256"]}


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    """Explicit test-only installed-trust substitution; no production override API."""
    installed = copy.deepcopy(prep.load_profile())
    source, upfs, output = tmp_path / "source", tmp_path / "upfs", tmp_path / "bundle"
    source.mkdir()
    upfs.mkdir()
    for pin in installed["upfs"]:
        data = (f'<UPF version="2.0.1"><PP_HEADER element="{pin["element"]}" functional="PBESOL" '
                f'pseudo_type="NC" relativistic="scalar" is_ultrasoft="F" is_paw="F" has_so="F" '
                f'z_valence="{pin["valence_electrons"]}"/></UPF>\n').encode()
        pin.update(bytes=len(data), sha256=prep.sha256(data), md5=hashlib.md5(data).hexdigest())
        (upfs / pin["filename"]).write_bytes(data)
    for state in installed["states"]:
        data = source_text(state)
        state["source_deck"].update(bytes=len(data), sha256=prep.sha256(data))
        path = source / state["source_deck"]["path"]
        path.parent.mkdir()
        path.write_bytes(data)
    monkeypatch.setattr(prep, "load_profile", lambda: copy.deepcopy(installed))
    prep.build(source, upfs, output)
    sets = {(sid, phase): context_files(output, sid, phase) for sid, phase in CONTEXTS}
    table = {"contexts": [context_pin(sid, phase, files) for (sid, phase), files in sets.items()]}
    monkeypatch.setattr(profile, "_load_trust", lambda: (installed, table))
    return sets, installed, table


@pytest.mark.parametrize(("sid", "phase"), CONTEXTS)
def test_eight_synthetic_contexts_round_trip_and_have_no_execution_authority(synthetic, sid, phase):
    sets, installed, _ = synthetic
    binding = profile.build_input_binding(sid, phase, sets[sid, phase])
    restored = profile.validate_input_binding(canonical(binding.model_dump(mode="json")), sets[sid, phase])
    assert restored == binding
    state = next(s for s in installed["states"] if s["id"] == sid)
    assert (binding.expected_electrons, binding.expected_nbnd) == (state["valence_electrons"], state["nbnd"])
    assert all(getattr(binding, name) is False for name in profile.AUTHORITY_FALSE)
    assert all(getattr(binding, name) is None for name in profile.CUSTODY_NULL)
    assert [p.element for p in binding.pseudopotentials] == [row.split()[0] for row in state["species_rows"]]


@pytest.mark.parametrize(("sid", "phase"), CONTEXTS)
def test_real_frozen_context_requires_explicit_local_path(sid, phase):
    root = os.environ.get("SCLIB_PBESOL_FORMAL_BUNDLE")
    if root is None:
        pytest.skip("Private frozen-real acceptance not invoked; set SCLIB_PBESOL_FORMAL_BUNDLE explicitly")
    bundle = Path(root)
    assert prep.sha256((bundle / "bundle-manifest.json").read_bytes()) == profile.BUNDLE_SHA256
    files = context_files(bundle, sid, phase)
    binding = profile.build_input_binding(sid, phase, files)
    assert profile.validate_input_binding(canonical(binding.model_dump(mode="json")), files) == binding


def test_installed_trust_table_covers_all_eight_and_has_no_private_paths():
    installed, table = profile._load_trust()
    assert len(installed["states"]) == 4 and len(table["contexts"]) == 8
    assert [(c["source_id"], c["phase"]) for c in table["contexts"]] == CONTEXTS
    assert b"/Users/" not in profile.PINS_PATH.read_bytes()
    assert b"/home/" not in profile.PINS_PATH.read_bytes()


@pytest.mark.parametrize("which", ["prepared_table", "preparer_code", "source_profile"])
def test_installed_trust_mutation_fails_closed(monkeypatch, which):
    original = prep.read_regular
    selected = {"prepared_table": profile.PINS_PATH.name, "preparer_code": Path(prep.__file__).name,
                "source_profile": prep.PROFILE.name}[which]
    def corrupt(root, name):
        data = original(root, name)
        return data + b" " if name == selected else data
    monkeypatch.setattr(prep, "read_regular", corrupt)
    with pytest.raises(ValueError, match="changed"):
        profile._load_trust()


@pytest.mark.parametrize("name", ["source.in", "input.in", "delta.json", "preparation.json", "Ti.upf"])
def test_one_changed_byte_cannot_be_blessed_by_self_declared_binding(synthetic, name):
    sets, _, _ = synthetic
    files = dict(sets[CONTEXTS[0]])
    binding = profile.build_input_binding(*CONTEXTS[0], files).model_dump(mode="json")
    files[name] += b" "
    # Even a coherently rewritten user pin is not source authority.
    for field in ("source_deck", "derived_deck", "line_delta", "preparation_manifest"):
        if binding[field]["name"] == name:
            binding[field] = file_pin(name, files[name])
    for pin in binding["pseudopotentials"]:
        if pin["file"]["name"] == name:
            pin["file"] = file_pin(name, files[name])
    with pytest.raises(ValueError):
        profile.validate_input_binding(canonical(binding), files)


@pytest.mark.parametrize("change", ["phase", "source", "missing", "extra", "path", "mutable", "large", "dict_subclass"])
def test_wrong_context_and_artifact_envelope_rejected(synthetic, change):
    sets, _, _ = synthetic
    sid, phase = CONTEXTS[0]
    files = dict(sets[sid, phase])
    if change == "phase":
        phase = "scf"
    elif change == "source":
        sid = CONTEXTS[2][0]
    elif change == "missing":
        del files["Ti.upf"]
    elif change == "extra":
        files["native.json"] = b"{}"
    elif change == "path":
        files["../Ti.upf"] = files.pop("Ti.upf")
    elif change == "mutable":
        files["input.in"] = bytearray(files["input.in"])
    elif change == "large":
        files["input.in"] = b"x" * (profile.MAX_METADATA_BYTES + 1)
    else:
        class Custom(dict):
            pass
        files = Custom(files)
    with pytest.raises(ValueError):
        profile.build_input_binding(sid, phase, files)


@pytest.mark.parametrize(("old", "new"), [
    ("la2f = .FALSE.", "la2f = .TRUE."), ("ecutwfc = 98.0", "ecutwfc = 50.0"),
    ("smearing = 'mp'", "smearing = 'mv'"), ("calculation = 'scf'", "calculation = 'relax'"),
    ("conv_thr = 1d-12,", "conv_thr = 1d-12,\n conv_thr = 1d-12,"),
    ("6 6 10 0 0 0", "12 12 20 0 0 0"),
    ("Ti 0.0 0.0 0.500000007208889", "Ti 0.0 0.0 0.5"),
    ("ecutwfc = 98.0,", "ecutwfc = 98.0,\n input_dft = 'PBE',"),
])
def test_source_semantics_reject_after_fixture_source_pin_updated(synthetic, old, new):
    sets, installed, _ = synthetic
    files = dict(sets[CONTEXTS[0]])
    assert old.encode() in files["source.in"]
    files["source.in"] = files["source.in"].replace(old.encode(), new.encode(), 1)
    installed["states"][0]["source_deck"].update(bytes=len(files["source.in"]), sha256=prep.sha256(files["source.in"]))
    with pytest.raises(ValueError, match="Source|source"):
        profile.build_input_binding(*CONTEXTS[0], files)


@pytest.mark.parametrize(("old", "new"), [
    ("nstep = 0", "nstep = 1"), ("nbnd = 31", "nbnd = 32"), ("ecutrho = 392", "ecutrho = 400"),
    ("nspin = 1", "nspin = 2"), ("tot_charge = 0", "tot_charge = 1"),
    ("'./out'", "'/tmp/out'"), ("'./pseudo'", "'../pseudo'"),
    ("mixing_mode = 'plain'", "mixing_mode = 'local-TF'"),
    ("max_seconds = 600", "max_seconds = 600\n/\n&IONS\n ion_dynamics = 'bfgs'"),
    ("&SYSTEM", "&CELL\n cell_dynamics = 'bfgs'\n/\n&SYSTEM"),
    ("electron_maxstep = 100", "electron_maxstep = 200"),
    ("nstep = 0,", "nstep = 0,\n nstep = 0,"),
    ("6 6 10 0 0 0", "6 6 10 0 0 0\n! extra directive"),
])
def test_derived_semantics_reject_even_with_replaced_fixture_pin(synthetic, old, new):
    sets, _, table = synthetic
    files = dict(sets[CONTEXTS[0]])
    assert old.encode() in files["input.in"]
    files["input.in"] = files["input.in"].replace(old.encode(), new.encode(), 1)
    table["contexts"][0]["derived_deck"] = file_pin("input.in", files["input.in"])
    with pytest.raises(ValueError, match="exact source-preserving derivation"):
        profile.build_input_binding(*CONTEXTS[0], files)


@pytest.mark.parametrize(("old", "new"), [('functional="PBESOL"', 'functional="PBE"'),
    ('pseudo_type="NC"', 'pseudo_type="PAW"'), ('element="Ti"', 'element="Nb"'), ('z_valence="12"', 'z_valence="13"')])
def test_upf_semantics_reject_after_fixture_pin_updated(synthetic, old, new):
    sets, installed, _ = synthetic
    files = dict(sets[CONTEXTS[0]])
    files["Ti.upf"] = files["Ti.upf"].replace(old.encode(), new.encode())
    pin = next(p for p in installed["upfs"] if p["element"] == "Ti")
    pin.update(bytes=len(files["Ti.upf"]), sha256=prep.sha256(files["Ti.upf"]), md5=hashlib.md5(files["Ti.upf"]).hexdigest())
    with pytest.raises(ValueError, match="UPF"):
        profile.build_input_binding(*CONTEXTS[0], files)


@pytest.mark.parametrize(("key", "value"), [("expected_nbnd", 32), ("expected_valence_electrons", 51),
    ("queue_authorization", True), ("execution_supported", 0), ("job_spec", {}), ("preparation_phase", "scf"),
    ("xc_from_exact_upfs", "PBE"), ("native_manifest", {})])
def test_manifest_semantics_reject_even_with_replaced_fixture_manifest_pin(synthetic, key, value):
    sets, _, table = synthetic
    files = dict(sets[CONTEXTS[0]])
    m = json.loads(files["preparation.json"])
    m[key] = value
    files["preparation.json"] = prep.encoded(m)
    table["contexts"][0]["preparation_manifest"] = file_pin("preparation.json", files["preparation.json"])
    with pytest.raises(ValueError, match="manifest semantic mismatch"):
        profile.build_input_binding(*CONTEXTS[0], files)


@pytest.mark.parametrize(("key", "value"), [("execution_enabled", True), ("execution_enabled", 0),
    ("queue_authorization", "false"), ("scientific_acceptance", None), ("job_spec", {}),
    ("runtime_observation", {}), ("attempt_receipt", False), ("expected_electrons", True),
    ("expected_electrons", 52.0), ("expected_nbnd", "31"), ("extra_field", "ignored?")])
def test_binding_authority_null_and_scalar_types_are_strict(synthetic, key, value):
    sets, _, _ = synthetic
    files = sets[CONTEXTS[0]]
    b = profile.build_input_binding(*CONTEXTS[0], files).model_dump(mode="json")
    b[key] = value
    with pytest.raises(ValueError):
        profile.validate_input_binding(canonical(b), files)


@pytest.mark.parametrize("key", [*profile.AUTHORITY_FALSE, *profile.CUSTODY_NULL])
def test_authority_and_null_fields_must_be_explicit(synthetic, key):
    sets, _, _ = synthetic
    files = sets[CONTEXTS[0]]
    b = profile.build_input_binding(*CONTEXTS[0], files).model_dump(mode="json")
    del b[key]
    with pytest.raises(ValueError):
        profile.validate_input_binding(canonical(b), files)


def test_reordered_upfs_and_wrong_geometry_or_pins_rejected(synthetic):
    sets, _, _ = synthetic
    files = sets[CONTEXTS[0]]
    b = profile.build_input_binding(*CONTEXTS[0], files).model_dump(mode="json")
    for modified in [dict(b, pseudopotentials=list(reversed(b["pseudopotentials"]))),
                     dict(b, geometry_sha256="f" * 64), dict(b, source_profile_sha256="f" * 64)]:
        with pytest.raises(ValueError, match="installed authority"):
            profile.validate_input_binding(canonical(modified), files)


@pytest.mark.parametrize("raw", [b'{"x":0,"x":1}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'{"x":Infinity}',
    b'[' * 2000 + b']' * 2000, b'{}' + b' ' * profile.MAX_METADATA_BYTES])
def test_duplicate_nonfinite_nested_or_unbounded_json_rejected(raw):
    with pytest.raises(ValueError):
        profile.validate_input_binding(raw, {})


@pytest.mark.parametrize("phase", ["initialize", "scf"])
def test_native_v1_rejects_binding_relabelled_descriptor_manifest_and_deck(synthetic, phase):
    sets, _, _ = synthetic
    sid = CONTEXTS[0][0]
    files = sets[sid, phase]
    binding = profile.build_input_binding(sid, phase, files).model_dump(mode="json")
    for version in ("sclib-pbesol-input-binding/1", "sclib-native-qe/1"):
        with pytest.raises(ValueError):
            NativeInput.model_validate(dict(binding, schema_version=version))
    descriptor = NativeInput(schema_version="sclib-native-qe/1", input_name="input.in",
                             source_manifest_name="preparation.json", prefix=binding["prefix"],
                             pseudo_names=[p["file"]["name"] for p in binding["pseudopotentials"]])
    native_files = {name: data for name, data in files.items() if name not in {"source.in", "delta.json"}}
    native_files["native.json"] = canonical(descriptor.model_dump(mode="json"))
    spec = SimpleNamespace(kind="qe_" + phase, input_artifacts=[FilePin(**file_pin(n, d)) for n, d in native_files.items()])
    with pytest.raises(ValueError, match="unsupported QE source manifest"):
        validate_inputs(spec, native_files)
    with pytest.raises(ValueError):
        validate_deck(files["input.in"], descriptor, "qe_" + phase)
    # Forge an otherwise well-formed v1 source envelope, keeping the exact
    # PBEsol deck bytes. The unchanged v1 grammar must still reject the deck.
    native_files["preparation.json"] = canonical({
        "version": "discovery-qe-input/1.0.0", "settings": {"calculation": "scf"},
        "files": {"initialization" if phase == "initialize" else "execution": {
            "filename": "input.in", "sha256": prep.sha256(files["input.in"])}},
        "pseudopotentials": [{"filename": name, "sha256": prep.sha256(files[name]), "byte_length": len(files[name])}
                             for name in descriptor.pseudo_names],
    })
    spec.input_artifacts = [FilePin(**file_pin(n, d)) for n, d in native_files.items()]
    with pytest.raises(ValueError, match="unreviewed/duplicate QE assignment"):
        validate_inputs(spec, native_files)


def test_entrypoints_only_read_installed_trust_and_do_not_write_execute_or_connect(synthetic, monkeypatch):
    sets, installed, table = synthetic
    files = sets[CONTEXTS[0]]
    read_regular, os_open = prep.read_regular, os.open
    reads = []
    def tracked(root, name):
        reads.append((root, name))
        return read_regular(root, name)
    def read_only_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return os_open(path, flags, *args, **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected side effect")
    monkeypatch.setattr(prep, "read_regular", tracked)
    monkeypatch.setattr(os, "open", read_only_open)
    for fn in ("write_bytes", "write_text", "mkdir", "unlink"):
        monkeypatch.setattr(Path, fn, forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    # Check the real fixed-path loader independently of synthetic input trust.
    monkeypatch.setattr(prep, "load_profile", REAL_LOAD_PROFILE)
    REAL_LOAD_TRUST()
    assert reads == [(prep.PROFILE.parent, prep.PROFILE.name),
                     (Path(prep.__file__).resolve().parent, Path(prep.__file__).name),
                     (profile.PINS_PATH.parent, profile.PINS_PATH.name)]
    reads.clear()
    binding = profile.build_input_binding(*CONTEXTS[0], files)
    profile.validate_input_binding(canonical(binding.model_dump(mode="json")), files)
    assert reads == []  # Explicit test-only in-memory trust override remains.
    assert installed is not None and table is not None


@pytest.mark.parametrize("value", [True, False, 1.0, "1"])
def test_nested_file_pin_sizes_are_strict(synthetic, value):
    sets, _, _ = synthetic
    files = sets[CONTEXTS[0]]
    b = profile.build_input_binding(*CONTEXTS[0], files).model_dump(mode="json")
    b["derived_deck"]["bytes"] = value
    with pytest.raises(ValueError):
        profile.validate_input_binding(canonical(b), files)


@pytest.mark.parametrize("index", [0, 2])
def test_same_composition_target_control_swaps_and_fraction_literals(synthetic, index):
    sets, installed, _ = synthetic
    target, control = installed["states"][index:index+2]
    for phase in ("initialize", "scf"):
        with pytest.raises(ValueError, match="Pinned source bytes changed"):
            profile.build_input_binding(target["id"], phase, sets[control["id"], phase])
        files = sets[control["id"], phase]
        b = profile.build_input_binding(control["id"], phase, files)
        assert b.geometry_sha256 == prep.sha256(prep.encoded(prep.geometry(control)))
        assert "\n".join(control["position_rows"]).encode() in files["input.in"]
    # The Ti FCC control deliberately preserves coordinates outside [0,1].
    if index == 0:
        assert "-0.750000010813334 2.25000003244 -0.750000010813334" in control["position_rows"][1]


@pytest.mark.parametrize("change", ["electrons", "bands", "geometry", "upf_order", "path"])
def test_inventory_and_manifest_relations_reject_with_test_trust_replaced(synthetic, change):
    sets, installed, table = synthetic
    files = dict(sets[CONTEXTS[0]])
    m = json.loads(files["preparation.json"])
    if change == "electrons":
        installed["states"][0]["valence_electrons"] = 51
        reason = "Composition-weighted UPF electron mismatch"
    elif change == "bands":
        installed["states"][0]["nbnd"] = 32
        reason = "Pinned electron/band inventory mismatch"
    else:
        if change == "geometry":
            m["geometry"]["source"]["atoms"][1]["fractional_literals"][1] = "0.5"
        elif change == "upf_order":
            m["pseudopotentials"].reverse()
        else:
            m["derived_file"]["path"] = "../../unexpected.in"
        files["preparation.json"] = prep.encoded(m)
        table["contexts"][0]["preparation_manifest"] = file_pin("preparation.json", files["preparation.json"])
        reason = "Prepared manifest semantic mismatch"
    with pytest.raises(ValueError, match=reason):
        profile.build_input_binding(*CONTEXTS[0], files)
