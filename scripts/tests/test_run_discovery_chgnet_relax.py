"""No CHGNet/ASE/model execution; fake optimizer/worker outputs test trust boundaries."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import types
import pytest

S=importlib.util.spec_from_file_location('relax_runner',Path(__file__).resolve().parents[1]/'run_discovery_chgnet_relax.py')
R=importlib.util.module_from_spec(S);S.loader.exec_module(R)


def data():
    return {'schema_version':'discovery-chgnet-structure-input/1.0.0','state_id':'state:test','role':'proposal',
      'parent_id':'parent:test','source_id':'COD:test','source_sha256':'a'*64,'source_snapshot_sha256':'b'*64,
      'structure_sha256':R.B.sha(b'cif\n'),'conditions':dict(R.B.CONDITIONS),
      'lattice_matrix_angstrom':[[2.,0.,0.],[0.,2.,0.],[0.,0.,2.]],'species':['Mg','B'],
      'fractional_coordinates':[[0.,0.,0.],[.5,.5,.5]],'occupancy':[1,1],'composition':{'Mg':1,'B':1},
      'periodic':True,'cell':{'a':2.,'b':2.,'c':2.,'alpha':90.,'beta':90.,'gamma':90.},'original_atom_ids':['a','b']}


def prediction(force=.01,stress=.02):
    p=R.B.normalize_prediction({'e':-5.,'f':[[force,0.,0.],[0.,0.,0.]],'s':[[stress,0.,0.],[0.,0.,0.],[0.,0.,0.]],'m':[0.,0.]},2,8.)
    p['forces']['frame']=p['stress']['frame']='Cartesian frame of final lattice_matrix_angstrom; atom order retained from original input'
    return p


def result(d,context,flag=True,steps=3,force=.01,stress=.02):
    p=prediction(force,stress);review=R.convergence(flag,steps,p)
    return {'schema_version':R.VERSION,'status':'converged' if review['converged'] else 'not_converged',
      'binding':context,'derived_structure':R.make_child(d,d['lattice_matrix_angstrom'],d['fractional_coordinates'],d['species'],d['original_atom_ids']),
      'prediction':p,'convergence':review,'authority':deepcopy(R.AUTHORITY),'compute_wall_seconds':.2,'artifacts':{}}


@pytest.mark.parametrize('flag,steps,force,stress,status',[
 (True,5,.01,.02,'converged'),(True,200,.01,.02,'converged_at_step_limit'),
 (False,200,.01,.02,'not_converged'),(False,4,.01,.02,'not_converged'),
 (True,3,.051,.02,'not_converged'),(True,3,.01,.101,'not_converged'),
 (True,0,.05,.1,'converged')])
def test_convergence_requires_native_flag_and_actual_atomic_force_and_stress(flag,steps,force,stress,status):
    c=R.convergence(flag,steps,prediction(force,stress));assert c['status']==status
    assert c['step_limit_reached']==(steps==200)
    assert c['converged']==(status!='not_converged')


@pytest.mark.parametrize('flag,steps',[(1,2),(None,0),(True,-1),(True,201),(True,2.5)])
def test_native_status_is_not_inferred_from_exit_code_or_frame_count(flag,steps):
    with pytest.raises(R.B.BatchError):R.convergence(flag,steps,prediction())


def test_recording_fire_keeps_native_return_and_real_steps():
    called=[]
    class FakeNative:
        def run(self,*,fmax,steps):
            called.append((fmax,steps));self.nsteps=200;return False
    record={};Fire=R.recording_fire_class(FakeNative,record);f=Fire()
    assert f.run(.005,200) is False and record=={'native_converged':False,'steps':200}
    with pytest.raises(R.B.BatchError,match='single'):f.run(.005,200)
    assert called==[(.005,200)]
    assert R.METHOD['optimizer_fmax_eV_per_angstrom']==.005
    assert R.METHOD['max_force_tolerance_eV_per_angstrom']==.05


def test_child_is_new_exact_artifact_without_source_pressure_assignment():
    d=data();l=deepcopy(d['lattice_matrix_angstrom']);l[0][0]=2.1
    frac=[[1.05,-.1,0.],[.5,.5,.5]] # Preserve native unwrapped coordinates verbatim.
    x=R.make_child(d,l,frac,d['species'],d['original_atom_ids'])
    assert x['id'].startswith('chgnet-relaxed-child:') and x['parent_state_id']==d['state_id']
    assert x['fractional_coordinates']==frac and x['lattice_matrix_angstrom']==l
    assert all(v is None for v in x['source_conditions'].values())
    assert x['optimization_target']['nominal_external_pressure_gpa']==0
    assert x['source_sha256']==d['source_sha256']
    assert x['id']!=R.make_child(d,d['lattice_matrix_angstrom'],frac,d['species'],d['original_atom_ids'])['id']


@pytest.mark.parametrize('mutate',[
 lambda d:d['species'].reverse(),lambda d:d['original_atom_ids'].reverse(),
 lambda d:d['lattice_matrix_angstrom'][0].__setitem__(0,-2),
 lambda d:d['fractional_coordinates'][0].__setitem__(0,float('nan'))])
def test_changed_order_or_species_or_invalid_structure_rejected(mutate):
    d=data();other=deepcopy(d);mutate(other)
    with pytest.raises(R.B.BatchError):R.make_child(d,other['lattice_matrix_angstrom'],other['fractional_coordinates'],other['species'],other['original_atom_ids'])


def test_final_energy_is_fresh_intensive_and_volume_roundoff_allowed():
    d=data();context=R.binding(d,'d'*64,'e'*64,'f'*64);x=result(d,context)
    x['prediction']['volume']['value']=8.+1e-14
    assert R.validate_result(x,context,d) is True
    assert x['prediction']['energy']['value']==-5. # Two atoms: never divide again.


@pytest.mark.parametrize('mutate',[
 lambda x:x['binding'].update(parent_state_id='sibling'),
 lambda x:x['prediction']['energy'].update(unit='eV/cell'),
 lambda x:x['prediction']['energy'].update(normalization='divided_by_atoms'),
 lambda x:x['prediction']['volume'].update(value=12.),
 lambda x:x['convergence'].update(converged=True),
 lambda x:x.update(status='converged'),
 lambda x:x['derived_structure']['source_conditions'].update(pressure_gpa=0),
 lambda x:x['derived_structure'].update(id='copied-parent'),
 lambda x:x['authority'].update(formation_energy_calculated=True),
 lambda x:x.update(Tc=300.)])
def test_mutated_semantic_result_is_not_accepted(mutate):
    d=data();context=R.binding(d,'d'*64,'e'*64,'f'*64);x=result(d,deepcopy(context),False)
    mutate(x)
    with pytest.raises(R.B.BatchError):R.validate_result(x,context,d)


def selection(ids):return {'schema_version':'discovery-chgnet-relax-selection/1.0.0','source_manifest_sha256':R.MANIFEST_SHA,'state_ids':ids}


@pytest.mark.parametrize('ids',[[],['a','a'],['unknown'],list(map(str,range(13))),[None]])
def test_selection_cannot_duplicate_expand_or_introduce_state(ids):
    with pytest.raises(R.B.BatchError):R.selected_ids(selection(ids),R.MANIFEST_SHA,['a']+list(map(str,range(20))))


def test_selection_keeps_explicit_requested_order_and_requires_original_pin():
    assert R.selected_ids(selection(['b','a']),R.MANIFEST_SHA,['a','b'])==['b','a']
    d=selection(['a']);d['source_manifest_sha256']='0'*64
    with pytest.raises(R.B.BatchError):R.selected_ids(d,R.MANIFEST_SHA,['a'])


def test_trajectory_frame_count_does_not_create_convergence_or_normalize_energy():
    o=types.SimpleNamespace(energies=[-12.,-14.,-14.],forces=[[[0,0,0],[0,0,0]]]*3,
       stresses=[[0]*6]*3,magmoms=[[0.,0.]]*3,atom_positions=[[[0,0,0],[1,1,1]]]*3,
       cells=[[[2.,0.,0.],[0.,2.,0.],[0.,0.,2.]]]*3)
    p=R.trajectory_payload(o,2)
    assert p['frames'][-1]['ase_energy_eV_per_cell']==-14. and 'optimizer_steps' not in p
    o.cells.pop()
    with pytest.raises(R.B.BatchError):R.trajectory_payload(o,2)


def test_bootstrap_rejects_changed_source_before_exec(tmp_path,monkeypatch):
    (tmp_path/'run_discovery_chgnet_batch.py').write_text('raise RuntimeError("must not execute")')
    monkeypatch.setattr(R,'__file__',str(tmp_path/'run_discovery_chgnet_relax.py'))
    with pytest.raises(ValueError,match='frozen_batch_hash'):R.load_frozen_batch()


@pytest.fixture
def batch(tmp_path,monkeypatch):
    d=data();records=[]
    for i in range(2):
        x=deepcopy(d);x['state_id']=f'state:{i}'
        records.append({'data':x,'entry':{'recipe_id':f'recipe-{i}'},'input_bytes':R.B.pretty(x),'cif_bytes':b'cif\n'})
    args=types.SimpleNamespace(output=tmp_path/'new-output',runtime_prefix=tmp_path/'not-a-real-runtime')
    runtime={'python':{'path':'bin/python3.12'}}
    monkeypatch.setattr(R.B,'enforce_cgroup',lambda:{'cpu_max':['400000','100000'],'memory_max_bytes':12*2**30})
    monkeypatch.setattr(R.B,'runtime_inventory',lambda *a:(runtime,b'runtime',b'not-loaded'))
    monkeypatch.setattr(R,'verify_method_runtime',lambda *a:None)
    clock=[0.];monkeypatch.setattr(R.time,'monotonic',lambda:clock[0])
    return args,records,clock


def fake_worker(monkeypatch,clock,*,flag=True,steps=3,advance=1.,outcome=None):
    calls=[]
    def execute(argv,*,cwd,stdout,env,deadline):
        calls.append({'argv':argv,'env':env,'deadline':deadline})
        req=R.B.decode((cwd/'request.json').read_bytes());d=R.B.decode((cwd/'input.json').read_bytes())
        x=result(d,req['binding'],flag,steps)
        child_raw=R.B.pretty(x['derived_structure']);trajectory=b'{"test_only":true}\n'
        for name,raw in [('derived-structure.json',child_raw),('trajectory.json',trajectory)]:R.B.write_bytes_new(cwd/name,raw)
        x['artifacts']={'derived_structure':{'path':'derived-structure.json','bytes':len(child_raw),'sha256':R.B.sha(child_raw)},
                        'trajectory':{'path':'trajectory.json','bytes':len(trajectory),'sha256':R.B.sha(trajectory)}}
        R.B.atomic_new(cwd/'result.json',x);clock[0]+=advance
        return outcome if outcome is not None else {'exit_code':0,'timed_out':False,'process_reaped':True}
    monkeypatch.setattr(R.B,'execute_before_deadline',execute)
    return calls


def run_fixture(batch,n=1):
    args,records,_=batch
    return R.run_batch(args,b'original-manifest',b'selection',records[:n],{},b'method',0.)


def test_sequential_jobs_preserve_pins_and_do_not_change_home(batch,monkeypatch):
    args,records,clock=batch;monkeypatch.setenv('HOME','/unchanged-home');calls=fake_worker(monkeypatch,clock)
    assert run_fixture(batch,2)==0
    finished=R.B.decode((args.output/'finished.json').read_bytes())
    assert len(calls)==2 and finished['converged_jobs']==finished['completed_optimizer_jobs']==2
    assert calls[0]['env']['HOME']=='/unchanged-home' and 'PYTHONPATH' not in calls[0]['env']
    assert calls[0]['deadline']==600 and calls[1]['deadline']==601
    assert finished['manifest_sha256']==R.MANIFEST_SHA and finished['method_manifest_sha256']==R.METHOD_FILES_SHA
    assert finished['authority']['scientific_acceptance'] is False and finished['authority']['relaxation_performed'] is True


def test_optimizer_false_is_nonconverged_not_success_despite_exit_zero(batch,monkeypatch):
    args,_,clock=batch;fake_worker(monkeypatch,clock,flag=False,steps=200)
    assert run_fixture(batch)==1
    f=R.B.decode((args.output/'finished.json').read_bytes())
    assert f['converged_jobs']==0 and f['completed_optimizer_jobs']==1 and f['jobs'][0]['status']=='not_converged'


def test_true_convergence_at_step_limit_is_recorded_separately(batch,monkeypatch):
    args,_,clock=batch;fake_worker(monkeypatch,clock,flag=True,steps=200)
    assert run_fixture(batch)==0
    r=R.B.decode((args.output/'jobs/000-recipe-0/result.json').read_bytes())
    assert r['convergence']['status']=='converged_at_step_limit'


@pytest.mark.parametrize('case',['late','timeout','unreaped'])
def test_process_failures_never_admit_leftover_result_and_no_retry(batch,monkeypatch,case):
    args,_,clock=batch
    outcome={'exit_code':-15,'timed_out':True,'process_reaped':True} if case=='timeout' else {'exit_code':None,'timed_out':True,'process_reaped':False} if case=='unreaped' else None
    calls=fake_worker(monkeypatch,clock,advance=601 if case=='late' else 1,outcome=outcome)
    assert run_fixture(batch,2 if case=='unreaped' else 1)==1
    f=R.B.decode((args.output/'finished.json').read_bytes())
    assert len(calls)==1 and f['completed_optimizer_jobs']==f['converged_jobs']==0 and f['jobs'][0]['status']=='failed'
    if case=='unreaped':assert f['unstarted_jobs']==1 and f['stop_reason']=='process_not_reaped'


def test_global_remaining_budget_prevents_worker_start(batch,monkeypatch):
    args,_,clock=batch;clock[0]=3490;calls=fake_worker(monkeypatch,clock)
    assert run_fixture(batch,2)==1 and calls==[]
    assert R.B.decode((args.output/'finished.json').read_bytes())['unstarted_jobs']==2


def test_existing_output_is_never_reused(batch,monkeypatch):
    args,_,clock=batch;args.output.mkdir();(args.output/'retain').write_text('old');calls=fake_worker(monkeypatch,clock)
    with pytest.raises(FileExistsError):run_fixture(batch)
    assert calls==[] and (args.output/'retain').read_text()=='old'


def test_no_execute_does_not_import_model_check_runtime_or_write_output(batch,monkeypatch):
    args,records,_=batch
    monkeypatch.setattr(R,'load_selection',lambda *a:(b'manifest',b'selection',records))
    monkeypatch.setattr(R,'load_method_file',lambda *a:({},b'method'))
    monkeypatch.setattr(R.B,'runtime_inventory',lambda *a:pytest.fail('must not inspect runtime'))
    monkeypatch.setattr(R,'calculate',lambda *a:pytest.fail('must not compute'))
    code=R.main(['--bundle','/not-read','--manifest-sha256',R.MANIFEST_SHA,'--selection','/not-read-selection',
       '--selection-sha256','a'*64,'--runtime-prefix',str(args.runtime_prefix),'--runtime-manifest-sha256',R.RUNTIME_SHA,
       '--checkpoint-sha256',R.CHECKPOINT_SHA,'--method-manifest','/not-read-method','--method-manifest-sha256',R.METHOD_FILES_SHA,
       '--output',str(args.output)])
    assert code==0 and not args.output.exists()


def test_calculate_uses_native_flag_preserves_atom_ids_and_fresh_model_energy(monkeypatch):
    """Exercise calculate wiring with fake native APIs, not fake scientific approval."""
    import importlib.metadata
    import sys
    calls={};prefix=Path('/fake-pinned-runtime')
    def module(name,path):
        m=types.ModuleType(name);m.__file__=str(prefix/'lib/python3.12/site-packages'/path)
        monkeypatch.setitem(sys.modules,name,m);return m
    torch=module('torch','torch/__init__.py')
    for name in ['set_num_threads','set_num_interop_threads','manual_seed','use_deterministic_algorithms']:
        setattr(torch,name,lambda value,key=name:calls.setdefault(key,value))
    def load(f,*,map_location,weights_only):
        assert f.read()==b'not-real-weights' and map_location=='cpu' and weights_only is True
        return {'model':{'test-only':True}}
    torch.load=load
    np=module('numpy','numpy/__init__.py');np.random=types.SimpleNamespace(seed=lambda x:None)
    ase=module('ase','ase/__init__.py');ase.__path__=[]
    filters=module('ase.filters','ase/filters.py');ase.filters=filters
    units=module('ase.units','ase/units.py');units.GPa=.0062415;ase.units=units
    opt=module('ase.optimize','ase/optimize/__init__.py');opt.__path__=[];ase.optimize=opt
    fire=module('ase.optimize.fire','ase/optimize/fire.py');opt.fire=fire
    class NativeFire:
        def __init__(self,atoms,**kwargs):assert kwargs==R.FIRE_KWARGS
        def run(self,*,fmax,steps):assert (fmax,steps)==(.005,200);self.nsteps=200;return False
    fire.FIRE=NativeFire
    class NativeFilter:
        def __init__(self,atoms,**kwargs):calls['filter']=kwargs;self.atoms=atoms
    filters.FrechetCellFilter=NativeFilter
    chg=module('chgnet','chgnet/__init__.py');chg.__path__=[]
    modelpkg=module('chgnet.model','chgnet/model/__init__.py');modelpkg.__path__=[];chg.model=modelpkg
    modelmod=module('chgnet.model.model','chgnet/model/model.py');modelpkg.model=modelmod
    dynamics=module('chgnet.model.dynamics','chgnet/model/dynamics.py');modelpkg.dynamics=dynamics
    class Model:
        is_intensive=True
        @classmethod
        def from_dict(cls,state,**kwargs):
            assert state=={'test-only':True} and kwargs=={'mlp_out_bias':False,'version':'0.3.0'};return cls()
        def to(self,where):assert where=='cpu';return self
        def parameters(self):return [types.SimpleNamespace(device=types.SimpleNamespace(type='cpu'))]
        def eval(self):calls['eval']=True
        def predict_structure(self,structure,*,task):
            assert task=='efsm';calls['fresh_predictions']=calls.get('fresh_predictions',0)+1
            return {'e':-5.,'f':[[.01,0.,0.],[0.,0.,0.]],'s':[[.02,0,0],[0,0,0],[0,0,0]],'m':[0.,0.]}
    modelmod.CHGNet=Model
    pm=module('pymatgen','pymatgen/__init__.py');pm.__path__=[]
    core=module('pymatgen.core','pymatgen/core/__init__.py');pm.core=core
    io=module('pymatgen.io','pymatgen/io/__init__.py');io.__path__=[];pm.io=io
    cif=module('pymatgen.io.cif','pymatgen/io/cif.py');io.cif=cif
    class Matrix(list):
        def tolist(self):return list(self)
    class Lattice:
        def __init__(self,rows):self.matrix=Matrix(rows)
    class Structure:
        volume=8.
        def __init__(self,lattice,species,frac,coords_are_cartesian=False,site_properties=None):
            self.lattice=lattice;self.species=species;self.frac_coords=Matrix(frac);self.site_properties=site_properties
        def __len__(self):return len(self.species)
        def __iter__(self):return iter([types.SimpleNamespace(specie=s) for s in self.species])
    core.Structure=Structure;core.Lattice=Lattice
    class Parser:
        @classmethod
        def from_str(cls,text,**kwargs):assert kwargs=={'occupancy_tolerance':1.,'site_tolerance':1e-8,'frac_tolerance':0};return cls()
        def parse_structures(self,**kwargs):assert kwargs=={'primitive':False,'check_occu':True};return ['independent-parser-output']
    cif.CifParser=Parser
    monkeypatch.setattr(R.B,'match_cif',lambda d,s:calls.update(independent_cif_matched=s))
    class StructOptimizer:
        def __init__(self,model,optimizer_class,**kwargs):
            assert kwargs=={'use_device':'cpu','stress_weight':units.GPa,'on_isolated_atoms':'error'}
            self.optimizer_class=optimizer_class
        def relax(self,structure,**kwargs):
            assert kwargs['assign_magmoms'] is False and kwargs['relax_cell'] is True
            assert kwargs['save_path'] is kwargs['crystal_feas_save_path'] is None
            filt=kwargs['ase_filter'](structure)
            self.optimizer_class(filt,**{k:kwargs[k] for k in R.FIRE_KWARGS}).run(fmax=kwargs['fmax'],steps=kwargs['steps'])
            obs=types.SimpleNamespace(energies=[-12.,-14.,-14.],forces=[[[0,0,0],[0,0,0]]]*3,
              stresses=[[0]*6]*3,magmoms=[[0.,0.]]*3,atom_positions=[[[0,0,0],[1,1,1]]]*3,cells=[data()['lattice_matrix_angstrom']]*3)
            return {'final_structure':structure,'trajectory':obs}
    dynamics.StructOptimizer=StructOptimizer
    runtime={'versions':{name:'test' for name in ['chgnet','torch','pymatgen','ase','numpy']}}
    runtime['versions']['python']=sys.version.split()[0]
    monkeypatch.setattr(importlib.metadata,'version',lambda name:runtime['versions'][name])
    monkeypatch.setattr(sys,'executable',str(prefix/'bin/python3.12'))
    out=R.calculate(data(),b'cif\n',prefix,runtime,b'not-real-weights')
    assert out['prediction']['energy']['value']==-5. and out['trajectory']['frames'][-1]['ase_energy_eV_per_cell']==-14.
    assert out['convergence']['converged'] is False and out['convergence']['optimizer_steps']==200
    assert calls['fresh_predictions']==1 and calls['use_deterministic_algorithms'] is True
    assert calls['filter']['scalar_pressure']==0.0 and calls['filter']['constant_volume'] is False
    assert out['derived_structure']['original_atom_ids']==['a','b']
