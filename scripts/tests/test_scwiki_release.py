import copy
import json
from pathlib import Path
import unittest

from scripts.verify_scwiki_release import API, Client, collection, verify

class Fixture:
    origin = 'https://jzis.org'

    def __init__(self):
        self.requests = 0
        self.articles = [{'id': 'scwiki-'+key, 'slug': key, 'revision': key+'-revision',
                          'markdown': '# '+key, 'review': {'scope': 'limited'},
                          'claims': [{'statement': 'scoped fixture'}]} for key in ('a1', 'a2', 'i', 'n1')]
        self.catalogue = {'revision': 'catalogue', 'articles': self.articles}
        self.library = {'notes': [{'id': 'note', 'review': {'scope': 'limited'}}]}
        self.routes = {
            '/': (200, b'<a href="/scwiki">Wiki</a><input name="q">', {}),
            '/scwiki': (200, ('<main data-revision="catalogue">'+''.join(
                '<a href="/scwiki/'+a['slug']+'">Topic</a>' for a in self.articles)+'</main>').encode(), {}),
            '/search?q=Meissner&source=release-smoke': (307, b'', {'location': '/?q=Meissner&source=release-smoke'}),
        }
        self.put(API+'revisions?limit=50', self.page('records', [
            {'id': a['id'], 'revision': a['revision']} for a in self.articles]), 'catalogue')
        self.put(API+'library?limit=50', self.page('notes', [dict(self.library['notes'][0], revision='note-r')]), 'catalogue')
        for article in self.articles:
            self.put(API+'articles/'+article['id'], {'article': article}, article['revision'])
        self.put(API+'search?q=Meissner&limit=50', {'results': [{'id': 'scwiki-a2'}]}, 'catalogue')
        self.routes[API+'articles/scwiki-a1/markdown'] = (200, b'# a1', {'x-scwiki-revision': 'a1-revision'})

    def page(self, key, records):
        return {'revision': 'catalogue', key: records, 'total': len(records),
                'page': {'returned': len(records), 'next': None, 'nextCursor': None}}

    def put(self, path, data, revision):
        self.routes[path] = (200, json.dumps(data).encode(), {'content-type': 'application/json', 'x-scwiki-revision': revision})

    def get(self, path):
        self.requests += 1
        return copy.deepcopy(self.routes[path])

    def check(self):
        return verify(self, self.catalogue, self.library)

class ReleaseSmokeTests(unittest.TestCase):
    def test_deploy_checks_public_wiki_before_persisting_release_pins(self):
        workflow = (Path(__file__).resolve().parents[2]/'.github/workflows/deploy.yml').read_text()
        start = workflow.index('python3 scripts/verify_scwiki_release.py')
        end = workflow.index('# Persist only after every smoke check succeeds.')
        self.assertLess(start, end)
        self.assertIn('--origin https://jzis.org', workflow[start:end])
        self.assertNotIn('--allow-noindex', workflow[start:end])

    def test_matching_payload_passes_with_explicit_limited_scope(self):
        result = Fixture().check()
        self.assertTrue(result['passed'])
        self.assertFalse(result['scientificAcceptance'])

    def test_production_noindex_header_fails(self):
        f = Fixture(); f.routes['/scwiki'][2]['x-robots-tag'] = 'noindex, nofollow'
        with self.assertRaisesRegex(ValueError, 'noindex'): f.check()

    def test_production_noindex_meta_fails(self):
        f = Fixture(); s,b,h = f.routes['/scwiki'];f.routes['/scwiki']=(s,b+b'<meta name="robots" content="noindex">',h)
        with self.assertRaisesRegex(ValueError, 'noindex'): f.check()

    def test_missing_topic_link_fails(self):
        f = Fixture();s,b,h=f.routes['/scwiki'];f.routes['/scwiki']=(s,b.replace(b'href="/scwiki/i"',b'href="/wrong"'),h)
        with self.assertRaisesRegex(ValueError, 'directory'): f.check()

    def test_external_or_query_losing_redirect_fails(self):
        for location in ('https://foreign.example/?q=Meissner&source=release-smoke',
                         'http://jzis.org/?q=Meissner&source=release-smoke','/?q=Meissner'):
            f=Fixture();f.routes['/search?q=Meissner&source=release-smoke'][2]['location']=location
            with self.subTest(location=location),self.assertRaisesRegex(ValueError, 'redirect'): f.check()

    def test_changed_claim_even_with_unchanged_revision_fails(self):
        f=Fixture();a=copy.deepcopy(f.articles[0]);a['claims'][0]['statement']='changed'
        f.put(API+'articles/scwiki-a1',{'article':a},a['revision'])
        with self.assertRaisesRegex(ValueError,'content/review/source'):f.check()

    def test_missing_published_article_fails(self):
        f=Fixture();f.put(API+'revisions?limit=50',f.page('records',[]),'catalogue')
        with self.assertRaisesRegex(ValueError,'inventory'):f.check()

    def test_stale_revision_header_fails(self):
        f=Fixture();f.routes[API+'revisions?limit=50'][2]['x-scwiki-revision']='old'
        with self.assertRaisesRegex(ValueError,'revision'):f.check()

    def test_library_review_change_fails(self):
        f=Fixture();f.put(API+'library?limit=50',f.page('notes',[{'id':'note','review':{'scope':'certified'}}]),'catalogue')
        with self.assertRaisesRegex(ValueError,'library'):f.check()

    def test_external_pagination_is_not_requested(self):
        f=Fixture();d=f.page('records',[]);d['page'].update(next='https://foreign.example/secret',nextCursor='cursor')
        f.put(API+'revisions?limit=50',d,'catalogue')
        with self.assertRaisesRegex(ValueError,'pagination'):collection(f,'revisions','records','catalogue')
        self.assertEqual(f.requests,1)

    def test_repeated_pagination_or_duplicate_records_fails(self):
        for loop in (True,False):
            f=Fixture();d=f.page('records',[{'id':'same'},{'id':'same'}])
            if loop:d['page'].update(next=API+'revisions?limit=50',nextCursor='cursor')
            f.put(API+'revisions?limit=50',d,'catalogue')
            with self.subTest(loop=loop),self.assertRaises(ValueError):collection(f,'revisions','records','catalogue')

    def test_invalid_or_insecure_origin_rejected_before_network(self):
        for origin in ('http://jzis.org','https://u:secret@jzis.org','https://jzis.org/path','https://jzis.org/?x=1'):
            with self.subTest(origin=origin),self.assertRaises(ValueError):Client(origin)

if __name__ == '__main__':
    unittest.main()
