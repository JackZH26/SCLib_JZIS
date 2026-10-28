"""Read frozen source objects without opening their historical logical paths."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def digest_shape(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def frozen_file(root, relative, expected_sha256, size_bytes=None):
    """Only regular files below the explicit package root; no symlink traversal."""
    require(isinstance(relative, str) and digest_shape(expected_sha256), 'package_file_pin')
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and relative == parts.as_posix()
            and bool(parts.parts) and not set(parts.parts) & {'.', '..'}, 'package_relative_path')
    root = Path(root).resolve(strict=True)
    path = root
    for part in parts.parts:
        path /= part
        require(not path.is_symlink(), 'package_symlink_refused')
    require(path.is_file(), 'package_file_missing')
    if size_bytes is not None:
        require(type(size_bytes) is int and size_bytes >= 0
                and path.stat().st_size == size_bytes, 'package_file_size')
    data = path.read_bytes()
    require(sha256(data) == expected_sha256, 'package_file_changed')
    return data


class SourceObjects:
    """Resolve a logical (path, hash) pair through one explicitly pinned manifest.

    Logical paths remain unchanged inside provenance and review subjects. They
    are identifiers here, never a fallback filesystem location. The manifest
    and bytes must travel together and be retained by the operator.
    """

    def __init__(self, root, *, manifest_sha256):
        self.root = Path(root).resolve(strict=True)
        raw = frozen_file(self.root, 'OBJECT_MANIFEST.json', manifest_sha256)
        manifest = json.loads(raw)
        require(manifest['schema'] == 'materials-review-source-objects/1', 'source_objects_version')
        objects = manifest['objects']
        require(isinstance(objects, list) and objects, 'source_objects_empty')
        self.objects = {}
        for row in objects:
            h = row['sha256']
            require(digest_shape(h) and row['path'] == 'objects/' + h
                    and type(row['size_bytes']) is int and row['size_bytes'] >= 0,
                    'source_object_shape')
            require(h not in self.objects, 'source_object_duplicate')
            self.objects[h] = row
        self.logical_paths = manifest['logical_path_to_sha256']
        require(isinstance(self.logical_paths, dict) and self.logical_paths
                and all(isinstance(p, str) and p and h in self.objects
                        for p, h in self.logical_paths.items()), 'source_object_mapping')
        require(set(self.logical_paths.values()) == set(self.objects), 'source_object_mapping_coverage')
        self.manifest_sha256 = manifest_sha256
        self.read_hashes = set()

    def read(self, ref):
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'pinned_file_shape')
        require(isinstance(ref['path'], str) and digest_shape(ref['sha256']), 'pinned_file_shape')
        require(self.logical_paths.get(ref['path']) == ref['sha256'], 'source_object_unmapped')
        row = self.objects[ref['sha256']]
        data = frozen_file(self.root, row['path'], row['sha256'], row['size_bytes'])
        self.read_hashes.add(row['sha256'])
        return data
