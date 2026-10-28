"""Capture, verify or locally import an existing automatic draft; never dispatch."""
import argparse
import json
from pathlib import Path

from ingestion.materials_ner import projector_proposals, reviewed_reader
from ingestion.materials_ner.proposals import verify_packet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build')
    build.add_argument('--queue', required=True, type=Path)
    build.add_argument('--job-id', required=True)
    build.add_argument('--findings', type=Path)
    build.add_argument('--output', required=True, type=Path)
    for name in ['verify', 'ingest']:
        item = sub.add_parser(name)
        item.add_argument('--packet', required=True, type=Path)
        if name == 'ingest': item.add_argument('--root', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'build':
        packet = projector_proposals.build(args.queue, args.job_id, review_findings=args.findings)
        reviewed_reader.put(args.output, packet)
        result = dict(packet=reviewed_reader.reference(args.output), results=len(packet['rows']['results']))
    else:
        packet = json.loads(args.packet.read_bytes()); verify_packet(packet)
        result = (projector_proposals.ingest_local(packet, args.root) if args.command == 'ingest'
                  else dict(verified=True, run_id=packet['run_id']))
    print(json.dumps(dict(result, model_calls=0, scientific_acceptance=False, production_writes=False)))


if __name__ == '__main__':
    main()
