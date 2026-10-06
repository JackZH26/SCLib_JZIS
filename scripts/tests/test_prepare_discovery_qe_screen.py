"""Native-deck preparation tests. Synthetic UPFs below are unit fixtures only.

No test launches QE or treats a header-only fixture as a usable pseudopotential.
Independent CIF tests use an existing Gemmi runtime, never an installation.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("qe_screen", ROOT / "scripts/prepare_discovery_qe_screen.py")
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)


def fixture_upf(element="Mg", functional=" SLA  PW   PBX  PBC", has_so="false"):
    return (f'<UPF version="2.0.1"><PP_INFO>UNIT FIXTURE ONLY; NEVER EXECUTE.</PP_INFO>'
            f'<PP_HEADER element="{element}" functional="{functional}" relativistic="scalar" has_so="{has_so}" '
            'is_coulomb="false" pseudo_type="PAW" z_valence="2.0D+0" wfc_cutoff="80.0" rho_cutoff="800.0"/></UPF>').encode()


def pin(element, raw):
    return {"element":element,"path":f"files/{element}.UPF","bytes":len(raw),"sha256":Q.sha(raw),
            "source_url":f"https://example.invalid/{element}.UPF","license":"Unit fixture only",
            "license_url":"https://example.invalid/license","release":"unit-fixture"}


class PinnedReaderBootstrapTest(unittest.TestCase):
    def test_tampered_code_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"reader.py"
            path.write_bytes(b"raise AssertionError('unverified code ran')\n")
            with self.assertRaisesRegex(ValueError,"shared_reader_hash_mismatch"):
                Q._load_pinned_input_reader(path,"0"*64)

    def test_symlink_nonregular_and_oversize_sources_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"reader.py";raw=b"value = 1\n";path.write_bytes(raw)
            link=Path(temp)/"link.py";link.symlink_to(path)
            fifo=Path(temp)/"fifo.py";os.mkfifo(fifo)
            oversized=Path(temp)/"large.py"
            with oversized.open("wb") as handle:handle.truncate(1024*1024+1)
            for candidate in [link,fifo,oversized]:
                with self.subTest(path=candidate.name),self.assertRaises(ValueError):
                    Q._load_pinned_input_reader(candidate,Q.sha(raw))

    def test_mutation_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"reader.py";raw=b"value = 1\n";path.write_bytes(raw)
            original_read=os.read
            changed=False
            def mutate(fd,size):
                nonlocal changed
                data=original_read(fd,size)
                if not changed:
                    changed=True;path.write_bytes(raw+b"# changed\n")
                return data
            with mock.patch.object(Q.os,"read",side_effect=mutate):
                with self.assertRaisesRegex(ValueError,"shared_reader_changed_during_read"):
                    Q._load_pinned_input_reader(path,Q.sha(raw))

    def test_compiles_verified_bytes_once_even_if_path_replaced_after_read(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"reader.py";raw=b"value = 7\n";path.write_bytes(raw)
            original=Q._read_pinned_source
            def replace_after_verified(candidate,expected):
                verified=original(candidate,expected)
                candidate.write_bytes(b"raise AssertionError('second read executed')\n")
                return verified
            with mock.patch.object(Q,"_read_pinned_source",side_effect=replace_after_verified),mock.patch.object(Q.os,"open",wraps=os.open) as opened:
                module=Q._load_pinned_input_reader(path,Q.sha(raw))
            self.assertEqual(opened.call_count,1)
            self.assertEqual(module.value,7)
            self.assertEqual(module.__file__,str(path))
            self.assertNotEqual(module.__name__,"__main__")


class UpfContractTest(unittest.TestCase):
    def test_native_whitespace_and_false_boolean_spelling_are_normalized(self):
        raw = fixture_upf()
        value = Q.inspect_upf(raw,pin("Mg",raw))
        self.assertEqual(value["functional"],"PBE")
        self.assertEqual(value["raw_functional"],"SLA  PW   PBX  PBC")
        self.assertEqual(value["valence_electrons"],2)
        self.assertEqual(value["header_cutoffs_ry"],{"wavefunction":80,"charge_density":800})

    def test_soc_other_functionals_identity_and_xml_entities_rejected(self):
        examples = [fixture_upf(has_so="true"),fixture_upf(functional="PBEsol"),fixture_upf(element="Ca"),
                    b'<!DOCTYPE UPF [<!ENTITY x "boom">]>'+fixture_upf(),
                    fixture_upf().replace(b'z_valence="2.0D+0"',b'z_valence="NaN"')]
        for raw in examples:
            with self.subTest(raw=raw[:30]), self.assertRaises(Q.inputs.BatchError):
                Q.inspect_upf(raw,pin("Mg",raw))

    def test_changed_bytes_rejected_even_if_header_still_valid(self):
        raw = fixture_upf()
        with self.assertRaises(Q.inputs.BatchError):
            Q.inspect_upf(raw+b"\n",pin("Mg",raw))

    def test_safe_number_round_trips_without_source_coordinate_idealization(self):
        for value in [0.16665,0.33335,1e-16,7.029219999999999]:
            self.assertEqual(float(Q.num(value)),value)
        self.assertNotEqual(float(Q.num(0.16665)),1/6)


class PreparedDeckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("SCLIB_GEMMI_RUNTIME"):
            sys.path.insert(0,os.environ["SCLIB_GEMMI_RUNTIME"])
        try:
            import gemmi
        except ImportError:
            raise unittest.SkipTest("Existing Gemmi runtime required; no dependencies installed")
        cls.gemmi = gemmi

    def create(self, folder):
        batch=json.loads((ROOT/"docs/data/discovery-research-catalogue/sclib-combined-6e52be02d9dd.json").read_bytes())
        candidate=next(c for c in batch["candidates"] if c["strain_percent"]==0 and len(c["edits"])==1)
        cell=candidate["cell"]
        gcell=self.gemmi.UnitCell(*[cell[k] for k in ["a","b","c","alpha","beta","gamma"]])
        lattice=[list(gcell.orthogonalize(self.gemmi.Fractional(*v))) for v in [[1,0,0],[0,1,0],[0,0,1]]]
        data={"schema_version":"discovery-chgnet-structure-input/1.0.0","state_id":"fixture-state:"+"1"*64,
            "role":"proposal","parent_id":batch["parent_id"],"source_id":"fixture-source:"+"2"*64,
            "source_sha256":batch["source_reference"]["source"]["file_sha256"],"source_snapshot_sha256":"3"*64,
            "structure_sha256":candidate["cif_sha256"],"conditions":dict(Q.inputs.CONDITIONS),
            "lattice_matrix_angstrom":lattice,"species":[a["element"] for a in candidate["atoms"]],
            "fractional_coordinates":[a["fractional"] for a in candidate["atoms"]],
            "occupancy":[1 for _ in candidate["atoms"]],"composition":candidate["composition"],"periodic":True,
            "cell":cell,"original_atom_ids":[a["id"] for a in candidate["atoms"]]}
        bundle=folder/"source";bundle.mkdir()
        cif=candidate["cif"].encode();raw=Q.encoded(data)
        (bundle/"structure.json").write_bytes(raw);(bundle/"model.cif").write_bytes(cif)
        manifest={"schema_version":"discovery-high-throughput-batch/1.0.0","inputs":[{"state_id":data["state_id"],"recipe_id":"retained-fixture",
            "role":data["role"],"path":"structure.json","bytes":len(raw),"sha256":Q.sha(raw),
            "cif":{"path":"model.cif","bytes":len(cif),"sha256":Q.sha(cif)}}]}
        source_raw=Q.encoded(manifest);(bundle/"batch-manifest.json").write_bytes(source_raw)
        settings={"mesh":[4,4,4],"shifts":[0,0,0],"ecutwfc_ry":80,"ecutrho_ry":800,"smearing":"mv",
            "degauss_ry":0.02,"conv_thr_ry":1e-10,"electron_maxstep":200,"mixing_beta":0.3,"max_seconds":900,
            "tot_charge":0,"nspin":1,"masses_amu":{e:{"Mg":24.305,"B":10.81,"C":12.011,"Ca":40.078,"Al":26.9815385}[e] for e in data["composition"]}}
        profile={"schema_version":"discovery-qe-screen-profile/1.0.0","version":"unit-fixture-v1",
            "source_batch_manifest_sha256":Q.sha(source_raw),"jobs":[{"id":"case-one","state_id":data["state_id"],"settings":settings}]}
        profile_path=folder/"profile.json";profile_path.write_bytes(Q.encoded(profile))
        pp=folder/"upfs";pp.mkdir();(pp/"files").mkdir();pins=[]
        for e in sorted(data["composition"]):
            raw=fixture_upf(e);pinning=pin(e,raw);(pp/pinning["path"]).write_bytes(raw);pins.append(pinning)
        pp_path=pp/"upf-manifest.json";pp_path.write_bytes(Q.encoded({"schema_version":"discovery-qe-screen-upfs/1.0.0","functional":"PBE","files":pins}))
        return {"bundle":bundle,"batch_sha":Q.sha(source_raw),"profile_path":profile_path,"profile":profile,
            "upf_path":pp_path,"data":data,"settings":settings}

    def prepare(self, f):
        return Q.prepare(f["bundle"],f["batch_sha"],f["profile_path"],Q.sha(f["profile_path"].read_bytes()),
                         f["upf_path"],Q.sha(f["upf_path"].read_bytes()),self.gemmi)

    def test_native_deck_exact_row_lattice_species_atom_order_and_explicit_units(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));artifacts,plan=self.prepare(f)
            text=artifacts["jobs/case-one/scf.in"].decode()
            lattice=text.split("CELL_PARAMETERS angstrom\n")[1].split("ATOMIC_POSITIONS crystal\n")[0].strip().splitlines()
            self.assertEqual([[float(x) for x in row.split()] for row in lattice],f["data"]["lattice_matrix_angstrom"])
            atoms=text.split("ATOMIC_POSITIONS crystal\n")[1].split("K_POINTS automatic\n")[0].strip().splitlines()
            self.assertEqual([row.split()[0] for row in atoms],f["data"]["species"])
            self.assertEqual([[float(x) for x in row.split()[1:]] for row in atoms],f["data"]["fractional_coordinates"])
            self.assertIn(" tprnfor = .true.,",text);self.assertIn(" tstress = .true.,",text)
            self.assertIn(" disk_io = 'nowf',",text)
            self.assertIn(" nstep = 1,",text);self.assertIn(" nspin = 1,",text)
            self.assertNotIn("input_dft",text);self.assertNotIn("&CELL",text)
            self.assertFalse(plan["authority"]["calculation_executed"])
            self.assertIsNone(plan["assigned_execution_bounds"])
            self.assertEqual(plan["shared_input_reader_sha256"],Q.SHARED_INPUT_READER_SHA256)
            self.assertIsNone(plan["io_policy"]["scratch_limit_bytes"])
            self.assertFalse(plan["io_policy"]["wavefunction_reuse_available"])
            self.assertFalse(plan["io_policy"]["interrupted_restart_available"])
            model=json.loads(artifacts["jobs/case-one/preparation.json"])
            self.assertEqual(model["io_policy"]["disk_io"],"nowf")
            self.assertEqual(model["schema_version"],"discovery-qe-screen-preparation/1.1.0")

    def test_initialization_has_separate_output_prefix_and_never_claims_result(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));artifacts,plan=self.prepare(f)
            execute=artifacts["jobs/case-one/scf.in"].decode();check=artifacts["jobs/case-one/check.in"].decode()
            prefix=lambda text:re.search(r" prefix = '([^']+)'",text)[1]
            self.assertEqual(prefix(check),prefix(execute)+"_check")
            self.assertIn(" nstep = 0,",check);self.assertIn(" outdir = './out-check',",check)
            self.assertIn(" disk_io = 'nowf',",check)
            self.assertFalse(plan["result_contract"]["old_browser_reader_compatible"])
            self.assertIn("JOB DONE alone",str(plan["result_contract"]))

    def test_computational_charge_does_not_overwrite_unknown_source_conditions(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));f["profile"]["jobs"][0]["settings"]["tot_charge"]=1
            f["profile_path"].write_bytes(Q.encoded(f["profile"]))
            artifacts,_=self.prepare(f);m=json.loads(artifacts["jobs/case-one/preparation.json"])
            self.assertEqual(m["source_conditions"],Q.inputs.CONDITIONS)
            self.assertEqual(m["computational_model"]["tot_charge_electrons_removed"],1)
            self.assertEqual(m["expected_valence_electrons"],2*len(f["data"]["species"])-1)
            self.assertIsNone(m["authority"]["rps_score"])

    def test_native_units_do_not_convert_input_ry_to_hartree_or_angstrom_to_bohr(self):
        with tempfile.TemporaryDirectory() as temp:
            artifacts,_=self.prepare(self.create(Path(temp)));text=artifacts["jobs/case-one/scf.in"].decode()
            self.assertIn(" ecutwfc = 80,",text);self.assertIn(" ecutrho = 800,",text)
            self.assertEqual(float(re.search(r" conv_thr = ([^,]+)",text)[1]),1e-10)

    def test_rejects_changed_cif_even_if_inventory_rehashed(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));p=f["bundle"]/"model.cif";old=p.read_text()
            new=re.sub(r"(_cell_length_a )[^\n]+",r"\g<1>99",old).encode();p.write_bytes(new)
            inp=f["bundle"]/"structure.json";data=json.loads(inp.read_bytes());data["structure_sha256"]=Q.sha(new);inp.write_bytes(Q.encoded(data))
            mp=f["bundle"]/"batch-manifest.json";m=json.loads(mp.read_bytes());row=m["inputs"][0]
            row.update(bytes=len(inp.read_bytes()),sha256=Q.sha(inp.read_bytes()));row["cif"].update(bytes=len(new),sha256=Q.sha(new));mp.write_bytes(Q.encoded(m))
            f["batch_sha"]=Q.sha(mp.read_bytes());f["profile"]["source_batch_manifest_sha256"]=f["batch_sha"];f["profile_path"].write_bytes(Q.encoded(f["profile"]))
            with self.assertRaisesRegex(Q.inputs.BatchError,"cif_cell_mismatch"):
                self.prepare(f)

    def test_profile_scope_spin_mass_grid_and_fake_authority_rejected(self):
        for key,value in [("nspin",2),("mesh",[0,4,4]),("masses_amu",{}),("max_seconds",float("inf")),("approved",True)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as temp:
                f=self.create(Path(temp));settings=f["profile"]["jobs"][0]["settings"];settings[key]=value
                # Write non-finite JSON deliberately to exercise the strict decoder.
                f["profile_path"].write_text(json.dumps(f["profile"]))
                with self.assertRaises(Q.inputs.BatchError):self.prepare(f)

    def test_duplicate_state_settings_cannot_pad_numerical_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));second=copy.deepcopy(f["profile"]["jobs"][0]);second["id"]="renamed-duplicate"
            f["profile"]["jobs"].append(second);f["profile_path"].write_bytes(Q.encoded(f["profile"]))
            with self.assertRaisesRegex(Q.inputs.BatchError,"duplicate_state_settings"):self.prepare(f)

    def test_preparation_is_deterministic_and_every_inventory_pin_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));a,_=self.prepare(f);b,_=self.prepare(f);self.assertEqual(a,b)
            inventory=json.loads(a["bundle-manifest.json"])
            for item in inventory["files"]:
                self.assertEqual(Q.sha(a[item["path"]]),item["sha256"])
                self.assertEqual(len(a[item["path"]]),item["bytes"])
            output=Path(temp)/"output";Q.write_new(output,a)
            with self.assertRaises(Q.inputs.BatchError):Q.write_new(output,a)
            self.assertEqual((output/"screen-plan.json").stat().st_mode&0o777,0o600)

    def test_explicit_unchanged_control_role_needs_no_fake_modification(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.create(Path(temp));inp=f["bundle"]/"structure.json";data=json.loads(inp.read_bytes());data["role"]="baseline_control";inp.write_bytes(Q.encoded(data))
            mp=f["bundle"]/"batch-manifest.json";m=json.loads(mp.read_bytes());m["inputs"][0].update(role="baseline_control",bytes=len(inp.read_bytes()),sha256=Q.sha(inp.read_bytes()));mp.write_bytes(Q.encoded(m))
            f["batch_sha"]=Q.sha(mp.read_bytes());f["profile"]["source_batch_manifest_sha256"]=f["batch_sha"];f["profile_path"].write_bytes(Q.encoded(f["profile"]))
            artifacts,plan=self.prepare(f)
            self.assertEqual(plan["jobs"][0]["role"],"baseline_control")
            self.assertNotIn("construction_request",json.loads(artifacts["jobs/case-one/preparation.json"]))


if __name__ == "__main__":
    unittest.main()
