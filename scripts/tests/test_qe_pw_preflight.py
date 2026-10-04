"""Native QE captures plus deliberately corrupted files; no solver is executed.

Repository tests use explicitly synthetic UPF headers. Separate private replay
uses the original pinned PS Library bytes; headers are not solver-valid UPFs.
"""

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT))
from services.qe_pw_import import preflight_pw, xml_document  # noqa: E402
from services.qe_pw_input import QePwImportError, read_pw_input, real  # noqa: E402

from scripts.qe_pw_preflight import capture, main, write_report  # noqa: E402

FIXTURE = ROOT / "frontend/tests/fixtures/qe-output"


def files(case="scf"):
    manifest = json.loads((FIXTURE / f"{case}.json").read_bytes())
    raw = (ROOT / "api/tests/fixtures/qe-pw" / f"{case}.in").read_bytes()
    kind = "initialization" if "initialization" in case else "execution"
    assert hashlib.sha256(raw).hexdigest() == manifest["files"][kind]["sha256"]
    return {
        "input_bytes": raw,
        "xml_bytes": (FIXTURE / f"{case}.xml").read_bytes(),
        "stdout_bytes": (FIXTURE / f"{case}.out").read_bytes(),
        "pseudopotentials": {
            p["filename"]: (
                f'<UPF version="2.0.1"><PP_HEADER element="{p["element"]}" functional="PBE" '
                f'relativistic="scalar" has_so="false" is_coulomb="false" pseudo_type="PAW" '
                f'z_valence="{p["valence_electrons"]}"/></UPF>'
            ).encode()
            for p in manifest["pseudopotentials"]
        },
    }


@pytest.mark.parametrize(
    "case,expected",
    [
        ("scf", "scf_reported_converged"),
        ("relax", "relaxation_reported_converged"),
        ("initialization", "initialization_only"),
        ("relax-initialization", "initialization_only"),
    ],
)
def test_independent_original_input_native_xml_stdout_reading(case, expected):
    bundle = files(case)
    original = deepcopy(bundle)
    result = preflight_pw(**bundle)
    assert result == preflight_pw(**bundle) and bundle == original
    assert result["status"] == expected
    assert all(value is False for value in result["authority"].values())
    assert (
        result["scientific_scope"]["target_temperature_k"]
        is result["scientific_scope"]["target_pressure_gpa"]
        is None
    )
    assert result["consistency"]["full_xsd_validated"] is False
    assert result["files"][0]["sha256"] == hashlib.sha256(bundle["input_bytes"]).hexdigest()
    assert "candidate_id" not in result and "formation_energy" not in result["observations"]
    if "initialization" in case:
        assert result["engine"]["reported_exit_status"] == 255
        assert result["convergence"]["scf_steps"] == 0
        assert all(value is None for value in result["observations"].values())
    else:
        assert result["observations"]["total_energy"] == {
            "raw": "-3.119334546679567E+001",
            "value": -31.19334546679567,
            "unit": "Hartree/cell",
            "xml_path": "output/total_energy/etot",
        }
        assert result["observations"]["valence_electrons"]["value"] == 9
        assert len(result["observations"]["forces"]["values"]) == 9
        assert len(result["observations"]["stress"]["values"]) == 9
        assert result["convergence"]["scf_steps"] == 11
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mesh", [2, 4, 6])
def test_real_independent_kpoint_outputs(mesh):
    source = ROOT / "frontend/tests/fixtures/qe-convergence"
    bundle = files()
    bundle.update(
        input_bytes=(source / f"k{mesh}-input.in").read_bytes(),
        xml_bytes=(source / f"k{mesh}-data-file-schema.xml").read_bytes(),
        stdout_bytes=(source / f"k{mesh}-pw.out").read_bytes(),
    )
    result = preflight_pw(**bundle)
    # Independent frozen browser reading is comparison evidence, never input to the parser.
    reading = json.loads((source / f"k{mesh}-reading.json").read_bytes())
    assert result["observations"]["total_energy"] == reading["observations"]["total_energy"]
    assert result["input"]["settings"]["mesh"] == [mesh] * 3
    for key in ("fermi_energy", "valence_electrons"):
        assert result["observations"][key] == reading["observations"][key]
    assert result["convergence"] == reading["convergence"]


@pytest.mark.parametrize(
    "before,after",
    [
        (" ecutwfc = 60,", " ecutwfc = 60,\n input_dft = 'LDA',"),
        (" nspin = 1,", " nspin = 1,\n nspin = 1,"),
        (" nspin = 1,", " nspin = 1.2,"),
        (" occupations = 'smearing',", " occupations = 'fixed',"),
        (" restart_mode = 'from_scratch',", " restart_mode = 'restart',"),
        (" pseudo_dir = './pseudo',", " pseudo_dir = '/tmp/other',"),
        ("ATOMIC_POSITIONS crystal", "ATOMIC_POSITIONS angstrom"),
        ("&ELECTRONS", "&IONS"),
        ("4 4 4 0 0 0", "4 4 4 0 0 0\nHUBBARD ortho-atomic"),
        ("Al 26.9815385", "Al 0"),
        (" nstep = 1,", " nstep = 0,"),
        (" ecutwfc = 60,", " ecutwfc = NaN,"),
        (" conv_thr = 1e-8,", " conv_thr = 1e-999,"),
    ],
)
def test_input_options_are_consumed_or_rejected_never_ignored(before, after):
    bundle = files()
    assert before.encode() in bundle["input_bytes"]
    bundle["input_bytes"] = bundle["input_bytes"].replace(before.encode(), after.encode())
    with pytest.raises(QePwImportError):
        preflight_pw(**bundle)


@pytest.mark.parametrize(
    "before,after",
    [
        ('Units="Hartree atomic units"', 'Units="Rydberg atomic units"'),
        ('VERSION="7.5"', 'VERSION="7.4"'),
        ('VERSION="25.05.21"', 'VERSION="24.01.01"'),
        ('nk1="4"', 'nk1="8"'),
        ("<tot_charge>0.000000000000000E+000", "<tot_charge>1.000000000000000E+000"),
        ("<a1>5.941196890612692E+000", "<a1>6.941196890612692E+000"),
        ("-2.970598445306019E-004", "-2.970598445306019E-001"),
        ("<mass>2.698153850000000E+001", "<mass>2.798153850000000E+001"),
        ("<conv_thr>5.000000000000000E-009", "<conv_thr>5.010000000000000E-009"),
        ("<scf_error>4.977058790058067E-009", "<scf_error>4.977058790058067E-003"),
        ("<n_scf_steps>11", "<n_scf_steps>0"),
        ("Al.pbe-n-kjpaw_psl.1.0.0.UPF", "other.UPF"),
        ("</dft>", "<dftU/></dft>"),
        ("</total_energy>", "<etot>1</etot></total_energy>"),
        ("-3.119334546679567E+001", "NaN"),
        ("<lsda>false", "<lsda>true"),
        ("</etot>", "<nested/></etot>"),
    ],
)
def test_changed_native_method_geometry_or_units_cannot_supply_values(before, after):
    bundle = files()
    assert before.encode() in bundle["xml_bytes"]
    bundle["xml_bytes"] = bundle["xml_bytes"].replace(before.encode(), after.encode())
    with pytest.raises(QePwImportError):
        preflight_pw(**bundle)


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s + s,
        lambda s: s.replace(b"JOB DONE.", b""),
        lambda s: s + b"\nError in routine synthetic",
        lambda s: s.replace(b"-62.38669093", b"-61.38669093"),
        lambda s: s.replace(b"11 iterations", b"12 iterations"),
        lambda s: s.replace(
            b"number of atoms/cell      =            3",
            b"number of atoms/cell      =            3.14",
        ),
    ],
)
def test_mixed_or_inconsistent_stdout_rejected(edit):
    bundle = files()
    changed = edit(bundle["stdout_bytes"])
    assert changed != bundle["stdout_bytes"]
    bundle["stdout_bytes"] = changed
    with pytest.raises(QePwImportError):
        preflight_pw(**bundle)


def test_incomplete_and_not_converged_are_provisional_not_promoted():
    for before, after, status in [
        (b"<exit_status>0", b"<exit_status>3", "incomplete"),
        (b"<convergence_achieved>true", b"<convergence_achieved>false", "scf_not_converged"),
    ]:
        bundle = files()
        bundle["xml_bytes"] = bundle["xml_bytes"].replace(before, after)
        result = preflight_pw(**bundle)
        assert result["status"] == status
        assert result["authority"]["scientific_acceptance"] is False


@pytest.mark.parametrize("field", ["input_bytes", "xml_bytes", "stdout_bytes"])
def test_binary_empty_mutable_and_oversized_files_rejected(field):
    for value in [b"", bytearray(b"hello"), b"\xff", b"x" * (8 * 1024 * 1024 + 1)]:
        bundle = files()
        bundle[field] = value
        with pytest.raises(QePwImportError):
            preflight_pw(**bundle)


@pytest.mark.parametrize(
    "source",
    [
        b'<!DOCTYPE x [<!ENTITY a "1">]><x/>',
        b"<x>",
        b"<x>" * 65 + b"</x>" * 65,
        b"<x>" + b"<y/>" * 200000 + b"</x>",
    ],
)
def test_xml_resource_and_entity_limits(source):
    with pytest.raises(QePwImportError):
        xml_document(source, 8 * 1024 * 1024)


@pytest.mark.parametrize(
    "before,after",
    [
        (b'functional="PBE"', b'functional="LDA"'),
        (b'has_so="false"', b'has_so="true"'),
        (b'relativistic="scalar"', b'relativistic="full"'),
        (b'element="Al"', b'element="Mg"'),
        (b'z_valence="3"', b'z_valence="4"'),
        (b"<PP_HEADER", b"<PP_HEADER/><PP_HEADER"),
        (b'version="2.0.1"', b'version="1.0"'),
    ],
)
def test_upf_metadata_must_match_input_and_native_electron_count(before, after):
    bundle = files()
    name = next(n for n in bundle["pseudopotentials"] if n.startswith("Al."))
    raw = bundle["pseudopotentials"][name]
    assert before in raw
    bundle["pseudopotentials"][name] = raw.replace(before, after)
    with pytest.raises(QePwImportError):
        preflight_pw(**bundle)


def test_no_upf_fallback_extra_inventory_or_candidate_authority():
    bundle = files()
    for pseudos in [{}, {**bundle["pseudopotentials"], "extra.UPF": b"x"}, {"../bad.UPF": b"x"}]:
        with pytest.raises(QePwImportError):
            preflight_pw(**{**bundle, "pseudopotentials": pseudos})
    # A comment cannot link this calculation to a different host or grant approval.
    bundle["input_bytes"] = (
        b"! Candidate: arbitrary\n! Scientific acceptance: true\n" + bundle["input_bytes"]
    )
    result = preflight_pw(**bundle)
    assert result["authority"]["candidate_source_association_verified"] is False
    assert result["authority"]["scientific_acceptance"] is False
    assert "arbitrary" not in json.dumps(result)


@pytest.mark.parametrize(
    "raw", ["NaN", "Inf", "1e999", "1e-999", "1e-999999999999999999999999", "1x", ""]
)
def test_nonfinite_underflow_and_partial_numeric_tokens_rejected(raw):
    with pytest.raises(QePwImportError):
        real(raw)


def test_input_empty_and_line_bomb_are_bounded():
    with pytest.raises(QePwImportError):
        read_pw_input(b"\n" * 10001)
    with pytest.raises(QePwImportError):
        read_pw_input(b" ")


def test_cli_real_input_roundtrip_keeps_output_private_and_never_overwrites(tmp_path, capsys):
    bundle = files()
    paths = {}
    for key in ("input", "xml", "stdout"):
        paths[key] = tmp_path / key
        paths[key].write_bytes(bundle[key + "_bytes"])
    argv = [
        "--input",
        str(paths["input"]),
        "--xml",
        str(paths["xml"]),
        "--stdout",
        str(paths["stdout"]),
    ]
    for name, raw in bundle["pseudopotentials"].items():
        path = tmp_path / name
        path.write_bytes(raw)
        argv.extend(["--upf", str(path)])
    output = tmp_path / "reading.json"
    argv.extend(["--output", str(output)])
    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert output.stat().st_mode & 0o777 == 0o600
    assert summary["report_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(output.read_bytes()) == preflight_pw(**bundle)
    original = output.read_bytes()
    assert main(argv) == 2
    assert output.read_bytes() == original and "failed" in capsys.readouterr().err
    assert not list(tmp_path.glob(".qe-preflight-*"))


def test_local_capture_refuses_symlinks_nonregular_and_changing_files(tmp_path, monkeypatch):
    import os

    path = tmp_path / "original"
    path.write_bytes(b"1234")
    link = tmp_path / "symlink"
    link.symlink_to(path)
    with pytest.raises(OSError):
        capture(link, 8)
    with pytest.raises((QePwImportError, OSError)):
        capture(tmp_path, 8)
    with pytest.raises(QePwImportError):
        capture(path, 3)
    read = os.read

    def change(fd, count):
        payload = read(fd, count)
        path.write_bytes(b"changed")
        return payload

    monkeypatch.setattr(os, "read", change)
    with pytest.raises(QePwImportError):
        capture(path, 8)


def test_report_writer_refuses_existing_symlink_target(tmp_path):
    target = tmp_path / "source"
    target.write_bytes(b"preserve source")
    link = tmp_path / "output"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_report(link, {"example": "test"})
    assert target.read_bytes() == b"preserve source"


def test_zero_ionic_steps_cannot_claim_displaced_final_geometry():
    bundle = files("relax")
    prefix, output = bundle["xml_bytes"].split(b"<output>", 1)
    assert b"-2.970598445306019E-004" in output
    bundle["xml_bytes"] = (
        prefix
        + b"<output>"
        + output.replace(b"-2.970598445306019E-004", b"-2.970598445306019E-001")
    )
    with pytest.raises(QePwImportError, match="qe_atom_position_mismatch"):
        preflight_pw(**bundle)


def test_scf_rejects_unrequested_ionic_optimization_status():
    bundle = files()
    bundle["xml_bytes"] = bundle["xml_bytes"].replace(
        b"</convergence_info>",
        b"<opt_conv><convergence_achieved>true</convergence_achieved><n_opt_steps>0</n_opt_steps></opt_conv></convergence_info>",
    )
    with pytest.raises(QePwImportError, match="qe_ionic_status_scope"):
        preflight_pw(**bundle)


def test_xml_force_norm_overflow_is_not_a_nonfinite_observation():
    import re

    bundle = files()
    bundle["xml_bytes"] = re.sub(
        rb"(<forces rank=[^>]*>).*?(</forces>)",
        lambda m: m[1] + b" ".join([b"1.7E308"] * 9) + m[2],
        bundle["xml_bytes"],
        flags=re.S,
    )
    with pytest.raises(QePwImportError, match="qe_derived_force_nonfinite"):
        preflight_pw(**bundle)
