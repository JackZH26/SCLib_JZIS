"""Offline checkpoint for complete Similar candidate lists from one sealed graph.

Only immutable candidate bindings and distances belong here. Access decisions,
current paper attribution, response construction and final pin checks remain
on the normal request path. A checkpoint is not a serving or coverage receipt.
"""
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct

WIDTH = 55  # Maximum supported top_k (50), plus the existing five spare candidates.
ENTRY = struct.Struct('>Id')
HASH = re.compile('[0-9a-f]{64}')
BINDINGS = ('content_sha256', 'vector_sha256', 'chunk_revision_sha256')


def digest_bytes(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError('Expected a canonical SHA-256 digest')
    return bytes.fromhex(value)


def exclusions_digest(revisions):
    ordered = sorted(digest_bytes(revision) for revision in revisions)
    if not ordered or len(ordered) > 20000 or len(set(ordered)) != len(ordered):
        raise ValueError('Invalid source revision inventory')
    return hashlib.sha256(b''.join(ordered)).hexdigest()


def identity(scope):
    return json.dumps({'format': 1, 'width': WIDTH, 'scope': scope},
                      sort_keys=True, separators=(',', ':'), allow_nan=False)


def create(path, scope):
    path = Path(path)
    # Refuse to initialize over another artifact, even if it is an empty file.
    with path.open('xb'):
        pass
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), scope TEXT NOT NULL)')
        db.execute('INSERT INTO meta VALUES (1,?)', (identity(scope),))
        db.execute('CREATE TABLE targets (slot INTEGER PRIMARY KEY, vector_id TEXT UNIQUE NOT NULL, '
                   'paper TEXT NOT NULL, bindings BLOB NOT NULL CHECK(length(bindings)=96))')
        db.execute('CREATE TABLE origins (paper TEXT NOT NULL, source BLOB NOT NULL CHECK(length(source)=32), '
                   'exclusions BLOB NOT NULL CHECK(length(exclusions)=32), ranks BLOB NOT NULL, '
                   'PRIMARY KEY(paper,source)) WITHOUT ROWID')


def open_existing(path, scope, *, writable=False):
    uri = Path(path).resolve().as_uri() + ('?mode=rw' if writable else '?mode=ro')
    db = sqlite3.connect(uri, uri=True)
    try:
        row = db.execute('SELECT scope FROM meta WHERE singleton=1').fetchone()
        if row != (identity(scope),):
            raise ValueError('Checkpoint identity mismatch')
        return db
    except BaseException:
        db.close()
        raise


def save(db, paper, source_sha, exclusion_sha, hits):
    """Publish one complete origin atomically. A conflicting replay rolls back."""
    source, exclusions = digest_bytes(source_sha), digest_bytes(exclusion_sha)
    if len(hits) != WIDTH:
        raise ValueError('A complete frontier is required')
    entries = []
    seen = set()
    previous = -1.0
    with db:
        for hit in hits:
            vid, target, distance = hit['vector_id'], hit['paper_id'], hit['distance']
            if (not vid or not target or vid in seen or type(distance) not in (int, float)
                    or not math.isfinite(distance) or not 0 <= distance <= 2 or distance < previous):
                raise ValueError('Invalid ordered candidate')
            seen.add(vid)
            previous = distance
            payload = b''.join(digest_bytes(hit[k]) for k in BINDINGS)
            db.execute('INSERT INTO targets(vector_id,paper,bindings) VALUES (?,?,?) '
                       'ON CONFLICT(vector_id) DO NOTHING', (vid, target, payload))
            slot, bound_paper, bindings = db.execute(
                'SELECT slot,paper,bindings FROM targets WHERE vector_id=?', (vid,)).fetchone()
            if (bound_paper, bindings) != (target, payload):
                raise ValueError('Conflicting target binding')
            entries.append(ENTRY.pack(slot, distance))
        ranks = b''.join(entries)
        db.execute('INSERT INTO origins VALUES (?,?,?,?) ON CONFLICT(paper,source) DO NOTHING',
                   (paper, source, exclusions, ranks))
        if db.execute('SELECT exclusions,ranks FROM origins WHERE paper=? AND source=?',
                      (paper, source)).fetchone() != (exclusions, ranks):
            raise ValueError('Conflicting origin replay')


def read(db, paper, source_sha, exclusion_sha, limit):
    """Return an ordered prefix, or None on a miss. Never return partial rows."""
    if type(limit) is not int or not 1 <= limit <= WIDTH:
        raise ValueError('Invalid frontier limit')
    row = db.execute('SELECT ranks FROM origins WHERE paper=? AND source=? AND exclusions=?',
                     (paper, digest_bytes(source_sha), digest_bytes(exclusion_sha))).fetchone()
    if row is None:
        return None
    if len(row[0]) != WIDTH * ENTRY.size:
        raise ValueError('Incomplete stored frontier')
    ranks = list(ENTRY.iter_unpack(row[0]))[:limit]
    slots = [slot for slot, _ in ranks]
    query = 'SELECT slot,vector_id,paper,bindings FROM targets WHERE slot IN (' + ','.join('?' * limit) + ')'
    targets = {slot: (vid, target, hashes) for slot, vid, target, hashes in db.execute(query, slots)}
    if len(targets) != limit:
        raise ValueError('Missing or repeated target')
    result = []
    previous = -1.0
    for slot, distance in ranks:
        vid, target, hashes = targets[slot]
        if len(hashes) != 96 or not previous <= distance <= 2 or distance < 0:
            raise ValueError('Invalid stored frontier')
        previous = distance
        binding = {k: hashes[i*32:(i+1)*32].hex() for i, k in enumerate(BINDINGS)}
        result.append(dict(vector_id=vid, paper_id=target, distance=distance, **binding))
    return result
