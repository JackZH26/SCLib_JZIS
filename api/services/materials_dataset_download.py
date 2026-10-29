"""Versioned CSV snapshots. A changed canonical result invalidates the snapshot."""
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text

from services.materials_admission_scope import CURRENT_ADMISSION_WHERE

FILES = {kind: f'materials_{kind}.csv' for kind in ('results', 'evidence', 'training')}
VERSION_RE = re.compile(r'[0-9a-f]{64}')


async def canonical_download_state(db):
    # Hash all source rows used by the exporter, including same-ID corrections.
    # Database-local paths stay inside this fingerprint and never reach clients.
    # Keep composition lookup on its UUID index. Only canonical lowercase UUID
    # strings matched the former id::text comparison; ignore other spellings.
    rows = (await db.execute(text('''SELECT c.id::text AS id,
        md5(jsonb_build_object('claim',to_jsonb(c),'event',to_jsonb(ev),
            'state',to_jsonb(s),'sample',to_jsonb(rs),'protocol',to_jsonb(rp),
            'paper_status',p.status,'publication_status',w.publication_status,
            'compositions',(SELECT jsonb_agg(to_jsonb(sc) ORDER BY sc.id)
                FROM sample_compositions sc WHERE sc.id = ANY(ARRAY(
                SELECT CASE WHEN cid ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    THEN cid::uuid END
                FROM jsonb_array_elements_text(ev.context->'materials_context'->'composition_ids') AS ids(cid)))),
            'source_occurrences',(SELECT jsonb_agg(jsonb_build_object('occurrence',to_jsonb(o),
                'revision',to_jsonb(r)) ORDER BY o.id) FROM claim_source_occurrences o
                JOIN source_revisions r ON r.id=o.source_revision_id WHERE o.claim_id=c.id),
            'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM event_evidence e
                WHERE e.event_id=ev.id AND e.link_type='source'))::text) AS revision
        FROM material_claims c JOIN research_events ev ON ev.id=c.event_id
        JOIN material_states s ON s.id=ev.state_id JOIN research_samples rs ON rs.id=s.sample_id
        JOIN research_protocols rp ON rp.id::text=ev.context->'materials_context'->>'protocol_id'
        JOIN papers p ON p.id=c.paper_id JOIN works w ON w.id=c.work_id
        WHERE ''' + CURRENT_ADMISSION_WHERE + ' ORDER BY c.id'))).mappings().all()
    payload = '\n'.join(f"{row['id']}:{row['revision']}" for row in rows)
    return dict(schema='materials-download-state/1', rows=len(rows),
                sha256=hashlib.sha256(payload.encode()).hexdigest())


class DownloadUnavailable(ValueError):
    def __init__(self, status=503, message='Dataset downloads are being prepared'):
        self.status = status
        super().__init__(message)


def read_snapshot(root, requested_version=None):
    if not root:
        raise DownloadUnavailable(404, 'Dataset downloads are not enabled')
    root = Path(root).expanduser().resolve()
    try:
        version = json.loads((root / 'CURRENT.json').read_text())['version']
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ValueError('invalid version')
        if requested_version is not None and requested_version != version:
            raise DownloadUnavailable(409, 'This dataset snapshot is no longer current; reload Materials')
        folder = root / version
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):
            raise ValueError('invalid snapshot directory')
        snapshot = json.loads((folder / 'SNAPSHOT.json').read_text())
        if snapshot['version'] != version or snapshot['schema'] != 'materials-downloads/1':
            raise ValueError('invalid snapshot')
        if set(snapshot['files']) != set(FILES):
            raise ValueError('invalid files')
        for item in snapshot['files'].values():
            if not VERSION_RE.fullmatch(item['sha256']) or not isinstance(item['rows'], int) or item['rows'] < 0:
                raise ValueError('invalid file metadata')
        state = snapshot['canonical_state']
        if state['schema'] != 'materials-download-state/1' or state['rows'] != snapshot['files']['results']['rows'] or not VERSION_RE.fullmatch(state['sha256']):
            raise ValueError('invalid canonical state')
        return folder, snapshot
    except DownloadUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise DownloadUnavailable() from error


def assert_current(snapshot, state):
    if snapshot['canonical_state'] != state:
        raise DownloadUnavailable(409, 'The dataset changed; updated downloads are being prepared')


def public_snapshot(snapshot):
    # Explicit allowlist: never expose the private manifest or capture paths.
    public = {key: snapshot[key] for key in ('version', 'created_at', 'paper_count',
        'source_scope', 'training_policy', 'grouping_policy')}
    public['files'] = {kind: {key: snapshot['files'][kind][key] for key in ('rows', 'columns', 'sha256')}
        for kind in FILES}
    return public


def read_csv(folder, snapshot, kind):
    if kind not in FILES:
        raise DownloadUnavailable(404, 'Dataset file not found')
    path = folder / FILES[kind]
    try:
        if path.is_symlink():
            raise ValueError('linked file')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != snapshot['files'][kind]['sha256']:
            raise ValueError('file changed')
        return content
    except (OSError, ValueError) as error:
        raise DownloadUnavailable() from error
