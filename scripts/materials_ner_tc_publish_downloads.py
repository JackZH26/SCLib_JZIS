"""Publish verified CSV bytes after matching a fresh canonical database export."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from materials_ner_tc_export import export
from ingestion.materials_ner.reviewed_reader import immutable
from services.materials_dataset_download import FILES, canonical_download_state


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_csv_files(csv_dir):
    manifest = json.loads((csv_dir / 'MANIFEST.json').read_text())
    verified = json.loads((csv_dir / 'CSV_VERIFICATION.json').read_text())
    if manifest['schema'] != 'materials-tabular-export/3' or verified['schema'] not in {
        'materials-csv-verification/3', 'materials-csv-verification/4'}:
        raise ValueError('verified_provenance_export_required')
    if verified['source_dataset_sha256'] != manifest['source']['sha256']:
        raise ValueError('verification_source_mismatch')
    language_flags = ('no_cjk_or_private_paths',) if verified['schema'].endswith('/3') else (
        'no_cjk_in_structured_fields', 'private_paths_absent')
    for key in ('csv_roundtrip_verified', 'original_quotes_unchanged', 'quantity_relations_preserved',
        'no_unknown_pressure_imputation', 'no_known_group_split_leakage', *language_flags,
        'training_quality_and_lifecycle_metadata_verified', 'training_metadata_is_not_model_input'):
        if verified.get(key) is not True:
            raise ValueError(f'csv_verification_missing:{key}')
    artifacts = {Path(item['path']).name: item for item in manifest['artifacts']}
    files = {}
    for kind, name in FILES.items():
        item = artifacts[name]
        if sha(csv_dir / name) != item['sha256']:
            raise ValueError(f'csv_changed:{kind}')
        if item['rows'] != verified[f'{"result" if kind == "results" else kind}_rows']:
            raise ValueError(f'csv_count_mismatch:{kind}')
        files[kind] = dict(rows=item['rows'], columns=item['columns'], sha256=item['sha256'])
    return manifest, files


async def publish(database_url, csv_dir, output, check_output, evidence_root=None):
    csv_dir, output = Path(csv_dir), Path(output)
    manifest, files = checked_csv_files(csv_dir)
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as db:
            before = await canonical_download_state(db)
        report, _ = await export(database_url, check_output, evidence_root=evidence_root)
        async with engine.connect() as db:
            after = await canonical_download_state(db)
    finally:
        await engine.dispose()
    if before != after:
        raise ValueError('canonical_database_changed_during_snapshot_preparation')
    version = manifest['source']['sha256']
    if report['dataset']['sha256'] != version or report['rows'] != files['results']['rows'] or before['rows'] != report['rows']:
        raise ValueError('csv_does_not_match_current_canonical_database')
    snapshot = dict(schema='materials-downloads/1', version=version,
        created_at=manifest['created_at'], canonical_state=before, files=files,
        paper_count=report['papers'], source_scope=manifest['source_scope'],
        training_policy=manifest['training_source']['interpretation'],
        grouping_policy=manifest['training_source']['grouping'])
    folder = output / version
    folder.mkdir(parents=True, exist_ok=True)
    for kind, name in FILES.items():
        immutable(folder / name, (csv_dir / name).read_bytes())
    immutable(folder / 'SNAPSHOT.json', (json.dumps(snapshot, indent=2, sort_keys=True) + '\n').encode())
    pointer = output / 'CURRENT.next.json'
    pointer.write_text(json.dumps(dict(version=version)) + '\n')
    pointer.replace(output / 'CURRENT.json')
    return dict(version=version, rows=report['rows'], papers=report['papers'],
        published_at=datetime.now(timezone.utc).isoformat(), local_only=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database-url', required=True)
    p.add_argument('--csv-directory', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--check-output', type=Path, required=True)
    p.add_argument('--evidence-root', type=Path)
    a = p.parse_args()
    print(json.dumps(asyncio.run(publish(a.database_url, a.csv_directory, a.output,
        a.check_output, a.evidence_root)), indent=2))


if __name__ == '__main__':
    main()
