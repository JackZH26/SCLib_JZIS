"""Prepare an isolated local queue and proposal store without enabling dispatch.

This command does not promote old attempts into a new campaign and does not run
the historical worker. The existing reviewed-drafting instruction remains the
scientific contract; its durable runner is a subsequent, separately tested step.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from materials_ner_source_manifest import reference, verify
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.proposals import ProposalDatabase
from ingestion.materials_ner.sources import private_write
from ingestion.materials_ner.store import Store


def prepare(root, *, name, manifest, manifest_sha256):
    root, manifest = Path(root), Path(manifest)
    if root.is_symlink() or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name):
        raise ValueError('invalid_staging_namespace')
    root, manifest = root.resolve(), manifest.resolve()
    verification = verify(manifest, sha256=manifest_sha256)
    source = json.loads(manifest.read_bytes())
    source_root = Path(source['source_root']).resolve()
    if (root.is_relative_to(source_root) or source_root.is_relative_to(root)
            or root.is_relative_to(manifest.parent) or manifest.is_relative_to(root)):
        raise ValueError('staging_namespace_must_be_separate')
    binding = {'schema': 'materials-staging-preparation/1', 'name': name,
               'root': str(root), 'source_manifest': reference(manifest),
               'workflow_intent': 'reviewed_drafting', 'requested_model': 'gpt-6-luna',
               'database_destination': 'local_proposal_staging_only',
               'model_dispatch': 'disabled_pending_source_preflight_and_durable_reader_adapter',
               'legacy_worker_dispatch': 'forbidden', 'production_writes': False,
               'scientific_acceptance': False, 'ml_training_eligible': False}
    marker = root / 'STAGING_PREPARATION.json'
    if root.exists():
        if (not marker.is_file() or marker.is_symlink()
                or json.loads(marker.read_bytes()) != binding):
            raise ValueError('existing_namespace_is_not_this_preparation')
    else:
        root.mkdir(parents=True, mode=0o700)
        private_write(marker, (canonical(binding) + '\n').encode())
    for name in ('queue.sqlite3', 'proposals.sqlite3'):
        if (root / name).is_symlink():
            raise ValueError('staging_database_must_be_local_regular_file')
    store, proposals = Store(root), ProposalDatabase(root)
    queue, database = store.summary(), proposals.summary()
    if queue['jobs'] or queue['attempts'] or any(database['tables'].values()):
        raise ValueError('preparation_namespace_must_remain_empty')
    return {'prepared': True, 'preparation': reference(marker),
            'source_verification': verification, 'queue': queue, 'proposal_database': database,
            'new_campaign_enqueued': 0, 'new_campaign_completed': 0,
            'model_calls': 0, 'production_writes': False, 'scientific_acceptance': False,
            'next_step': 'Freeze source-complete scopes and connect the existing reviewed reading to a durable adapter; do not use the legacy run command.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, name=args.name, manifest=args.manifest,
                             manifest_sha256=args.manifest_sha256)))


if __name__ == '__main__':
    main()
