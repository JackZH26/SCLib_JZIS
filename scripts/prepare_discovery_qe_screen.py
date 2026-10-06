"""Prepare immutable QE 7.5 fixed-cell SCF inputs; never execute or fetch files.

Inputs are selected from an externally pinned coordinate batch, a closed explicit
numerical profile, and pinned local PBE UPFs. Source conditions stay unknown;
charge and nspin=1 describe a chosen computational approximation only. This is a
new preparation contract, not the old nine-job pilot or browser result format.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import types
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SHARED_INPUT_READER_SHA256 = "93007282b1b2eece5f2b5573bf9b5e0980b4c2d1ae93579abdbe41bfc47d0cf3"


def _read_pinned_source(path, expected):
    """Bootstrap the shared reader from one bounded regular-file descriptor."""
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1024 * 1024:
            raise ValueError("shared_reader_file_type_or_size")
        chunks, remaining = [], before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if signature(before) != signature(after) or len(raw) != before.st_size:
            raise ValueError("shared_reader_changed_during_read")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("shared_reader_hash_mismatch")
        return raw
    except OSError:
        raise ValueError("shared_reader_unavailable_or_unsafe") from None
    finally:
        if fd is not None:
            os.close(fd)


def _load_pinned_input_reader(path, expected=SHARED_INPUT_READER_SHA256):
    raw = _read_pinned_source(path, expected)
    module = types.ModuleType("screen_input_contract")
    module.__file__ = str(path)
    # Compile the exact verified bytes; importlib would reopen a mutable path.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


# Its own lifecycle helper is also loaded from verified bytes. Only byte/schema
# functions are used here; no shared execution API is called.
inputs = _load_pinned_input_reader(ROOT / "scripts/run_discovery_chgnet_batch.py")
require, read_bounded, decode, sha = inputs.require, inputs.read_bounded, inputs.decode, inputs.sha
VERSION = "discovery-qe-screen-preparation/1.1.0"
UPF_MAX = 8 * 1024 * 1024
JOBS_MAX = 96
OUTPUT_BYTES_MAX = 512 * 1024 * 1024
SETTINGS = {"mesh", "shifts", "ecutwfc_ry", "ecutrho_ry", "smearing", "degauss_ry", "conv_thr_ry",
            "electron_maxstep", "mixing_beta", "max_seconds", "tot_charge", "nspin", "masses_amu"}
AUTHORITY = {"status": "prepared_not_executed", "initialization_checked": False, "calculation_executed": False,
             "electronic_convergence_established": False, "basis_sampling_convergence_established": False,
             "pressure_established": False, "stability_validated": False, "tc_calculated": False,
             "carrier_density_calculated": False, "scientific_acceptance": False,
             "formal_scientific_release": False, "rps_score": None, "rank": None, "high_potential": None}
IO_POLICY = {"disk_io": "nowf", "reference_url": "https://www.quantum-espresso.org/Doc/INPUT_PW.html",
             "scope": "QE 7.5 fixed-cell SCF: save XML and charge density at convergence, never save wavefunctions.",
             "wavefunction_reuse_available": False, "interrupted_restart_available": False,
             "future_nscf_scope": "A separate NSCF protocol must explicitly prepare its required wavefunctions; this preparation promises no reusable wavefunctions.",
             "scratch_scope": "nowf reduces persistent output; it does not impose a scratch-space quota and can increase RAM use.",
             "scratch_limit_bytes": None,
             "wall_time_scope": "QE max_seconds is a chosen native control, not an external deadline. A future runner must bound initialization, SCF, termination and capture together."}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def closed(value, fields, reason):
    require(type(value) is dict and set(value) == set(fields), reason)


def safe_name(value):
    return type(value) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value)


def numeric(value, low, high, reason, integer=False):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high
            and (not integer or type(value) is int), reason)
    return value


def num(value):
    """Round-trip the supplied double, without idealizing coordinates or cell."""
    require(inputs.finite(value), "nonfinite_deck_value")
    return "0" if value == 0 else format(value, ".17g")


def read_document(path, expected, maximum=4*1024*1024):
    require(type(expected) is str and inputs.HASH.fullmatch(expected), "external_document_pin_required")
    path = path.absolute()
    raw = read_bounded(path.parent, path.name, expected=expected, maximum=maximum)
    return decode(raw), raw


def upf_number(token, label):
    require(type(token) is str and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?", token.strip()), label)
    value = float(token.strip().replace("D", "e").replace("d", "e"))
    require(math.isfinite(value), label)
    return value


def inspect_upf(raw, pin):
    require(0 < len(raw) <= UPF_MAX and sha(raw) == pin["sha256"] and len(raw) == pin["bytes"], "upf_bytes_mismatch")
    try:
        text = raw.decode("utf-8")
        require(not re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I), "upf_external_declaration")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError):
        raise inputs.BatchError("invalid_upf_xml") from None
    require(root.tag == "UPF" and re.fullmatch(r"2(?:\.\d+)*", root.get("version", "")), "upf2_required")
    headers = [node for node in root if node.tag == "PP_HEADER"]
    require(len(headers) == 1, "one_upf_header_required")
    header = headers[0]
    get = lambda key: header.get(key, "").strip()
    require(get("element") == pin["element"], "upf_element_mismatch")
    functional = " ".join(get("functional").upper().split())
    require(functional in {"PBE", "SLA PW PBX PBC"}, "pbe_upf_required")
    require(get("relativistic").lower() in {"scalar", "no"} and get("has_so").lower() in {"f", "false", ".false."}, "scalar_no_soc_upf_required")
    require(get("pseudo_type").upper() in {"NC", "US", "USPP", "PAW"}
            and get("is_coulomb").lower() in {"f", "false", ".false."}, "supported_pseudopotential_required")
    valence = upf_number(get("z_valence"), "upf_valence")
    numeric(valence, 0.000001, 118, "upf_valence")
    def recommendation(key):
        token = get(key)
        if not token:
            return None
        value = upf_number(token, "upf_cutoff_header")
        return value if value > 0 else None
    filename = Path(pin["path"]).name
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.[Uu][Pp][Ff]", filename), "safe_upf_filename_required")
    return {"element": pin["element"], "filename": filename, "sha256": sha(raw), "bytes": len(raw),
            "functional": "PBE", "raw_functional": get("functional"), "relativistic": get("relativistic"),
            "pseudo_type": get("pseudo_type").upper(), "valence_electrons": valence,
            "header_cutoffs_ry": {"wavefunction": recommendation("wfc_cutoff"), "charge_density": recommendation("rho_cutoff")},
            "provider_claim": {k: pin[k] for k in ["source_url", "license", "license_url", "release"]},
            "provenance_scope": "Provided pinned local manifest and bytes; no network provenance verification or pseudopotential accuracy certification."}


def read_upfs(path, expected):
    document, raw = read_document(path, expected)
    closed(document, {"schema_version", "functional", "files"}, "upf_manifest_fields")
    require(document["schema_version"] == "discovery-qe-screen-upfs/1.0.0" and document["functional"] == "PBE", "upf_manifest_method")
    require(type(document["files"]) is list and 0 < len(document["files"]) <= 32, "upf_manifest_bound")
    result, names = {}, set()
    for item in document["files"]:
        closed(item, {"element", "path", "bytes", "sha256", "source_url", "license", "license_url", "release"}, "upf_pin_fields")
        require(type(item["element"]) is str and re.fullmatch(r"[A-Z][a-z]?", item["element"])
                and item["element"] not in result, "duplicate_or_invalid_upf_element")
        for key in ["source_url", "license_url"]:
            require(type(item[key]) is str and re.fullmatch(r"https://[^\s]{1,500}", item[key]), "upf_provenance_url")
        for key in ["license", "release"]:
            require(type(item[key]) is str and 1 <= len(item[key]) <= 160, "upf_provenance_label")
        contents = inputs.pinned(path.absolute().parent, item, UPF_MAX)
        inspected = inspect_upf(contents, item)
        require(inspected["filename"] not in names, "colliding_upf_filenames")
        names.add(inspected["filename"])
        result[item["element"]] = {"metadata": inspected, "raw": contents}
    return result, raw


def validate_settings(settings, data, upfs):
    closed(settings, SETTINGS, "profile_settings_fields")
    for key, low, high in [("mesh",1,64),("shifts",0,1)]:
        require(type(settings[key]) is list and len(settings[key]) == 3, "profile_grid_dimensions")
        for value in settings[key]:
            numeric(value, low, high, "profile_grid_value", integer=True)
    for key, low, high in [("ecutwfc_ry",1,5000),("ecutrho_ry",settings["ecutwfc_ry"],20000),
                           ("degauss_ry",1e-6,1),("conv_thr_ry",1e-14,0.01),("mixing_beta",0.001,1),
                           ("max_seconds",1,86400),("tot_charge",-96,96)]:
        numeric(settings[key],low,high,"profile_numeric_"+key)
    numeric(settings["electron_maxstep"],1,2000,"profile_electron_steps",integer=True)
    require(type(settings["nspin"]) is int and settings["nspin"] == 1, "screen_nspin1_only")
    require(settings["smearing"] in {"mv","gaussian","fd"}, "screen_smearing")
    elements = set(data["species"])
    require(1 <= len(elements) <= 8, "per_state_species_bound")
    require(type(settings["masses_amu"]) is dict and set(settings["masses_amu"]) == elements, "explicit_species_masses_required")
    require(elements <= set(upfs), "missing_selected_upf")
    for mass in settings["masses_amu"].values():
        numeric(mass,0.1,500,"species_mass")
    electrons = sum(upfs[e]["metadata"]["valence_electrons"]*count for e,count in data["composition"].items())-settings["tot_charge"]
    require(math.isfinite(electrons) and electrons > 0, "nonpositive_model_electron_count")
    return electrons


def verify_cif(data, raw, gemmi):
    """Independently parse the actual pinned CIF, retaining input atom order."""
    require(sha(raw) == data["structure_sha256"], "source_cif_hash")
    try:
        source = raw.decode("utf-8")
        block = gemmi.cif.read_string(source).sole_block()
        structure = gemmi.make_small_structure_from_block(block)
    except Exception:
        raise inputs.BatchError("invalid_selected_cif") from None
    require("_symmetry_Int_Tables_number 1" in source.splitlines()
            and "_symmetry_space_group_name_H-M 'P 1'" in source.splitlines(), "explicit_p1_source_model_required")
    operations = list(block.find_values("_symmetry_equiv_pos_as_xyz"))
    require(len(operations) == 1 and operations[0].strip("'\"").replace(" ", "") == "x,y,z", "identity_only_explicit_model_required")
    require(len(structure.sites) == len(data["species"]), "cif_atom_count")
    for key, actual in zip(["a","b","c","alpha","beta","gamma"], structure.cell.parameters):
        require(math.isclose(data["cell"][key],actual,rel_tol=1e-10,abs_tol=1e-10), "cif_cell_mismatch")
    remaining = list(structure.sites)
    for element, coordinates in zip(data["species"],data["fractional_coordinates"]):
        matches = [i for i,site in enumerate(remaining) if site.element.name == element and site.occ == 1
                   and all(abs((a-b+0.5)%1-0.5) <= 1e-10 for a,b in zip(site.fract,coordinates))]
        require(len(matches) == 1, "cif_site_mismatch_or_overlap")
        remaining.pop(matches[0])
    require(not remaining, "cif_extra_sites")


def deck(data, settings, pseudopotentials, prefix, initialization=False):
    elements = sorted(data["composition"])
    return "\n".join([
        "! SCLib prepared SCF screen; not executed or scientifically qualified.",
        "! Source state: " + data["state_id"], "! Source model CIF SHA-256: " + data["structure_sha256"],
        "! Physical source pressure, temperature, charge and magnetic state remain unknown.",
        "! Initialization only; no SCF result." if initialization else "! Computational charge/spin/occupation settings are explicit approximations.",
        "&CONTROL", " calculation = 'scf',", " restart_mode = 'from_scratch',",
        f" prefix = '{prefix}{'_check' if initialization else ''}',", " pseudo_dir = './pseudo',",
        f" outdir = './{'out-check' if initialization else 'out'}',", f" nstep = {0 if initialization else 1},",
        " disk_io = 'nowf',",
        f" max_seconds = {num(settings['max_seconds'])},", " tprnfor = .true.,", " tstress = .true.,", "/",
        "&SYSTEM", " ibrav = 0,", f" nat = {len(data['species'])},", f" ntyp = {len(elements)},",
        f" ecutwfc = {num(settings['ecutwfc_ry'])},", f" ecutrho = {num(settings['ecutrho_ry'])},",
        f" tot_charge = {num(settings['tot_charge'])},", " nspin = 1,", " noncolin = .false.,", " lspinorb = .false.,",
        " occupations = 'smearing',", f" smearing = '{settings['smearing']}',", f" degauss = {num(settings['degauss_ry'])},", "/",
        "&ELECTRONS", f" conv_thr = {num(settings['conv_thr_ry'])},", f" electron_maxstep = {settings['electron_maxstep']},",
        f" mixing_beta = {num(settings['mixing_beta'])},", " diagonalization = 'david',", "/",
        "ATOMIC_SPECIES", *[f"{e} {num(settings['masses_amu'][e])} {pseudopotentials[e]['metadata']['filename']}" for e in elements],
        "CELL_PARAMETERS angstrom", *[" ".join(num(x) for x in row) for row in data["lattice_matrix_angstrom"]],
        "ATOMIC_POSITIONS crystal", *[" ".join([e,*[num(x) for x in row]]) for e,row in zip(data["species"],data["fractional_coordinates"])],
        "K_POINTS automatic", " ".join(str(x) for x in settings["mesh"]+settings["shifts"]), ""])


def prepare(bundle, batch_sha, profile_path, profile_sha, upf_path, upf_sha, gemmi):
    manifest, manifest_raw, records = inputs.load_bundle(bundle.absolute(),batch_sha)
    require("selection" not in manifest, "use_original_batch_for_explicit_screen_selection")
    profile, profile_raw = read_document(profile_path,profile_sha)
    closed(profile,{"schema_version","version","source_batch_manifest_sha256","jobs"},"profile_fields")
    require(profile["schema_version"] == "discovery-qe-screen-profile/1.0.0" and safe_name(profile["version"]), "profile_version")
    require(profile["source_batch_manifest_sha256"] == batch_sha, "profile_source_batch_pin")
    jobs = profile["jobs"]
    require(type(jobs) is list and 0 < len(jobs) <= JOBS_MAX, "screen_job_bound")
    upfs, upf_raw = read_upfs(upf_path,upf_sha)
    by_state = {r["data"]["state_id"]:r for r in records}
    ids, computations, per_state, validated = set(),set(),Counter(),set()
    artifacts = {"source-batch-manifest.json":manifest_raw,"profile.json":profile_raw,"source-upfs/upf-manifest.json":upf_raw}
    # Retain the provided manifest in a self-contained source directory. Job UPFs
    # are exact copies, not aliases or symlinks into a mutable external location.
    for item in decode(upf_raw)["files"]:
        artifacts["source-upfs/"+item["path"]] = upfs[item["element"]]["raw"]
    plan_jobs, used_elements = [],set()
    for item in jobs:
        closed(item,{"id","state_id","settings"},"screen_job_fields")
        require(safe_name(item["id"]) and item["id"] not in ids,"duplicate_or_unsafe_job_id")
        require(type(item["state_id"]) is str and item["state_id"] in by_state,"unknown_selected_state")
        ids.add(item["id"]); per_state[item["state_id"]] += 1
        require(per_state[item["state_id"]] <= 16,"per_state_profile_bound")
        record = by_state[item["state_id"]]; data,settings = record["data"],item["settings"]
        electrons = validate_settings(settings,data,upfs)
        if item["state_id"] not in validated:
            verify_cif(data,record["cif_bytes"],gemmi); validated.add(item["state_id"])
        semantic = sha(canonical({"state_id":item["state_id"],"settings":settings}))
        require(semantic not in computations,"duplicate_state_settings")
        computations.add(semantic)
        selected = [upfs[e]["metadata"] for e in sorted(data["composition"])]
        used_elements.update(data["composition"])
        binding = {"schema_version":VERSION,"state_id":data["state_id"],"input_sha256":sha(record["input_bytes"]),
            "cif_sha256":sha(record["cif_bytes"]),"source_batch_manifest_sha256":batch_sha,"profile_sha256":profile_sha,
            "upf_manifest_sha256":upf_sha,"settings":settings,"pseudopotentials":selected,"io_policy":IO_POLICY}
        job_digest = sha(canonical(binding)); prefix = "sclib_screen_"+job_digest[:16]
        directory = "jobs/"+item["id"]
        names = {"execution":directory+"/scf.in","initialization":directory+"/check.in"}
        for kind,initial in [("execution",False),("initialization",True)]:
            artifacts[names[kind]] = deck(data,settings,upfs,prefix,initial).encode("ascii")
        structure_path,cif_path = directory+"/source-structure.json",directory+"/source-model.cif"
        artifacts[structure_path] = record["input_bytes"]
        artifacts[cif_path] = record["cif_bytes"]
        pp_pins = []
        for pseudo in selected:
            path = directory+"/pseudo/"+pseudo["filename"]
            artifacts[path] = upfs[pseudo["element"]]["raw"]
            pp_pins.append({"path":path,"bytes":len(artifacts[path]),"sha256":sha(artifacts[path]),"element":pseudo["element"]})
        warnings = []
        for pseudo in selected:
            for field,setting in [("wavefunction","ecutwfc_ry"),("charge_density","ecutrho_ry")]:
                value = pseudo["header_cutoffs_ry"][field]
                if value is not None and settings[setting] < value:
                    warnings.append(pseudo["element"]+": chosen "+setting+" is below UPF header suggestion; numerical accuracy is unestablished.")
        pins = {kind:{"path":path,"bytes":len(artifacts[path]),"sha256":sha(artifacts[path])} for kind,path in names.items()}
        pins.update({kind:{"path":path,"bytes":len(artifacts[path]),"sha256":sha(artifacts[path])}
                     for kind,path in [("source_structure",structure_path),("source_cif",cif_path)]})
        model = {"id":"qe-screen:"+job_digest, **binding, "role":data["role"], "parent_id":data["parent_id"],
            "source_id":data["source_id"],"source_sha256":data["source_sha256"],"source_snapshot_sha256":data["source_snapshot_sha256"],
            "source_conditions":data["conditions"],"composition":data["composition"],"original_atom_ids":data["original_atom_ids"],
            "species":data["species"],"fractional_coordinates":data["fractional_coordinates"],
            "lattice_matrix_angstrom":data["lattice_matrix_angstrom"],"cell":data["cell"],"occupancy":data["occupancy"],
            "computational_model":{"functional":"PBE from pinned UPFs","calculation":"scf","geometry":"fixed cell and fixed ionic coordinates",
                "tot_charge_electrons_removed":settings["tot_charge"],"nspin":1,"spin_scope":"Chosen spin-unpolarized approximation; not evidence of nonmagnetic order.",
                "charge_scope":"Chosen electron count; nonzero charge uses a periodic compensating background. Not measured carrier density.",
                "occupation_scope":"Numerical smearing is not an experimental temperature.","pressure_scope":"No applied-pressure target or ambient-pressure inference."},
            "expected_valence_electrons":electrons,"electron_count_scope":"UPF valence count minus computational tot_charge; not mobile-carrier density.",
            "engine":{"name":"PWSCF","expected_version":"7.5","expected_xml_format":"QEXSD 25.05.21","binary_sha256":None},
            "native_outputs":{"execution_prefix":prefix,"initialization_prefix":prefix+"_check",
                "execution_xml":"out/"+prefix+".save/data-file-schema.xml",
                "initialization_xml":"out-check/"+prefix+"_check.save/data-file-schema.xml"},
            "files":pins,"pseudopotential_files":pp_pins,"warnings":warnings,"authority":AUTHORITY}
        metadata_path = directory+"/preparation.json";artifacts[metadata_path] = encoded(model)
        plan_jobs.append({"id":item["id"],"preparation_id":model["id"],"state_id":data["state_id"],"role":data["role"],
            "directory":directory,"metadata":{"path":metadata_path,"bytes":len(artifacts[metadata_path]),"sha256":sha(artifacts[metadata_path])},
            "initialization_input":pins["initialization"],"execution_input":pins["execution"],"pseudopotentials":pp_pins,
            "source_structure":pins["source_structure"],"source_cif":pins["source_cif"]})
        require(sum(len(raw) for raw in artifacts.values()) <= OUTPUT_BYTES_MAX, "prepared_bundle_byte_bound")
    plan = {"schema_version":"discovery-qe-screen-plan/1.0.0","version":profile["version"],"status":"prepared_not_executed",
        "preparer_sha256":sha(Path(__file__).read_bytes()),"shared_input_reader_sha256":SHARED_INPUT_READER_SHA256,
        "source_batch_manifest_sha256":batch_sha,"profile_sha256":profile_sha,"upf_manifest_sha256":upf_sha,
        "upf_source_manifest_path":"source-upfs/upf-manifest.json",
        "independent_cif_parser":{"name":"Gemmi","version":gemmi.__version__},"jobs":plan_jobs,
        "counts":{"selected_states":len(per_state),"jobs":len(jobs),"source_batch_states":len(records)},
        "used_upf_elements":sorted(used_elements),"provided_unused_upf_elements":sorted(set(upfs)-used_elements),
        "assigned_execution_bounds":None,"io_policy":IO_POLICY,"authority":AUTHORITY,
        "result_contract":{"status":"screen_native_reader_adapter_required","old_browser_reader_compatible":False,
             "old_nine_job_runner_compatible":False,"reason":"This source-model contract includes unchanged controls and is not a CombinedBatch preparation. Do not forge legacy IDs or feed the old fixed pilot runner.",
             "minimum_future_checks":["Pin runtime, actual execution input, UPFs, stdout and original QEXSD XML.",
                 "Match model cell, atom order, species, method, charge/spin and every numerical setting in native XML.",
                 "Initialization nstep0 is not an SCF result. JOB DONE alone does not establish convergence.",
                 "Require native electronic convergence flag, positive iteration count, SCF error compatible with conv_thr, exit status and stdout/XML energy agreement.",
                 "An electronically converged SCF does not establish basis/mesh, force/stress or physical convergence."]}}
    artifacts["screen-plan.json"] = encoded(plan)
    inventory = {"schema_version":"discovery-qe-screen-bundle/1.0.0","version":profile["version"],
        "plan":{"path":"screen-plan.json","bytes":len(artifacts["screen-plan.json"]),"sha256":sha(artifacts["screen-plan.json"])},
        "files":[{"path":p,"bytes":len(raw),"sha256":sha(raw)} for p,raw in sorted(artifacts.items())],"authority":AUTHORITY}
    artifacts["bundle-manifest.json"] = encoded(inventory)
    require(sum(len(raw) for raw in artifacts.values()) <= OUTPUT_BYTES_MAX, "prepared_bundle_byte_bound")
    return artifacts,plan


def write_new(output, artifacts):
    require(not output.exists(),"output_exists")
    output.mkdir(mode=0o700,parents=False)
    for name,raw in artifacts.items():
        inputs.relative(name)
        path=output/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(raw)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ["bundle","profile","upf-manifest","output","gemmi-runtime"]:
        parser.add_argument("--"+name,type=Path,required=True)
    for name in ["batch-manifest-sha256","profile-sha256","upf-manifest-sha256"]:
        parser.add_argument("--"+name,required=True)
    args=parser.parse_args(argv);os.umask(0o077)
    try:
        require(not args.output.exists(),"output_exists")
        sys.path.insert(0,str(args.gemmi_runtime.resolve()))
        import gemmi
        artifacts,plan=prepare(args.bundle,args.batch_manifest_sha256,args.profile,args.profile_sha256,
                               args.upf_manifest,args.upf_manifest_sha256,gemmi)
        write_new(args.output,artifacts)
        print(json.dumps({"status":"prepared_not_executed","jobs":len(plan["jobs"]),
                          "plan_sha256":sha(artifacts["screen-plan.json"]),"bundle_manifest_sha256":sha(artifacts["bundle-manifest.json"])}))
        return 0
    except Exception as error:
        print(json.dumps({"status":"rejected","reason":str(error) if isinstance(error,inputs.BatchError) else type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
