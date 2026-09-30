import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.prepare_site_integration import render, server_blocks

TLS = """
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
"""
API = 'server {\n server_name api.jzis.org;\n listen 443 ssl;\n location /sclib/ { proxy_pass http://127.0.0.1:8000/; }\n}'
SOURCE = f"""# A brace in a comment {{ must not affect parsing.
server {{
    server_name jzis.org www.jzis.org;
    root /var/www/jzis;
    include /etc/nginx/snippets/york-interview.conf;
    location /sclib {{ proxy_pass http://127.0.0.1:3100; }}
    {TLS}
}}
server {{
    server_name asrp.jzis.org;
    root /var/www/asrp;
    location /api/ {{ proxy_pass http://127.0.0.1:3000; }}
    {TLS}
}}
{API}
server {{ listen 80; server_name jzis.org; return 301 https://$host$request_uri; }}
"""


def test_candidate_preserves_api_tls_and_unrelated_private_site():
    candidate = render(SOURCE)
    assert API in candidate
    assert "include /etc/nginx/snippets/york-interview.conf;" in candidate
    assert candidate.count("ssl_certificate /etc/letsencrypt/live/example/fullchain.pem;") == 2
    assert len(server_blocks(candidate)) == 4
    main, retired, *_ = [block for _, _, block in server_blocks(candidate)]
    assert "try_files $uri $uri/" not in main
    assert "access_log off;" in main
    assert "private, no-store" in main
    assert "legacy-static/" in main
    assert "return 410;" in retired
    assert "proxy_pass" not in retired
    assert "try_files $uri =404;" in retired


def test_quotes_and_commented_braces_do_not_truncate_api():
    source = SOURCE.replace("location /sclib/", 'add_header X-Test "} {";\n # }\n location /sclib/')
    assert 'add_header X-Test "} {";' in render(source)


@pytest.mark.parametrize("source", [SOURCE.replace("asrp.jzis.org", "other.example"), SOURCE + SOURCE, SOURCE + "{"])
def test_ambiguous_or_changed_topology_is_rejected(source):
    with pytest.raises(ValueError):
        render(source)


def test_cli_refuses_stale_audit_or_in_place_overwrite(tmp_path):
    source = tmp_path / "input.conf"
    source.write_text(SOURCE)
    script = Path(__file__).resolve().parents[1] / "prepare_site_integration.py"
    for digest, output in [("0" * 64, tmp_path / "candidate.conf"), (hashlib.sha256(source.read_bytes()).hexdigest(), source)]:
        result = subprocess.run([sys.executable, str(script), "--input", str(source), "--output", str(output), "--expected-sha256", digest], capture_output=True)
        assert result.returncode != 0
    assert source.read_text() == SOURCE
