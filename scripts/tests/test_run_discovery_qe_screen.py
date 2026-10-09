"""Preparation integrity and fake-executor tests; never launches native QE."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("qe_screen_runner",ROOT/"scripts/run_discovery_qe_screen.py")
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
from scripts.tests import test_prepare_discovery_qe_screen as prep_tests  # noqa: E402
Q=prep_tests.Q


class ScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prep_tests.PreparedDeckTest.setUpClass()

    def setup(self, folder, two_jobs=False):
        folder=folder.resolve()
        fixture=prep_tests.PreparedDeckTest();f=fixture.create(folder)
        if two_jobs:
            second=copy.deepcopy(f["profile"]["jobs"][0]);second["id"]="case-two";second["settings"]["mesh"]=[2,2,2]
            f["profile"]["jobs"].append(second);f["profile_path"].write_bytes(Q.encoded(f["profile"]))
        files,plan=fixture.prepare(f)
        root=folder/"prepared";Q.write_new(root,files)
        request={"schema_version":"discovery-qe-screen-request/1.0.0",
            "prepared":{"bundle_manifest_sha256":R.sha(files["bundle-manifest.json"]),"plan_sha256":R.sha(files["screen-plan.json"])},
            "job_ids":[j["id"] for j in plan["jobs"]],"runtime":{"prefix":str(folder/"runtime"),"version":"7.5",
                "pw":{"path":"bin/pw.x","bytes":8,"sha256":R.PW_SHA},"mpirun":{"path":"bin/mpirun","bytes":8,"sha256":"a"*64}},
            "limits":{"ranks":4,"threads_per_rank":1,"memory_bytes":12*2**30,"job_seconds":1100,"global_seconds":7100,"service_seconds":7200,"minimum_free_disk_bytes":10*2**30},
            "service_name":"sclib-qe-screen-unit-test.service"}
        p=folder/"request.json";p.write_bytes(Q.encoded(request))
        return {"source":root,"files":files,"plan":plan,"request":request,"request_path":p,"output":folder/"execution"}

    def repack(self,f):
        """Repin outer custody to ensure semantic tampering still gets rejected."""
        files=f["files"];plan=json.loads(files["screen-plan.json"])
        for job in plan["jobs"]:
            for key in ["source_structure","source_cif","execution_input","initialization_input"]:
                name=job[key]["path"];job[key]=R.pin(name,files[name])
            name=job["metadata"]["path"];model=json.loads(files[name])
            model["files"]={"source_structure":job["source_structure"],"source_cif":job["source_cif"],"execution":job["execution_input"],"initialization":job["initialization_input"]}
            files[name]=Q.encoded(model);job["metadata"]=R.pin(name,files[name])
        files["screen-plan.json"]=Q.encoded(plan)
        inv=json.loads(files["bundle-manifest.json"]);inv["plan"]=R.pin("screen-plan.json",files["screen-plan.json"])
        inv["files"]=[R.pin(n,b) for n,b in sorted(files.items()) if n!="bundle-manifest.json"]
        files["bundle-manifest.json"]=Q.encoded(inv)
        for n,b in files.items():(f["source"]/n).write_bytes(b)
        f["request"]["prepared"]={"bundle_manifest_sha256":R.sha(files["bundle-manifest.json"]),"plan_sha256":R.sha(files["screen-plan.json"])}
        f["request_path"].write_bytes(Q.encoded(f["request"]))

    def verified(self,f):
        return R.verify_prepared(f["source"],f["request"])

    def launch(self,f,fake,clock=None,start=None):
        files,plan,models=self.verified(f)
        now=R.time.monotonic() if start is None else start
        with mock.patch.object(R,"resources",return_value={"test_enforced":True}), \
             mock.patch.object(R,"runtime_check",side_effect=lambda runtime:{"version":"7.5","pins":runtime}), \
             mock.patch.object(R,"service_limit",return_value={"runtime_max_seconds":7200}), \
             mock.patch.object(R,"disk_guard",return_value=200*2**30), \
             mock.patch.object(R,"execute_before_deadline",side_effect=fake), redirect_stdout(io.StringIO()):
            if clock is not None:
                with mock.patch.object(R.time,"monotonic",side_effect=lambda:clock[0]):
                    return R.run(f["request"],Q.encoded(f["request"]),files,plan,models,f["output"],now)
            return R.run(f["request"],Q.encoded(f["request"]),files,plan,models,f["output"],now)

    def native(self,argv,*,cwd,stdout,env,deadline):
        assert argv[-2]=="-in" and argv[-1] in {"check.in","scf.in"}
        assert argv[1:6]==["--allow-run-as-root","--bind-to","core","-np","4"]
        assert env["OMP_NUM_THREADS"]==env["OPENBLAS_NUM_THREADS"]=="1"
        assert env["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"]=="1" and "LD_PRELOAD" not in env
        assert env.get("HOME")==os.environ.get("HOME")
        metadata=json.loads((cwd/"preparation.json").read_bytes())
        kind="initialization" if argv[-1]=="check.in" else "execution"
        p=cwd/metadata["native_outputs"][kind+"_xml"];p.parent.mkdir();p.write_bytes(b"<fake-native-xml>NOT SCIENTIFIC DATA</fake-native-xml>\n")
        stdout.write(b"FAKE EXECUTOR UNIT TEST ONLY\nJOB DONE\n")
        return {"exit_code":0,"timed_out":False,"process_reaped":True}

    def test_dry_run_validates_every_artifact_no_runtime_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));p=f["request_path"]
            with mock.patch.object(R,"run",side_effect=AssertionError("dry run executed")),redirect_stdout(io.StringIO()) as out:
                rc=R.main(["--bundle",str(f["source"]),"--request",str(p),"--request-sha256",R.sha(p.read_bytes()),"--output",str(f["output"])])
            self.assertEqual(rc,0);self.assertFalse(f["output"].exists())
            self.assertEqual(json.loads(out.getvalue())["prepared_files"],len(f["files"]))
            self.assertFalse(json.loads(out.getvalue())["runtime_checked"])

    def test_corrupt_even_unused_source_upf_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));name=next(n for n in f["files"] if n.startswith("source-upfs/files/"))
            (f["source"]/name).write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"file_(size|hash)_mismatch"):self.verified(f)

    def test_symlink_prepared_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));p=f["source"]/"profile.json";sibling=Path(temp)/"sibling.json";sibling.write_bytes(p.read_bytes());p.unlink();p.symlink_to(sibling)
            with self.assertRaisesRegex(ValueError,"file_unavailable_or_unsafe"):self.verified(f)

    def test_rebound_native_deck_changed_method_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));name="jobs/case-one/scf.in"
            f["files"][name]=f["files"][name].replace(b" nspin = 1,",b" nspin = 2,");self.repack(f)
            with self.assertRaisesRegex(ValueError,"native_deck_not_prepared_model"):self.verified(f)

    def test_rebound_source_condition_and_metadata_geometry_rejected(self):
        for kind in ["pressure","cell"]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                f=self.setup(Path(temp));name="jobs/case-one/preparation.json";m=json.loads(f["files"][name])
                if kind=="pressure":m["source_conditions"]["pressure_gpa"]=0
                else:m["lattice_matrix_angstrom"][0][0]+=0.1
                f["files"][name]=Q.encoded(m);self.repack(f)
                with self.assertRaisesRegex(ValueError,"model_scope|metadata_source_mismatch"):self.verified(f)

    def test_rebound_sibling_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));plan=json.loads(f["files"]["screen-plan.json"])
            plan["jobs"][0]["source_cif"]["path"]="profile.json";f["files"]["screen-plan.json"]=Q.encoded(plan);self.repack(f)
            with self.assertRaisesRegex(ValueError,"job_sibling_path"):self.verified(f)

    def test_preparer_and_shared_reader_pins_cannot_be_rebound(self):
        for key in ["preparer_sha256","shared_input_reader_sha256"]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as temp:
                f=self.setup(Path(temp));plan=json.loads(f["files"]["screen-plan.json"]);plan[key]="0"*64
                f["files"]["screen-plan.json"]=Q.encoded(plan);self.repack(f)
                with self.assertRaisesRegex(ValueError,"plan_provenance_or_scope"):self.verified(f)

    def test_selection_unknown_duplicate_reordering_and_unbounded_request_reject(self):
        for change in ["unknown","duplicate","excessive","disk","rank","authority"]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                f=self.setup(Path(temp));r=f["request"]
                if change=="unknown":r["job_ids"]=["absent"]
                if change=="duplicate":r["job_ids"]=["case-one"]*2
                if change=="excessive":r["limits"]["job_seconds"]=1101
                if change=="disk":r["limits"]["minimum_free_disk_bytes"]=1
                if change=="rank":r["limits"]["ranks"]=8
                if change=="authority":r["scientific_approval"]=True
                f["request_path"].write_bytes(Q.encoded(r))
                with self.assertRaises(ValueError):
                    R.load_request(f["request_path"],R.sha(f["request_path"].read_bytes()));self.verified(f)

    def test_two_job_selection_is_exact_subset_in_original_order(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp),two_jobs=True);self.verified(f)
            f["request"]["job_ids"]=["case-two"];self.verified(f)
            f["request"]["job_ids"]=["case-two","case-one"]
            with self.assertRaisesRegex(ValueError,"selection_not_original_order"):self.verified(f)

    def test_unselected_job_is_still_byte_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp),two_jobs=True);f["request"]["job_ids"]=["case-one"]
            (f["source"]/"jobs/case-two/scf.in").write_bytes(b"corrupt unselected sibling")
            with self.assertRaises(ValueError):self.verified(f)

    def test_success_captures_only_files_and_preserves_original_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));self.assertEqual(self.launch(f,self.native),0)
            final=json.loads((f["output"]/"finished.json").read_bytes())
            self.assertEqual(final["status"],"execution_files_captured");self.assertFalse(final["authority"]["electronic_convergence_established"])
            rec=json.loads((f["output"]/final["jobs"][0]["path"]).read_bytes())
            self.assertEqual([s["kind"] for s in rec["steps"]],["initialization","execution"])
            self.assertEqual(rec["source_conditions"],R.I.CONDITIONS)
            for step in rec["steps"]:
                for kind in ["xml","stdout"]:
                    pp=step[kind];raw=(f["output"]/pp["path"]).read_bytes();self.assertEqual(pp,R.pin(pp["path"],raw))
            for name,raw in f["files"].items():
                self.assertEqual((f["source"]/name).read_bytes(),raw)
                self.assertEqual((f["output"]/"prepared"/name).read_bytes(),raw)
            self.assertFalse((f["source"]/"jobs/case-one/out").exists())
            self.assertEqual((f["output"]/"request.json").stat().st_mode&0o777,0o600)

    def test_initializer_failure_prevents_scf_no_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));calls=[]
            def fail(argv,**kw):calls.append(argv);self.native(argv,**kw);return {"exit_code":2,"timed_out":False,"process_reaped":True}
            self.assertEqual(self.launch(f,fail),1);self.assertEqual(len(calls),1)
            r=json.loads((f["output"]/"receipts/case-one.json").read_bytes());self.assertIsNotNone(r["steps"][0]["xml"])

    def test_initializer_cannot_seed_stale_execution_xml(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));calls=[]
            def seed(argv,**kw):
                calls.append(argv);result=self.native(argv,**kw)
                model=json.loads((kw["cwd"]/"preparation.json").read_bytes());p=kw["cwd"]/model["native_outputs"]["execution_xml"]
                p.parent.mkdir();p.write_bytes(b"stale result from wrong process")
                return result
            self.assertEqual(self.launch(f,seed),1);self.assertEqual(len(calls),1)
            final=json.loads((f["output"]/"finished.json").read_bytes());self.assertEqual(final["stop_reason"],"stale_native_output")

    def test_timeout_with_native_files_is_partial_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp),two_jobs=True);calls=[]
            def timeout(argv,**kw):calls.append(argv);self.native(argv,**kw);return {"exit_code":0,"timed_out":True,"process_reaped":True}
            self.assertEqual(self.launch(f,timeout),1);self.assertEqual(len(calls),1)
            final=json.loads((f["output"]/"finished.json").read_bytes());self.assertEqual(final["stop_reason"],"native_timeout_requires_diagnosis")
            self.assertEqual(final["unstarted_jobs"],1)

    def test_native_failure_contents_never_become_a_convergence_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp))
            def unconverged(argv,**kw):
                outcome=self.native(argv,**kw)
                if argv[-1]=="scf.in":
                    kw["stdout"].write(b"convergence NOT achieved; JOB DONE\n")
                    model=json.loads((kw["cwd"]/"preparation.json").read_bytes())
                    (kw["cwd"]/model["native_outputs"]["execution_xml"]).write_bytes(b"<output><convergence_achieved>false</convergence_achieved></output>")
                return outcome
            # This runner reports only file custody. The future native reader
            # must reject electronic convergence from the preserved false flag.
            self.assertEqual(self.launch(f,unconverged),0)
            final=json.loads((f["output"]/"finished.json").read_bytes())
            self.assertEqual(final["status"],"execution_files_captured")
            self.assertFalse(final["authority"]["electronic_convergence_established"])

    def test_post_process_runtime_integrity_failure_stops_with_original_files(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));files,plan,models=self.verified(f)
            checks=[{"pin":"original"},{"pin":"original"},R.I.BatchError("runtime_bytes_changed")]
            with mock.patch.object(R,"resources",return_value={}),mock.patch.object(R,"runtime_check",side_effect=checks), \
                 mock.patch.object(R,"service_limit",return_value={}),mock.patch.object(R,"disk_guard",return_value=2**40), \
                 mock.patch.object(R,"execute_before_deadline",side_effect=self.native),redirect_stdout(io.StringIO()):
                self.assertEqual(R.run(f["request"],Q.encoded(f["request"]),files,plan,models,f["output"],R.time.monotonic()),1)
            rec=json.loads((f["output"]/"receipts/case-one.json").read_bytes())
            self.assertEqual(rec["reason_code"],"runtime_bytes_changed");self.assertIsNotNone(rec["steps"][0]["xml"])

    def test_unreaped_process_stops_without_reading_any_native_output(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp))
            with mock.patch.object(R,"capture",side_effect=AssertionError("must not capture while writer alive")):
                self.assertEqual(self.launch(f,lambda *a,**k:{"exit_code":None,"timed_out":True,"process_reaped":False}),1)
            rec=json.loads((f["output"]/"receipts/case-one.json").read_bytes())
            self.assertIsNone(rec["steps"][0]["stdout"]);self.assertIsNone(rec["steps"][0]["xml"])

    def test_initialization_and_scf_share_deadline_including_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));clock=[10.];deadlines=[]
            def advance(argv,**kw):
                deadlines.append(kw["deadline"]);result=self.native(argv,**kw);clock[0]+=500;return result
            self.assertEqual(self.launch(f,advance,clock,start=10),0)
            self.assertEqual(deadlines,[1110,1110])

    def test_capture_overrun_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));clock=[10.];original=R.capture
            def late(*a,**k):result=original(*a,**k);clock[0]=1111.;return result
            with mock.patch.object(R,"capture",side_effect=late):self.assertEqual(self.launch(f,self.native,clock,start=10),1)
            rec=json.loads((f["output"]/"receipts/case-one.json").read_bytes())
            self.assertTrue(rec["job_deadline_exceeded"]);self.assertEqual(rec["status"],"partial_or_failed")

    def test_global_exhaustion_starts_no_process(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp))
            self.assertEqual(self.launch(f,lambda *a,**k:self.fail("budget exhausted"),clock=[7100.],start=0),1)
            final=json.loads((f["output"]/"finished.json").read_bytes());self.assertEqual(final["unstarted_jobs"],1)

    def test_changed_work_upf_after_process_fails_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp))
            def corrupt(argv,**kw):
                result=self.native(argv,**kw);next((kw["cwd"]/"pseudo").iterdir()).write_bytes(b"corrupt");return result
            self.assertEqual(self.launch(f,corrupt),1)
            rec=json.loads((f["output"]/"receipts/case-one.json").read_bytes())
            self.assertFalse(rec["steps"][0]["source_bytes_unchanged_after"])
            self.assertIsNotNone(rec["steps"][0]["xml"])

    def test_bounded_log_or_unsafe_native_output_cannot_qualify(self):
        for kind in ["large_log","xml_symlink"]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                f=self.setup(Path(temp))
                def invalid(argv,**kw):
                    result=self.native(argv,**kw)
                    if kind=="large_log":kw["stdout"].seek(R.LOG_MAX);kw["stdout"].write(b"X")
                    else:
                        model=json.loads((kw["cwd"]/"preparation.json").read_bytes());p=kw["cwd"]/model["native_outputs"]["initialization_xml"]
                        p.unlink();p.symlink_to(kw["cwd"]/"source-model.cif")
                    return result
                self.assertEqual(self.launch(f,invalid),1)
                rec=json.loads((f["output"]/"receipts/case-one.json").read_bytes());self.assertTrue(rec["steps"][0]["capture_errors"])

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));f["output"].mkdir();(f["output"]/"mine").write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError,"output_must_be_fresh"):self.launch(f,self.native)
            self.assertEqual((f["output"]/"mine").read_bytes(),b"keep")

    def test_runtime_bytes_and_symlinks_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/"bin").mkdir();runtime={"prefix":str(root),"version":"7.5"}
            for key,path in [("pw","bin/pw.x"),("mpirun","bin/mpirun")]:
                raw=b"not executable in test";p=root/path;p.write_bytes(raw);p.chmod(0o700);runtime[key]=R.pin(path,raw)
            self.assertEqual(R.runtime_check(runtime)["binaries"]["pw"],runtime["pw"])
            (root/"bin/pw.x").write_bytes(b"changed")
            with self.assertRaises(ValueError):R.runtime_check(runtime)
            (root/"bin/pw.x").unlink();(root/"bin/pw.x").symlink_to(root/"bin/mpirun")
            with self.assertRaises(ValueError):R.runtime_check(runtime)

    def test_cgroup_and_file_limit_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.setup(Path(temp));request=f["request"]
            def read(path,*a,**kw):
                if str(path)=="/proc/self/cgroup":return "0::/system.slice/"+request["service_name"]+"\n"
                return "400000 100000" if path.name=="cpu.max" else str(12*2**30)
            with mock.patch.object(Path,"read_text",read),mock.patch.object(R.resource,"getrlimit",return_value=(2**30,2**30)):
                self.assertEqual(R.resources(request)["memory_max_bytes"],12*2**30)
            for size in [8*2**20,-1,2*2**30]:
                with mock.patch.object(Path,"read_text",read),mock.patch.object(R.resource,"getrlimit",return_value=(size,size)):
                    with self.assertRaisesRegex(ValueError,"finite_file_limit"):R.resources(request)
            def unlimited(path,*a,**kw):return "max 100000" if path.name=="cpu.max" else read(path)
            with mock.patch.object(Path,"read_text",unlimited),mock.patch.object(R.resource,"getrlimit",return_value=(2**30,2**30)):
                with self.assertRaisesRegex(ValueError,"cgroup_cpu_memory"):R.resources(request)

    def test_service_runtime_property_must_be_actual_7200_seconds(self):
        for text,accepted in [(b"2h\n",True),(b"1h 59min 59s\n",False),(b"infinity\n",False)]:
            with self.subTest(text=text),tempfile.TemporaryDirectory() as temp:
                request={"service_name":"sclib-qe-screen-test.service","limits":{"service_seconds":7200}}
                def fake(argv,**kw):kw["stdout"].write(text);return {"exit_code":0,"timed_out":False,"process_reaped":True}
                with mock.patch.object(R,"execute_before_deadline",side_effect=fake):
                    if accepted:self.assertEqual(R.service_limit(request,Path(temp),{},R.time.monotonic()+60)["runtime_max_seconds"],7200)
                    else:
                        with self.assertRaises(ValueError):R.service_limit(request,Path(temp),{},R.time.monotonic()+60)


class FrozenLifecycleTest(unittest.TestCase):
    def test_actual_reused_c94_lifecycle_shares_budget_and_reaps_group(self):
        clock=[0.];pending=[[(50,0)],["timeout","timeout",(1,-9)]];processes=[];sent=[]
        class Process:
            pid=987654321
            def __init__(self,outcomes):self.outcomes=outcomes;self.timeouts=[]
            def wait(self,timeout):
                self.timeouts.append(timeout);item=self.outcomes.pop(0)
                if item=="timeout":clock[0]+=timeout;raise subprocess.TimeoutExpired("unit fake",timeout)
                elapsed,code=item;clock[0]+=elapsed;return code
        def spawn(*args,**kw):
            self.assertTrue(kw["start_new_session"]);p=Process(pending.pop(0));processes.append(p);return p
        self.assertIs(R.execute_before_deadline,R.I._helpers["execute_before_deadline"])
        with mock.patch.object(subprocess,"Popen",side_effect=spawn),mock.patch.object(os,"killpg",side_effect=lambda pid,sig:sent.append(sig)), \
             mock.patch.object(R.time,"monotonic",side_effect=lambda:clock[0]):
            first=R.execute_before_deadline(["fake-init"],cwd=Path("."),stdout=None,env={},deadline=1100)
            second=R.execute_before_deadline(["fake-scf"],cwd=Path("."),stdout=None,env={},deadline=1100)
        self.assertEqual(first,{"exit_code":0,"timed_out":False,"process_reaped":True})
        self.assertEqual(second,{"exit_code":-9,"timed_out":True,"process_reaped":True})
        self.assertEqual([p.timeouts for p in processes],[[1089],[1039,10,1]])
        self.assertEqual(clock[0],1100);self.assertEqual(sent,[signal.SIGTERM,signal.SIGKILL])

    def test_reused_c94_will_not_start_without_termination_reserve(self):
        with mock.patch.object(subprocess,"Popen",side_effect=AssertionError("must not start")),mock.patch.object(R.time,"monotonic",return_value=100.):
            self.assertIsNone(R.execute_before_deadline(["fake"],cwd=Path("."),stdout=None,env={},deadline=111))


if __name__=="__main__":unittest.main()
