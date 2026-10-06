"""Bounded CHGNet ion/cell relaxation of <=12 pinned states, never scientific admission.

Official API: https://github.com/CederGroupHub/chgnet/blob/v0.4.2/chgnet/model/dynamics.py
ASE 3.29.0: https://pypi.org/project/ase/3.29.0/ (wheel member manifest, no installer).
StructOptimizer returns no convergence flag: a thin FIRE subclass records the
native run() return and nsteps. Final eV/atom comes from a fresh predict_structure,
not ASE's extensive trajectory energy. Nominal zero external optimizer pressure
is distinct from unknown source physical conditions. No execution without flag.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
from pathlib import Path
import stat
import sys
import time
import types

BATCH_SHA = '93007282b1b2eece5f2b5573bf9b5e0980b4c2d1ae93579abdbe41bfc47d0cf3'
MANIFEST_SHA = 'e189c07a064a7c5b850b9a739660f5f821ba2e5108a615e7ba537d1fa7dadb83'
RUNTIME_SHA = '39a9e6f8fd14dbce0ec7d09f8c6c8691d67789509759f9a01c0576f343c8049e'
CHECKPOINT_SHA = 'd14ab7c0f093efe64b60a7bcd540bca10e74fb7f46c86108a079af60524659d1'
METHOD_FILES_SHA = '84efa7269bfb4ccabad6e1338d2085b5f6ca50eb2e1338b857f86938aef212e4'
ASE_WHEEL_SHA = '7b9dd103f007810339c24acfee2f6b677c0c48443b21d3c98e52959246cf4ebf'
VERSION = 'discovery-chgnet-relaxation/1.0.0'
JOB_SECONDS, GLOBAL_SECONDS, MAX_STEPS = 600, 3500, 200
FMAX, STRESS_GPA = 0.05, 0.1
# Cell-filter forces are scaled by atom count. This tighter algorithmic stop
# target improves the chance of reaching the independent stress criterion; it
# does not guarantee it for every volume/geometry or authorize a retry.
OPTIMIZER_FMAX = 0.005


def load_frozen_batch():
    """Minimal bootstrap only; subsequent input/runtime I/O reuses the pinned module."""
    p=Path(__file__).parent/'run_discovery_chgnet_batch.py'
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=1024*1024:
            raise ValueError('frozen_batch_type_or_size')
        chunks=[];remaining=before.st_size+1
        while remaining:
            data=os.read(fd,remaining)
            if not data:break
            chunks.append(data);remaining-=len(data)
        raw=b''.join(chunks);after=os.fstat(fd)
        signature=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
        if signature(before)!=signature(after) or len(raw)!=before.st_size or hashlib.sha256(raw).hexdigest()!=BATCH_SHA:
            raise ValueError('frozen_batch_hash_or_change')
    finally:os.close(fd)
    module=types.ModuleType('frozen_chgnet_batch')
    module.__file__=str(p)
    exec(compile(raw,str(p),'exec'),module.__dict__)
    return module


B=load_frozen_batch()
require=B.require
AUTHORITY={**B.AUTHORITY,'relaxation_performed':True,
           'experimentally_verified':False,'optimization_is_physical_condition':False}
FIRE_KWARGS={'dt':0.1,'maxstep':0.2,'dtmax':1.0,'Nmin':5,'finc':1.1,'fdec':0.5,
             'astart':0.1,'fa':0.99,'a':0.1,'downhill_check':False,
             'restart':None,'trajectory':None,'logfile':None}
METHOD={'name':'CHGNet','package_version':'0.4.2','checkpoint_version':'0.3.0',
        'ase_version':'3.29.0','device':'cpu','threads':4,'operation':'ion_and_cell_relaxation',
        'mlp_out_bias':False,'optimizer':'ASE FIRE','optimizer_parameters':FIRE_KWARGS,
        'filter':'ASE FrechetCellFilter','filter_parameters':{'mask':[1,1,1,1,1,1],
            'hydrostatic_strain':False,'constant_volume':False,'scalar_pressure_eV_per_angstrom3':0.0,
            'exp_cell_factor':'number_of_atoms'},
        'optimization_target':{'nominal_external_pressure_gpa':0.0,
            'scope':'Algorithmic target only; not a source-reported or measured pressure.'},
        'max_steps':MAX_STEPS,'optimizer_fmax_eV_per_angstrom':OPTIMIZER_FMAX,
        'max_force_tolerance_eV_per_angstrom':FMAX,
        'max_absolute_stress_tolerance_GPa':STRESS_GPA,
        'final_prediction':'fresh native predict_structure(task=efsm), no ASE energy normalization',
        'isolated_atoms':'error','random_seed':0,'torch_deterministic_algorithms':True,
        'source_conditions':dict(B.CONDITIONS)}


def load_method_file(path,expected):
    require(expected==METHOD_FILES_SHA,'unsupported_method_manifest_pin')
    raw=B.read_bounded(path.parent,path.name,expected=expected,maximum=B.MAX_MANIFEST)
    value=B.decode(raw)
    require(value['schema_version']=='discovery-chgnet-relax-method-files/1.0.0'
            and value['package']=='ase' and value['version']=='3.29.0'
            and value['official_wheel_sha256']==ASE_WHEEL_SHA,'method_package_identity')
    return value,raw


def verify_method_runtime(prefix,value,runtime):
    require(runtime['versions']['ase']=='3.29.0','ase_runtime_version')
    rows=value['files'];require(type(rows) is list and 1<=len(rows)<=2048,'method_file_bound')
    require(sum(r['bytes'] for r in rows)<=32*1024*1024,'method_total_bound')
    names=set()
    for row in rows:
        require(row['path'].startswith('lib/python3.12/site-packages/ase/') and row['path'].endswith('.py')
                and row['path'] not in names,'method_file_scope')
        names.add(row['path'])
        B.pinned(prefix,row,maximum=B.MAX_RUNTIME_FILE,allow_empty=row['bytes']==0)
    installed=prefix/'lib/python3.12/site-packages/ase'
    actual={str(p.relative_to(prefix)) for p in installed.rglob('*.py') if '__pycache__' not in p.parts}
    require(actual==names,'ase_python_inventory_changed')
    dyn=value['chgnet_struct_optimizer']
    require(dyn in runtime['files'],'struct_optimizer_not_in_runtime_inventory')
    B.pinned(prefix,dyn)


def selected_ids(value,manifest_sha,known_ids):
    require(type(value) is dict and set(value)=={'schema_version','source_manifest_sha256','state_ids'},'relax_selection_fields')
    require(value['schema_version']=='discovery-chgnet-relax-selection/1.0.0'
            and value['source_manifest_sha256']==manifest_sha,'relax_selection_source')
    ids=value['state_ids'];require(type(ids) is list and 1<=len(ids)<=12
            and all(type(x) is str for x in ids) and len(set(ids))==len(ids),'relax_selection_bound_or_duplicates')
    require(all(s in known_ids for s in ids),'relax_selection_unknown_state')
    return ids


def load_selection(bundle,manifest_sha,selection,selection_sha):
    require(manifest_sha==MANIFEST_SHA,'unsupported_original_manifest')
    manifest,raw,records=B.load_bundle(bundle,manifest_sha)
    require(len(records)==173 and 'selection' not in manifest,'full_original_bundle_required')
    selected_raw=B.read_bounded(selection.parent,selection.name,expected=selection_sha)
    by_id={r['data']['state_id']:r for r in records}
    ids=selected_ids(B.decode(selected_raw),manifest_sha,by_id)
    return raw,selected_raw,[by_id[s] for s in ids]


def binding(data,input_sha,selection_sha,script_sha):
    base=B.context(data,input_sha,data['structure_sha256'],MANIFEST_SHA,RUNTIME_SHA,CHECKPOINT_SHA,script_sha)
    return {**base,'method':METHOD,'batch_adapter_sha256':BATCH_SHA,'method_files_sha256':METHOD_FILES_SHA,
            'selection_sha256':selection_sha,'parent_state_id':data['state_id'],
            'parent_structure_sha256':data['structure_sha256'],'authority_scope':'model_geometry_prefilter_only'}


def convergence(native_flag,steps,prediction):
    require(type(native_flag) is bool and type(steps) is int and 0<=steps<=MAX_STEPS,'native_optimizer_status_shape')
    force=prediction['max_force']['value'];stress=max(abs(x) for row in prediction['stress']['values'] for x in row)
    require(B.finite(force) and B.finite(stress),'final_convergence_nonfinite')
    reasons=[]
    if not native_flag:reasons.append('native_optimizer_not_converged')
    if force>FMAX:reasons.append('final_force_above_tolerance')
    if stress>STRESS_GPA:reasons.append('final_stress_above_tolerance')
    passed=not reasons
    return {'native_optimizer_converged':native_flag,'optimizer_steps':steps,'step_limit_reached':steps==MAX_STEPS,
            'force_tolerance_passed':force<=FMAX,'stress_tolerance_passed':stress<=STRESS_GPA,
            'max_force_eV_per_angstrom':force,'max_absolute_stress_GPa':stress,
            'status':'converged_at_step_limit' if passed and steps==MAX_STEPS else 'converged' if passed else 'not_converged',
            'converged':passed,'reason_codes':reasons,
            'scope':'Model optimizer convergence only; no phonon, hull, physical phase or superconductivity conclusion.'}


def recording_fire_class(fire_class,observed):
    class RecordingFIRE(fire_class):
        def run(self,fmax,steps):
            require(not observed,'optimizer_run_must_be_single')
            flag=super().run(fmax=fmax,steps=steps)
            observed.update(native_converged=bool(flag),steps=int(self.nsteps))
            return flag
    return RecordingFIRE


def make_child(data,lattice,frac,species,atom_ids):
    n=len(data['species'])
    require(species==data['species'] and atom_ids==data['original_atom_ids'],'relaxation_atom_order_or_species_changed')
    require(B.matrix(lattice,3,3) and B.determinant(lattice)>1e-8 and B.matrix(frac,n,3),'invalid_final_structure')
    body={'schema_version':'discovery-chgnet-derived-structure/1.0.0','parent_state_id':data['state_id'],
          'parent_input_structure_sha256':data['structure_sha256'],'source_id':data['source_id'],
          'source_sha256':data['source_sha256'],'source_snapshot_sha256':data['source_snapshot_sha256'],
          'lattice_matrix_angstrom':lattice,'fractional_coordinates':frac,'fractional_coordinate_convention':'unwrapped_native',
          'species':species,'original_atom_ids':atom_ids,'occupancy':[1]*n,'composition':data['composition'],
          'periodic':True,'source_conditions':dict(B.CONDITIONS),'optimization_target':METHOD['optimization_target'],
          'optimization_protocol_sha256':B.sha(B.pretty(METHOD)),
          'relationship':'model_relaxed_child_of_exact_source_bound_state; no inherited measured properties'}
    return {'id':'chgnet-relaxed-child:'+B.sha(B.pretty(body)),**body}


def trajectory_payload(observer,n):
    fields=['energies','forces','stresses','magmoms','atom_positions','cells']
    lengths=[len(getattr(observer,k)) for k in fields]
    require(len(set(lengths))==1 and 1<=lengths[0]<=MAX_STEPS+2,'trajectory_shape_or_bound')
    convert=lambda x:x.tolist() if hasattr(x,'tolist') else x
    frames=[]
    for i in range(lengths[0]):
        e=float(observer.energies[i]);f,s,m,positions,cell=[convert(getattr(observer,k)[i]) for k in fields[1:]]
        require(B.finite(e) and B.matrix(f,n,3) and B.matrix(positions,n,3) and B.matrix(cell,3,3)
                and B.determinant(cell)>1e-8 and type(s) is list and len(s)==6 and all(B.finite(x) for x in s)
                and type(m) is list and len(m)==n and all(B.finite(x) for x in m),'trajectory_nonfinite_or_shape')
        frames.append({'observer_frame':i,'ase_energy_eV_per_cell':e,'forces_eV_per_angstrom':f,
                       'ase_stress_eV_per_angstrom3_voigt':s,'site_moment_magnitudes_muB':m,
                       'cartesian_positions_angstrom':positions,'lattice_matrix_angstrom':cell})
    return {'schema_version':'discovery-chgnet-relax-trajectory/1.0.0','frames':frames,
            'note':'Observer includes initial and repeated final frames; its length is not optimizer step count. ASE energies are extensive and are not the reported final eV/atom.'}


def calculate(data,cif,prefix,runtime,checkpoint):
    import importlib.metadata
    import random
    import torch
    import numpy as np
    import ase
    import ase.units
    import ase.filters
    import ase.optimize.fire
    import chgnet.model.dynamics as dynamics
    import chgnet.model.model as model_module
    from pymatgen.core import Lattice,Structure
    from pymatgen.io.cif import CifParser
    for package in ['chgnet','torch','pymatgen','ase','numpy']:
        require(importlib.metadata.version(package)==runtime['versions'][package],'imported_package_version')
    expected={dynamics:'chgnet/model/dynamics.py',model_module:'chgnet/model/model.py',
              ase:'ase/__init__.py',ase.filters:'ase/filters.py',ase.optimize.fire:'ase/optimize/fire.py'}
    for module,path in expected.items():
        require(Path(module.__file__).resolve()==prefix/'lib/python3.12/site-packages'/path,'imported_module_outside_runtime')
    require(Path(torch.__file__).resolve().is_relative_to(prefix) and Path(np.__file__).resolve().is_relative_to(prefix)
            and sys.version.split()[0]==runtime['versions']['python'] and Path(sys.executable).resolve()==prefix/'bin/python3.12','worker_interpreter_or_import')
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.manual_seed(0);np.random.seed(0);random.seed(0);torch.use_deterministic_algorithms(True)
    parsed=CifParser.from_str(cif.decode('utf8'),occupancy_tolerance=1.0,site_tolerance=1e-8,frac_tolerance=0).parse_structures(primitive=False,check_occu=True)
    require(len(parsed)==1,'cif_single_structure_required');B.match_cif(data,parsed[0])
    structure=Structure(Lattice(data['lattice_matrix_angstrom']),data['species'],data['fractional_coordinates'],
                        coords_are_cartesian=False,site_properties={'sclib_atom_id':data['original_atom_ids']})
    state=torch.load(io.BytesIO(checkpoint),map_location='cpu',weights_only=True)
    require(type(state) is dict and 'model' in state,'checkpoint_model_missing')
    model=model_module.CHGNet.from_dict(state['model'],mlp_out_bias=False,version='0.3.0').to('cpu')
    require(model.is_intensive is True and all(p.device.type=='cpu' for p in model.parameters()),'model_intensive_cpu_required')
    model.eval()
    observed={};RecordingFIRE=recording_fire_class(ase.optimize.fire.FIRE,observed)
    class ZeroPressureCellFilter(ase.filters.FrechetCellFilter):
        def __init__(self,atoms):
            super().__init__(atoms,mask=[1,1,1,1,1,1],exp_cell_factor=float(len(atoms)),
                             hydrostatic_strain=False,constant_volume=False,scalar_pressure=0.0)
    optimizer=dynamics.StructOptimizer(model=model,optimizer_class=RecordingFIRE,use_device='cpu',
                                       stress_weight=ase.units.GPa,on_isolated_atoms='error')
    relaxed=optimizer.relax(structure,fmax=OPTIMIZER_FMAX,steps=MAX_STEPS,relax_cell=True,ase_filter=ZeroPressureCellFilter,
                           save_path=None,crystal_feas_save_path=None,loginterval=1,verbose=False,assign_magmoms=False,**FIRE_KWARGS)
    require(set(observed)=={'native_converged','steps'},'native_optimizer_status_missing')
    final=relaxed['final_structure']
    species=[str(site.specie) for site in final]
    child=make_child(data,final.lattice.matrix.tolist(),final.frac_coords.tolist(),species,final.site_properties.get('sclib_atom_id'))
    # Fresh intensive prediction; do not divide TrajectoryObserver's extensive energies.
    prediction=B.normalize_prediction(model.predict_structure(final,task='efsm'),len(species),float(final.volume))
    frame='Cartesian frame of final lattice_matrix_angstrom; atom order retained from original input'
    prediction['forces']['frame']=prediction['stress']['frame']=frame
    review=convergence(observed['native_converged'],observed['steps'],prediction)
    return {'derived_structure':child,'prediction':prediction,'convergence':review,
            'trajectory':trajectory_payload(relaxed['trajectory'],len(species))}


def validate_result(result,context,data):
    require(type(result) is dict and set(result)=={'schema_version','status','binding','derived_structure','prediction',
            'convergence','authority','compute_wall_seconds','artifacts'},'result_fields')
    require(result['schema_version']==VERSION and result['binding']==context and result['authority']==AUTHORITY,'result_binding_or_authority')
    child=result['derived_structure'];rebuilt=make_child(data,child['lattice_matrix_angstrom'],child['fractional_coordinates'],child['species'],child['original_atom_ids'])
    require(child==rebuilt,'derived_child_identity_mismatch')
    p=result['prediction']
    require(B.finite(p['volume']['value']) and B.math.isclose(p['volume']['value'],B.determinant(child['lattice_matrix_angstrom']),rel_tol=1e-10,abs_tol=1e-10),'final_volume_mismatch')
    expected=B.normalize_prediction({'e':p['energy']['value'],'f':p['forces']['values'],
           's':p['stress']['values'],'m':p['magnetic_moments']['values']},len(data['species']),p['volume']['value'])
    expected['forces']['frame']=expected['stress']['frame']='Cartesian frame of final lattice_matrix_angstrom; atom order retained from original input'
    require(p==expected,'final_prediction_units_or_shape')
    c=result['convergence'];require(c==convergence(c['native_optimizer_converged'],c['optimizer_steps'],p),'convergence_replay_mismatch')
    require(result['status']==('converged' if c['converged'] else 'not_converged'),'result_convergence_status')
    require(B.finite(result['compute_wall_seconds']) and 0<=result['compute_wall_seconds']<=JOB_SECONDS,'result_compute_time')
    return c['converged']


def worker(args):
    import resource
    B.enforce_cgroup()
    resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(JOB_SECONDS*4,JOB_SECONDS*4))
    job=args.worker_request.parent.resolve(strict=True)
    request=B.decode(B.read_bounded(job,args.worker_request.name,expected=args.worker_request_sha256))
    require(set(request)=={'binding','input','cif','runtime_prefix','method_manifest'},'worker_request_fields')
    require(request['runtime_prefix']==str(args.runtime_prefix),'worker_runtime_path')
    own=B.read_bounded(Path(__file__).parent,Path(__file__).name)
    raw=B.pinned(job,request['input']);data=B.validate_input(B.decode(raw));cif=B.pinned(job,request['cif'])
    require(B.sha(cif)==data['structure_sha256'],'worker_cif_binding')
    output_root=Path(__file__).parent
    manifest=B.decode(B.read_bounded(output_root,'batch-manifest.json',expected=MANIFEST_SHA,maximum=B.MAX_MANIFEST))
    selection=B.decode(B.read_bounded(output_root,'selection.json',expected=request['binding']['selection_sha256']))
    require(len(manifest['inputs'])==173 and 'selection' not in manifest,'worker_original_manifest')
    ids=selected_ids(selection,MANIFEST_SHA,[row['state_id'] for row in manifest['inputs']])
    rows=[row for row in manifest['inputs'] if row['state_id']==data['state_id']]
    require(data['state_id'] in ids and len(rows)==1 and rows[0]['sha256']==B.sha(raw) and rows[0]['bytes']==len(raw)
            and rows[0]['cif']['sha256']==B.sha(cif) and rows[0]['cif']['bytes']==len(cif),'worker_state_not_selected_exact_original')
    expected=binding(data,B.sha(raw),request['binding']['selection_sha256'],B.sha(own))
    require(expected==request['binding'],'worker_binding')
    method,method_raw=load_method_file(args.method_manifest,args.method_manifest_sha256)
    require(request['method_manifest']=={'sha256':B.sha(method_raw),'bytes':len(method_raw)},'worker_method_pin')
    runtime,_,checkpoint=B.runtime_inventory(args.runtime_prefix,RUNTIME_SHA,CHECKPOINT_SHA)
    verify_method_runtime(args.runtime_prefix,method,runtime)
    t0=time.monotonic();computed=calculate(data,cif,args.runtime_prefix,runtime,checkpoint)
    B.runtime_inventory(args.runtime_prefix,RUNTIME_SHA,CHECKPOINT_SHA);verify_method_runtime(args.runtime_prefix,method,runtime)
    trajectory_raw=B.pretty(computed.pop('trajectory'))
    require(len(trajectory_raw)<=8*1024*1024,'trajectory_serialization_bound')
    B.write_bytes_new(job/'trajectory.json',trajectory_raw)
    child_raw=B.pretty(computed['derived_structure']);B.write_bytes_new(job/'derived-structure.json',child_raw)
    result={'schema_version':VERSION,'status':'converged' if computed['convergence']['converged'] else 'not_converged',
            'binding':expected,**computed,'authority':AUTHORITY,'compute_wall_seconds':time.monotonic()-t0,
            'artifacts':{'trajectory':{'path':'trajectory.json','sha256':B.sha(trajectory_raw),'bytes':len(trajectory_raw)},
                         'derived_structure':{'path':'derived-structure.json','sha256':B.sha(child_raw),'bytes':len(child_raw)}}}
    validate_result(result,expected,data);B.atomic_new(job/'result.json',result)


def run_batch(args,manifest_raw,selection_raw,records,method,method_raw,start):
    limits=B.enforce_cgroup()
    runtime,runtime_raw,_=B.runtime_inventory(args.runtime_prefix,RUNTIME_SHA,CHECKPOINT_SHA)
    verify_method_runtime(args.runtime_prefix,method,runtime)
    script=B.read_bounded(Path(__file__).parent,Path(__file__).name)
    adapter=B.read_bounded(Path(__file__).parent,'run_discovery_chgnet_batch.py',expected=BATCH_SHA)
    lifecycle=B.read_bounded(Path(__file__).parent,'run_discovery_qe_pilot.py',expected=B.LIFECYCLE_SHA)
    args.output.mkdir(mode=0o700,parents=False,exist_ok=False);(args.output/'jobs').mkdir(mode=0o700)
    for name,raw in {'relax-runner.py':script,'run_discovery_chgnet_batch.py':adapter,'run_discovery_qe_pilot.py':lifecycle,
                     'batch-manifest.json':manifest_raw,'selection.json':selection_raw,'method-manifest.json':method_raw,
                     'runtime-artifact-manifest.json':runtime_raw}.items():B.write_bytes_new(args.output/name,raw)
    common={'schema_version':'discovery-chgnet-relax-execution/1.0.0','started_at_utc':B.stamp(),
            'runner_sha256':B.sha(script),'batch_adapter_sha256':BATCH_SHA,'lifecycle_sha256':B.LIFECYCLE_SHA,
            'manifest_sha256':MANIFEST_SHA,'selection_sha256':B.sha(selection_raw),'runtime_manifest_sha256':RUNTIME_SHA,
            'method_manifest_sha256':METHOD_FILES_SHA,'checkpoint_sha256':CHECKPOINT_SHA,'method':METHOD,
            'per_job_seconds':JOB_SECONDS,'global_seconds':GLOBAL_SECONDS,'term_grace_seconds':B._helpers['TERM_GRACE_SECONDS'],
            'kill_reap_seconds':B._helpers['KILL_REAP_SECONDS'],'limits':limits,'selected_input_count':len(records),
            'authority':{**AUTHORITY,'relaxation_performed':False}}
    B.atomic_new(args.output/'started.json',common)
    env={'PATH':str(args.runtime_prefix/'bin')+':/usr/bin:/bin','XDG_CACHE_HOME':str(args.output/'cache'),
         'MPLCONFIGDIR':str(args.output/'mpl-cache'),'PYTHONNOUSERSITE':'1','CUDA_VISIBLE_DEVICES':'',
         'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','MKL_NUM_THREADS':'4','NUMEXPR_NUM_THREADS':'4'}
    if 'HOME' in os.environ:env['HOME']=os.environ['HOME']
    receipts=[];converged_count=0;completed_count=0;stop_reason=None
    try:
        for i,record in enumerate(records):
            if start+GLOBAL_SECONDS-time.monotonic()<=B.RESERVE_SECONDS:stop_reason='global_budget_exhausted';break
            begun=time.monotonic();deadline=min(start+GLOBAL_SECONDS,begun+JOB_SECONDS)
            job=args.output/'jobs'/f"{i:03d}-{record['entry']['recipe_id']}";job.mkdir(mode=0o700)
            receipt={'state_id':record['data']['state_id'],'role':record['data']['role'],'status':'failed',
                     'job_started_at_utc':B.stamp(),'process':None,'result':None,'worker_log':None,'reason_code':None}
            B.write_bytes_new(job/'input.json',record['input_bytes']);B.write_bytes_new(job/'input.cif',record['cif_bytes'])
            context=binding(record['data'],B.sha(record['input_bytes']),B.sha(selection_raw),B.sha(script))
            request={'binding':context,'input':{'path':'input.json','sha256':B.sha(record['input_bytes']),'bytes':len(record['input_bytes'])},
                     'cif':{'path':'input.cif','sha256':B.sha(record['cif_bytes']),'bytes':len(record['cif_bytes'])},
                     'runtime_prefix':str(args.runtime_prefix),'method_manifest':{'sha256':B.sha(method_raw),'bytes':len(method_raw)}}
            request_raw=B.pretty(request);B.write_bytes_new(job/'request.json',request_raw)
            try:
                argv=[str(args.runtime_prefix/runtime['python']['path']),'-I',str(args.output/'relax-runner.py'),
                      '--execute','--worker-request',str(job/'request.json'),'--worker-request-sha256',B.sha(request_raw),
                      '--runtime-prefix',str(args.runtime_prefix),'--runtime-manifest-sha256',RUNTIME_SHA,'--checkpoint-sha256',CHECKPOINT_SHA,
                      '--method-manifest',str(args.output/'method-manifest.json'),'--method-manifest-sha256',METHOD_FILES_SHA]
                with (job/'worker.log').open('xb') as log:
                    outcome=B.execute_before_deadline(argv,cwd=job,stdout=log,env=env,deadline=deadline)
                receipt['process']=outcome
                if outcome is None or outcome['process_reaped']:
                    log_raw=B.read_bounded(job,'worker.log',maximum=8*1024*1024,allow_empty=True)
                    receipt['worker_log']={'path':str((job/'worker.log').relative_to(args.output)),'sha256':B.sha(log_raw),'bytes':len(log_raw)}
                if outcome is None:receipt['reason_code']='insufficient_remaining_job_budget'
                elif not outcome['process_reaped']:
                    receipt['reason_code']='process_not_reaped';stop_reason='process_not_reaped'
                elif outcome['exit_code']!=0 or outcome['timed_out']:receipt['reason_code']='worker_failed_or_timed_out'
                else:
                    raw=B.read_bounded(job,'result.json',maximum=4*1024*1024);result=B.decode(raw)
                    passed=validate_result(result,context,record['data'])
                    require(set(result['artifacts'])=={'trajectory','derived_structure'},'result_artifact_fields')
                    for label,name in [('trajectory','trajectory.json'),('derived_structure','derived-structure.json')]:
                        pin=result['artifacts'][label];require(pin['path']==name,'result_artifact_path')
                        artifact_raw=B.pinned(job,pin,maximum=8*1024*1024)
                        if label=='derived_structure':require(B.decode(artifact_raw)==result['derived_structure'],'child_file_mismatch')
                    require(time.monotonic()<=deadline,'job_deadline_exceeded')
                    receipt['result']={'path':str((job/'result.json').relative_to(args.output)),'bytes':len(raw),'sha256':B.sha(raw)}
                    receipt['status']='converged' if passed else 'not_converged'
                    receipt['reason_code']=None if passed else 'model_optimizer_criteria_not_met'
                    completed_count+=1;converged_count+=int(passed)
            except Exception as error:receipt['reason_code']=str(error) if isinstance(error,B.BatchError) else type(error).__name__
            receipt.update(binding=context,job_wall_seconds=time.monotonic()-begun,
                           job_deadline_exceeded=time.monotonic()>deadline,job_finished_at_utc=B.stamp())
            if receipt['job_deadline_exceeded'] and receipt['status'] in ('converged','not_converged'):
                converged_count-=int(receipt['status']=='converged');completed_count-=1
                receipt.update(status='failed',reason_code='job_deadline_exceeded')
            B.atomic_new(job/'receipt.json',receipt);receipt_raw=B.read_bounded(job,'receipt.json')
            receipts.append({'state_id':receipt['state_id'],'status':receipt['status'],'path':str((job/'receipt.json').relative_to(args.output)),
                             'sha256':B.sha(receipt_raw),'bytes':len(receipt_raw)})
            print(B.pretty({'index':i,'status':receipt['status'],'reason_code':receipt['reason_code']}).decode(),flush=True)
            if stop_reason:break
    except Exception as error:stop_reason=str(error) if isinstance(error,B.BatchError) else type(error).__name__
    complete=converged_count==len(records) and time.monotonic()-start<=GLOBAL_SECONDS and stop_reason is None
    B.atomic_new(args.output/'finished.json',{**common,'finished_at_utc':B.stamp(),'wall_seconds':time.monotonic()-start,
        'status':'all_model_relaxations_converged' if complete else 'partial_failed_or_not_converged','converged_jobs':converged_count,
        'completed_optimizer_jobs':completed_count,'jobs':receipts,'unstarted_jobs':len(records)-len(receipts),'stop_reason':stop_reason,
        'authority':{**AUTHORITY,'relaxation_performed':True if completed_count else None if receipts else False}})
    return 0 if complete else 1


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path);p.add_argument('--manifest-sha256');p.add_argument('--selection',type=Path);p.add_argument('--selection-sha256')
    p.add_argument('--runtime-prefix',type=Path,required=True);p.add_argument('--runtime-manifest-sha256',required=True)
    p.add_argument('--checkpoint-sha256',required=True);p.add_argument('--method-manifest',type=Path,required=True)
    p.add_argument('--method-manifest-sha256',required=True);p.add_argument('--output',type=Path);p.add_argument('--execute',action='store_true')
    p.add_argument('--worker-request',type=Path,help=argparse.SUPPRESS);p.add_argument('--worker-request-sha256',help=argparse.SUPPRESS)
    args=p.parse_args(argv);os.umask(0o077);start=time.monotonic()
    try:
        require(args.runtime_manifest_sha256==RUNTIME_SHA and args.checkpoint_sha256==CHECKPOINT_SHA,'unsupported_runtime_or_checkpoint_pin')
        args.runtime_prefix=args.runtime_prefix.absolute();args.method_manifest=args.method_manifest.absolute()
        if args.worker_request:
            require(args.execute and args.worker_request_sha256 and not args.bundle and not args.output and not args.selection,'worker_arguments')
            worker(args);return 0
        require(args.bundle and args.selection and args.output and args.manifest_sha256
                and type(args.selection_sha256) is str and B.HASH.fullmatch(args.selection_sha256),'batch_arguments')
        manifest,selection,records=load_selection(args.bundle.absolute(),args.manifest_sha256,args.selection.absolute(),args.selection_sha256)
        method,method_raw=load_method_file(args.method_manifest,args.method_manifest_sha256)
        if not args.execute:
            print(B.pretty({'status':'selected_inputs_verified_not_executed','selected_input_count':len(records),
                  'method_manifest_sha256':B.sha(method_raw),'runtime_checked':False,'model_imported':False}).decode());return 0
        args.output=args.output.absolute()
        return run_batch(args,manifest,selection,records,method,method_raw,start)
    except Exception as error:
        print(B.pretty({'status':'rejected','reason_code':str(error) if isinstance(error,B.BatchError) else type(error).__name__}).decode());return 2


if __name__=='__main__':sys.exit(main())
