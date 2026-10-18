import hashlib
import json
import subprocess
import sys
from pathlib import Path

import unittest
import tempfile

from scripts.prepare_scwiki_proxy import directives, render, HTTP_BEGIN, HTTP_END, SERVER_BEGIN, SERVER_END


WEBSITE = '''server
{
    server_name "jzis.org" www.jzis.org;
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/jzis.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jzis.org/privkey.pem;
    include /etc/nginx/snippets/york-interview.conf;
    location ^~ /.well-known/acme-challenge/ { root /var/www/acme; }
    location ~ ^/(auth|login)(/|$) { add_header Cache-Control "private, no-store"; }
    location / { proxy_pass http://127.0.0.1:3100; }
}'''
OTHER = '''
server { server_name api.jzis.org; listen 443 ssl; location / { proxy_pass http://127.0.0.1:8000; } }
server { server_name asrp.jzis.org; listen 443 ssl; return 410; }
server { server_name jzis.org www.jzis.org api.jzis.org; listen 80; return 301 https://${host}$request_uri; }
'''
SOURCE = '# preserve this comment { }\n' + WEBSITE + OTHER


def remove_generated(candidate):
    for start, end in [(HTTP_BEGIN, HTTP_END), (SERVER_BEGIN, SERVER_END)]:
        first = candidate.index(start)
        last = candidate.index(end, first) + len(end)
        candidate = candidate[:first] + candidate[last:]
    return candidate


class CandidateTests(unittest.TestCase):
    def test_additive_candidate_retains_every_original_byte_and_other_server(self):
        candidate, receipt = render(SOURCE)
        assert remove_generated(candidate) == SOURCE
        assert OTHER in candidate
        assert len([d for d in directives(candidate) if d.words == ['server']]) == 4
        assert candidate.count('limit_req_zone $binary_remote_addr zone=scwiki_api:10m rate=10r/s;') == 1
        assert candidate.count('limit_req zone=scwiki_api burst=20 nodelay;') == 2
        assert '/etc/nginx/snippets/scwiki-proxy-common.conf' not in candidate
        assert 'location = /api/scwiki/v1 {' in candidate
        assert 'location ^~ /api/scwiki/v1/ {' in candidate
        assert receipt['originalBytesPreserved']
        assert not receipt['productionChanged']
        assert not receipt['targetNginxValidated']
        assert not receipt['externalIncludesValidated']
        assert receipt['outputSha256'] == hashlib.sha256(candidate.encode()).hexdigest()


    def test_comments_quotes_escaped_quotes_and_braced_variables_preserved(self):
        source = SOURCE.replace('location / {', 'add_header X-Diagnostic \'{"value":"} ; { #"}\';\n # fake server {\n location / {', 1)
        candidate, _ = render(source)
        assert remove_generated(candidate) == source
        parsed = directives('map $request_uri $uri_value { default "a\\\"b"; }\n' + source)
        assert parsed[0].words == ['map', '$request_uri', '$uri_value']
        assert len(parsed) == 5


    def test_ambiguous_conflicting_or_incomplete_input_rejected(self):
        cases = [
        SOURCE + WEBSITE,
        SOURCE.replace('"jzis.org" www.jzis.org', 'jzis.org unexpected.example'),
        SOURCE.replace('listen 443 ssl;', 'listen 443;', 1),
        SOURCE.replace('location / {', 'return 301 /other;\n location / {', 1),
        SOURCE.replace('location / {', 'real_ip_header X-Forwarded-For;\n location / {', 1),
        SOURCE + '\nlimit_req_zone $remote_addr zone=scwiki_api:10m rate=1r/s;',
        SOURCE.replace('location / {', 'location = /api/scwiki/v1/catalogue { deny all; }\n location / {', 1),
        SOURCE + '\n{', SOURCE + '\n}', SOURCE + '\ninclude "incomplete',
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(ValueError):
                render(source)


    def test_regeneration_rejected(self):
        candidate, _ = render(SOURCE)
        with self.assertRaisesRegex(ValueError, 'Existing SCWiki'):
            render(candidate)


    def test_cli_snapshot_guard_permissions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            self.check_cli(Path(directory))

    def check_cli(self, tmp_path):
        input_path = tmp_path / 'original.conf'
        input_path.write_text(SOURCE)
        output = tmp_path / 'candidate.conf'
        receipt = tmp_path / 'receipt.json'
        script = Path(__file__).resolve().parents[1] / 'prepare_scwiki_proxy.py'
        digest = hashlib.sha256(input_path.read_bytes()).hexdigest()

        def run(target=output, audit=digest):
            return subprocess.run([sys.executable, str(script), '--input', str(input_path), '--output', str(target), '--receipt', str(receipt), '--expected-sha256', audit], capture_output=True)

        assert run(audit='0' * 64).returncode != 0
        assert not output.exists()
        assert run(target=input_path).returncode != 0
        assert run().returncode == 0
        assert output.stat().st_mode & 0o777 == 0o600
        before = output.read_bytes()
        assert json.loads(receipt.read_text())['inputSha256'] == digest
        assert run().returncode != 0
        assert output.read_bytes() == before
        assert input_path.read_text() == SOURCE
        # Failure to create a separate receipt removes only this run's new candidate.
        second = tmp_path / 'second.conf'
        assert run(target=second).returncode != 0
        assert not second.exists()
        assert receipt.exists()
