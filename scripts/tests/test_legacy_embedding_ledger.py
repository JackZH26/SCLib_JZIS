"""Offline durability and failure boundaries of the real embedding worker."""

from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "api"), str(ROOT / "ingestion")]
from embed_legacy_index_pack import Ledger, PROFILE, file_sha, run
from legacy_index_pack import Pack, PackError, specification
from services.embedding_contract import validate_embedding_response


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a, **kw):
        raise AssertionError("No network in embedding ledger tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def retained(tmp_path, request):
    tmp_path.chmod(0o700)
    source = tmp_path / "input.sqlite"
    pack = Pack(source, specification({"synthetic": True}))
    paper = {"id": "synthetic-paper", "title": "Synthetic title"}
    count = getattr(request, "param", 30)
    for seq in range(1, count + 1):
        pack.append(
            seq,
            {"id": f"c{seq:03}", "paper_id": paper["id"], "text": "test " * 1100},
            paper,
        )
    pack.seal(count)
    pack.close()
    pack = Pack(source, readonly=True)
    try:
        yield pack, tmp_path / "completions.sqlite", file_sha(source)
    finally:
        pack.close()


def completed(batch):
    return validate_embedding_response(
        [i["text"] for i in batch],
        {
            "embeddings": [
                {
                    "values": [0.125] * 768,
                    "statistics": {"truncated": False, "token_count": i["tokens"]},
                }
                for i in batch
            ]
        },
        local_counts=[i["tokens"] for i in batch],
        **PROFILE,
    )


def test_complete_reopen_and_full_verify(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    for batch in ledger.pending():
        attempt = ledger.reserve(batch)
        ledger.finish(attempt, batch, completed(batch))
    report = ledger.seal()
    assert report["members"] == 30 and report["embedding_completion_verified"] is True
    assert report["activation_eligible"] is False
    assert report["scientific_acceptance"] is False
    assert list(ledger.pending()) == []
    ledger.close()
    reopened = Ledger(path, pack, digest)
    try:
        assert reopened.seal() == report
        assert reopened.status()["completed_members"] == 30
    finally:
        reopened.close()


def test_interrupted_reservation_is_still_charged_and_not_a_completion(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    batch = next(ledger.pending())
    ledger.reserve(batch)
    budget = ledger.budget[:]
    ledger.close()
    ledger = Ledger(path, pack, digest)
    try:
        assert ledger.budget == budget
        assert next(ledger.pending()) == batch
        assert ledger.status()["completed_members"] == 0
        with pytest.raises(PackError, match="incomplete"):
            ledger.seal()
    finally:
        ledger.close()


def test_attempt_identity_conflict_is_atomic(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    try:
        batches = list(ledger.pending())
        attempt = ledger.reserve(batches[0])
        with pytest.raises(PackError, match="binding"):
            ledger.finish(attempt, batches[1], completed(batches[1]))
        assert ledger.status()["completed_members"] == 0
        results = completed(batches[0])
        results[-1][1]["provider_truncated"] = True
        with pytest.raises(ValueError):
            ledger.finish(attempt, batches[0], results)
        assert ledger.status()["completed_members"] == 0
    finally:
        ledger.close()


def test_no_hidden_retry_and_no_claim_after_provider_failure(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    calls = []

    def failed(project, location, batch):
        calls.append(batch)
        return "provider_failure", None

    try:
        args = SimpleNamespace(
            concurrency=1,
            requests_per_minute=600,
            max_new_requests=30,
            project="synthetic",
            location="us-central1",
        )
        assert run(ledger, args, call=failed) == 2
        assert len(calls) == ledger.status()["reserved_requests"] == 1
        assert ledger.status()["completed_members"] == 0
        assert not ledger.sealed
    finally:
        ledger.close()


def test_process_lock_and_private_files(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    try:
        with pytest.raises(PackError, match="already_running"):
            Ledger(path, pack, digest)
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        ledger.close()
    path.chmod(0o644)
    with pytest.raises(PackError, match="unsafe_embedding_ledger"):
        Ledger(path, pack, digest)


def test_budget_and_member_attempt_limits_survive_restart(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    # Use one small request, rather than consume 40% of the corpus per retry.
    batch = next(ledger.pending())[:1]
    for _ in range(3):
        attempt = ledger.reserve(batch)
        ledger.fail(attempt, "provider_throttled")
    ledger.close()
    ledger = Ledger(path, pack, digest)
    try:
        with pytest.raises(PackError, match="retry_limit"):
            ledger.reserve(batch)
        assert ledger.status()["reserved_requests"] == 3
        ledger.budget[0] = ledger.spec["max_characters"]
        with pytest.raises(PackError, match="budget_exhausted"):
            ledger.reserve(next(ledger.pending())[1:2])
        assert ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 3
    finally:
        ledger.close()


def test_source_hash_and_completion_history_cannot_be_silently_changed(retained):
    pack, path, digest = retained
    with pytest.raises(PackError, match="hash_required"):
        Ledger(path, pack, "0" * 64, create=True)
    ledger = Ledger(path, pack, digest, create=True)
    try:
        batch = next(ledger.pending())
        attempt = ledger.reserve(batch)
        ledger.finish(attempt, batch, completed(batch))
        for table in ("completions", "attempts", "metadata", "outcomes"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                ledger.db.execute(f"DELETE FROM {table}")
            ledger.db.rollback()
        with pytest.raises(PackError, match="already_completed"):
            ledger.reserve(batch)
    finally:
        ledger.close()


def test_batch_limits_and_invalid_response_never_store_partial_vectors(retained):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    try:
        for batch in ledger.pending():
            assert len(batch) <= 250 and sum(i["tokens"] for i in batch) <= 14000
            attempt = ledger.reserve(batch)
            invalid = completed(batch)
            invalid[-1] = ([float("nan")] * 768, invalid[-1][1])
            with pytest.raises(ValueError):
                ledger.finish(attempt, batch, invalid)
            assert ledger.status()["completed_members"] == 0
            break
    finally:
        ledger.close()


@pytest.mark.parametrize("retained", [100], indirect=True)
def test_request_split_isolates_bad_input_without_truncation_or_false_completion(
    retained,
):
    pack, path, digest = retained
    ledger = Ledger(path, pack, digest, create=True)
    calls = []

    def limited(project, location, batch):
        calls.append([i["seq"] for i in batch])
        if any(i["seq"] == 1 for i in batch):
            return "provider_input_limit", None
        return "complete", completed(batch)

    try:
        args = SimpleNamespace(
            concurrency=1,
            requests_per_minute=600,
            max_new_requests=100,
            max_batch_inputs=2,
            project="synthetic",
            location="us-central1",
        )
        assert run(ledger, args, call=limited) == 2
        assert calls[0] == [1, 2] and [1] in calls and [2] in calls
        assert ledger.status()["completed_members"] == 99
        assert ledger.status()["rejected_inputs"] == 1
        assert list(ledger.pending()) == [] and not ledger.sealed
        with pytest.raises(PackError, match="incomplete"):
            ledger.seal()
        budget = ledger.budget[:]
    finally:
        ledger.close()
    ledger = Ledger(path, pack, digest)
    try:
        assert ledger.status()["rejected_inputs"] == 1 and ledger.budget == budget
        assert list(ledger.pending()) == []
    finally:
        ledger.close()


@pytest.mark.parametrize(('message', 'expected'), [
    ('Request token count is 21378 but model supports up to 20000.', 'provider_input_limit'),
    ('Input exceeds the maximum token count 2048.', 'provider_input_limit'),
    ('Invalid token configuration PRIVATE_DIAGNOSTIC', 'provider_http_400'),
])
def test_provider_diagnostics_are_private_and_unknown_400_still_stops(monkeypatch, tmp_path, capsys, message, expected):
    import json
    import embed_legacy_index_pack as worker
    from google import genai

    class Rejected(Exception):
        code = 400

    def reject(**kwargs):
        assert kwargs['config'].auto_truncate is False
        raise Rejected(message)

    monkeypatch.setattr(worker, '_CLIENT_LOCAL', SimpleNamespace())
    monkeypatch.setattr(worker, '_CLIENTS', [])
    monkeypatch.setattr(genai, 'Client', lambda **kw: SimpleNamespace(models=SimpleNamespace(embed_content=reject)))
    monkeypatch.setenv('SCLIB_EMBED_DIAGNOSTICS', str(tmp_path))
    assert worker.provider('synthetic', 'us-central1', [{'seq': 7, 'text': 'synthetic'}]) == (expected, None)
    files = list(tmp_path.glob('provider-400-*.json'))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(files[0].read_text()) == {'code': 400, 'message': message, 'member_seqs': [7]}
    captured = capsys.readouterr()
    assert message not in captured.out + captured.err
