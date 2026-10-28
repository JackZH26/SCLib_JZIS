"""Portable-file boundary tests; no model, scientific acceptance or database."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materials_ner_source_objects import SourceObjects, frozen_file


def package(tmp_path):
    root = tmp_path / 'package'
    (root / 'objects').mkdir(parents=True)
    original = tmp_path / 'old-source'
    original.write_bytes(b'source bytes')
    h = hashlib.sha256(original.read_bytes()).hexdigest()
    (root / 'objects' / h).write_bytes(original.read_bytes())
    manifest = {'schema': 'materials-review-source-objects/1',
                'objects': [{'path': 'objects/' + h, 'sha256': h, 'size_bytes': 12}],
                'logical_path_to_sha256': {str(original): h}}
    return root, original, h, manifest


def store(root, manifest):
    raw = json.dumps(manifest).encode()
    (root / 'OBJECT_MANIFEST.json').write_bytes(raw)
    return SourceObjects(root, manifest_sha256=hashlib.sha256(raw).hexdigest())


def test_reads_relocated_object_with_original_missing(tmp_path):
    root, original, h, m = package(tmp_path)
    original.unlink()
    assert store(root, m).read({'path': str(original), 'sha256': h}) == b'source bytes'


def test_missing_object_does_not_fall_back_to_existing_original(tmp_path):
    root, original, h, m = package(tmp_path)
    resolver = store(root, m)
    (root / 'objects' / h).unlink()
    with pytest.raises(ValueError, match='package_file_missing'):
        resolver.read({'path': str(original), 'sha256': h})
    assert original.read_bytes() == b'source bytes'


def test_hash_and_mapping_are_both_required(tmp_path):
    root, original, h, m = package(tmp_path)
    resolver = store(root, m)
    with pytest.raises(ValueError, match='source_object_unmapped'):
        resolver.read({'path': str(original) + '-unlisted', 'sha256': h})
    (root / 'objects' / h).write_bytes(b'changed data')
    with pytest.raises(ValueError, match='package_file_changed'):
        resolver.read({'path': str(original), 'sha256': h})


def test_symlink_to_original_is_refused(tmp_path):
    root, original, h, m = package(tmp_path)
    (root / 'objects' / h).unlink()
    (root / 'objects' / h).symlink_to(original)
    with pytest.raises(ValueError, match='package_symlink_refused'):
        store(root, m).read({'path': str(original), 'sha256': h})


def test_manifest_pin_and_duplicate_objects(tmp_path):
    root, original, h, m = package(tmp_path)
    store(root, m)
    with pytest.raises(ValueError, match='package_file_changed'):
        SourceObjects(root, manifest_sha256='0' * 64)
    m['objects'] *= 2
    with pytest.raises(ValueError, match='source_object_duplicate'):
        store(root, m)


@pytest.mark.parametrize('path', ['../outside', '/absolute', 'objects/../outside', 'objects//object'])
def test_relative_package_boundary(tmp_path, path):
    with pytest.raises(ValueError, match='package_relative_path'):
        frozen_file(tmp_path, path, '0' * 64)
