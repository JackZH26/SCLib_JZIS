"""Run the bounded Luna Tc profile using the existing durable queue."""
import argparse
import json
from pathlib import Path
from ingestion.materials_ner import production_tc
from ingestion.materials_ner.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('enqueue').add_argument('--input', type=Path, required=True)
    for name in ('run', 'recover'):
        sub.add_parser(name).add_argument('--job-id', required=True)
    args = parser.parse_args()
    store = Store(args.root)
    if args.command == 'enqueue':
        value = {'job_id': production_tc.enqueue(store, args.input)}
    else:
        value = getattr(production_tc, args.command)(store, args.job_id)
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
