"""Local fake-native tests only: no ASE/CHGNet import, model job or network."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'run_discovery_chgnet_relax_screen.py'
SPEC = importlib.util.spec_from_file_location('relax_screen_tests', SCRIPT)
S = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(S)
PINS = list(S.REVIEWED_MANIFESTS)


def data(state='state:test'):
    return {'schema_version': 'discovery-chgnet-structure-input/1.0.0', 'state_id': state, 'role': 'proposal',
            'parent_id': 'parent:test', 'source_id': 'COD:test', 'source_sha256': 'a' * 64,
            'source_snapshot_sha256': 'b' * 64, 'structure_sha256': S.B.sha(b'cif\n'),
            'conditions': dict(S.B.CONDITIONS), 'lattice_matrix_angstrom': [[2.,0.,0.],[0.,2.,0.],[0.,0.,2.]],
            'species': ['Mg','B'], 'fractional_coordinates': [[0.,0.,0.],[.5,.5,.5]], 'occupancy': [1,1],
            'composition': {'Mg':1,'B':1}, 'periodic': True,
            'cell': {'a':2.,'b':2.,'c':2.,'alpha':90.,'beta':90.,'gamma':90.}, 'original_atom_ids': ['a','b']}


def record(i):
    d = data('state:'+str(i)); raw = S.B.pretty(d); cif = b'cif\n'
    entry = {'state_id':d['state_id'], 'recipe_id':'recipe-'+str(i), 'role':d['role'],
             'path':f'inputs/{i}.json', 'bytes':len(raw), 'sha256':S.B.sha(raw),
             'cif':{'path':f'cifs/{i}.cif', 'bytes':len(cif), 'sha256':S.B.sha(cif)}}
    return {'data':d,'entry':entry,'input_bytes':raw,'cif_bytes':cif}


def selection(ids, pin):
    return {'schema_version':'discovery-chgnet-relax-selection/1.0.0','source_manifest_sha256':pin,'state_ids':ids}


def manifest(count):
    return {'schema_version':'discovery-high-throughput-batch/1.0.0','inputs':[record(i)['entry'] for i in range(count)]}


def result(d, context, flag=True, force=.01, stress=.02):
    p = S.B.normalize_prediction({'e':-5.,'f':[[force,0.,0.],[0.,0.,0.]],
        's':[[stress,0.,0.],[0.,0.,0.],[0.,0.,0.]],'m':[0.,0.]},2,8.)
    p['forces']['frame'] = p['stress']['frame'] = 'Cartesian frame of final lattice_matrix_angstrom; atom order retained from original input'
    c = S.R.convergence(flag, 200 if not flag else 3, p)
    child = S.R.make_child(d, d['lattice_matrix_angstrom'],d['fractional_coordinates'],d['species'],d['original_atom_ids'])
    diag = S.generalized_force_payload([[.001,0.,0.],[0.,0.,0.],[.004,0.,0.],[0.,.003,0.],[0.,0.,0.]], d, child)
    return {'schema_version':S.VERSION,'status':'converged' if c['converged'] else 'not_converged',
            'binding':deepcopy(context),'derived_structure':child,'prediction':p,'convergence':c,
            'generalized_forces':diag,'authority':deepcopy(S.AUTHORITY),'compute_wall_seconds':.2,'artifacts':{}}


class SourceAndSelectorTests(unittest.TestCase):
    def test_pins_method_and_bounds_are_exact(self):
        self.assertEqual(S.REVIEWED_MANIFESTS, {PINS[0]:173, PINS[1]:117})
        self.assertEqual(hashlib.sha256(S.RELAX_BYTES).hexdigest(), S.RELAX_SHA)
        self.assertIs(S.METHOD, S.R.METHOD)
        self.assertEqual((S.JOB_SECONDS,S.GLOBAL_SECONDS,S.R.MAX_STEPS,S.R.OPTIMIZER_FMAX,S.R.FMAX,S.R.STRESS_GPA),
                         (600,3500,200,.005,.05,.1))
        self.assertEqual(len(S.EXCLUDED_STATE_IDS),6)

    def test_manifest_pin_count_and_schema_are_closed(self):
        for pin, count in S.REVIEWED_MANIFESTS.items():
            with self.subTest(pin=pin):
                m=manifest(count); self.assertEqual(len(S.validate_manifest(m,pin)),count)
                for other in [manifest(count-1),{**m,'schema_version':'other'}, {**m,'selection':{}}]:
                    with self.assertRaises(S.B.BatchError): S.validate_manifest(other,pin)
                with self.assertRaises(S.B.BatchError): S.validate_manifest(m,'0'*64)
                m['inputs'][-1]=m['inputs'][0]
                with self.assertRaises(S.B.BatchError): S.validate_manifest(m,pin)

    def test_selection_bounded_and_requested_order_preserved(self):
        known=['state:'+str(i) for i in range(20)]
        for pin in PINS:
            self.assertEqual(S.selected_ids(selection(known[:12][::-1],pin),pin,known),known[:12][::-1])
            for ids in [[],known[:13],[known[0],known[0]],['sibling'],[None]]:
                with self.subTest(ids=ids), self.assertRaises(S.B.BatchError):
                    S.selected_ids(selection(ids,pin),pin,known)
            with self.assertRaises(S.B.BatchError): S.selected_ids(selection(known[:1],PINS[1]),PINS[0],known)

    def test_old_six_attempts_cannot_be_accidentally_retried(self):
        for state in S.EXCLUDED_STATE_IDS:
            with self.subTest(state=state), self.assertRaisesRegex(S.B.BatchError,'not_authorized_for_retry'):
                S.selected_ids(selection([state],PINS[0]),PINS[0],[state])

    def test_load_selection_verifies_full_records_then_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'selection.json'
            for pin,count in S.REVIEWED_MANIFESTS.items():
                raw=S.B.pretty(selection(['state:7','state:2'],pin)); p.write_bytes(raw)
                rows=[record(i) for i in range(count)]
                with patch.object(S.B,'load_bundle',return_value=(manifest(count),b'full-source',rows)) as load:
                    full, selected, records=S.load_selection(Path(tmp),pin,p,S.B.sha(raw))
                    self.assertEqual([r['data']['state_id'] for r in records],['state:7','state:2'])
                    self.assertEqual((full,selected),(b'full-source',raw)); load.assert_called_once_with(Path(tmp),pin)
                p.write_bytes(raw+b' ')
                with patch.object(S.B,'load_bundle',return_value=(manifest(count),b'full-source',rows)):
                    with self.assertRaises(S.B.BatchError): S.load_selection(Path(tmp),pin,p,S.B.sha(raw))

    def test_worker_closes_exact_source_count_role_and_input_bytes(self):
        for pin,count in S.REVIEWED_MANIFESTS.items():
            r=record(3); m=manifest(count); chosen=selection([r['data']['state_id']],pin)
            S.verify_worker_selection(m,pin,chosen,r['data'],r['input_bytes'],r['cif_bytes'])
            for mutate in [lambda x:x['inputs'][3].update(sha256='0'*64),
                           lambda x:x['inputs'][3].update(bytes=1),
                           lambda x:x['inputs'][3]['cif'].update(sha256='0'*64),
                           lambda x:x['inputs'][3].update(role='baseline_control')]:
                changed=deepcopy(m); mutate(changed)
                with self.assertRaises(S.B.BatchError):
                    S.verify_worker_selection(changed,pin,chosen,r['data'],r['input_bytes'],r['cif_bytes'])
            with self.assertRaises(S.B.BatchError):
                S.verify_worker_selection(m,pin,selection(['state:4'],pin),r['data'],r['input_bytes'],r['cif_bytes'])

    def test_binding_dynamic_manifest_and_no_source_pressure_inheritance(self):
        contexts=[S.binding(data(),'1'*64,'2'*64,'3'*64,pin) for pin in PINS]
        self.assertNotEqual(contexts[0],contexts[1])
        for c,pin in zip(contexts,PINS):
            self.assertEqual(c['batch_manifest_sha256'],pin)
            self.assertEqual(c['source_manifest_input_count'],S.REVIEWED_MANIFESTS[pin])
            self.assertTrue(all(v is None for v in c['conditions'].values()))
            self.assertEqual(c['frozen_relax_adapter_sha256'],S.RELAX_SHA)
        with self.assertRaises(S.B.BatchError): S.binding(data(),'1'*64,'2'*64,'3'*64,'0'*64)

    def test_bootstrap_tamper_and_symlink_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'run_discovery_chgnet_relax.py'; p.write_text('raise RuntimeError("must never execute")')
            with self.assertRaisesRegex(ValueError,'hash_or_change'): S.load_frozen_relax(p)
            link=Path(tmp)/'link.py'; link.symlink_to(SCRIPT.parent/'run_discovery_chgnet_relax.py')
            with self.assertRaises(OSError): S.load_frozen_relax(link)

    def test_bootstrap_compiles_verified_bytes_not_reopened_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['run_discovery_chgnet_relax.py','run_discovery_chgnet_batch.py','run_discovery_qe_pilot.py']:
                (root/name).write_bytes((SCRIPT.parent/name).read_bytes())
            p=root/'run_discovery_chgnet_relax.py'; compile_original=builtins.compile; changed=[]
            def compile_hook(source, filename, mode, *args, **kwargs):
                if filename==str(p):
                    self.assertEqual(S.B.sha(source),S.RELAX_SHA)
                    p.write_text('raise RuntimeError("replacement must not execute")'); changed.append(True)
                return compile_original(source,filename,mode,*args,**kwargs)
            with patch('builtins.compile',side_effect=compile_hook): module,raw=S.load_frozen_relax(p)
            self.assertEqual(changed,[True]); self.assertEqual(module.VERSION,'discovery-chgnet-relaxation/1.0.0')
            self.assertEqual(S.B.sha(raw),S.RELAX_SHA)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.d=data(); self.context=S.binding(self.d,'1'*64,'2'*64,'3'*64,PINS[1])

    def test_native_false_stays_false_despite_tiny_generalized_forces(self):
        x=result(self.d,self.context,False)
        self.assertFalse(S.validate_result(x,self.context,self.d))
        self.assertFalse(x['convergence']['native_optimizer_converged'])
        self.assertEqual(x['status'],'not_converged')
        self.assertEqual(x['prediction']['energy']['value'],-5.)
        self.assertEqual(x['prediction']['energy']['unit'],'eV/atom')

    def test_native_true_still_requires_fresh_atomic_and_stress_thresholds(self):
        for force,stress in [(.051,.01),(.01,.101)]:
            x=result(self.d,self.context,True,force,stress)
            self.assertFalse(S.validate_result(x,self.context,self.d))
        self.assertTrue(S.validate_result(result(self.d,self.context),self.context,self.d))

    def test_blocks_are_observed_values_with_distinct_coordinate_units(self):
        x=result(self.d,self.context); d=x['generalized_forces']
        self.assertEqual(len(d['atomic']['values']),2); self.assertEqual(len(d['cell']['values']),3)
        self.assertEqual(d['cell']['max_row_norm'],.004)
        self.assertNotEqual(d['cell']['unit'],'GPa'); self.assertIn('dimensionless',d['cell']['unit'])
        self.assertEqual(d['atomic']['atom_ids'],['a','b'])
        self.assertEqual(d['final_structure_id'],x['derived_structure']['id'])
        self.assertNotIn('limiting_term',d)
        self.assertNotIn('tc',d)

    def test_diagnostic_and_scientific_tampering_rejected(self):
        mutations=[lambda x:x['generalized_forces']['atomic'].update(unit='GPa'),
                   lambda x:x['generalized_forces']['atomic'].update(atom_ids=['b','a']),
                   lambda x:x['generalized_forces']['cell'].update(max_row_norm=0.),
                   lambda x:x['generalized_forces']['cell']['values'][0].__setitem__(0,float('nan')),
                   lambda x:x['generalized_forces'].update(final_structure_id='sibling'),
                   lambda x:x['generalized_forces'].update(limiting_term='cell'),
                   lambda x:x['generalized_forces'].update(exp_cell_factor=1),
                   lambda x:x['derived_structure']['source_conditions'].update(pressure_gpa=0),
                   lambda x:x['authority'].update(high_potential=True),
                   lambda x:x['binding'].update(batch_manifest_sha256=PINS[0]),
                   lambda x:x.update(tc=300.)]
        for mutate in mutations:
            x=result(self.d,self.context); mutate(x)
            with self.subTest(mutate=mutate), self.assertRaises(S.B.BatchError): S.validate_result(x,self.context,self.d)

    def test_raw_shape_and_norm_overflow_are_rejected(self):
        child=result(self.d,self.context)['derived_structure']
        for values in [[],[[0.,0.,0.]]*4,[[True,0.,0.]]*5,[[float('inf'),0.,0.]]*5,[[1e308,0.,0.]]*5]:
            with self.assertRaises(S.B.BatchError): S.generalized_force_payload(values,self.d,child)

    def test_fire_retains_actual_object_and_native_flag_without_override(self):
        actual=object(); observed={}; holder=[]; calls=[]
        class FakeNative:
            def __init__(self,atoms): self.atoms=atoms
            def run(self,fmax,steps): calls.append((fmax,steps)); self.nsteps=200; return False
        cls=S.retaining_fire_factory(S.R.recording_fire_class,holder)(FakeNative,observed)
        fire=cls(actual); self.assertIs(holder[0],actual)
        self.assertFalse(fire.run(.005,200)); self.assertEqual(observed,{'native_converged':False,'steps':200})
        self.assertEqual(calls,[(.005,200)])
        with self.assertRaises(S.B.BatchError): cls(actual)
        with self.assertRaises(S.B.BatchError): fire.run(.005,200)

    def test_capture_occurs_after_native_return_and_restores_hook(self):
        events=[]; original=S.R.recording_fire_class; obj=object()
        class FakeFire:
            def __init__(self,atoms): self.atoms=atoms
        def fake_native(*args):
            S.R.recording_fire_class(FakeFire,{})(obj)
            events.append('native-return'); return {'derived_structure':{'id':'child'},'convergence':{'native_optimizer_converged':False}}
        def capture(actual,*args):
            self.assertEqual(events,['native-return']); self.assertIs(actual,obj)
            self.assertIs(S.R.recording_fire_class,original); events.append('get-forces'); return {'observed':True}
        with patch.object(S.R,'calculate',side_effect=fake_native), patch.object(S,'capture_generalized_forces',side_effect=capture):
            got=S.calculate(self.d,b'cif',Path('/unused'),{},b'none')
        self.assertEqual(events,['native-return','get-forces']); self.assertFalse(got['convergence']['native_optimizer_converged'])
        self.assertIs(S.R.recording_fire_class,original)
        with patch.object(S.R,'calculate',side_effect=RuntimeError('native-failure')):
            with self.assertRaises(RuntimeError): S.calculate(self.d,b'cif',Path('/unused'),{},b'none')
        self.assertIs(S.R.recording_fire_class,original)

    def test_native_filter_capture_calls_real_interface_once_after_geometry_checks(self):
        # A fake ASE module exercises our adapter without importing a model.
        class Array:
            def __init__(self,value): self.value=value
            def tolist(self): return self.value
        class Frechet:
            pass
        f=Frechet(); calls=[]; child=result(self.d,self.context)['derived_structure']
        f.exp_cell_factor=2; f.hydrostatic_strain=False; f.constant_volume=False; f.scalar_pressure=0.
        f.mask=Array([[1.]*3 for _ in range(3)])
        f._utility=types.SimpleNamespace(orig_cell=Array(self.d['lattice_matrix_angstrom']))
        f.atoms=types.SimpleNamespace(cell=types.SimpleNamespace(array=Array(child['lattice_matrix_angstrom'])),
            get_chemical_symbols=lambda:child['species'],
            get_scaled_positions=lambda wrap:Array(child['fractional_coordinates']))
        observed=[[.01,0.,0.],[0.,0.,0.],[0.,.2,0.],[0.,0.,.3],[.4,0.,0.]]
        def get_forces(): calls.append('native'); return Array(observed)
        f.get_forces=get_forces
        ase=types.ModuleType('ase'); filters=types.ModuleType('ase.filters')
        filters.FrechetCellFilter=Frechet; ase.filters=filters
        with patch.dict('sys.modules',{'ase':ase,'ase.filters':filters}):
            actual=S.capture_generalized_forces(f,self.d,child)
            self.assertEqual(calls,['native'])
            self.assertEqual(actual['atomic']['values']+actual['cell']['values'],observed)
            f.scalar_pressure=1.
            with self.assertRaisesRegex(S.B.BatchError,'parameters_changed'):
                S.capture_generalized_forces(f,self.d,child)
            f.scalar_pressure=0.; f.atoms.get_chemical_symbols=lambda:['B','Mg']
            with self.assertRaisesRegex(S.B.BatchError,'atom_order'):
                S.capture_generalized_forces(f,self.d,child)
            f.atoms.get_chemical_symbols=lambda:child['species']
            f.atoms.get_scaled_positions=lambda wrap:Array([[.01,0.,0.],[.5,.5,.5]])
            with self.assertRaisesRegex(S.B.BatchError,'geometry_mismatch'):
                S.capture_generalized_forces(f,self.d,child)
        self.assertEqual(calls,['native'])


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.clock=[0.]; self.records=[record(0),record(1)]
        self.manifest_raw=S.B.pretty(manifest(117)); self.pin=S.B.sha(self.manifest_raw)
        self.selection_raw=S.B.pretty(selection(['state:0','state:1'],self.pin))
        self.args=types.SimpleNamespace(output=self.root/'fresh',runtime_prefix=self.root/'unused-runtime',manifest_sha256=self.pin)
        self.runtime={'python':{'path':'bin/python3.12'}}; self.calls=[]
        for target,name,value in [(S,'REVIEWED_MANIFESTS',{self.pin:117}),
            (S.B,'enforce_cgroup',lambda:{'cpu_max':['400000','100000'],'memory_max_bytes':12*2**30}),
            (S.B,'runtime_inventory',lambda *a:(self.runtime,b'runtime',b'never loaded')),
            (S,'verify_method_runtime',lambda *a:None), (S.time,'monotonic',lambda:self.clock[0])]:
            p=patch.object(target,name,value); p.start(); self.addCleanup(p.stop)

    def install_worker(self,*,flag=True,advance=1.,outcome=None,corrupt=None):
        def execute(argv,*,cwd,stdout,env,deadline):
            self.calls.append({'argv':argv,'env':env,'deadline':deadline})
            request=S.B.decode((cwd/'request.json').read_bytes()); d=S.B.decode((cwd/'input.json').read_bytes())
            x=result(d,request['binding'],flag)
            child_raw=S.B.pretty(x['derived_structure']); trajectory=b'{"test_only":true}\n'
            for name,raw in [('derived-structure.json',child_raw),('trajectory.json',trajectory)]: S.B.write_bytes_new(cwd/name,raw)
            x['artifacts']={label:{'path':name,'bytes':len(raw),'sha256':S.B.sha(raw)} for label,name,raw in [
                ('derived_structure','derived-structure.json',child_raw),('trajectory','trajectory.json',trajectory)]}
            if corrupt: corrupt(x)
            S.B.atomic_new(cwd/'result.json',x); self.clock[0]+=advance
            return outcome if outcome is not None else {'exit_code':0,'timed_out':False,'process_reaped':True}
        p=patch.object(S.B,'execute_before_deadline',side_effect=execute); p.start(); self.addCleanup(p.stop)

    def run_batch(self,n=2):
        return S.run_batch(self.args,self.manifest_raw,self.selection_raw,self.records[:n],{},b'method',0.)

    def finished(self): return S.B.decode((self.args.output/'finished.json').read_bytes())

    def test_dynamic_manifest_snapshot_pins_and_unchanged_native_method(self):
        self.install_worker()
        with patch.dict(os.environ,{'HOME':'/existing-home'}): self.assertEqual(self.run_batch(),0)
        f=self.finished(); self.assertEqual((f['manifest_sha256'],f['source_manifest_input_count']),(self.pin,117))
        self.assertEqual((f['per_job_seconds'],f['global_seconds'],f['required_service_runtime_max_seconds']),(600,3500,3600))
        self.assertEqual(f['method'],S.R.METHOD); self.assertEqual(f['completed_optimizer_jobs'],2)
        self.assertEqual(S.B.sha((self.args.output/'run_discovery_chgnet_relax.py').read_bytes()),S.RELAX_SHA)
        self.assertEqual(self.calls[0]['env']['HOME'],'/existing-home')
        self.assertNotIn('PYTHONPATH',self.calls[0]['env']); self.assertEqual([c['deadline'] for c in self.calls],[600,601])
        self.assertFalse(f['authority']['tc_calculated']); self.assertIsNone(f['authority']['rank'])

    def test_native_false_is_completed_but_not_converged(self):
        self.install_worker(flag=False); self.assertEqual(self.run_batch(1),1)
        f=self.finished(); self.assertEqual((f['converged_jobs'],f['completed_optimizer_jobs']),(0,1))
        self.assertEqual(f['jobs'][0]['status'],'not_converged')

    def test_timeout_keeps_failure_does_not_admit_stale_result(self):
        self.install_worker(outcome={'exit_code':-15,'timed_out':True,'process_reaped':True})
        self.assertEqual(self.run_batch(1),1); self.assertEqual(self.finished()['completed_optimizer_jobs'],0)

    def test_unreaped_process_stops_without_reading_native_output(self):
        self.install_worker(outcome={'exit_code':None,'timed_out':True,'process_reaped':False})
        self.assertEqual(self.run_batch(),1); f=self.finished()
        self.assertEqual((len(self.calls),f['unstarted_jobs'],f['completed_optimizer_jobs']),(1,1,0))
        self.assertEqual(f['stop_reason'],'process_not_reaped')
        receipt=S.B.decode((self.args.output/f['jobs'][0]['path']).read_bytes())
        self.assertIsNone(receipt['result']); self.assertIsNone(receipt['worker_log'])

    def test_late_result_never_admitted(self):
        self.install_worker(advance=601); self.assertEqual(self.run_batch(1),1)
        self.assertEqual(self.finished()['completed_optimizer_jobs'],0)

    def test_global_deadline_prevents_start(self):
        self.clock[0]=3490; self.install_worker(); self.assertEqual(self.run_batch(),1)
        self.assertEqual(self.calls,[]); self.assertEqual(self.finished()['unstarted_jobs'],2)

    def test_remaining_global_budget_is_shared_with_job(self):
        self.clock[0]=3400; self.install_worker(); self.assertEqual(self.run_batch(1),0)
        self.assertEqual(self.calls[0]['deadline'],3500)

    def test_sibling_binding_and_diagnostic_tamper_fail_closed(self):
        self.install_worker(corrupt=lambda x:x['binding'].update(batch_manifest_sha256='0'*64))
        self.assertEqual(self.run_batch(1),1); self.assertEqual(self.finished()['completed_optimizer_jobs'],0)

    def test_output_cannot_be_reused_and_manifest_cannot_change(self):
        self.args.output.mkdir(); (self.args.output/'retained').write_text('keep')
        self.install_worker()
        with self.assertRaises(FileExistsError): self.run_batch()
        self.assertEqual(self.calls,[]); self.assertEqual((self.args.output/'retained').read_text(),'keep')
        self.args.manifest_sha256='0'*64
        with self.assertRaises(S.B.BatchError): self.run_batch()


if __name__ == '__main__':
    unittest.main()
