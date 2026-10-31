"""Continue one completed Production-90 run without overlapping its workers.

This controller only launches the existing pipeline once. It does not retry
provider failures or claim that an exhausted source queue completes the goal.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


SCRIPTS = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_bytes())


def pin(path):
    path = Path(path).absolute()
    data = path.read_bytes()
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def checked(ref):
    if pin(ref['path']) != ref:
        raise ValueError('continuation_evidence_changed')
    return Path(ref['path'])


def write(path, value, *, immutable=False):
    path = Path(path)
    if immutable and path.exists():
        if read(path) != value:
            raise ValueError('continuation_configuration_changed')
        return
    temporary = path.with_suffix('.writing')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def status(directory, state, **fields):
    value = dict(state=state, at=datetime.now(timezone.utc).isoformat(),
                 owner_pid=os.getpid(), **fields)
    write(directory / 'STATUS.json', value)
    return value


def busy(root):
    with (root / '.production90-pipeline.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def prepare(args):
    previous = read(args.after / 'PLAN.json')
    if hashlib.sha256(args.database_url.encode()).hexdigest() != previous['database_url_sha256']:
        raise ValueError('continuation_database_changed')
    root = Path(previous['root'])
    with sqlite3.connect(f'file:{root}/corpus.sqlite3?mode=ro', uri=True) as db:
        denominator = db.execute('SELECT count(*) FROM papers').fetchone()[0]
    if denominator < 1:
        raise ValueError('empty_frozen_corpus')
    # More than enough 60-paper cohorts for this frozen denominator. The
    # existing pipeline exits earlier when its queued source scope is empty.
    bound = math.ceil(denominator / 60) + 1
    maximum = args.max_batches if args.max_batches is not None else bound
    if not 1 <= maximum <= bound:
        raise ValueError('continuation_exceeds_frozen_corpus_bound')
    command = [sys.executable, str(SCRIPTS / 'materials_ner_tc_pipeline.py')]
    for flag, value in [('root', previous['root']), ('campaign', previous['campaign']),
                        ('directory', args.next_directory), ('audit-root', previous['audit_root']),
                        ('plan', previous['source_plan']['path']), ('source-python', previous['source_python']),
                        ('source-start', previous['source_start'] + previous['max_batches']),
                        ('batch-start', previous['batch_start'] + previous['max_batches']),
                        ('max-batches', maximum), ('ssh-host', previous['ssh_host'])]:
        command += ['--' + flag, str(value)]
    if previous.get('prefetch_next_source'):
        command.append('--prefetch-next-source')
    config = dict(schema='production90-continuation/1', previous_plan=pin(args.after / 'PLAN.json'),
                  controller=pin(__file__), command_without_database_url=command,
                  database_url_sha256=previous['database_url_sha256'], frozen_papers=denominator,
                  max_batches=maximum, deployment_enabled=False, automatic_provider_retry=False)
    return previous, config, command + ['--database-url', args.database_url]


def verify_finished(after, previous):
    observed = read(after / 'STATUS.json')
    if observed['state'] == 'queued_source_scope_exhausted':
        return False
    if observed['state'] != 'bounded_run_finished':
        raise ValueError('previous_pipeline_not_successfully_finished')
    completed = []
    for offset in range(previous['max_batches']):
        item = read(after / f'BATCH_{offset:03}.json')
        if item['batch'] != f"batch-{previous['batch_start'] + offset:03}":
            raise ValueError('previous_batch_sequence_changed')
        if item['state'] not in {'admission_processed', 'scientific_batch_held', 'no_eligible_candidates'}:
            raise ValueError('previous_batch_not_terminal')
        for ref in item['completion_evidence']:
            checked(ref)
        completed.append(item)
    if observed.get('completed') != completed:
        raise ValueError('previous_terminal_receipt_incomplete')
    return True


def run(args):
    args.directory.mkdir(parents=True, exist_ok=True)
    with (args.directory / '.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (args.directory / 'RESULT.json').exists():
            return read(args.directory / 'RESULT.json')
        try:
            previous, config, command = prepare(args)
            write(args.directory / 'PLAN.json', config, immutable=True)
            if (args.directory / 'CHILD_STARTED.json').exists():
                raise ValueError('previous_child_outcome_requires_review')
            root = Path(previous['root'])
            while busy(root):
                if (args.directory / 'STOP').exists() or (args.after / 'STOP_AFTER_BATCH').exists():
                    return finish(args, 'stopped_before_continuation')
                status(args.directory, 'waiting_for_existing_pipeline', previous_directory=str(args.after))
                time.sleep(args.poll_seconds)
            if (args.directory / 'STOP').exists() or (args.after / 'STOP_AFTER_BATCH').exists():
                return finish(args, 'stopped_before_continuation')
            checked(config['previous_plan'])
            for ref in [previous['source_plan'], *previous['stage_sources']]:
                checked(ref)
            if not verify_finished(args.after, previous):
                return finish(args, 'queued_source_scope_already_exhausted')
            if args.next_directory.exists():
                raise ValueError('next_pipeline_directory_already_exists')
            # Freeze intent before Popen: an interrupted launch is uncertain,
            # never an invitation to automatically launch another provider run.
            write(args.directory / 'CHILD_STARTED.json',
                  dict(next_directory=str(args.next_directory), launch_intent=True), immutable=True)
            with (args.directory / 'PIPELINE.log').open('ab') as log:
                child = subprocess.Popen(command, cwd=SCRIPTS.parent, stdout=log, stderr=log)
                while child.poll() is None:
                    stopping = (args.directory / 'STOP').exists()
                    if stopping and args.next_directory.exists():
                        (args.next_directory / 'STOP_AFTER_BATCH').touch(exist_ok=True)
                    status(args.directory, 'draining_current_batch' if stopping else 'running_continuation',
                           child_pid=child.pid, next_directory=str(args.next_directory))
                    time.sleep(args.poll_seconds)
            if child.returncode:
                raise ValueError('continued_pipeline_failed_requires_review')
            observed = read(args.next_directory / 'STATUS.json')
            if observed['state'] not in {'bounded_run_finished', 'queued_source_scope_exhausted',
                                          'stopped_at_batch_boundary'}:
                raise ValueError('continued_pipeline_terminal_receipt_missing')
            return finish(args, observed['state'], child_exit_code=child.returncode,
                          next_status=pin(args.next_directory / 'STATUS.json'))
        except Exception as exc:
            finish(args, 'stopped_for_review', error_class=type(exc).__name__, error=str(exc)[:500])
            raise


def finish(args, state, **fields):
    result = status(args.directory, state, full_corpus_complete=False, production_deployed=False, **fields)
    write(args.directory / 'RESULT.json', result, immutable=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['after', 'directory', 'next-directory']:
        parser.add_argument('--' + name, required=True, type=lambda p: Path(p).absolute())
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--max-batches', type=int)
    parser.add_argument('--poll-seconds', type=float, default=15)
    arguments = parser.parse_args()
    if not 1 <= arguments.poll_seconds <= 60:
        raise ValueError('poll_interval_must_be_between_1_and_60_seconds')
    run(arguments)
