"""Explicit local commands for the fixed reviewed-reading stage."""
from pathlib import Path
import argparse
import json

from ingestion.materials_ner import reviewed_reader as reader
from ingestion.materials_ner.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    enqueue = sub.add_parser('enqueue')
    enqueue.add_argument('--scope', type=Path, required=True)
    for name in ['run', 'recover']:
        sub.add_parser(name).add_argument('--job-id', required=True)
    sub.add_parser('status')
    args = parser.parse_args(argv)
    store = Store(args.root)
    if args.command == 'enqueue':
        result = {'job_id': reader.enqueue(store, args.scope)}
    elif args.command == 'run':
        result = reader.run(store, args.job_id)
    elif args.command == 'recover':
        result = reader.recover(store, args.job_id)
    else:
        result = reader.status(store)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
