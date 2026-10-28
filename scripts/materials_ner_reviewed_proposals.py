"""Local reviewed proposal/coverage CLI. No provider dispatch or remote writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ingestion'))
from ingestion.materials_ner import paper_coverage, reviewed_proposals, reviewed_reader
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.sources import load_bundle
from ingestion.materials_ner.store import Store


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); commands = p.add_subparsers(dest='action', required=True)
    seed = commands.add_parser('coverage-seed')
    seed.add_argument('--preflight', type=Path, required=True)
    seed.add_argument('--review', type=Path, required=True, help='JSON author and timezone-qualified created_at')
    seed.add_argument('--output', type=Path, required=True)
    build = commands.add_parser('project')
    for flag in ['reader-root', 'graph', 'coverage', 'review', 'output']:
        build.add_argument('--' + flag, type=Path, required=True)
    build.add_argument('--job-id', required=True)
    build.add_argument('--visual-evidence', type=Path)
    ingest = commands.add_parser('ingest-local')
    ingest.add_argument('--packet', type=Path, required=True); ingest.add_argument('--root', type=Path, required=True)
    status = commands.add_parser('paper-status')
    status.add_argument('--coverage', type=Path, required=True); status.add_argument('--bundle', type=Path, required=True)
    status.add_argument('--packet', type=Path, action='append', default=[])
    status.add_argument('--reconciliation', type=Path, help='Attributed source-unit/result dispositions; required for paper readiness')
    args = p.parse_args(argv)
    def read(path): return json.loads(path.read_text())
    if args.action == 'coverage-seed':
        review = read(args.review)
        result = paper_coverage.seed(reviewed_reader.reference(args.preflight), **review)
        reviewed_reader.put(args.output, result); result = reviewed_reader.reference(args.output)
    elif args.action == 'project':
        if not (args.reader_root / 'queue.sqlite3').is_file(): raise ValueError('existing_reader_queue_required')
        result = reviewed_proposals.build(Store(args.reader_root), args.job_id, graph=read(args.graph),
            manifest=read(args.coverage), visual_support=read(args.visual_evidence) if args.visual_evidence else None,
            **read(args.review))
        reviewed_reader.put(args.output, result); result = reviewed_reader.reference(args.output)
    elif args.action == 'ingest-local':
        result = reviewed_proposals.ingest_local(read(args.packet), args.root)
    else:
        result = reviewed_proposals.paper_status(read(args.coverage), load_bundle(args.bundle), [read(p) for p in args.packet],
            reconciliation=read(args.reconciliation) if args.reconciliation else None)
    print(canonical(result))


if __name__ == '__main__': main()
