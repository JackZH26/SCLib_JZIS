"""Explicit source-role workflow; decisions never authorize database admission."""
import argparse
import json
from pathlib import Path
from ingestion.materials_ner.census import roles
from ingestion.materials_ner.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('enqueue').add_argument('--input', type=Path, required=True)
    for name in ['run', 'recover']:
        commands.add_parser(name).add_argument('--job-id', required=True)
    args = parser.parse_args(argv)
    store = Store(args.root)
    result = dict(job_id=roles.enqueue(store, args.input)) if args.command == 'enqueue' else getattr(roles, args.command)(store, args.job_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
