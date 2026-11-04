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

    def test_coverage_uses_all_exclusions_and_checks_dictionary_beyond_first_20(self):
        groups = {}
        for paper in ('a', 'b'):
            rows = [dict(vector_id=f'{paper}{i:02d}', paper_id=paper, distance=i / 71,
                         **{k: digest(f'{paper}-{k}-{i}') for k in store.BINDINGS}) for i in range(56)]
            rows[1]['vector_sha256'] = rows[0]['vector_sha256']
            groups[paper] = rows
        members = groups['a'] + groups['b']
        def verify(inventory=members):
            return store.verify_coverage(self.path, self.scope, iter(inventory), sealed_member_count=len(members))
        with closing(store.open_existing(self.path, self.scope, writable=True)) as db:
            for paper, other in [('a', 'b'), ('b', 'a')]:
                revisions = store.exclusions_digest([m['chunk_revision_sha256'] for m in groups[paper]])
                for source in groups[paper][:20]:
                    store.save(db, paper, source['vector_sha256'], revisions, groups[other][:store.WIDTH])
            self.assertEqual(verify(), dict(papers=2, members=112, source_positions=40,
                                            distinct_origins=38, bound_targets=110))
            changed = list(members)
            changed[54] = dict(changed[54], content_sha256=digest('different'))
            with self.assertRaisesRegex(ValueError, 'binding'):
                verify(changed)
            changed[54] = members[54]
            changed[55] = dict(changed[55], chunk_revision_sha256=digest('different'))
            with self.assertRaisesRegex(ValueError, 'source absent'):
                verify(changed)
            with self.assertRaisesRegex(ValueError, 'order'):
                verify(members[::-1])
            store.save(db, 'extra', self.source, self.excluded, groups['a'][:store.WIDTH])
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                verify()
            with db:
                db.execute("DELETE FROM origins WHERE paper='a'")
            with self.assertRaisesRegex(ValueError, 'source absent'):
                verify()

if __name__ == '__main__':
    unittest.main()
