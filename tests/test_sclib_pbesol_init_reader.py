"""Default tests use synthetic inputs and outputs; optional actual input checks are explicit.

Neither path executes QE, creates JobSpecs or establishes result custody.
"""

import copy
import json
import os
import socket
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/tests"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/sclib_compute"))

import pbesol_init_reader as reader
import test_sclib_pbesol_profile as binding_tests
from pbesol_init_fixtures import initialization_outputs
from sclib_compute import pbesol_profile as profile
from sclib_compute.contracts import canonical

synthetic = binding_tests.synthetic


def make_context(sid, files):
    binding = profile.build_input_binding(sid, "initialize", files)
    manifest = json.loads(files["preparation.json"])
    root, stdout = initialization_outputs(manifest)
    return {
        "files": files,
        "binding": canonical(binding.model_dump(mode="json")),
        "xml": ET.tostring(root),
        "stdout": stdout,
    }


class InitializationReadingTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def synthetic_contexts(self, synthetic):
        self.source_sets = synthetic[0]
        self.contexts = {sid: make_context(sid, self.source_sets[sid, "initialize"]) for sid in profile.CONTEXT_IDS}

    def read(self, sid="agm001228974", **changes):
        context = self.contexts[sid]
        values = {"xml": context["xml"], "stdout": context["stdout"], "stderr": b"", "process_exit_code": 0}
        values.update(changes)
        return reader.read_initialization(context["binding"], context["files"], **values)

    def mutate(self, path, value=None, *, attr=None, sid="agm001228974"):
        root = ET.fromstring(self.contexts[sid]["xml"])
        node = root.find(path)
        assert node is not None, path
        if attr:
            node.set(attr, value)
        else:
            node.text = value
        return ET.tostring(root)

    def rejected(self, **changes):
        report = self.read(**changes)
        self.assertIn(report["semantic_reading_status"], ("rejected", "unreadable"))
        self.assertFalse(report["execution_consistency_ready_for_review"])
        self.assertFalse(report["scientific_acceptance"])
        self.assertIsNotNone(report["rejection"])
        self.assertTrue(all(value is None for value in report["physical_outputs"].values()))
        return report

    def test_four_synthetic_contexts_keep_all_physical_values_null(self):
        for sid, electrons, bands in [
            ("agm001228974", 52, 31),
            ("agm002322068", 52, 31),
            ("agm001828806", 94, 56),
            ("agm001416090", 94, 56),
        ]:
            with self.subTest(sid=sid):
                report = self.read(sid)
                self.assertEqual(report["semantic_reading_status"], "initialization_only")
                self.assertEqual(report["schema_version"], "sclib-pbesol-initialization-reading/1")
                self.assertEqual(report["implementation_status"], "offline_reader_synthetic_output_tests_only")
                self.assertTrue(report["input_binding_verified"])
                self.assertEqual(report["expected_input"]["expected_electrons"], electrons)
                self.assertEqual(report["expected_input"]["expected_nbnd"], bands)
                self.assertEqual(report["expected_input"]["electron_scope"], "input_UPF_inventory_not_measured_output")
                self.assertTrue(all(value is None for value in report["physical_outputs"].values()))
                self.assertFalse(report["custody_verified"])
                self.assertIsNone(report["capture_complete"])
                self.assertIsNone(report["current_returned_attempt"])
                self.assertIsNone(report["transport_outcome_verified"])
                for key in (
                    "actual_runtime_acceptance",
                    "next_stage_ready",
                    "execution_consistency_ready_for_review",
                    "scientific_acceptance",
                    "tc_calculated",
                    "candidate_grade_changed",
                ):
                    self.assertIs(report[key], False)
                self.assertEqual((report["solver_calls"], report["queue_calls"]), (0, 0))

    def test_os_exit_and_xml_status_remain_distinct(self):
        for xml_status in (0, 255):
            for os_status in (None, 0, 255, 1, -15):
                with self.subTest(xml=xml_status, os=os_status):
                    report = self.read(xml=self.mutate("exit_status", str(xml_status)), process_exit_code=os_status)
                    self.assertEqual(report["semantic_reading_status"], "initialization_only")
                    self.assertEqual(report["xml_exit_status"], xml_status)
                    self.assertEqual(report["process_exit_code_supplied"], os_status)
                    self.assertEqual(report["exit_requires_review"], os_status != 0)
                    self.assertFalse(report["next_stage_ready"])
                    if os_status == 255:
                        self.assertEqual(report["supplied_process_classification"], "solver_failure")
        report = self.read(stderr=b"STOP 255\n", process_exit_code=255)
        self.assertEqual(report["semantic_reading_status"], "initialization_only")
        self.assertTrue(report["exit_requires_review"])
        for bad in (True, False, 0.0, "0", 256, -256):
            with self.assertRaises(reader.Rejected):
                self.read(process_exit_code=bad)

    def test_revalidates_every_synthetic_input_against_test_only_installed_trust(self):
        context = self.contexts["agm001228974"]
        for name in context["files"]:
            with self.subTest(file=name):
                files = dict(context["files"])
                files[name] += b" "
                report = reader.read_initialization(
                    context["binding"], files, xml=context["xml"], stdout=context["stdout"]
                )
                self.assertFalse(report["input_binding_verified"])
                self.assertEqual(report["semantic_reading_status"], "rejected")
        fabricated = json.loads(context["binding"])
        fabricated["expected_electrons"] = 54
        report = reader.read_initialization(
            canonical(fabricated), context["files"], xml=context["xml"], stdout=context["stdout"]
        )
        self.assertFalse(report["input_binding_verified"])
        report = reader.read_initialization(fabricated, context["files"], xml=context["xml"], stdout=context["stdout"])
        self.assertFalse(report["input_binding_verified"])

    def test_rejects_scf_preparation_without_starting_reader(self):
        sid = "agm001228974"
        files = self.source_sets[sid, "scf"]
        binding = profile.build_input_binding(sid, "scf", files)
        context = self.contexts[sid]
        report = reader.read_initialization(
            canonical(binding.model_dump(mode="json")), files, xml=context["xml"], stdout=context["stdout"]
        )
        self.assertEqual(report["rejection"]["code"], "INITIALIZATION_ONLY")

    def test_exact_method_units_inventory_and_flags(self):
        changes = [
            ("input/dft/functional", "PBE"),
            ("output/dft/functional", "PBEsol"),
            ("input/basis/ecutwfc", "98"),
            ("output/basis_set/ecutrho", "98"),
            ("input/electron_control/conv_thr", "1e-12"),
            ("input/electron_control/mixing_mode", "TF"),
            ("input/electron_control/diagonalization", "cg"),
            ("input/electron_control/max_nstep", "99"),
            ("input/bands/nbnd", "30"),
            ("input/bands/tot_charge", "1"),
            ("input/bands/occupations", "fixed"),
            ("input/bands/smearing", "gaussian"),
            ("input/spin/lsda", "true"),
            ("input/spin/noncolin", "true"),
            ("output/magnetization/spinorbit", "true"),
            ("input/control_variables/nstep", "1"),
            ("input/control_variables/prefix", "other"),
            ("input/control_variables/max_seconds", "900"),
            ("input/control_variables/restart_mode", "restart"),
            ("input/control_variables/calculation", "relax"),
            ("input/ion_control/ion_dynamics", "bfgs"),
            ("input/cell_control/cell_dynamics", "bfgs"),
        ]
        for path, value in changes:
            with self.subTest(path=path):
                self.rejected(xml=self.mutate(path, value))
        for path, name, value in [
            ("input/bands/smearing", "degauss", "0.014699728870262"),
            ("input/k_points_IBZ/monkhorst_pack", "nk1", "8"),
            ("input/k_points_IBZ/monkhorst_pack", "k1", "1"),
        ]:
            with self.subTest(path=path, attr=name):
                self.rejected(xml=self.mutate(path, value, attr=name))
        root = ET.fromstring(self.contexts["agm001228974"]["xml"])
        ET.SubElement(root.find("input/dft"), "dftU")
        self.rejected(xml=ET.tostring(root))

    def test_general_fcc_basis_and_equivalent_integer_translation(self):
        for sid in ("agm002322068", "agm001416090"):
            root = ET.fromstring(self.contexts[sid]["xml"])
            for section in ("input", "output"):
                basis = [
                    [float(x) for x in root.find(f"{section}/atomic_structure/cell/{axis}").text.split()]
                    for axis in ("a1", "a2", "a3")
                ]
                self.assertLess(basis[0][0], 0)
                self.assertNotEqual(basis[0][2], 0)
                atom = root.find(f"{section}/atomic_structure/atomic_positions/atom")
                cart = [float(x) for x in atom.text.split()]
                atom.text = " ".join(format(cart[i] + basis[0][i], ".16g") for i in range(3))
            report = self.read(sid, xml=ET.tostring(root))
            self.assertEqual(report["semantic_reading_status"], "initialization_only")

    def test_geometry_order_basis_and_huge_coordinate_counterexample(self):
        for sid in profile.CONTEXT_IDS:
            for section in ("input", "output"):
                with self.subTest(sid=sid, section=section):
                    root = ET.fromstring(self.contexts[sid]["xml"])
                    for atom in root.findall(f"{section}/atomic_structure/atomic_positions/atom"):
                        atom.text = "1e30 1e30 1e30"
                    report = self.rejected(sid=sid, xml=ET.tostring(root))
                    self.assertEqual(report["rejection"]["code"], "STRUCTURE_POSITION_PRECISION")
        for path, value, attr in [
            ("input/atomic_structure", "2", "bravais_index"),
            ("output/atomic_structure", "3", "nat"),
            ("input/atomic_structure/atomic_positions/atom", "Nb", "name"),
            ("input/atomic_structure/atomic_positions/atom", "2", "index"),
        ]:
            self.rejected(xml=self.mutate(path, value, attr=attr))
        for value in ("0 0 0", "-8 0 0", "nan 0 0", "1e309 0 0"):
            self.rejected(xml=self.mutate("input/atomic_structure/cell/a1", value))
        self.rejected(xml=self.mutate("input/atomic_structure/atomic_positions/atom", "0 0 0"))
        for basis in ([[1, 0, 0], [1, 1e-14, 0], [0, 0, 1]], [[1, 0, 0], [0, 1, 0], [0, 0, -1]]):
            with self.assertRaises(reader.Rejected):
                reader.inv3(basis)

    def test_unique_full_stdout_summaries(self):
        raw = self.contexts["agm001228974"]["stdout"]
        for row in (
            b"number of electrons = 52.00",
            b"number of atoms/cell = 4",
            b"number of atomic types = 3",
            b"number of Kohn-Sham states = 31",
        ):
            for changed in (
                raw + row + b"\n",
                raw.replace(row, row + b" suffix"),
                raw + row.split(b"=")[0] + b"=bad\n",
            ):
                with self.subTest(row=row, changed=changed[-70:]):
                    self.rejected(stdout=changed)
        for changed in (
            raw.replace(b"52.00", b"52.01"),
            raw.replace(b"31\n", b"30\n"),
            raw.replace(b"v.7.5", b"v.7.4"),
            raw + b"Program PWSCF v.7.4 starts\n",
            raw + b"JOB DONE.\n",
            raw.replace(b"JOB DONE.", b"JOB DONE. suffix"),
            b"\xff",
        ):
            self.rejected(stdout=changed)

    def test_contradictory_markers_in_both_streams(self):
        markers = [
            "iteration # 1",
            "! total energy = -10 Ry",
            "total energy = -10 Ry",
            "convergence has been achieved in 1 iterations",
            "convergence NOT achieved",
            "maximum CPU time exceeded",
            "maximum time reached",
            "wallclock time limit reached",
            "signal received",
            "Caught signal 15",
            "signal 15 received",
            "SIGTERM",
            "stopping by user",
            "user requested stop",
            "Error in routine electrons",
            "MPI_ABORT",
            "Segmentation fault",
            "killed",
            "STOP 1",
            "STOP 255 suffix",
            "Fermi energy is 1 eV",
            "total force = 0",
            "Self-consistent Calculation",
        ]
        for marker in markers:
            with self.subTest(marker=marker):
                self.rejected(stdout=self.contexts["agm001228974"]["stdout"] + marker.encode() + b"\n")
                self.rejected(stderr=marker.encode() + b"\n")

    def test_no_scf_or_physical_result_objects_even_nested(self):
        for path, value in [
            ("output/convergence_info/scf_conv/convergence_achieved", "true"),
            ("output/convergence_info/scf_conv/n_scf_steps", "1"),
            ("output/convergence_info/scf_conv/scf_error", "-1"),
            ("exit_status", "1"),
        ]:
            self.rejected(xml=self.mutate(path, value))
        for tag in reader.FORBIDDEN_INIT_OUTPUT:
            for nesting in (False, True):
                root = ET.fromstring(self.contexts["agm001228974"]["xml"])
                output = root.find("output")
                if nesting:
                    output = ET.SubElement(output, "unexpected_container")
                ET.SubElement(output, tag).text = "0"
                with self.subTest(tag=tag, nesting=nesting):
                    self.rejected(xml=ET.tostring(root))
        root = ET.fromstring(self.contexts["agm001228974"]["xml"])
        ET.SubElement(root, "step")
        self.rejected(xml=ET.tostring(root))

    def test_malformed_missing_duplicate_or_hidden_xml(self):
        raw = self.contexts["agm001228974"]["xml"]
        self.assertEqual(self.rejected(xml=raw[:-20])["semantic_reading_status"], "unreadable")
        self.assertEqual(self.rejected(xml=b"")["semantic_reading_status"], "unreadable")
        self.rejected(stdout=b"")
        self.rejected(xml=b'<!DOCTYPE x [<!ENTITY p "x">]>' + raw)
        self.rejected(xml=raw.replace(b"25.05.21", b"24.04.03"))
        self.rejected(xml=raw.replace(b"Hartree atomic units", b"Rydberg atomic units"))
        for kind in ("remove", "duplicate", "child", "attribute"):
            root = ET.fromstring(raw)
            node = root.find("input/electron_control/conv_thr")
            parent = root.find("input/electron_control")
            if kind == "remove":
                parent.remove(node)
            elif kind == "duplicate":
                parent.append(copy.deepcopy(node))
            elif kind == "child":
                ET.SubElement(node, "hidden").text = "1"
            else:
                node.set("units", "Ry")
            self.rejected(xml=ET.tostring(root))
        root = ET.fromstring(raw)
        ET.SubElement(root.find("output"), "{http://untrusted.example}etot").text = "0"
        self.rejected(xml=ET.tostring(root))

    def test_bounded_bytes_and_no_process_or_network_calls(self):
        for args in (
            {"xml": bytearray(b"x")},
            {"xml": b"x" * (reader.MAX_XML + 1)},
            {"stdout": b"x" * (reader.MAX_STDOUT + 1)},
            {"stderr": b"x" * (reader.MAX_STDERR + 1)},
        ):
            with self.assertRaises(reader.Rejected):
                self.read(**args)
        with (
            patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")),
            patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
        ):
            self.assertEqual(self.read()["semantic_reading_status"], "initialization_only")

    def test_rejects_all_source_confirmed_uncomputed_result_families(self):
        # PW/src/pw_restart_new.f90 only_init jump 613 -> 848 bypasses all ten.
        families = {
            "total_energy",
            "band_structure",
            "forces",
            "stress",
            "electric_field",
            "fcp_force",
            "fcp_tot_charge",
            "rism3d",
            "rismlaue",
            "two_chem",
        }
        for tag in families:
            for nested in (False, True):
                root = ET.fromstring(self.contexts["agm001228974"]["xml"])
                parent = root.find("output")
                if nested:
                    parent = ET.SubElement(parent, "unexpected_container")
                ET.SubElement(parent, tag)
                with self.subTest(tag=tag, nested=nested):
                    self.rejected(xml=ET.tostring(root))

    def test_rejects_alternative_coordinate_representations_and_preserves_alat(self):
        for section in ("input", "output"):
            for kind in ("crystal_positions", "wyckoff_positions", "atomic_positions"):
                root = ET.fromstring(self.contexts["agm001228974"]["xml"])
                parent = root.find(f"{section}/atomic_structure")
                extra = ET.SubElement(parent, kind)
                ET.SubElement(extra, "atom", name="Ti", index="1").text = "0 0 0"
                with self.subTest(section=section, kind=kind):
                    report = self.rejected(xml=ET.tostring(root))
                    self.assertEqual(report["rejection"]["code"], "STRUCTURE_REPRESENTATION")
        root = ET.fromstring(self.contexts["agm001228974"]["xml"])
        for section in ("input", "output"):
            root.find(f"{section}/atomic_structure").set("alat", "8.585747348635769")
        self.assertEqual(self.read(xml=ET.tostring(root))["semantic_reading_status"], "initialization_only")

    def test_rejects_ambiguous_unit_attributes_on_numeric_ancestors(self):
        paths = [
            "input",
            "output",
            "input/atomic_structure",
            "output/atomic_structure",
            "input/atomic_structure/atomic_positions",
            "output/atomic_structure/atomic_positions",
            "input/atomic_structure/cell",
            "output/atomic_structure/cell",
            "input/basis",
            "output/basis_set",
            "input/bands",
            "input/electron_control",
            "input/atomic_structure/cell/a1",
            "input/electron_control/conv_thr",
        ]
        for path in paths:
            for attr in ("units", "Units", "unit", "{http://untrusted.example}Units"):
                with self.subTest(path=path, attr=attr):
                    report = self.rejected(xml=self.mutate(path, "angstrom", attr=attr))
                    self.assertEqual(report["rejection"]["code"], "XML_UNITS")
        root = ET.fromstring(self.contexts["agm001228974"]["xml"])
        root.set("units", "Rydberg atomic units")
        self.rejected(xml=ET.tostring(root))

    def test_caller_mutation_after_validation_cannot_change_the_reading_snapshot(self):
        context = self.contexts["agm001228974"]
        caller_files = dict(context["files"])
        validate = reader.validate_input_binding

        def mutate_caller(binding_bytes, captured_files):
            self.assertIsNot(captured_files, caller_files)
            binding = validate(binding_bytes, captured_files)
            caller_files["preparation.json"] = b"{}"
            caller_files["input.in"] = b"unrelated input"
            return binding

        with patch.object(reader, "validate_input_binding", side_effect=mutate_caller):
            result = reader.read_initialization(
                context["binding"], caller_files, xml=context["xml"], stdout=context["stdout"]
            )
        self.assertEqual(result["semantic_reading_status"], "initialization_only")
        self.assertTrue(result["input_binding_verified"])
        self.assertEqual(
            result["expected_input"]["input_sha256"], json.loads(context["binding"])["derived_deck"]["sha256"]
        )
        self.assertEqual(caller_files["preparation.json"], b"{}")


def optional_actual_files(sid):
    """Unset skips; an explicitly supplied missing/corrupt path always fails."""
    configured = os.environ.get("SCLIB_PBESOL_FORMAL_BUNDLE")
    if configured is None:
        pytest.skip("Actual frozen inputs unavailable; set SCLIB_PBESOL_FORMAL_BUNDLE explicitly")
    if not configured.strip():
        raise ValueError("Explicit actual-input path cannot be empty")
    root = Path(configured)
    prep = profile.prep
    assert prep.sha256(prep.read_regular(root, "bundle-manifest.json")) == profile.BUNDLE_SHA256
    _, table = profile._load_trust()
    pin = next(
        c["preparation_manifest"] for c in table["contexts"] if c["source_id"] == sid and c["phase"] == "initialize"
    )
    prefix = f"prepared/{sid}/initialize/"
    manifest_raw = prep.read_regular(root, prefix + "preparation-manifest.json")
    prep.check_pin(manifest_raw, pin)  # Verify before following any manifest path.
    manifest = json.loads(manifest_raw)
    files = {
        "preparation.json": manifest_raw,
        "source.in": prep.read_regular(root, manifest["source_file"]["path"]),
        "input.in": prep.read_regular(root, prefix + "input.in"),
        "delta.json": prep.read_regular(root, prefix + "delta.json"),
    }
    files.update(
        {
            p["filename"]: prep.read_regular(root, prefix + "pseudo/" + p["filename"])
            for p in manifest["pseudopotentials"]
        }
    )
    return files


@pytest.mark.parametrize("sid", profile.CONTEXT_IDS)
def test_four_optional_actual_input_contexts_with_synthetic_outputs(sid):
    context = make_context(sid, optional_actual_files(sid))
    report = reader.read_initialization(
        context["binding"], context["files"], xml=context["xml"], stdout=context["stdout"], process_exit_code=0
    )
    assert report["semantic_reading_status"] == "initialization_only"
    assert report["input_binding_verified"] is True
    assert report["custody_verified"] is report["actual_runtime_acceptance"] is report["scientific_acceptance"] is False
    assert all(value is None for value in report["physical_outputs"].values())


def test_optional_actual_input_selection_never_silently_skips_bad_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("SCLIB_PBESOL_FORMAL_BUNDLE", raising=False)
    with pytest.raises(pytest.skip.Exception):
        optional_actual_files(profile.CONTEXT_IDS[0])
    monkeypatch.setenv("SCLIB_PBESOL_FORMAL_BUNDLE", "")
    with pytest.raises(ValueError, match="cannot be empty"):
        optional_actual_files(profile.CONTEXT_IDS[0])
    monkeypatch.setenv("SCLIB_PBESOL_FORMAL_BUNDLE", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="directory is missing"):
        optional_actual_files(profile.CONTEXT_IDS[0])
    (tmp_path / "bundle-manifest.json").write_bytes(b"{}")
    monkeypatch.setenv("SCLIB_PBESOL_FORMAL_BUNDLE", str(tmp_path))
    with pytest.raises(AssertionError):
        optional_actual_files(profile.CONTEXT_IDS[0])
