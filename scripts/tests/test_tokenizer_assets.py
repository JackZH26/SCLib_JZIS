"""Tokenizer assets are explicit install inputs; test execution stays offline.

Run the documented dependency preparation before this suite. These checks do
not download ranks or replace missing ranks with a stub tokenizer.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
CACHE_KEY = hashlib.sha1(ASSET_URL.encode()).hexdigest()  # tiktoken's cache naming, not integrity.
ASSET_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
PREPARE = "python -c \"import tiktoken; tiktoken.get_encoding('cl100k_base')\""
PROBE = """
import sys
def deny_network(event, args):
    if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('tokenizer_network_forbidden')
sys.addaudithook(deny_network)
import tiktoken
text = 'SCLib: pressure, ΔTc, 数据, and literal <script> text.'
encoder = tiktoken.get_encoding('cl100k_base')
tokens = encoder.encode(text)
assert tokens and encoder.decode(tokens) == text
print('tokenizer_cache_verified')
"""


def probe(cache):
    return subprocess.run([sys.executable, "-I", "-B", "-c", PROBE], check=False,
        env={"TIKTOKEN_CACHE_DIR": str(cache), "LANG": "C.UTF-8"},
        capture_output=True, text=True, timeout=20)


def test_installed_tokenizer_has_exact_asset_and_works_in_fresh_offline_process():
    directory = os.environ.get("TIKTOKEN_CACHE_DIR", os.environ.get(
        "DATA_GYM_CACHE_DIR", str(Path(tempfile.gettempdir()) / "data-gym-cache")))
    assert directory, "Disabled tokenizer cache: prepare the documented dependency before offline tests"
    path = Path(directory) / CACHE_KEY
    assert path.is_file(), "Missing tokenizer ranks: run the dependency preparation in docs/TESTING_SAFELY.md"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ASSET_SHA256
    result = probe(path.parent)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "tokenizer_cache_verified\n"


@pytest.mark.parametrize("corrupt", [False, True], ids=["absent", "corrupt"])
def test_missing_or_corrupt_ranks_cannot_silently_download_in_offline_probe(tmp_path, corrupt):
    if corrupt:
        (tmp_path / CACHE_KEY).write_bytes(b"synthetic corrupt tokenizer ranks")
    result = probe(tmp_path)
    assert result.returncode != 0 and "tokenizer_network_forbidden" in result.stderr
    assert "tokenizer_cache_verified" not in result.stdout


def test_both_runtime_images_install_ranks_then_verify_as_non_root_without_network():
    smoke = "RUN --network=none python -c \"import tiktoken; assert tiktoken.get_encoding('cl100k_base').encode('SCLib')\""
    for project in ("api", "ingestion"):
        source = (ROOT / project / "Dockerfile").read_text()
        assert "TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache" in source
        assert source.index("uv sync --locked --no-dev --no-install-project") < source.index(PREPARE)
        assert source.index(PREPARE) < source.index("USER sclib") < source.index(smoke)


def test_all_python_ci_jobs_prepare_before_offline_or_owned_service_tests():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    for name, following, test_step in (
        ("api-tests", "migration-tests", "Verify all offline script contracts"),
        ("migration-tests", "ingestion-tests", "Upgrade and verify an owned disposable database"),
        ("ingestion-tests", "frontend-build", "Run unit tests only"),
    ):
        block = workflow.split(f"\n  {name}:", 1)[1].split(f"\n  {following}:", 1)[0]
        assert block.index("uv sync --locked --extra dev") < block.index(PREPARE) < block.index(test_step)
        assert "Prepare hash-verified tokenizer data (dependency download)\n        timeout-minutes: 2" in block
