#!/usr/bin/env python3
"""Bounded, read-only HTTP checks against the exact SCWiki release payload.

This verifies published content and routing, not scientific accuracy, browser
interaction, authenticated literature search, or database recovery.
"""
import argparse
import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = '/api/scwiki/v1/'
MAX_BYTES = 2 * 1024 * 1024

def require(condition, message):
    if not condition:
        raise ValueError(message)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Markup(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.tags = []
        self.feed(body.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def has(self, tag, **attrs):
        return any(t == tag and all(a.get(k) == v for k, v in attrs.items()) for t, a in self.tags)

class Client:
    def __init__(self, origin):
        parsed = urlsplit(origin)
        require(parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username
                and not parsed.password and parsed.path in ('', '/') and not parsed.query
                and not parsed.fragment, 'Expected a credential-free origin without a path')
        require(parsed.scheme == 'https' or parsed.hostname in ('localhost', '127.0.0.1', '::1'),
                'Non-loopback origins require HTTPS')
        self.origin = origin.rstrip('/')
        self.opener = build_opener(NoRedirect())
        self.last = 0.0
        self.requests = 0

    def get(self, path):
        require(path.startswith('/') and not path.startswith('//') and '\\' not in path,
                'Refusing a nonlocal request path')
        time.sleep(max(0, .15 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.requests += 1
        try:
            response = self.opener.open(Request(self.origin + path, headers={
                'User-Agent': 'SCWiki-release-verifier/1', 'Accept-Encoding': 'identity'}), timeout=15)
        except HTTPError as error:
            response = error
        with response:
            body = response.read(MAX_BYTES + 1)
            require(len(body) <= MAX_BYTES, 'Response exceeds bounded verifier limit')
            return response.status, body, {k.lower(): v for k, v in response.headers.items()}

def success(client, path, allow_noindex=False):
    status, body, headers = client.get(path)
    require(status == 200, f'{path}: expected 200, received {status}')
    if not allow_noindex:
        require('noindex' not in headers.get('x-robots-tag', '').lower(), f'{path}: production noindex header')
    return body, headers

def collection(client, endpoint, key, revision=None):
    path = API + endpoint + '?limit=50'
    seen, records = set(), []
    while path:
        parsed = urlsplit(path)
        require(not parsed.scheme and not parsed.netloc and not parsed.fragment
                and parsed.path == API + endpoint and path not in seen and len(seen) < 32,
                'Invalid or looping pagination target')
        seen.add(path)
        body, headers = success(client, path, True)
        require('application/json' in headers.get('content-type', ''), 'Expected JSON response')
        data = json.loads(body)
        if revision is None:
            revision = data['revision']
        require(data['revision'] == revision and headers.get('x-scwiki-revision') == revision,
                'Collection revision mismatch')
        require(data['page']['returned'] == len(data[key]) <= 50, 'Invalid page count')
        records.extend(data[key])
        path = data['page']['next']
        require(bool(path) == bool(data['page']['nextCursor']), 'Incomplete pagination metadata')
    require(len(records) == data['total'], 'Collection total mismatch')
    ids = [r['id'] for r in records]
    require(len(ids) == len(set(ids)), 'Duplicate collection records')
    return records

def verify(client, catalogue, library, allow_noindex=False):
    revision = catalogue['revision']
    expected = {a['id']: a for a in catalogue['articles']}
    body, _ = success(client, '/scwiki', allow_noindex)
    wiki = Markup(body)
    require(wiki.has('main', **{'data-revision': revision}), 'Wiki HTML revision mismatch')
    require(all(wiki.has('a', href='/scwiki/' + a['slug']) for a in expected.values()),
            'Wiki topic directory is incomplete')
    if not allow_noindex:
        require(not any(t == 'meta' and a.get('name', '').lower() == 'robots'
                        and 'noindex' in a.get('content', '').lower() for t, a in wiki.tags),
                'Production Wiki meta noindex')
    body, _ = success(client, '/', allow_noindex)
    home = Markup(body)
    require(home.has('a', href='/scwiki') and home.has('input', name='q'), 'Home discovery entry missing')
    status, _, headers = client.get('/search?q=Meissner&source=release-smoke')
    location = urlsplit(headers.get('location', ''))
    require(status in (307, 308) and location.scheme in ('', urlsplit(client.origin).scheme)
            and (not location.netloc or location.netloc == urlsplit(client.origin).netloc)
            and location.path == '/' and location.query == 'q=Meissner&source=release-smoke',
            'Legacy search redirect changed destination or query')
    records = collection(client, 'revisions', 'records', revision)
    require({r['id']: r['revision'] for r in records} == {i: a['revision'] for i, a in expected.items()},
            'Published article inventory differs from candidate')
    notes = collection(client, 'library', 'notes')
    require([{k: v for k, v in n.items() if k != 'revision'} for n in notes] == library['notes'],
            'Published research library differs from candidate')
    for identity in ('scwiki-a1', 'scwiki-i', 'scwiki-n1'):
        article = expected[identity]
        body, headers = success(client, API + 'articles/' + identity, True)
        require(json.loads(body)['article'] == article and headers.get('x-scwiki-revision') == article['revision'],
                f'{identity}: article content/review/source mismatch')
    body, _ = success(client, API + 'search?q=Meissner&limit=50', True)
    require('scwiki-a2' in {r['id'] for r in json.loads(body)['results']}, 'Wiki search misses Meissner article')
    body, headers = success(client, API + 'articles/scwiki-a1/markdown', True)
    require(body.decode('utf-8') == expected['scwiki-a1']['markdown']
            and headers.get('x-scwiki-revision') == expected['scwiki-a1']['revision'], 'Markdown content mismatch')
    return {'passed': True, 'catalogueRevision': revision, 'articleRevisions': len(records),
            'libraryNotes': len(notes), 'fullArticlesCompared': 3, 'httpRequests': client.requests,
            'allowNoindex': allow_noindex, 'scientificAcceptance': False,
            'scope': 'Read-only HTTP content/routing; excludes browser, authenticated literature and database recovery.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--content', type=Path, default=Path('frontend/content/scwiki'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-noindex', action='store_true', help='Isolated local preview only')
    args = parser.parse_args()
    require(not args.allow_noindex or urlsplit(args.origin).hostname in ('localhost', '127.0.0.1', '::1'),
            'Noindex exception is restricted to loopback')
    report = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'origin': args.origin}
    try:
        report.update(verify(Client(args.origin), json.loads((args.content/'catalogue.json').read_text()),
                             json.loads((args.content/'research-library.json').read_text()), args.allow_noindex))
    except Exception as error:
        report.update(passed=False, error=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as temp:
        json.dump(report, temp, indent=2)
        temp.write('\n')
    Path(temp.name).replace(args.output)
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)

if __name__ == '__main__':
    main()
