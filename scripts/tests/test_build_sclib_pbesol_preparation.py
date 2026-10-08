"""Method-preservation and fail-closed tests; fixture UPFs are not scientific data."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "build_sclib_pbesol_preparation.py"
SPEC = importlib.util.spec_from_file_location("pbesol_preparation", MODULE_PATH)
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


def source_text(state):
    celldm = "".join(f"  {key} = {value},\n" for key, value in state["celldm_literals"].items())
    maxstep = "" if state["source_electron_maxstep"] is None else f"  electron_maxstep = {state['source_electron_maxstep']},\n"
    return ("&CONTROL\n  calculation = 'scf',\n  etot_conv_thr = 1d-08,\n  forc_conv_thr = 1d-06,\n"
            "  outdir = 'outdir',\n  prefix = 'qe',\n  pseudo_dir = '/synthetic/inert/source/',\n"
            "  restart_mode = 'from_scratch',\n  tprnfor = .TRUE.,\n  tstress = .TRUE.,\n/\n&SYSTEM\n"
            + celldm + f"  degauss = 0.014699728870262,\n  ecutwfc = {state['ecutwfc_ry']}.0,\n  ibrav = {state['ibrav']},\n"
            + f"  la2f = .FALSE.,\n  occupations = 'smearing',\n  smearing = 'mp',\n  nat = 4,\n  ntyp = {len(state['species_rows'])},\n"
            "/\n&ELECTRONS\n  conv_thr = 1d-12,\n  diagonalization = 'david',\n" + maxstep
            + "  mixing_beta = 0.7,\n  mixing_mode = 'plain',\n/\n&IONS\n  ion_dynamics = 'bfgs',\n/\n"
            "&CELL\n  cell_dynamics = 'bfgs',\n  press_conv_thr = 0.05,\n/\nATOMIC_SPECIES\n"
            + "\n".join(state["species_rows"]) + "\nATOMIC_POSITIONS crystal\n" + "\n".join(state["position_rows"])
            + "\nK_POINTS automatic\n  " + " ".join(map(str, [*state["mesh"], 0, 0, 0])) + "\n\n").encode()


@pytest.fixture
def sources(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source, upf = root / "source", root / "upf"
    source.mkdir()
    upf.mkdir()
    profile = copy.deepcopy(preparer.load_profile())
    for pin in profile["upfs"]:
        data = (f'<UPF version="2.0.1"><PP_HEADER element="{pin["element"]}" functional="PBESOL" '
                f'pseudo_type="NC" relativistic="scalar" is_ultrasoft="F" is_paw="F" has_so="F" '
                f'z_valence="{pin["valence_electrons"]}"/></UPF>\n').encode()
        pin.update(bytes=len(data), sha256=preparer.sha256(data), md5=hashlib.md5(data).hexdigest())
        (upf / pin["filename"]).write_bytes(data)
    for state in profile["states"]:
        data = source_text(state)
        state["source_deck"].update(bytes=len(data), sha256=preparer.sha256(data))
        path = source / state["source_deck"]["path"]
        path.parent.mkdir()
        path.write_bytes(data)
    # Fixture-only profile pins; production load_profile never accepts custom profiles.
    monkeypatch.setattr(preparer, "load_profile", lambda: copy.deepcopy(profile))
    return source, upf, root / "output", profile


def inspect_bundle(source, output, profile):
    bundle = json.loads((output / "bundle-manifest.json").read_text())
    assert len(bundle["preparations"]) == 8
    assert bundle["execution_supported"] is bundle["queue_authorization"] is False
    assert bundle["native_profile_pending"] is True
    assert not list(output.rglob("native.json"))
    for pin in bundle["files"]:
        content = (output / pin["path"]).read_bytes()
        assert len(content) == pin["bytes"] and preparer.sha256(content) == pin["sha256"]
    for entry in bundle["preparations"]:
        state = next(s for s in profile["states"] if s["id"] == entry["source_id"])
        m = json.loads((output / entry["manifest"]["path"]).read_text())
        raw_source = (source / state["source_deck"]["path"]).read_bytes()
        derived = (output / m["derived_file"]["path"]).read_bytes()
        delta = json.loads((output / m["line_delta"]["path"]).read_text())
        assert (output / m["source_file"]["path"]).read_bytes() == raw_source
        assert "".join(x["before"] for x in delta["entries"] if x["before"] is not None).encode() == raw_source
        assert "".join(x["after"] for x in delta["entries"] if x["after"] is not None).encode() == derived
        source_lines = [x["source_line"] for x in delta["entries"] if x["source_line"] is not None]
        assert source_lines == list(range(1, len(raw_source.splitlines()) + 1))
        after_lines = [x["derived_line"] for x in delta["entries"] if x["derived_line"] is not None]
        assert after_lines == list(range(1, len(derived.splitlines()) + 1))
        assert m["geometry"]["source"] == m["geometry"]["derived"]
        assert m["geometry"]["source_sha256"] == m["geometry"]["derived_sha256"]
        assert m["schema_version"] != "discovery-qe-input/1.0.0"
        assert m["job_spec"] is m["native_manifest"] is None
        text = derived.decode()
        assert "&IONS" not in text and "&CELL" not in text
        assert "etot_conv_thr" not in text and "forc_conv_thr" not in text and "press_conv_thr" not in text
        expected_step = 0 if entry["phase"] == "initialize" else 1
        for field in [f"nstep = {expected_step},", "max_seconds = 600,", "la2f = .FALSE.,",
                      f"nbnd = {state['nbnd']},", f"ecutrho = {state['ecutrho_ry']},", "conv_thr = 1d-12,",
                      "nspin = 1,", "tot_charge = 0,", "noncolin = .FALSE.,", "lspinorb = .FALSE.,",
                      "outdir = './out',", "pseudo_dir = './pseudo',"]:
            assert field in text
        assert "/synthetic/inert/source/" not in text
        assert "electron_maxstep = " + str(state["source_electron_maxstep"] or 100) + "," in text
        for row in [*state["species_rows"], *state["position_rows"]]:
            assert row + "\n" in text
        for group in ["SYSTEM", "ELECTRONS"]:
            for key, literal in m["source_namelist_literals"][group].items():
                assert m["derived_settings"]["namelist_literals"][group][key] == literal
        assert m["geometry"]["source"]["celldm_literals"] == state["celldm_literals"]
        assert m["derived_settings"]["mesh"] == state["mesh"]
        for pin in m["pseudopotentials"]:
            data = (output / pin["prepared_file"]["path"]).read_bytes()
            assert preparer.sha256(data) == pin["sha256"]
            assert hashlib.md5(data).hexdigest() == pin["md5"]
    return bundle


def test_eight_decks_preserve_method_and_have_complete_deltas(sources):
    source, upf, output, profile = sources
    result = preparer.build(source, upf, output)
    assert result["prepared_decks"] == 8
    inspect_bundle(source, output, profile)


@pytest.mark.parametrize(("old", "new", "reason"), [
    ("  conv_thr = 1d-12,\n", "", "Missing/extra"),
    ("conv_thr = 1d-12,", "conv_thr = 1d-12,\n  conv_thr = 1d-10,", "duplicate"),
    ("conv_thr = 1d-12", "conv_thr = .TRUE.", "method mismatch"),
    ("conv_thr = 1d-12", "conv_thr = nan", "Unsupported source primitive"),
    ("conv_thr = 1d-12", "conv_thr = 1e999", "Unbounded"),
    ("la2f = .FALSE.", "la2f = .TRUE.", "method mismatch"),
    ("smearing = 'mp'", "smearing = 'mv'", "method mismatch"),
    ("ecutwfc = 98.0", "ecutwfc = 60.0", "method mismatch"),
    ("  mixing_mode = 'plain',", "  mixing_mode = 'plain',\n  diagonalization_extra = 'david',", "Unsupported"),
    ("ATOMIC_POSITIONS crystal", "ATOMIC_POSITIONS angstrom", "Missing/unsupported"),
    ("6 6 10 0 0 0", "24 24 40 0 0 0", "mesh/shift"),
    ("Mo.upf", "../Mo.upf", "species/order/mass"),
    ("Ti 0.0 0.0 0.500000007208889", "Ti 0.0 0.0 0.5", "coordinates/order"),
])
def test_semantic_mutation_rejected_separately_from_pins(old, new, reason):
    state = preparer.load_profile()["states"][0]
    data = source_text(state).decode()
    assert old in data
    with pytest.raises(ValueError, match=reason):
        preparer.parse_source(data.replace(old, new, 1).encode(), state)


@pytest.mark.parametrize("relative", ["../a", "/a", "a//b", "a/./b", "a\\b", ""])
def test_path_aliases_rejected(relative):
    with pytest.raises(ValueError, match="normalized relative"):
        preparer.safe_relative(relative)


@pytest.mark.parametrize("change", ["missing_deck", "changed_deck", "missing_upf", "changed_upf", "linked_deck", "linked_directory"])
def test_missing_corrupt_or_linked_sources_leave_no_output(sources, change):
    source, upf, output, profile = sources
    deck = source / profile["states"][0]["source_deck"]["path"]
    target = upf / "Ti.upf"
    if change == "missing_deck":
        deck.unlink()
    elif change == "changed_deck":
        deck.write_bytes(deck.read_bytes() + b"\n")
    elif change == "missing_upf":
        target.unlink()
    elif change == "changed_upf":
        target.write_bytes(target.read_bytes() + b"\n")
    elif change == "linked_deck":
        other = deck.with_suffix(".copy")
        deck.rename(other)
        deck.symlink_to(other)
    else:
        other = deck.parent.with_name("real-state")
        deck.parent.rename(other)
        deck.parent.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        preparer.build(source, upf, output)
    assert not output.exists()
    assert not list(output.parent.glob(".pbesol-preparation-*"))


@pytest.mark.parametrize(("old", "new"), [('functional="PBESOL"', 'functional="PBE"'), ('pseudo_type="NC"', 'pseudo_type="PAW"'), ('z_valence="12"', 'z_valence="13"')])
def test_upf_semantics_rejected_even_with_fixture_pins(sources, old, new):
    _, upf, _, profile = sources
    pin = copy.deepcopy(next(p for p in profile["upfs"] if p["element"] == "Ti"))
    data = (upf / "Ti.upf").read_bytes().replace(old.encode(), new.encode())
    pin.update(bytes=len(data), sha256=preparer.sha256(data), md5=hashlib.md5(data).hexdigest())
    with pytest.raises(ValueError, match="UPF"):
        preparer.validate_upf(data, pin)


def test_composition_electrons_are_independently_checked(sources):
    source, upf, output, profile = sources
    profile["states"][0]["valence_electrons"] = 51
    with pytest.raises(ValueError, match="Composition-weighted"):
        preparer.build(source, upf, output)
    assert not output.exists()


def test_existing_output_is_untouched(sources):
    source, upf, output, _ = sources
    output.mkdir()
    (output / "retained").write_bytes(b"retained")
    with pytest.raises(ValueError, match="immutable"):
        preparer.build(source, upf, output)
    assert (output / "retained").read_bytes() == b"retained"


def test_publication_race_cannot_replace_even_empty_directory(sources, monkeypatch):
    source, upf, output, _ = sources
    publish = preparer.publish_exclusive
    def race(staging, destination):
        destination.mkdir()
        publish(staging, destination)
    monkeypatch.setattr(preparer, "publish_exclusive", race)
    with pytest.raises(OSError):
        preparer.build(source, upf, output)
    assert output.is_dir() and list(output.iterdir()) == []
    assert not list(output.parent.glob(".pbesol-preparation-*"))


def test_staging_failure_has_no_partial_final_output(sources, monkeypatch):
    source, upf, output, _ = sources
    original = preparer.derive
    calls = 0
    def fail_later(*args):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("injected after prior prepared files")
        return original(*args)
    monkeypatch.setattr(preparer, "derive", fail_later)
    with pytest.raises(ValueError, match="injected"):
        preparer.build(source, upf, output)
    assert not output.exists() and not list(output.parent.glob(".pbesol-preparation-*"))


def test_original_fractional_geometry_is_not_wrapped_or_triangularized():
    states = preparer.load_profile()["states"]
    fcc = preparer.geometry(states[1])
    a = preparer.Decimal(states[1]["celldm_literals"]["celldm(1)"])
    basis = [[preparer.Decimal(x) for x in row] for row in fcc["cell_vectors_bohr_decimal"]]
    assert basis == [[-a/2, 0, a/2], [0, a/2, a/2], [-a/2, a/2, 0]]
    assert fcc["atoms"][1]["fractional_literals"] == ["-0.750000010813334", "2.25000003244", "-0.750000010813334"]
    tetragonal = preparer.geometry(states[0])
    assert tetragonal["cell_vectors_bohr_decimal"][0][1:] == ["0", "0"]


def test_real_source_acceptance_requires_explicit_paths_and_never_passes_missing_files(tmp_path):
    source = os.environ.get("SCLIB_PBESOL_SOURCE_ROOT")
    upf = os.environ.get("SCLIB_PBESOL_UPF_ROOT")
    if source is None and upf is None:
        pytest.skip("Private real-file acceptance not invoked; set both explicit SCLIB_PBESOL_*_ROOT paths")
    assert source is not None and upf is not None, "Both real-file paths must be explicitly set"
    output = tmp_path.resolve() / "real-output"
    preparer.build(Path(source), Path(upf), output)  # Missing/changed files fail; never silently skip.
    inspect_bundle(Path(source), output, preparer.load_profile())
