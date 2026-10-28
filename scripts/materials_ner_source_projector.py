"""Explicit commands for a single-attempt source-to-graph diagnostic stage."""
import argparse
import json
from pathlib import Path
from ingestion.materials_ner import source_projector as projector
from ingestion.materials_ner.store import Store


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('enqueue').add_argument('--input', type=Path, required=True)
    for name in ['run', 'recover']:
        sub.add_parser(name).add_argument('--job-id', required=True)
    args = p.parse_args(argv)
    store = Store(args.root)
    if args.command == 'enqueue':
        result = dict(job_id=projector.enqueue(store, args.input))
    else:
        result = getattr(projector, args.command)(store, args.job_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
