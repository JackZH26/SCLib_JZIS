"""Crash/replay and graph isolation checks for staged Similar candidate artifacts."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import similar_frontier_checkpoint as store


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.path = Path(work.name) / 'frontier.sqlite'
        self.scope = {'build': 'primary', 'content': 'sealed-test', 'policy': 'fixture'}
        self.source = digest('source')
        self.excluded = store.exclusions_digest([digest('first'), digest('second')])
        self.hits = [dict(vector_id=f'v{i}', paper_id=f'p{i//2}', distance=i / 71,
                          **{k: digest(f'{k}-{i}') for k in store.BINDINGS}) for i in range(store.WIDTH)]
        store.create(self.path, self.scope)

    def test_interrupted_conflicting_source_rolls_back_dictionary_and_resumes(self):
        with closing(store.open_existing(self.path, self.scope, writable=True)) as db:
            store.save(db, 'paper', self.source, self.excluded, self.hits)
            other = [dict(self.hits[0], vector_id='new'), dict(self.hits[1], paper_id='wrong'), *self.hits[2:]]
            with self.assertRaises(ValueError):
                store.save(db, 'paper', digest('next'), self.excluded, other)
        with closing(store.open_existing(self.path, self.scope, writable=True)) as db:
            self.assertIsNone(db.execute("SELECT slot FROM targets WHERE vector_id='new'").fetchone())
            self.assertIsNone(store.read(db, 'paper', digest('next'), self.excluded, 1))
            store.save(db, 'paper', self.source, self.excluded, self.hits)
            store.save(db, 'paper', digest('next'), self.excluded, self.hits)
            self.assertEqual(db.execute('SELECT count(*) FROM targets').fetchone(), (store.WIDTH,))
        with closing(store.open_existing(self.path, self.scope)) as db:
            self.assertEqual(store.read(db, 'paper', digest('next'), self.excluded, 55), self.hits)
            self.assertEqual(store.read(db, 'paper', self.source, self.excluded, 15), self.hits[:15])
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM targets')

    def test_changed_scope_or_exclusions_cannot_return_stale_or_partial_hits(self):
        with closing(store.open_existing(self.path, self.scope, writable=True)) as db:
            store.save(db, 'paper', self.source, self.excluded, self.hits)
            self.assertIsNone(store.read(db, 'paper', self.source, digest('changed'), 15))
            self.assertIsNone(store.read(db, 'different-paper', self.source, self.excluded, 15))
            with self.assertRaises(ValueError):
                store.save(db, 'paper', self.source, self.excluded, self.hits[:54])
            db.execute('DELETE FROM targets WHERE vector_id=?', ('v5',))
            with self.assertRaises(ValueError):
                store.read(db, 'paper', self.source, self.excluded, 15)
        with self.assertRaises(ValueError):
            store.open_existing(self.path, {**self.scope, 'build': 'standby'})

if __name__ == '__main__':
    unittest.main()
