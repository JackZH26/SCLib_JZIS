"""Read optional original-paper regression fixtures without publishing archives.

Set SCLIB_NER_PRIVATE_FIXTURES to the existing fixture directory to replay these
checks locally. Synthetic regression tests require no private files. Missing
originals are reported as skips; supplied files must match their retained hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

EXPECTED_SHA256 = {'materials_ner_catalog_integrity_failures.json': 'e6ca1f6a928d17f0edc866ce143b496c5aab9763bc16f5cd8e45d9a195726dda', 'materials_ner_source_selection_failures.json': 'e72cc5bf0cc5c5d59b72e58941fe91c494941d143b2c3fc213bf51ceda2a5be9', 'materials_ner_quantity_state_failures.json': '06fdf8d905006b0d1fde5acdae9cd74e35f148c32e6f4b7a3974a00f7240ec64', 'materials_ner_table_ownership_ledger.json': 'd161984d5c2e0a9e5c21639f18afa32bc2197092bf07023ad3d92abe805b0f04', 'materials_ner_task_feature_failure.json': 'b621ed69bb47bca16f0de4134c69a62cb7a57a2c172606aec3f4e7de0f78a98a', 'materials_ner_compiled_catalog_source.json': '6952e5ea6e22dcf56b865b2f9efb7908085cf3122097c19e2786d8b2bded3321', 'materials_ner_owner_witness_w4.json': '23bbc4b80c488e001c9c625ed8fb2f6769819c4bbf43b3c9f4967cd54eea896c'}


def private_json(name: str):
    expected = EXPECTED_SHA256[name]
    root = Path(os.environ.get("SCLIB_NER_PRIVATE_FIXTURES", Path(__file__).parent / "fixtures"))
    path = root / name
    if not path.is_file():
        pytest.skip(f"Original-paper regression fixture is private: {name}; set SCLIB_NER_PRIVATE_FIXTURES to replay")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise AssertionError(f"Private fixture bytes changed: {name} ({actual})")
    return json.loads(raw)
