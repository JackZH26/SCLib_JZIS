"""Capture a bounded QE fixed-cell screen in a fresh private directory.

Dry-run validates prepared bytes and an operational request only. Execution is
opt-in, requires the named externally limited service and pinned runtime, and
never interprets electronic convergence, physical pressure or superconductivity.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
READER_SHA = "93007282b1b2eece5f2b5573bf9b5e0980b4c2d1ae93579abdbe41bfc47d0cf3"
PREPARER_SHA = "2ed40d2f1d96da4ae26d0e0cbed8617a4e298a03b4fe75d18d0f66cc3fed39fe"
PW_SHA = "1d66c7856f5d6b3cd9c66b8578e01512b16bbe907b4360e54234890712ccd6a1"


def _bootstrap():
    """Only bootstrap before the reusable pinned reader is available."""
    path = ROOT / "scripts/run_discovery_chgnet_batch.py"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1024*1024:
            raise ValueError("reader_type_or_size")
        raw = b""
        while len(raw) <= before.st_size:
            block = os.read(fd, min(65536, before.st_size + 1 - len(raw)))
            if not block:
                break
            raw += block
        after = os.fstat(fd)
        sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if sig(before) != sig(after) or len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != READER_SHA:
            raise ValueError("reader_changed_or_hash_mismatch")
        module = types.ModuleType("screen_frozen_reader"); module.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), module.__dict__)
        return module, raw
    finally:
        os.close(fd)


I, READER_BYTES = _bootstrap()
PREPARER_BYTES = I.read_bounded(ROOT / "scripts", "prepare_discovery_qe_screen.py", expected=PREPARER_SHA)
P = types.ModuleType("screen_frozen_preparer")
P.__file__ = str(ROOT / "scripts/prepare_discovery_qe_screen.py")
exec(compile(PREPARER_BYTES, P.__file__, "exec"), P.__dict__)
require, read_bounded, decode, sha = I.require, I.read_bounded, I.decode, I.sha
execute_before_deadline, atomic_new = I.execute_before_deadline, I.atomic_new
RESERVE = I.RESERVE_SECONDS
VERSION = "discovery-qe-screen-execution/1.0.0"
LOG_MAX, XML_MAX = 8*2**20, 16*2**20
AUTHORITY = {"scope": "native_file_capture_only", "electronic_convergence_established": False,
             "basis_sampling_convergence_established": False, "physical_conditions_established": False,
             "scientific_acceptance": False, "formal_scientific_release": False,
             "tc_calculated": False, "carrier_density_calculated": False, "hull_calculated": False,
             "high_potential": None, "rank": None, "rps_score": None, "formal_campaign_budget": None}
MODEL_KEYS = {"authority", "cell", "cif_sha256", "composition", "computational_model", "electron_count_scope", "engine",
              "expected_valence_electrons", "files", "fractional_coordinates", "id", "input_sha256", "io_policy",
              "lattice_matrix_angstrom", "native_outputs", "occupancy", "original_atom_ids", "parent_id", "profile_sha256",
              "pseudopotential_files", "pseudopotentials", "role", "schema_version", "settings", "source_batch_manifest_sha256",
              "source_conditions", "source_id", "source_sha256", "source_snapshot_sha256", "species", "state_id", "upf_manifest_sha256", "warnings"}


def pin(name, raw):
    return {"path": name, "bytes": len(raw), "sha256": sha(raw)}


def closed(value, keys, reason):
    require(type(value) is dict and set(value) == set(keys), reason)


def valid_pin(value):
    closed(value, {"path", "bytes", "sha256"}, "pin_fields")
    I.relative(value["path"])
    require(type(value["bytes"]) is int and 0 < value["bytes"] <= 512*2**20
            and type(value["sha256"]) is str and I.HASH.fullmatch(value["sha256"]), "pin_size_or_hash")


def load_request(path, expected):
    raw = read_bounded(path.absolute().parent, path.name, expected=expected)
    request = decode(raw)
    closed(request, {"schema_version", "prepared", "job_ids", "runtime", "limits", "service_name"}, "request_fields")
    require(request["schema_version"] == "discovery-qe-screen-request/1.0.0", "request_version")
    closed(request["prepared"], {"bundle_manifest_sha256", "plan_sha256"}, "request_prepared_fields")
    require(all(type(h) is str and I.HASH.fullmatch(h) for h in request["prepared"].values()), "request_prepared_pin")
    ids = request["job_ids"]
    require(type(ids) is list and 1 <= len(ids) <= 6 and all(P.safe_name(x) for x in ids) and len(set(ids)) == len(ids), "request_selection")
    require(type(request["service_name"]) is str and re.fullmatch(r"sclib-qe-screen-[a-z0-9-]{1,100}\.service", request["service_name"]), "request_service")
    runtime = request["runtime"]
    closed(runtime, {"prefix", "version", "pw", "mpirun"}, "request_runtime_fields")
    require(type(runtime["prefix"]) is str and runtime["prefix"].startswith("/")
            and str(Path(runtime["prefix"])) == runtime["prefix"] and ".." not in Path(runtime["prefix"]).parts
            and runtime["version"] == "7.5", "request_runtime_identity")
    for name in ["pw", "mpirun"]:
        valid_pin(runtime[name])
    require(runtime["pw"]["path"] == "bin/pw.x" and runtime["pw"]["sha256"] == PW_SHA
            and runtime["mpirun"]["path"] == "bin/mpirun", "request_runtime_binary")
    limits = request["limits"]
    closed(limits, {"ranks", "threads_per_rank", "memory_bytes", "job_seconds", "global_seconds", "service_seconds", "minimum_free_disk_bytes"}, "request_limit_fields")
    require(all(type(v) is int for v in limits.values()) and limits["ranks"] == 4 and limits["threads_per_rank"] == 1
            and limits["memory_bytes"] == 12*2**30 and 60 <= limits["job_seconds"] <= 1100
            and limits["job_seconds"] <= limits["global_seconds"] <= 7100 and limits["service_seconds"] == 7200
            and limits["minimum_free_disk_bytes"] >= 2*2**30, "request_limits")
    return request, raw


def verify_prepared(bundle, request):
    """Read each pinned artifact once; all later validation/copies use these bytes."""
    inventory_raw = read_bounded(bundle, "bundle-manifest.json", expected=request["prepared"]["bundle_manifest_sha256"], maximum=4*2**20)
    inventory = decode(inventory_raw)
    closed(inventory, {"schema_version", "version", "plan", "files", "authority"}, "bundle_fields")
    require(inventory["schema_version"] == "discovery-qe-screen-bundle/1.0.0" and inventory["authority"] == P.AUTHORITY, "bundle_scope")
    rows = inventory["files"]
    require(type(rows) is list and 1 <= len(rows) <= 2048, "bundle_file_bound")
    files = {"bundle-manifest.json": inventory_raw}
    for item in rows:
        valid_pin(item)
        require(item["path"] not in files, "duplicate_prepared_path")
        require(sum(len(x) for x in files.values()) + item["bytes"] <= P.OUTPUT_BYTES_MAX, "bundle_total_bound")
        files[item["path"]] = I.pinned(bundle, item, maximum=32*2**20)
    def checked(item):
        valid_pin(item)
        require(item["path"] in files and pin(item["path"], files[item["path"]]) == item, "internal_pin_mismatch")
        return files[item["path"]]
    require(inventory["plan"]["path"] == "screen-plan.json" and inventory["plan"]["sha256"] == request["prepared"]["plan_sha256"], "plan_request_pin")
    plan = decode(checked(inventory["plan"]))
    closed(plan, {"assigned_execution_bounds", "authority", "counts", "independent_cif_parser", "io_policy", "jobs", "preparer_sha256",
                  "profile_sha256", "provided_unused_upf_elements", "result_contract", "schema_version", "shared_input_reader_sha256",
                  "source_batch_manifest_sha256", "status", "upf_manifest_sha256", "upf_source_manifest_path", "used_upf_elements", "version"}, "plan_fields")
    require(plan.get("schema_version") == "discovery-qe-screen-plan/1.0.0" and plan.get("status") == "prepared_not_executed"
            and plan.get("version") == inventory["version"] and plan.get("preparer_sha256") == PREPARER_SHA
            and plan.get("shared_input_reader_sha256") == READER_SHA and plan.get("authority") == P.AUTHORITY
            and plan.get("assigned_execution_bounds") is None and plan.get("io_policy") == P.IO_POLICY, "plan_provenance_or_scope")
    profile = decode(files["profile.json"]); original = decode(files["source-batch-manifest.json"])
    require(sha(files["profile.json"]) == plan["profile_sha256"] and sha(files["source-batch-manifest.json"]) == plan["source_batch_manifest_sha256"]
            and original.get("schema_version") == "discovery-high-throughput-batch/1.0.0" and "selection" not in original, "original_batch_pin")
    P.closed(profile, {"schema_version", "version", "source_batch_manifest_sha256", "jobs"}, "profile_fields")
    require(profile["schema_version"] == "discovery-qe-screen-profile/1.0.0" and profile["version"] == plan["version"]
            and profile["source_batch_manifest_sha256"] == plan["source_batch_manifest_sha256"], "profile_binding")
    require(type(original.get("inputs")) is list and 1 <= len(original["inputs"]) <= 200, "original_batch_bound")
    upf_path = "source-upfs/upf-manifest.json"
    require(plan["upf_source_manifest_path"] == upf_path and sha(files[upf_path]) == plan["upf_manifest_sha256"], "upf_manifest_binding")
    upf_manifest = decode(files[upf_path]); P.closed(upf_manifest, {"schema_version", "functional", "files"}, "upf_manifest_fields")
    require(upf_manifest["schema_version"] == "discovery-qe-screen-upfs/1.0.0" and upf_manifest["functional"] == "PBE"
            and type(upf_manifest["files"]) is list and 1 <= len(upf_manifest["files"]) <= 32, "upf_manifest_scope")
    upfs, expected_paths = {}, {"bundle-manifest.json", "screen-plan.json", "profile.json", "source-batch-manifest.json", upf_path}
    for item in upf_manifest["files"]:
        P.closed(item, {"element", "path", "bytes", "sha256", "source_url", "license", "license_url", "release"}, "upf_pin_fields")
        name = "source-upfs/" + item["path"]
        raw = checked({"path":name, "bytes":item["bytes"], "sha256":item["sha256"]})
        require(item["element"] not in upfs, "duplicate_upf")
        upfs[item["element"]] = {"raw":raw, "metadata":P.inspect_upf(raw,item)}
        expected_paths.add(name)
    jobs = plan.get("jobs")
    require(type(jobs) is list and 1 <= len(jobs) <= 96 and type(profile["jobs"]) is list and len(jobs) == len(profile["jobs"]), "prepared_job_bound")
    ids, models = [], {}
    for job, spec in zip(jobs, profile["jobs"]):
        closed(job, {"id", "preparation_id", "state_id", "role", "directory", "metadata", "initialization_input", "execution_input", "pseudopotentials", "source_structure", "source_cif"}, "job_fields")
        P.closed(spec, {"id", "state_id", "settings"}, "profile_job_fields")
        require(P.safe_name(job["id"]) and job["id"] not in ids and job["id"] == spec["id"] and job["state_id"] == spec["state_id"]
                and job["directory"] == "jobs/"+job["id"], "job_identity")
        ids.append(job["id"]); directory = job["directory"]
        names = {"metadata":"preparation.json", "initialization_input":"check.in", "execution_input":"scf.in", "source_structure":"source-structure.json", "source_cif":"source-model.cif"}
        for key, basename in names.items():
            require(job[key]["path"] == directory+"/"+basename, "job_sibling_path")
            checked(job[key]); expected_paths.add(job[key]["path"])
        data = I.validate_input(decode(checked(job["source_structure"])))
        require(data["state_id"] == job["state_id"] and data["role"] == job["role"] and data["structure_sha256"] == job["source_cif"]["sha256"], "job_source_identity")
        matches = [r for r in original["inputs"] if r["state_id"] == job["state_id"]]
        require(len(matches) == 1, "original_state_identity")
        source = matches[0]
        require(source["role"] == job["role"] and all(source[k] == job["source_structure"][k] for k in ["bytes", "sha256"])
                and all(source["cif"][k] == job["source_cif"][k] for k in ["bytes", "sha256"]), "original_source_byte_binding")
        settings = spec["settings"]; electrons = P.validate_settings(settings, data, upfs)
        require(settings["tot_charge"] == 0 and settings["nspin"] == 1 and settings["max_seconds"] <= 900, "screen_method_scope")
        require(settings["max_seconds"] + RESERVE < request["limits"]["job_seconds"], "native_time_exceeds_external_job")
        selected = [upfs[e]["metadata"] for e in sorted(data["composition"])]
        binding = {"schema_version":P.VERSION, "state_id":data["state_id"], "input_sha256":job["source_structure"]["sha256"],
                   "cif_sha256":job["source_cif"]["sha256"], "source_batch_manifest_sha256":plan["source_batch_manifest_sha256"],
                   "profile_sha256":plan["profile_sha256"], "upf_manifest_sha256":plan["upf_manifest_sha256"],
                   "settings":settings, "pseudopotentials":selected, "io_policy":P.IO_POLICY}
        digest = sha(P.canonical(binding)); prefix = "sclib_screen_"+digest[:16]
        model = decode(checked(job["metadata"]))
        closed(model, MODEL_KEYS, "model_fields")
        require(job["preparation_id"] == model.get("id") == "qe-screen:"+digest and all(model.get(k) == v for k,v in binding.items()), "model_binding")
        for key in ["role", "parent_id", "source_id", "source_sha256", "source_snapshot_sha256", "composition", "original_atom_ids", "species", "fractional_coordinates", "lattice_matrix_angstrom", "cell", "occupancy"]:
            require(model[key] == data[key], "metadata_source_mismatch")
        require(model["source_conditions"] == I.CONDITIONS and model["authority"] == P.AUTHORITY and model["expected_valence_electrons"] == electrons
                and model["engine"] == {"name":"PWSCF", "expected_version":"7.5", "expected_xml_format":"QEXSD 25.05.21", "binary_sha256":None}, "model_scope")
        computational = model["computational_model"]
        require(computational["calculation"] == "scf" and computational["geometry"] == "fixed cell and fixed ionic coordinates"
                and computational["tot_charge_electrons_removed"] == 0 and computational["nspin"] == 1, "computational_method")
        for kind, initial in [("initialization",True), ("execution",False)]:
            require(checked(job[kind+"_input"]) == P.deck(data, settings, upfs, prefix, initial).encode("ascii"), "native_deck_not_prepared_model")
        expected_native = {"execution_prefix":prefix, "initialization_prefix":prefix+"_check", "execution_xml":"out/"+prefix+".save/data-file-schema.xml",
                           "initialization_xml":"out-check/"+prefix+"_check.save/data-file-schema.xml"}
        require(model["native_outputs"] == expected_native, "native_output_paths")
        expected_pp = []
        for pp in selected:
            name = directory+"/pseudo/"+pp["filename"]
            expected = {**pin(name, upfs[pp["element"]]["raw"]), "element":pp["element"]}
            checked({k:expected[k] for k in ["path", "bytes", "sha256"]}); expected_paths.add(name); expected_pp.append(expected)
        require(job["pseudopotentials"] == expected_pp == model["pseudopotential_files"], "job_upf_binding")
        require(model["files"] == {"execution":job["execution_input"], "initialization":job["initialization_input"], "source_structure":job["source_structure"], "source_cif":job["source_cif"]}, "model_file_binding")
        models[job["id"]] = model
    require(set(files) == expected_paths, "unbound_prepared_artifact")
    require(plan["counts"] == {"selected_states":len({j["state_id"] for j in jobs}), "jobs":len(jobs), "source_batch_states":len(original["inputs"])}, "prepared_counts")
    require(all(x in ids for x in request["job_ids"]) and [x for x in ids if x in request["job_ids"]] == request["job_ids"], "selection_not_original_order")
    return files, plan, models


def runtime_check(runtime):
    prefix = Path(runtime["prefix"])
    pins = {}
    for key in ["pw", "mpirun"]:
        raw = I.pinned(prefix, runtime[key], maximum=512*2**20)
        require(os.access(prefix/runtime[key]["path"], os.X_OK), "runtime_not_executable")
        pins[key] = pin(runtime[key]["path"], raw)
    return {"prefix":str(prefix), "expected_pw_version":"7.5", "binaries":pins}


def resources(request):
    entries = Path("/proc/self/cgroup").read_text().strip().splitlines()
    groups = [line[3:] for line in entries if line.startswith("0::/")]
    require(len(groups) == 1 and groups[0].endswith("/"+request["service_name"]) and ".." not in Path(groups[0]).parts, "named_cgroup_required")
    cg = Path("/sys/fs/cgroup") / groups[0].lstrip("/")
    cpu = (cg/"cpu.max").read_text().split(); memory = (cg/"memory.max").read_text().strip()
    require(len(cpu) == 2 and cpu[0].isdigit() and cpu[1].isdigit() and 0 < int(cpu[0]) <= 4*int(cpu[1])
            and memory.isdigit() and 0 < int(memory) <= request["limits"]["memory_bytes"], "cgroup_cpu_memory")
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    require(128*2**20 <= soft <= hard <= 2**30, "finite_file_limit_128mib_to_1gib_required")
    return {"service_name":request["service_name"], "cpu_max":cpu, "memory_max_bytes":int(memory), "file_size_limit_bytes":[soft,hard]}


def service_limit(request, output, env, deadline):
    name = "service-runtime-max.log"
    with new_log(output/name) as log:
        outcome = execute_before_deadline(["/usr/bin/systemctl", "show", "--property=RuntimeMaxUSec", "--value", request["service_name"]],
                                          cwd=output, stdout=log, env=env, deadline=min(deadline,time.monotonic()+30))
    require(outcome is not None and outcome["process_reaped"] and not outcome["timed_out"] and outcome["exit_code"] == 0, "service_limit_read_failed")
    raw = read_bounded(output, name, maximum=65536)
    value = raw.decode("ascii").strip()
    multipliers = {"h":3600, "min":60, "s":1, "ms":0.001, "us":0.000001}
    tokens = re.findall(r"([0-9]+(?:\.[0-9]+)?)(min|ms|us|h|s)",value)
    require(tokens and "".join(n+u for n,u in tokens) == value.replace(" ", ""), "service_time_format")
    seconds = sum(float(n)*multipliers[u] for n,u in tokens)
    require(seconds == request["limits"]["service_seconds"], "service_wall_bound")
    return {"runtime_max_seconds":seconds, "evidence":pin(name,raw)}


def disk_guard(directory, minimum):
    free = shutil.disk_usage(directory).free
    require(free >= minimum, "insufficient_remaining_disk")
    return free


def write_new(path, raw):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as handle:
        handle.write(raw)


def new_log(path):
    return os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),"wb")


def capture(output, work, relative, destination, maximum, allow_empty=False):
    """Only called after the child has been reaped; hash the same captured bytes."""
    raw = read_bounded(work, relative, maximum=maximum, allow_empty=allow_empty)
    write_new(output/destination,raw)
    return pin(destination,raw)


def checked_work(work, job, files):
    for name, raw in files.items():
        if name.startswith(job["directory"]+"/"):
            read_bounded(work,name[len(job["directory"])+1:],expected=sha(raw),size=len(raw),maximum=32*2**20)


def run(request, request_raw, files, plan, models, output, start):
    limits = resources(request); runtime = runtime_check(request["runtime"])
    require(not output.exists() and not output.is_symlink(), "output_must_be_fresh")
    require(output.parent.resolve(strict=True) == output.parent, "output_parent_must_be_canonical")
    disk_guard(output.parent, request["limits"]["minimum_free_disk_bytes"])
    output.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name, raw in files.items():
        write_new(output/"prepared"/name,raw)
    write_new(output/"request.json",request_raw)
    runner = read_bounded(Path(__file__).parent,Path(__file__).name)
    write_new(output/"runner.py",runner); write_new(output/"prepare_discovery_qe_screen.py",PREPARER_BYTES)
    write_new(output/"run_discovery_chgnet_batch.py",READER_BYTES)
    helper = read_bounded(ROOT/"scripts","run_discovery_qe_pilot.py",expected=I.LIFECYCLE_SHA)
    write_new(output/"run_discovery_qe_pilot.py",helper)
    env = {"PATH":request["runtime"]["prefix"]+"/bin:/usr/bin:/bin", "OMP_NUM_THREADS":"1", "OPENBLAS_NUM_THREADS":"1",
           "MKL_NUM_THREADS":"1", "NUMEXPR_NUM_THREADS":"1", "OMPI_ALLOW_RUN_AS_ROOT":"1", "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM":"1",
           "LC_ALL":"C", "LANG":"C"}
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    deadline_global = start+request["limits"]["global_seconds"]
    common = {"schema_version":VERSION, "started_at_utc":I.stamp(), "runner_sha256":sha(runner), "preparer_sha256":PREPARER_SHA,
              "shared_reader_sha256":READER_SHA, "lifecycle_sha256":I.LIFECYCLE_SHA, "request_sha256":sha(request_raw),
              "prepared":request["prepared"], "runtime":runtime, "enforced_resources":limits, "requested_limits":request["limits"],
              "scope":"Operational execution request; not a formal campaign budget or scientific review.", "authority":AUTHORITY}
    atomic_new(output/"started.json",common)
    receipts, complete, stop_reason = [],[],None
    try:
        service = service_limit(request,output,env,deadline_global)
        atomic_new(output/"runtime-resource-verification.json",{"runtime":runtime,"resources":limits,"service":service})
        selected = [j for j in plan["jobs"] if j["id"] in request["job_ids"]]
        for job in selected:
            if deadline_global-time.monotonic() <= RESERVE:
                stop_reason="global_budget_exhausted"; break
            begun=time.monotonic(); deadline=min(deadline_global,begun+request["limits"]["job_seconds"])
            work=output/"work"/job["id"]; model=models[job["id"]]
            record={"job_id":job["id"],"state_id":job["state_id"],"preparation_id":job["preparation_id"],"role":job["role"],
                    "source_conditions":model["source_conditions"],"steps":[],"status":"partial_or_failed","reason_code":None,
                    "job_started_at_utc":I.stamp(),"available_job_seconds":deadline-begun,"authority":AUTHORITY}
            try:
                record["free_disk_before_bytes"]=disk_guard(output,request["limits"]["minimum_free_disk_bytes"])
                work.mkdir(mode=0o700,parents=True,exist_ok=False)
                for name, raw in files.items():
                    if name.startswith(job["directory"]+"/"):
                        write_new(work/name[len(job["directory"])+1:],raw)
                (work/"out-check").mkdir(mode=0o700);(work/"out").mkdir(mode=0o700)
                for kind in ["initialization","execution"]:
                    if deadline-time.monotonic() <= RESERVE:
                        record["reason_code"]="insufficient_remaining_job_budget";break
                    checked_work(work,job,files);before=runtime_check(request["runtime"])
                    disk_guard(work,request["limits"]["minimum_free_disk_bytes"])
                    native=model["native_outputs"][kind+"_xml"]
                    require(not (work/native).exists() and not (work/native).is_symlink(),"stale_native_output")
                    input_name=Path(job[kind+"_input"]["path"]).name
                    argv=[str(Path(request["runtime"]["prefix"])/request["runtime"]["mpirun"]["path"]),"--allow-run-as-root","--bind-to","core","-np","4",
                          str(Path(request["runtime"]["prefix"])/request["runtime"]["pw"]["path"]),"-in",input_name]
                    log_name=kind+".out";t0=time.monotonic()
                    with new_log(work/log_name) as log:
                        outcome=execute_before_deadline(argv,cwd=work,stdout=log,env=env,deadline=deadline)
                    step={"kind":kind,"process":outcome,"stdout":None,"xml":None,"capture_errors":[],"input":job[kind+"_input"],"argv":argv,
                          "runtime_before":before,"runtime_after":None,"source_bytes_unchanged_after":False,"wall_seconds":time.monotonic()-t0}
                    record["steps"].append(step)
                    if outcome is not None and not outcome["process_reaped"]:
                        record["reason_code"]=stop_reason="process_not_reaped";break
                    # No capture while an unreaped writer may still be changing bytes.
                    for source_name,label,maximum,empty in [(log_name,"stdout",LOG_MAX,True),(native,"xml",XML_MAX,False)]:
                        try:
                            extension="out" if label=="stdout" else "xml"
                            step[label]=capture(output,work,source_name,"captured/"+job["id"]+"/"+kind+"."+extension,maximum,empty)
                        except Exception as error:
                            step["capture_errors"].append({"artifact":label,"reason_code":str(error) if isinstance(error,I.BatchError) else type(error).__name__})
                    step["runtime_after"]=runtime_check(request["runtime"]);checked_work(work,job,files)
                    step["source_bytes_unchanged_after"]=True;step["wall_seconds"]=time.monotonic()-t0
                    if outcome is None:
                        record["reason_code"]="insufficient_remaining_job_budget";break
                    if outcome["timed_out"]:
                        record["reason_code"]=stop_reason="native_timeout_requires_diagnosis";break
                    if outcome["exit_code"] != 0 or step["xml"] is None or step["stdout"] is None:
                        record["reason_code"]="process_or_capture_failed";break
                    if time.monotonic()>deadline:
                        record["reason_code"]="job_deadline_exceeded";break
                if len(record["steps"])==2 and record["reason_code"] is None:
                    record["status"]="execution_files_captured"
            except Exception as error:
                record["reason_code"]=str(error) if isinstance(error,I.BatchError) else type(error).__name__
                # Integrity/resources failures need diagnosis before another calculation.
                stop_reason=record["reason_code"]
            record.update({"job_finished_at_utc":I.stamp(),"job_wall_seconds":time.monotonic()-begun,"job_deadline_exceeded":time.monotonic()>deadline})
            if record["job_deadline_exceeded"]:
                record["status"]="partial_or_failed";record["reason_code"]="job_deadline_exceeded"
            name="receipts/"+job["id"]+".json";write_new(output/name,P.encoded(record))
            receipts.append(pin(name,P.encoded(record)))
            if record["status"]=="execution_files_captured":complete.append(job["id"])
            print(I.json.dumps({"job_id":job["id"],"status":record["status"],"reason_code":record["reason_code"]}),flush=True)
            if stop_reason:break
    except Exception as error:
        stop_reason=str(error) if isinstance(error,I.BatchError) else type(error).__name__
    success=len(complete)==len(request["job_ids"]) and not stop_reason and time.monotonic()<=deadline_global
    atomic_new(output/"finished.json",{**common,"finished_at_utc":I.stamp(),"wall_seconds":time.monotonic()-start,
               "status":"execution_files_captured" if success else "partial_or_failed","jobs":receipts,"jobs_with_complete_execution_files":complete,
               "unstarted_jobs":len(request["job_ids"])-len(receipts),"stop_reason":stop_reason})
    return 0 if success else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ["bundle","request","output"]:parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--request-sha256",required=True);parser.add_argument("--execute",action="store_true")
    args=parser.parse_args(argv);os.umask(0o077);start=time.monotonic()
    try:
        request,raw=load_request(args.request,args.request_sha256)
        files,plan,models=verify_prepared(args.bundle.absolute(),request)
        if not args.execute:
            print(I.json.dumps({"status":"verified_not_executed","prepared_files":len(files),"selected_jobs":len(request["job_ids"]),
                                "request_sha256":sha(raw),"runtime_checked":False,"authority":AUTHORITY}));return 0
        return run(request,raw,files,plan,models,args.output.absolute(),start)
    except Exception as error:
        print(I.json.dumps({"status":"rejected","reason_code":str(error) if isinstance(error,I.BatchError) else type(error).__name__}),flush=True);return 2


if __name__=="__main__":
    sys.exit(main())
