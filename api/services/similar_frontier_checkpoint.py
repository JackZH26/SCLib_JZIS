"""Offline checkpoint for complete Similar candidate lists from one sealed graph.

Only immutable candidate bindings and distances belong here. Access decisions,
current paper attribution, response construction and final pin checks remain
on the normal request path. A checkpoint is not a serving or coverage receipt.
"""
from contextlib import closing
import hashlib
from itertools import groupby
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
from tempfile import TemporaryDirectory

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
    # A crash during schema creation must not publish a partly initialized checkpoint.
    with TemporaryDirectory(dir=path.parent) as work:
        staging = Path(work) / 'new.sqlite'
        with closing(sqlite3.connect(staging)) as db, db:
            db.execute('CREATE TABLE meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), scope TEXT NOT NULL)')
            db.execute('INSERT INTO meta VALUES (1,?)', (identity(scope),))
            db.execute('CREATE TABLE targets (slot INTEGER PRIMARY KEY, vector_id TEXT UNIQUE NOT NULL, '
                       'paper TEXT NOT NULL, bindings BLOB NOT NULL CHECK(length(bindings)=96))')
            db.execute('CREATE TABLE origins (paper TEXT NOT NULL, source BLOB NOT NULL CHECK(length(source)=32), '
                       'exclusions BLOB NOT NULL CHECK(length(exclusions)=32), ranks BLOB NOT NULL, '
                       'PRIMARY KEY(paper,source)) WITHOUT ROWID')
        staging.chmod(0o600)
        os.link(staging, path)  # Exclusive; an existing checkpoint always wins.



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


def verify_coverage(path, scope, members, *, sealed_member_count):
    """Compare a checkpoint with an independent sealed member stream, in C paper/id order.

    Each input row supplies paper_id, vector_id and the three digest bindings.
    The caller must obtain it from the scope's sealed content in one snapshot.
    Only the first 20 positions can be sources. All revisions remain exclusions,
    and even members beyond position 20 may appear in the target dictionary.
    """
    if type(sealed_member_count) is not int or sealed_member_count <= 0:
        raise ValueError('A nonempty sealed inventory is required')
    papers = positions = total = origins = targets = 0
    last_paper = ''
    with closing(open_existing(path, scope)) as db:
        db.execute('BEGIN')
        for paper, group in groupby(members, key=lambda member: member['paper_id']):
            if not isinstance(paper, str) or not last_paper < paper or len(paper) > 100:
                raise ValueError('Invalid sealed paper order')
            last_paper = paper
            last_vector = ''
            revisions = set()
            sources = set()
            for member in group:
                vid = member['vector_id']
                if not isinstance(vid, str) or not last_vector < vid:
                    raise ValueError('Invalid sealed member order')
                last_vector = vid
                payload = b''.join(digest_bytes(member[k]) for k in BINDINGS)
                revision = member['chunk_revision_sha256']
                if revision in revisions or len(revisions) >= 20000:
                    raise ValueError('Invalid sealed revision inventory')
                if len(revisions) < 20:
                    sources.add(member['vector_sha256'])
                    positions += 1
                revisions.add(revision)
                target = db.execute('SELECT paper,bindings FROM targets WHERE vector_id=?', (vid,)).fetchone()
                if target is not None:
                    if target != (paper, payload):
                        raise ValueError('Candidate binding differs from sealed member')
                    targets += 1
                total += 1
            exclusion_sha = exclusions_digest(revisions)
            for source in sources:
                hits = read(db, paper, source, exclusion_sha, WIDTH)
                if hits is None or any(hit['chunk_revision_sha256'] in revisions for hit in hits):
                    raise ValueError('Required source absent or exclusion violated')
                origins += 1
            papers += 1
        if (total != sealed_member_count
                or origins != db.execute('SELECT count(*) FROM origins').fetchone()[0]
                or targets != db.execute('SELECT count(*) FROM targets').fetchone()[0]):
            raise ValueError('Incomplete coverage or unexpected checkpoint entries')
    return dict(papers=papers, members=total, source_positions=positions,
                distinct_origins=origins, bound_targets=targets)
