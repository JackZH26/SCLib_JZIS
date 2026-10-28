"""Shared single-attempt source stage lifecycle, with immutable provider receipts.

Stages supply preparation, configuration and deterministic evaluation only.
A returned model verdict never grants scientific or proposal acceptance.
"""
from dataclasses import asdict
import json
from pathlib import Path
import time
from pydantic import ValidationError
from . import page_images, reviewed_reader as reader
from .contract import canonical, digest
from .providers import CodexProvider, ProviderFailure
from .sources import sha


def row(store, identifier, stage):
    with store.connect() as db:
        value = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
    if value is None:
        raise ValueError('projector_unknown_job')
    job = dict(value)
    job['config'] = json.loads(job['config_json'])
    if job['config'].get('workflow') != stage.WORKFLOW or job['max_attempts'] != 1:
        raise ValueError('projector_wrong_workflow_or_retry_policy')
    return job


def validate_job(job, stage):
    for pin in job['config']['input_pins'] + job['config']['implementation']:
        reader.checked(pin)
    p = stage.prepare(reader.checked(job['config']['request']))
    if stage.configuration(p) != job['config'] or p['work_id'] != job['work_id'] or p['bundle_sha256'] != job['bundle_hash']:
        raise ValueError('projector_configuration_drift')
    return p


def terminal(job, directory, stage, *, recovered=False, error=None):
    result = dict(schema=stage.ATTEMPT_SCHEMA, job_id=job['id'], attempt_id=job['lease_token'],
        work_id=job['work_id'], bundle_sha256=job['bundle_hash'], config_sha256=digest(job['config']),
        recovered_without_provider_call=recovered, automatic_retry=False, usage={},
        semantic_validation_qualified=False,
        paper_completed=False, proposal_generated=False, scientific_acceptance=False,
        ml_training_eligible=False, production_writes=False)
    result.update(stage.provenance(job['config']) if hasattr(stage, 'provenance') else stage.PROVENANCE)
    marker = directory / 'provider-result.json'
    dispatched = (directory / 'DISPATCH_INTENT.json').exists()
    result['provider_dispatch_intent_recorded'] = dispatched
    if error is not None or not marker.exists():
        result.update(state='blocked', outcome='completion_unknown' if dispatched else 'not_dispatched',
            error_code=error or ('provider_completion_unknown' if dispatched else 'local_attempt_interrupted'))
        if (directory / 'failure.json').is_file():
            result['failure'] = reader.reference(directory / 'failure.json')
            result['usage'] = json.loads((directory / 'failure.json').read_bytes())['usage']
        return result
    try:
        p = validate_job(job, stage)
        returned = json.loads(marker.read_bytes())
        if (returned['job_id'] != job['id'] or returned['attempt_id'] != job['lease_token']
                or returned['config_sha256'] != digest(job['config'])
                or returned['result']['provider'] != job['config']['provider']
                or returned['result']['model'] != job['config']['model']):
            raise ValueError('projector_provider_identity')
        for pin in returned['raw_artifacts']:
            reader.checked(pin)
        result.update(provider_return=reader.reference(marker), usage=returned['result']['usage'],
            model_elapsed_seconds=returned['result']['elapsed_seconds'])
        stage.evaluate(p, returned['result']['text'], directory, result)
    except (ValueError, KeyError, OSError) as exc:
        code = stage.ERROR_PREFIX + '_schema_invalid' if isinstance(exc, ValidationError) else stage.ERROR_PREFIX + '_output_or_artifact_invalid'
        details = [{'location':list(e['loc']), 'type':e['type']} for e in exc.errors(include_input=False)] if isinstance(exc, ValidationError) else []
        reader.put(directory / 'validation-errors.json', dict(error_code=code, details=details, exception_class=type(exc).__name__))
        result.update(state='quarantined', outcome=stage.INVALID_OUTCOME, error_code=code,
            diagnostic=reader.reference(directory / 'validation-errors.json'))
    return result


def existing(job, stage):
    path = Path(job['result_path']) if job.get('result_path') else None
    if path is None or sha(path.read_bytes()) != job['result_hash']:
        raise ValueError('projector_terminal_receipt_changed')
    result = json.loads(path.read_bytes())
    if result['job_id'] != job['id'] or result['config_sha256'] != digest(job['config']):
        raise ValueError('projector_terminal_identity')
    for pin in job['config']['input_pins']:
        reader.checked(pin)
    for key in ['diagnostic', 'failure', 'provider_return', *stage.RESULT_PINS]:
        if key in result:
            reader.checked(result[key])
    if 'provider_return' in result:
        returned = json.loads(reader.checked(result['provider_return']).read_bytes())
        for pin in returned['raw_artifacts']:
            reader.checked(pin)
    if 'failure' in result:
        for pin in json.loads(reader.checked(result['failure']).read_bytes())['raw_artifacts']:
            reader.checked(pin)
    return result


def recover_locked(store, identifier, stage):
    job = row(store, identifier, stage)
    if job['state'] == 'queued':
        return None
    if job['state'] not in {'running', 'failed'} or job['state'] == 'failed' and job['last_error'] != 'lease_expired':
        return existing(job, stage)
    with store.connect() as db:
        attempt = dict(db.execute('SELECT * FROM attempts WHERE job_id=? AND ordinal=1', (identifier,)).fetchone())
    job['lease_token'] = attempt['id']
    directory = store.root / stage.ATTEMPTS_DIRECTORY / identifier / attempt['id']
    directory.mkdir(parents=True, exist_ok=True)
    result = stage.terminal(job, directory, recovered=True)
    reader._hold_uncertain_dispatch(store, result)
    path = directory / 'recovery-receipt.json'
    reader.put(path, result)
    pin = reader.reference(path)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        live = dict(db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())
        if live['attempts'] != 1 or not (live['state'] == 'running' or live['state'] == 'failed' and live['last_error'] == 'lease_expired'):
            raise ValueError('projector_recovery_state_changed')
        now = time.time()
        db.execute('UPDATE attempts SET status=?,finished_at=?,error_code=?,receipt_path=?,receipt_hash=?,usage_json=? WHERE id=?',
            (result['state'], now, result.get('error_code'), str(path), pin['sha256'], canonical(result['usage']), attempt['id']))
        db.execute('UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,last_error=?,result_path=?,result_hash=?,updated_at=? WHERE id=?',
            (result['state'], result.get('error_code'), str(path), pin['sha256'], now, identifier))
        store._audit(db, identifier, stage.WORKFLOW + '_recovered_without_dispatch', dict(receipt=pin))
    return result


def recover(store, identifier, stage):
    with reader.job_lock(store, identifier):
        return recover_locked(store, identifier, stage)


def run(store, identifier, stage, *, provider_override=None):
    with reader.job_lock(store, identifier):
        previous = recover_locked(store, identifier, stage)
        if previous is not None:
            return previous
        job = store.claim(lease_seconds=1200, job_id=identifier, workflow=stage.WORKFLOW)
        if job is None:
            raise ValueError('projector_job_not_claimable')
        directory = store.root / stage.ATTEMPTS_DIRECTORY / identifier / job['lease_token']
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        started = time.monotonic()
        error = None
        try:
            p = validate_job(job, stage)
            reader.immutable(directory / 'input.txt', p['prompt'].encode())
            reader.put(directory / 'output-schema.json', p['schema'])
            reader.put(directory / 'request.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                config=job['config'], input_tokens_estimate=p['input_tokens_estimate'], output_token_limit_enforced_by_provider=False))
            for pin in job['config']['implementation']:
                relative = Path(pin['path']).relative_to(Path(__file__).parents[1])
                reader.immutable(directory / 'implementation' / relative, reader.checked(pin).read_bytes())
            effective = dict(job['config'], image_inputs=[])
            if p['scope']['image_capture']:
                capture = json.loads(reader.checked(p['scope']['image_capture']).read_bytes())
                effective['image_inputs'] = page_images.materialize(capture, p['bundle'], directory / 'images')
            provider = provider_override or CodexProvider()
            reader.put(directory / 'DISPATCH_INTENT.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                config_sha256=digest(job['config']), at=time.time()))
            response = provider.extract(p['prompt'], p['schema'], effective, directory)
            reader.put(directory / 'provider-result.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                config_sha256=digest(job['config']), result=asdict(response),
                raw_artifacts=[reader.reference(f) for f in sorted(directory.rglob('*')) if f.is_file()]))
        except (Exception, KeyboardInterrupt) as exc:
            error = exc.code if isinstance(exc, ProviderFailure) else 'projector_local_or_provider_interruption'
            reader.put(directory / 'failure.json', dict(error_code=error, exception_class=type(exc).__name__,
                usage=exc.usage if isinstance(exc, ProviderFailure) else {},
                raw_artifacts=[reader.reference(f) for f in sorted(directory.rglob('*')) if f.is_file()]))
        result = stage.terminal(job, directory, error=error)
        reader._hold_uncertain_dispatch(store, result)
        path = directory / 'receipt.json'
        reader.put(path, result)
        store.finish(job, state=result['state'], receipt_path=str(path), receipt_hash=sha(path.read_bytes()),
            usage=result['usage'], duration_seconds=time.monotonic()-started,
            error_code=result.get('error_code'), retryable=False)
        return result
