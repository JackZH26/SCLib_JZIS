"""Durable passage readings under the unchanged iteration-98 protocol.

This stage produces a reading, never a proposal or a completed paper. A dispatch
intent consumes the sole automatic attempt. Unknown provider completion stays on
hold; recovery can adopt a pinned, locally observed provider return without a
second call. This is not an exactly-once remote billing guarantee.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time

import tiktoken

from . import page_images, reader_scope
from .contract import canonical, digest
from .providers import CodexProvider, ProviderFailure
from .sources import check_admission, load_bundle, sha
from .store import Store

WORKFLOW = 'reviewed_reader_v1'
PROTOCOL = Path(__file__).with_name('reader_protocol')
PINS = {'instruction.txt': 'a0b4804726eae090d9e7e39435dc3ee93c4f7a7bd4adb0e5c1231e4da537da29',
        'response_schema.json': 'dcc54ccac9ac5a0cc9b07c4237f22bef9959eb78af463d03f129620081574ac6'}


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path), sha256=sha(raw), bytes=len(raw))


def checked(ref):
    if reference(ref['path']) != ref:
        raise ValueError('reader_input_pin_changed')
    return Path(ref['path'])


def immutable(path, raw):
    """Atomic create-or-verify, including directory durability before dispatch."""
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.reader-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError('reader_immutable_artifact_collision') from None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(tmp)


def put(path, value):
    immutable(path, canonical(value).encode())


def protocol():
    for name, checksum in PINS.items():
        if sha((PROTOCOL / name).read_bytes()) != checksum:
            raise ValueError('reader_fixed_protocol_changed')
    return (PROTOCOL / 'instruction.txt').read_text(), json.loads((PROTOCOL / 'response_schema.json').read_bytes())


def implementation():
    names = ['reviewed_reader.py', 'store.py', 'providers.py', 'sources.py', 'contract.py', 'page_images.py', 'reader_scope.py', '__init__.py']
    return [reference(Path(__file__).with_name(name)) for name in names] + [reference(PROTOCOL / name) for name in PINS]


def source_input(preflight_pin):
    """Shared read-only source preflight for reading and coverage inventory."""
    pins = [preflight_pin]
    preflight = json.loads(checked(preflight_pin).read_bytes())
    if (preflight.get('schema') != 'materials-source-preflight/1'
            or preflight.get('permits_bounded_passage_reading') is not True
            or preflight.get('official_identity_verified') is not True
            or preflight.get('scientific_acceptance') is not False):
        raise ValueError('reader_source_preflight_hold')
    binding = preflight.get('exact_version_binding') or {}
    version = binding.get('publication_version', '')
    if not re.fullmatch(r'v[1-9]\d*', version) or version != preflight.get('latest_version_observed'):
        raise ValueError('reader_version_binding_unresolved')
    for name in ['bundle', 'original', 'structure', 'official_metadata_receipt']:
        checked(preflight[name]); pins.append(preflight[name])
    for name in ['official_bytes', 'request_receipt']:
        checked(binding[name]); pins.append(binding[name])
    bundle = load_bundle(Path(preflight['bundle']['path']))
    if (bundle.work_id != preflight['work_id'] or not bundle.work_id.startswith('arxiv:')
            or digest(bundle.model_dump()) != preflight['bundle_sha256'] or check_admission(bundle)
            or any(d.source_sha256 != preflight['original']['sha256'] for d in bundle.documents)
            or binding['source_sha256'] != preflight['original']['sha256']
            or binding['official_bytes']['sha256'] != binding['source_sha256']):
        raise ValueError('reader_original_binding_mismatch')
    request = json.loads(checked(binding['request_receipt']).read_bytes())
    aid = bundle.work_id.removeprefix('arxiv:')
    expected_urls = {f'https://arxiv.org/{kind}/{aid}{version}' for kind in ['pdf', 'src']}
    if (request.get('status') != 200 or request.get('requested_url') not in expected_urls
            or request.get('final_url') not in expected_urls or request.get('artifact') != binding['official_bytes']):
        raise ValueError('reader_version_request_mismatch')
    metadata = json.loads(checked(preflight['official_metadata_receipt']).read_bytes())
    if metadata.get('status') != 200 or metadata.get('requested_url') != f'https://arxiv.org/abs/{aid}':
        raise ValueError('reader_official_metadata_unresolved')
    html = checked(metadata['artifact']).read_text(errors='replace')
    pins.append(metadata['artifact'])
    if not re.search(r'name=["\']citation_arxiv_id["\'][^>]*content=["\']' + re.escape(aid) + r'(?:v\d+)?["\']', html):
        raise ValueError('reader_official_metadata_identity')
    versions = {int(v) for v in re.findall(re.escape(aid) + r'v([1-9]\d*)', html)}
    versions.update(int(v) for v in re.findall(r'\[v([1-9]\d*)\]', html))
    if not versions or version != f'v{max(versions)}':
        raise ValueError('reader_official_version_history_mismatch')
    if re.search(r'(?:this (?:paper|article|submission) (?:has been|is|was) withdrawn|arxiv:withdrawn)', html, re.I):
        raise ValueError('reader_source_advisory_hold')
    if any(code in preflight.get('hold_codes', []) for code in [
            'withdrawn_source', 'retracted_source', 'archived_version_is_not_latest',
            'unsafe_archive_path', 'archive_link_requires_review', 'duplicate_archive_member_path']):
        raise ValueError('reader_source_advisory_hold')
    return preflight, bundle, pins


def prepare_scope(scope_path):
    """Verify exact original slices and byte-bound versions; render no label hints."""
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_bytes())
    reader_scope.shape(scope)
    preflight, bundle, source_pins = source_input(scope['preflight'])
    pins = [reference(scope_path), *source_pins]
    aid = bundle.work_id.removeprefix('arxiv:')

    instruction, schema = protocol()
    prompt = instruction + '\nOriginal source: arXiv ' + aid + '\n'
    blocks = {b.id: b for b in bundle.blocks}
    positions, seen, target_blocks, included_blocks = [], set(), set(), set()
    if not scope['passages']:
        raise ValueError('reader_empty_scope')
    for passage in scope['passages']:
        if set(passage) != {'block_id', 'start_char', 'end_char', 'role'}:
            raise ValueError('reader_passage_shape')
        start, end, role = (passage[k] for k in ['start_char', 'end_char', 'role'])
        block = blocks.get(passage['block_id'])
        if (block is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(block.text) or role not in {'target', 'context'}):
            raise ValueError('reader_passage_bounds')
        if digest(passage) in seen:
            raise ValueError('reader_duplicate_passage')
        seen.add(digest(passage)); included_blocks.add(block.id)
        if role == 'target':
            target_blocks.add(block.id)
        if scope['schema'] == reader_scope.VERSION:
            prompt += '\nOriginal-text coordinates: ' + canonical(dict(block_id=block.id, locator=block.locator,
                start_char=start, end_char=end)) + '\n'
        prompt += '\n<' + role.upper() + '>\n'
        begin = len(prompt)
        prompt += block.text[start:end]
        positions.append(dict(**passage, original_block_sha256=block.sha256,
                              prompt_start_char=begin, prompt_end_char=len(prompt)))
        prompt += '\n</' + role.upper() + '>\n'
    if not target_blocks:
        raise ValueError('reader_target_required')
    images = []; capture = None
    if scope['image_capture'] is not None:
        pins.append(scope['image_capture'])
        capture = json.loads(checked(scope['image_capture']).read_bytes())
        page_images.verify(capture, bundle)
        if any(not set(p['original_block_ids']) <= included_blocks for p in capture['pages']):
            raise ValueError('reader_image_outside_scope')
        images = capture['pages']
    if scope['schema'] == reader_scope.VERSION:
        prompt += reader_scope.render(scope, capture, bundle)
    count = len(tiktoken.get_encoding('cl100k_base').encode(prompt + canonical(schema), disallowed_special=()))
    if count > 60000:
        raise ValueError('reader_input_budget_exceeded')
    return dict(work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
                source_scope=scope, prompt=prompt, schema=schema, prompt_source_spans=positions,
                input_pins=list({p['path']: p for p in pins}.values()), input_tokens_estimate=count,
                image_count=len(images), coverage_holds=preflight['hold_codes'])


def configuration(prepared):
    return dict(workflow=WORKFLOW, provider='codex', model='gpt-6-luna', reasoning='medium',
                timeout_seconds=900, max_input_tokens=60000, automatic_attempts=1,
                scope=prepared['input_pins'][0], input_pins=prepared['input_pins'],
                prompt_sha256=sha(prepared['prompt'].encode()), schema_sha256=digest(prepared['schema']),
                implementation=implementation(), output_kind='scientific_reading_only')


def enqueue(store, scope_path):
    store._require_dispatch_enabled()
    prepared = prepare_scope(scope_path)
    config = configuration(prepared)
    identifier = store.enqueue(work_id=prepared['work_id'], bundle_hash=prepared['bundle_sha256'],
                               config=config, max_attempts=1)
    return identifier


@contextmanager
def job_lock(store, identifier):
    if not re.fullmatch('[a-f0-9]{64}', identifier):
        raise ValueError('reader_job_identifier')
    folder = store.root / 'reader-locks'
    folder.mkdir(mode=0o700, exist_ok=True)
    with (folder / identifier).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def row(store, identifier):
    with store.connect() as db:
        value = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
    if value is None:
        raise ValueError('reader_unknown_job')
    result = dict(value); result['config'] = json.loads(result['config_json'])
    if result['config'].get('workflow') != WORKFLOW or result['max_attempts'] != 1:
        raise ValueError('reader_wrong_workflow_or_retry_policy')
    return result


def validate_job(job):
    for pin in job['config']['input_pins'] + job['config']['implementation']:
        checked(pin)
    prepared = prepare_scope(checked(job['config']['scope']))
    if (configuration(prepared) != job['config'] or prepared['work_id'] != job['work_id']
            or prepared['bundle_sha256'] != job['bundle_hash']):
        raise ValueError('reader_configuration_drift')
    return prepared


def _reading(text):
    def pairs(values):
        if len(dict(values)) != len(values):
            raise ValueError('reader_duplicate_json_key')
        return dict(values)
    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        raise ValueError('reader_invalid_output_json') from None
    if (not isinstance(value, dict) or set(value) != {'reading'}
            or not isinstance(value['reading'], str) or not value['reading'].strip()):
        raise ValueError('reader_invalid_output_container')
    return value


def _terminal(job, directory, *, recovered=False, error=None):
    receipt = dict(schema='materials-reviewed-reader-attempt/1', job_id=job['id'],
                   attempt_id=job['lease_token'], work_id=job['work_id'],
                   config_sha256=digest(job['config']), recovered_without_provider_call=recovered,
                   output_kind='scientific_reading_only', proposal_generated=False,
                   paper_completed=False, scientific_acceptance=False, ml_training_eligible=False,
                   production_writes=False, automatic_retry=False, usage={})
    marker = directory / 'provider-result.json'
    dispatched = (directory / 'DISPATCH_INTENT.json').exists()
    receipt['provider_dispatch_intent_recorded'] = dispatched
    if marker.exists() and error is None:
        try:
            validate_job(job)
            result = json.loads(marker.read_bytes())
            if (result['job_id'] != job['id'] or result['attempt_id'] != job['lease_token']
                    or result['config_sha256'] != digest(job['config'])
                    or result['result']['provider'] != 'codex' or result['result']['model'] != 'gpt-6-luna'):
                raise ValueError('reader_provider_result_identity')
            for pin in result['raw_artifacts']:
                checked(pin)
            receipt.update(provider_return=reference(marker), usage=result['result']['usage'])
            parsed = _reading(result['result']['text'])
            put(directory / 'reading.json', parsed)
            receipt.update(state='succeeded', reading=reference(directory / 'reading.json'),
                           outcome='reading_completed_pending_review')
        except (ValueError, KeyError, OSError) as exc:
            error = str(exc) if isinstance(exc, ValueError) else 'reader_recovery_artifact_invalid'
            receipt.update(state='quarantined', outcome='reading_not_admitted', error_code=error)
    else:
        receipt.update(state='blocked', outcome='completion_unknown' if dispatched else 'not_dispatched',
                       error_code=error or ('provider_completion_unknown' if dispatched else 'local_attempt_interrupted'))
        failure = directory / 'failure.json'
        if failure.exists():
            receipt['failure'] = reference(failure)
            receipt['usage'] = json.loads(failure.read_bytes()).get('usage', {})
    return receipt


def _existing(job):
    path = Path(job['result_path']) if job.get('result_path') else None
    if path is None or sha(path.read_bytes()) != job['result_hash']:
        raise ValueError('reader_terminal_receipt_missing_or_changed')
    receipt = json.loads(path.read_bytes())
    if receipt['job_id'] != job['id'] or receipt['config_sha256'] != digest(job['config']):
        raise ValueError('reader_terminal_receipt_identity')
    if receipt.get('reading'):
        checked(receipt['reading'])
        # Historical code may have advanced; the captured implementation and all
        # source inputs must still match the completed attempt. Never redraft on
        # a failed integrity check.
        for pin in job['config']['input_pins']:
            checked(pin)
        returned = json.loads(checked(receipt['provider_return']).read_bytes())
        for pin in returned['raw_artifacts']:
            checked(pin)
    return receipt


def _recover_locked(store, identifier):
    job = row(store, identifier)
    if job['state'] == 'queued':
        return None
    if job['state'] not in {'running', 'failed'} or (job['state'] == 'failed' and job['last_error'] != 'lease_expired'):
        return _existing(job)
    with store.connect() as db:
        attempt = dict(db.execute('SELECT * FROM attempts WHERE job_id=? AND ordinal=1', (identifier,)).fetchone())
    job['lease_token'] = attempt['id']
    directory = store.root / 'reader-attempts' / identifier / attempt['id']
    directory.mkdir(parents=True, exist_ok=True)
    receipt = _terminal(job, directory, recovered=True)
    _hold_uncertain_dispatch(store, receipt)
    path = directory / 'recovery-receipt.json'; put(path, receipt)
    pin, now = reference(path), time.time()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        live = dict(db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())
        if live['attempts'] != 1 or not (live['state'] == 'running' or
                (live['state'] == 'failed' and live['last_error'] == 'lease_expired')):
            raise ValueError('reader_recovery_state_changed')
        db.execute('UPDATE attempts SET status=?,finished_at=?,error_code=?,receipt_path=?,receipt_hash=?,usage_json=? WHERE id=?',
                   (receipt['state'], now, receipt.get('error_code'), str(path), pin['sha256'], canonical(receipt['usage']), attempt['id']))
        db.execute('UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,last_error=?,result_path=?,result_hash=?,updated_at=? WHERE id=?',
                   (receipt['state'], receipt.get('error_code'), str(path), pin['sha256'], now, identifier))
        store._audit(db, identifier, 'reviewed_reader_recovered_without_dispatch', dict(receipt=pin))
    return receipt


def recover(store, identifier):
    with job_lock(store, identifier):
        return _recover_locked(store, identifier)


def _hold_uncertain_dispatch(store, receipt):
    if receipt['outcome'] == 'completion_unknown':
        # Codex may expose authentication/quota failures as a generic failed
        # turn. Stop this queue for every uncertain dispatch, not just an error
        # string we happen to recognize. Never clear this marker automatically.
        put(store.root / 'READER_DISPATCH_HOLD.json', dict(
            schema='materials-reviewed-reader-dispatch-hold/1',
            reason='uncertain_provider_completion_requires_reconciliation',
            evidence='Inspect retained reader-attempts and queue audit before explicitly resuming.',
            automatic_resume=False))


def run(store, identifier, *, provider_override=None):
    with job_lock(store, identifier):
        previous = _recover_locked(store, identifier)
        if previous is not None:
            return previous
        job = store.claim(lease_seconds=1200, job_id=identifier, workflow=WORKFLOW)
        if job is None:
            raise ValueError('reader_job_not_claimable')
        directory = store.root / 'reader-attempts' / identifier / job['lease_token']
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        started = time.monotonic(); error = None
        try:
            prepared = validate_job(job)
            immutable(directory / 'input.txt', prepared['prompt'].encode())
            put(directory / 'source-spans.json', prepared['prompt_source_spans'])
            put(directory / 'request.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                                               config=job['config'], input_tokens_estimate=prepared['input_tokens_estimate'],
                                               output_token_limit_enforced_by_provider=False))
            for pin in job['config']['implementation']:
                immutable(directory / 'implementation' / Path(pin['path']).name, checked(pin).read_bytes())
            effective = dict(job['config'], image_inputs=[])
            if prepared['source_scope']['image_capture']:
                capture = json.loads(checked(prepared['source_scope']['image_capture']).read_bytes())
                preflight = json.loads(checked(prepared['source_scope']['preflight']).read_bytes())
                bundle = load_bundle(checked(preflight['bundle']))
                effective['image_inputs'] = page_images.materialize(capture, bundle, directory / 'images')
            provider = provider_override or CodexProvider()
            put(directory / 'DISPATCH_INTENT.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                                                       config_sha256=digest(job['config']), at=time.time()))
            response = provider.extract(prepared['prompt'], prepared['schema'], effective, directory)
            raw = [reference(p) for p in sorted(directory.rglob('*')) if p.is_file()]
            put(directory / 'provider-result.json', dict(job_id=identifier, attempt_id=job['lease_token'],
                config_sha256=digest(job['config']), result=asdict(response), raw_artifacts=raw))
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, ProviderFailure):
                error = exc.code
            elif isinstance(exc, ValueError) and re.fullmatch('reader_[a-z_]+', str(exc)):
                error = str(exc)
            else:
                error = 'reader_local_or_provider_interruption'
            put(directory / 'failure.json', dict(error_code=error, exception_class=type(exc).__name__,
                usage=exc.usage if isinstance(exc, ProviderFailure) else {},
                raw_artifacts=[reference(p) for p in sorted(directory.rglob('*')) if p.is_file()]))
        receipt = _terminal(job, directory, error=error)
        _hold_uncertain_dispatch(store, receipt)
        path = directory / 'receipt.json'; put(path, receipt)
        store.finish(job, state=receipt['state'], receipt_path=str(path), receipt_hash=sha(path.read_bytes()),
                     usage=receipt['usage'], duration_seconds=time.monotonic()-started,
                     error_code=receipt.get('error_code'), retryable=False)
        return receipt


def status(store):
    jobs = [j for j in store.results() if json.loads(j['config_json']).get('workflow') == WORKFLOW]
    return dict(schema='materials-reviewed-reader-status/1', jobs=len(jobs),
                states={s: sum(j['state'] == s for j in jobs) for s in sorted({j['state'] for j in jobs})},
                attempts=sum(j['attempts'] for j in jobs), paper_completions=0, proposals=0,
                scientific_admissions=0, qualified_ml_rows=0, production_writes=False)
