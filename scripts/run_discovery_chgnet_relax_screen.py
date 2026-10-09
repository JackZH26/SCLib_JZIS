"""Bounded relaxation screening for two externally pinned, reviewed source batches.

The frozen aa2 calculation, native FIRE flag and scientific thresholds are reused
unchanged. Additional FrechetCellFilter forces are post-relaxation diagnostics;
cell generalized forces are not physical stress. No execution without --execute.
The external launcher must cap its named cgroup service at 3600 seconds, 4 CPUs
and 12 GiB. This coordinator and the pinned c94 process lifecycle retain the
600-second job and 3500-second global bounds, including capture and validation.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import time
import types

RELAX_SHA = 'aa2cce9f42fbe77acf485b0c9c747512efbcd0e9024a18f3d76a9b8d1a5ee429'
REVIEWED_MANIFESTS = {
    'e189c07a064a7c5b850b9a739660f5f821ba2e5108a615e7ba537d1fa7dadb83': 173,
    '3a5fff82b7f14ef94866781a9d1470ae5e2a0df8ba7d56669e8667715f099427': 117,
}
# These six already have a bounded historical attempt, including failed Nb/Ta.
# No retry is authorized by the new screen. Their original artifacts stay intact.
EXCLUDED_STATE_IDS = frozenset({
    'ht-state:09ccf3044aebfeacb735172f2cdd8b78781f2593759b06e15ec4b06a933d71ee',
    'ht-state:a46ac34c7e4eee1675de67bd408e60bf5ed3517fe2c48e8bb3fbe44294b8c7b1',
    'ht-state:a9e64d5fc8cb920d0283623fec9701e37dac710ecf6060621659eef59d3fbbba',
    'ht-state:a60f93d908f28f3dda892e82fd4b8f077d1cd9943e8a9d98cc43b7acbb031579',
    'ht-state:bfeb687cfda5d07fad0e42155e14eb460074c65ce20f9a3c25f8dbb558ff5113',
    'ht-state:b4d747211db948cfef986f0bd318b7fce9ee149c04808f33b564cf2cfecdef82',
})
VERSION = 'discovery-chgnet-relaxation/1.1.0'
EXECUTION_VERSION = 'discovery-chgnet-relax-execution/1.1.0'
DIAGNOSTIC_VERSION = 'discovery-chgnet-relax-generalized-forces/1.0.0'


def load_frozen_relax(path=None):
    """Hash and execute the same bounded regular-file bytes, never import by path."""
    p = path if path is not None else Path(__file__).parent / 'run_discovery_chgnet_relax.py'
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1024 * 1024:
            raise ValueError('frozen_relax_type_or_size')
        chunks = []; remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b''.join(chunks); after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if signature(before) != signature(after) or len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != RELAX_SHA:
            raise ValueError('frozen_relax_hash_or_change')
    finally:
        os.close(fd)
    module = types.ModuleType('frozen_chgnet_relax_screen_method')
    module.__file__ = str(p)
    exec(compile(raw, str(p), 'exec'), module.__dict__)
    return module, raw


R, RELAX_BYTES = load_frozen_relax()
B = R.B
require = B.require
METHOD, AUTHORITY = R.METHOD, R.AUTHORITY
BATCH_SHA, RUNTIME_SHA, CHECKPOINT_SHA = R.BATCH_SHA, R.RUNTIME_SHA, R.CHECKPOINT_SHA
METHOD_FILES_SHA = R.METHOD_FILES_SHA
JOB_SECONDS, GLOBAL_SECONDS = R.JOB_SECONDS, R.GLOBAL_SECONDS
load_method_file, verify_method_runtime = R.load_method_file, R.verify_method_runtime


def validate_manifest(manifest, manifest_sha):
    require(manifest_sha in REVIEWED_MANIFESTS, 'unsupported_original_manifest')
    require(type(manifest) is dict and manifest.get('schema_version') == 'discovery-high-throughput-batch/1.0.0'
            and 'selection' not in manifest and type(manifest.get('inputs')) is list
            and len(manifest['inputs']) == REVIEWED_MANIFESTS[manifest_sha], 'full_original_bundle_required')
    ids = [row.get('state_id') for row in manifest['inputs']]
    require(all(type(x) is str for x in ids) and len(set(ids)) == len(ids), 'original_state_ids')
    return ids


def selected_ids(value, manifest_sha, known_ids):
    ids = R.selected_ids(value, manifest_sha, known_ids)
    require(not EXCLUDED_STATE_IDS.intersection(ids), 'historical_attempt_not_authorized_for_retry')
    return ids


def load_selection(bundle, manifest_sha, selection, selection_sha):
    require(manifest_sha in REVIEWED_MANIFESTS, 'unsupported_original_manifest')
    manifest, raw, records = B.load_bundle(bundle, manifest_sha)
    known_ids = validate_manifest(manifest, manifest_sha)
    require(len(records) == REVIEWED_MANIFESTS[manifest_sha], 'original_record_count')
    selected_raw = B.read_bounded(selection.parent, selection.name, expected=selection_sha)
    by_id = {r['data']['state_id']: r for r in records}
    ids = selected_ids(B.decode(selected_raw), manifest_sha, known_ids)
    return raw, selected_raw, [by_id[s] for s in ids]


def binding(data, input_sha, selection_sha, script_sha, manifest_sha):
    require(manifest_sha in REVIEWED_MANIFESTS, 'unsupported_original_manifest')
    base = B.context(data, input_sha, data['structure_sha256'], manifest_sha, RUNTIME_SHA, CHECKPOINT_SHA, script_sha)
    return {**base, 'method': METHOD, 'batch_adapter_sha256': BATCH_SHA,
            'frozen_relax_adapter_sha256': RELAX_SHA, 'method_files_sha256': METHOD_FILES_SHA,
            'source_manifest_input_count': REVIEWED_MANIFESTS[manifest_sha],
            'selection_sha256': selection_sha, 'parent_state_id': data['state_id'],
            'parent_structure_sha256': data['structure_sha256'], 'authority_scope': 'model_geometry_prefilter_only'}


def generalized_force_payload(values, data, child):
    """Only format observed native values. Never infer an optimizer limiting term."""
    n = len(data['species'])
    require(B.matrix(values, n + 3, 3), 'generalized_force_shape_or_nonfinite')
    atomic, cell = values[:n], values[n:]
    norms = lambda rows: [B.math.sqrt(sum(v * v for v in row)) for row in rows]
    atomic_norms, cell_norms = norms(atomic), norms(cell)
    require(all(B.finite(x) for x in atomic_norms + cell_norms), 'generalized_force_norm_nonfinite')
    return {
        'schema_version': DIAGNOSTIC_VERSION,
        'capture': 'actual FrechetCellFilter.get_forces() after native relaxation returns',
        'filter': 'ASE 3.29.0 FrechetCellFilter',
        'method_files_sha256': METHOD_FILES_SHA,
        'final_structure_id': child['id'],
        'exp_cell_factor': n,
        'atomic': {'values': atomic, 'row_norms': atomic_norms, 'max_row_norm': max(atomic_norms),
                   'unit': 'eV/angstrom', 'atom_ids': data['original_atom_ids'],
                   'coordinate_convention': 'Original undeformed-cell position coordinates; native Cartesian atomic forces multiplied by the current deformation gradient.'},
        'cell': {'values': cell, 'row_norms': cell_norms, 'max_row_norm': max(cell_norms),
                 'unit': 'eV per scaled dimensionless log-deformation coordinate',
                 'coordinate_convention': 'Negative energy derivatives with respect to N * log(deformation_gradient); native Frechet cell block divided by exp_cell_factor=N. Not Cauchy stress.'},
        'optimizer_numeric_max_row_norm': max(atomic_norms + cell_norms),
        'scope': 'Post-relaxation diagnostic in mixed ASE optimizer coordinates. Not a physical stress, a reconstructed native stop flag, or proof of which term limited convergence. Admission still requires the recorded native flag and separate fresh Cartesian atomic-force/stress checks.',
    }


def retaining_fire_factory(original_factory, holder):
    """Keep the real filter used by the unchanged optimizer; do not alter run()."""
    def factory(fire_class, observed):
        recorded = original_factory(fire_class, observed)
        class RetainingFIRE(recorded):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                require(not holder, 'single_native_cell_filter_required')
                holder.append(self.atoms)
        return RetainingFIRE
    return factory


def capture_generalized_forces(cell_filter, data, child):
    import ase.filters
    require(isinstance(cell_filter, ase.filters.FrechetCellFilter), 'native_frechet_filter_required')
    atoms = cell_filter.atoms
    require(cell_filter.exp_cell_factor == len(data['species']) and not cell_filter.hydrostatic_strain
            and not cell_filter.constant_volume and cell_filter.scalar_pressure == 0.0
            and cell_filter.mask.tolist() == [[1.0] * 3 for _ in range(3)], 'native_filter_parameters_changed')
    require(atoms.get_chemical_symbols() == child['species'], 'diagnostic_atom_order_mismatch')
    close = lambda a, b: len(a) == len(b) and all(len(x) == len(y) and all(
        B.finite(v) and B.math.isclose(v, w, rel_tol=1e-10, abs_tol=1e-10)
        for v, w in zip(x, y)) for x, y in zip(a, b))
    require(close(atoms.cell.array.tolist(), child['lattice_matrix_angstrom'])
            and close(atoms.get_scaled_positions(wrap=False).tolist(), child['fractional_coordinates'])
            and close(cell_filter._utility.orig_cell.tolist(), data['lattice_matrix_angstrom']),
            'diagnostic_final_or_reference_geometry_mismatch')
    # Actual filter call after R.calculate has returned. No formula-derived proxy.
    return generalized_force_payload(cell_filter.get_forces().tolist(), data, child)


def calculate(data, cif, prefix, runtime, checkpoint):
    holder = []; original = R.recording_fire_class
    R.recording_fire_class = retaining_fire_factory(original, holder)
    try:
        computed = R.calculate(data, cif, prefix, runtime, checkpoint)
    finally:
        R.recording_fire_class = original
    require(len(holder) == 1, 'native_cell_filter_not_recorded')
    computed['generalized_forces'] = capture_generalized_forces(holder[0], data, computed['derived_structure'])
    return computed


def validate_result(result, context, data):
    require(type(result) is dict and 'generalized_forces' in result and result.get('schema_version') == VERSION,
            'screen_result_fields_or_version')
    projected = {key: value for key, value in result.items() if key != 'generalized_forces'}
    projected['schema_version'] = R.VERSION
    passed = R.validate_result(projected, context, data)
    observed = result['generalized_forces']
    require(type(observed) is dict and type(observed.get('atomic')) is dict and type(observed.get('cell')) is dict,
            'generalized_force_fields')
    atomic, cell = observed['atomic'].get('values'), observed['cell'].get('values')
    require(B.matrix(atomic, len(data['species']), 3) and B.matrix(cell, 3, 3), 'generalized_force_blocks')
    require(observed == generalized_force_payload(atomic + cell, data, result['derived_structure']), 'generalized_force_replay')
    return passed


def verify_worker_selection(manifest, manifest_sha, selection, data, raw, cif):
    ids = selected_ids(selection, manifest_sha, validate_manifest(manifest, manifest_sha))
    rows = [row for row in manifest['inputs'] if row['state_id'] == data['state_id']]
    require(data['state_id'] in ids and len(rows) == 1 and rows[0]['sha256'] == B.sha(raw)
            and rows[0]['bytes'] == len(raw) and rows[0]['cif']['sha256'] == B.sha(cif)
            and rows[0]['cif']['bytes'] == len(cif) and rows[0]['role'] == data['role'],
            'worker_state_not_selected_exact_original')


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
    manifest_sha=request['binding']['batch_manifest_sha256']
    require(manifest_sha in REVIEWED_MANIFESTS,'unsupported_original_manifest')
    manifest=B.decode(B.read_bounded(output_root,'batch-manifest.json',expected=manifest_sha,maximum=B.MAX_MANIFEST))
    selection=B.decode(B.read_bounded(output_root,'selection.json',expected=request['binding']['selection_sha256']))
    verify_worker_selection(manifest,manifest_sha,selection,data,raw,cif)
    expected=binding(data,B.sha(raw),request['binding']['selection_sha256'],B.sha(own),manifest_sha)
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
    require(B.sha(manifest_raw)==args.manifest_sha256,'coordinator_manifest_pin')
    validate_manifest(B.decode(manifest_raw),args.manifest_sha256)
    limits=B.enforce_cgroup()
    runtime,runtime_raw,_=B.runtime_inventory(args.runtime_prefix,RUNTIME_SHA,CHECKPOINT_SHA)
    verify_method_runtime(args.runtime_prefix,method,runtime)
    script=B.read_bounded(Path(__file__).parent,Path(__file__).name)
    adapter=B.read_bounded(Path(__file__).parent,'run_discovery_chgnet_batch.py',expected=BATCH_SHA)
    lifecycle=B.read_bounded(Path(__file__).parent,'run_discovery_qe_pilot.py',expected=B.LIFECYCLE_SHA)
    args.output.mkdir(mode=0o700,parents=False,exist_ok=False);(args.output/'jobs').mkdir(mode=0o700)
    for name,raw in {'relax-screen-runner.py':script,'run_discovery_chgnet_relax.py':RELAX_BYTES,'run_discovery_chgnet_batch.py':adapter,'run_discovery_qe_pilot.py':lifecycle,
                     'batch-manifest.json':manifest_raw,'selection.json':selection_raw,'method-manifest.json':method_raw,
                     'runtime-artifact-manifest.json':runtime_raw}.items():B.write_bytes_new(args.output/name,raw)
    common={'schema_version':EXECUTION_VERSION,'started_at_utc':B.stamp(),
            'runner_sha256':B.sha(script),'batch_adapter_sha256':BATCH_SHA,'lifecycle_sha256':B.LIFECYCLE_SHA,
            'manifest_sha256':args.manifest_sha256,'source_manifest_input_count':REVIEWED_MANIFESTS[args.manifest_sha256],
            'frozen_relax_adapter_sha256':RELAX_SHA,'required_service_runtime_max_seconds':3600,'selection_sha256':B.sha(selection_raw),'runtime_manifest_sha256':RUNTIME_SHA,
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
            context=binding(record['data'],B.sha(record['input_bytes']),B.sha(selection_raw),B.sha(script),args.manifest_sha256)
            request={'binding':context,'input':{'path':'input.json','sha256':B.sha(record['input_bytes']),'bytes':len(record['input_bytes'])},
                     'cif':{'path':'input.cif','sha256':B.sha(record['cif_bytes']),'bytes':len(record['cif_bytes'])},
                     'runtime_prefix':str(args.runtime_prefix),'method_manifest':{'sha256':B.sha(method_raw),'bytes':len(method_raw)}}
            request_raw=B.pretty(request);B.write_bytes_new(job/'request.json',request_raw)
            try:
                argv=[str(args.runtime_prefix/runtime['python']['path']),'-I',str(args.output/'relax-screen-runner.py'),
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
                  'manifest_sha256':args.manifest_sha256,'source_manifest_input_count':REVIEWED_MANIFESTS[args.manifest_sha256],
                  'selection_sha256':B.sha(selection),'selected_state_ids':[r['data']['state_id'] for r in records],
                  'frozen_relax_adapter_sha256':RELAX_SHA,'method_manifest_sha256':B.sha(method_raw),
                  'runtime_checked':False,'model_imported':False}).decode());return 0
        args.output=args.output.absolute()
        return run_batch(args,manifest,selection,records,method,method_raw,start)
    except Exception as error:
        print(B.pretty({'status':'rejected','reason_code':str(error) if isinstance(error,B.BatchError) else type(error).__name__}).decode());return 2


if __name__=='__main__':sys.exit(main())
