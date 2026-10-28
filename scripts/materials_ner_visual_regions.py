"""Capture one original PDF page and local OCR, without model calls or writes to a database."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ingestion'))
from ingestion.materials_ner import reviewed_reader, visual_regions
from ingestion.materials_ner.contract import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--page', type=int, required=True)
    parser.add_argument('--dpi', type=int, default=200)
    parser.add_argument('--renderer', type=Path, required=True)
    parser.add_argument('--ocr-executable', type=Path, required=True)
    parser.add_argument('--ocr-source', type=Path, required=True)
    parser.add_argument('--ocr-region', nargs=4, type=float,
        help='Optional normalized left top right bottom OCR region; requires the v2 recognizer. The page image remains uncropped.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise ValueError('visual_output_exists')
    asset = visual_regions.capture_pdf(reviewed_reader.reference(args.preflight), page=args.page, dpi=args.dpi,
        renderer=args.renderer, ocr_executable=args.ocr_executable, ocr_source=args.ocr_source, ocr_region=args.ocr_region)
    reviewed_reader.put(args.output, asset)
    print(canonical(reviewed_reader.reference(args.output)))


if __name__ == '__main__': main()
