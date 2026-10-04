"""Build a lossless, versioned Organic reference reader from the pinned NIMS file."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

SOURCE_SHA256 = "d116848a90d01e48356ed6cf0bb69035fa863a3a559deac1ef188025bdb3b423"
HEADER_SHA256 = "c1e031a258d9c822eeba109fb40a76198219af1735c35c586f7332dbaf936fa7"
FILENAME = "materials-mdr-organic-240322.json"
COLUMNS = "num refno name fullname shape str lata latb latc alpha beta lgamma tc tcmax pmax pcrit tcmeth isotope isoel dtcdp tcn hc1zero hc2zero dhc2dt cohere penet glpar gap gapmeth gamma debyet curiet neelt fig1 fig2 figname tbl tblname commt f1_filename f2_filename title year keyword institute journal author sample comments".split()


def build(raw: bytes) -> dict:
    if len(raw) != 263372 or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected versioned Organic source bytes")
    lines = raw.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), delimiter="\t")
    labels, columns = next(reader), next(reader)
    if columns != COLUMNS or len(labels) != 49 or hashlib.sha256(b"".join(lines[:2])).hexdigest() != HEADER_SHA256:
        raise ValueError("Unexpected Organic headers")
    rows, excluded, seen = [], [], set()
    previous = reader.line_num
    for values in reader:
        start, end = previous + 1, reader.line_num
        previous = end
        if len(values) != len(columns):
            raise ValueError("Unexpected source width")
        digest = hashlib.sha256(b"".join(lines[start - 1:end])).hexdigest()
        if not any(values):
            excluded.append({"line_start": start, "line_end": end, "sha256": digest, "reason": "all_cells_empty"})
            continue
        if not values[0].isdigit() or values[0] in seen:
            raise ValueError("Invalid source row identity")
        seen.add(values[0])
        rows.append({"id": values[0], "line_start": start, "line_end": end, "sha256": digest, "values": values})
    if len(rows) != 568 or len(excluded) != 1 or reader.line_num != len(lines):
        raise ValueError("Unexpected source row inventory")
    return {
        "version": "mdr-organic-reference/1.0.0", "dataset_version": "240322",
        "dataset_url": "https://doi.org/10.48505/nims.4487",
        "source": {"filename": "240322_MDR_Organic.txt", "bytes": len(raw), "sha256": SOURCE_SHA256,
                   "header_sha256": HEADER_SHA256, "url": "https://mdr.nims.go.jp/filesets/1a18e447-8ec2-4316-be12-b4acdc885fb8/download",
                   "guide_url": "https://mdr.nims.go.jp/filesets/dd00e931-e7b7-4bc5-bde2-ba0ff1e9adaf/download",
                   "guide_page": 9, "guide_sha256": "89096c1f006a5d5c256d14394880b31684ad2ce0b4f7ea0d37175256ea6a029d"},
        "attribution": "MDR SuperCon Datasheet Ver.240322, National Institute for Materials Science (NIMS), DOI 10.48505/nims.4487. SCLib preserves all original Organic cells and adds row provenance and a reading interface.",
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "columns": columns, "source_labels": labels, "rows": rows, "excluded_rows": excluded,
        "coverage": {column: sum(bool(row["values"][i]) for row in rows) for i, column in enumerate(columns)},
        "interpretation": {"units": "Only pcrit explicitly names GPa in the table header. Other numeric columns have no unit columns; no numeric normalization is performed.",
                           "tc": "The actual source header says Tc at pcrit or atmospheric pressure; the guide abbreviates it as Tc at pcrit. Missing pcrit does not establish ambient pressure.",
                           "tcmax": "Maximum Tc under pressure; pmax is its associated applied pressure, unlike the oxide/metallic table pmax definition.",
                           "tcn": "Lowest measurement temperature for a non-superconducting report, not a Tc value.",
                           "names": "Common name can contain only the counterion; full name, structure label, isotope and comments remain separate. No molecular expansion, phase or sample matching is inferred."},
        "scope": {"source_publication_status": "not_checked", "scientific_acceptance": False,
                  "catalogue_association": "unestablished", "ml_training_approved": False, "canonical_properties_modified": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "frontend/public/research-pilots")
    args = parser.parse_args()
    if args.source.stat().st_size != 263372:
        parser.error("Unexpected source size")
    raw = args.source.read_bytes()
    payload = (json.dumps(build(raw), ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / FILENAME).write_bytes(payload)
    (args.output / (FILENAME + ".sha256")).write_text(hashlib.sha256(payload).hexdigest() + "  " + FILENAME + "\n")
    (args.output / "240322_MDR_Organic.txt").write_bytes(raw)
    print(json.dumps({"rows": 568, "excluded_empty_rows": 1, "columns": 49, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}))


if __name__ == "__main__":
    main()
