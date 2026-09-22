"""Bounded, offline corpus preservation, restart and tamper tests."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "ingestion")]
from legacy_index_pack import Pack, PackError, TOKEN_LIMIT, specification


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a, **kw):
        raise AssertionError("No network in legacy preparation tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


def inputs(n=1, text="Retained synthetic text.\n"):
    paper = {"id": "arxiv:synthetic", "title": "Synthetic paper", "authors": ["Synthetic author"]}
    chunk = {"id": f"arxiv:synthetic_chunk_{n:06}", "paper_id": paper["id"], "title": paper["title"],
             "text": text, "section": "Results", "chunk_index": n}
    return chunk, paper


@pytest.fixture
def destination(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path / "pack.sqlite"


def create(path):
    return Pack(path, specification({"synthetic": True}))


def test_small_text_intact_and_unknown_lineage_stays_unknown(destination):
    pack = create(destination)
    try:
        pack.append(1, *inputs())
        report = pack.seal(1)
        value = json.loads(pack.db.execute("SELECT body FROM members").fetchone()[0])
        assert value["prefix"] == "" and value["char_start"] == 0
        assert report["sources"] == report["members"] == report["partitions"] == 1
        assert report["retained_text_coverage_complete"] is True
        assert not report["activation_eligible"] and not report["embedding_completion_verified"]
        assert pack.spec["historical_parser_version"] is None
        assert pack.spec["historical_embedding_completion"] is None
        assert pack.spec["permission_status"] == "unresolved"
        with pytest.raises(PackError, match="sealed"):
            pack.append(2, *inputs(2))
    finally:
        pack.close()
    reopened = Pack(destination, readonly=True)
    try:
        assert reopened.verify(1) == report
    finally:
        reopened.close()


@pytest.mark.parametrize("body", ["word " * 6000, "超导😀𓀀é\r\n\t" * 900, "A" * 30000,
                                    "LaH10\t250\t170\n" * 1500, " " * 20000])
def test_long_unicode_table_ocr_and_whitespace_keep_every_character(destination, body):
    pack = create(destination)
    try:
        pack.append(1, *inputs(text=body))
        report = pack.seal(1)
        assert report["source_characters"] == len(body)
        assert report["source_utf8_bytes"] == len(body.encode())
        assert report["max_input_tokens"] <= TOKEN_LIMIT
        if not body.strip():
            assert report["inadmissible_embedding_inputs"] > 0
        reconstructed = ""
        covered = 0
        for (raw,) in pack.db.execute("SELECT body FROM members ORDER BY seq"):
            row = json.loads(raw)
            assert row["char_start"] <= covered < row["char_end"]
            reconstructed += body[covered:row["char_end"]]
            covered = row["char_end"]
        assert reconstructed == body
    finally:
        pack.close()


def test_checkpoint_resume_matches_uninterrupted_pack_and_rejects_drift(destination):
    pack = create(destination)
    pack.append(1, *inputs())
    pack.db.commit()
    pack.append(2, *inputs(2, "uncommitted attempt"))
    pack.close()
    pack = Pack(destination, specification({"synthetic": True}), resume=True)
    try:
        assert pack.source_count == 1 and pack.member_count == 1
        with pytest.raises(PackError, match="changed_on_resume"):
            pack.append(1, *inputs(text="changed historical text"))
        assert pack.append(1, *inputs()) is False
        pack.append(2, *inputs(2))
        resumed = pack.seal(2)
    finally:
        pack.close()
    reference = create(destination.with_name("reference.sqlite"))
    try:
        for n in (1, 2):
            reference.append(n, *inputs(n))
        assert reference.seal(2) == resumed
    finally:
        reference.close()


def test_abrupt_process_exit_recovers_only_committed_sources(destination):
    chunk, paper = inputs()
    second, _ = inputs(2)
    script = "\n".join([
        "import os,sys",
        "sys.path[:0] = " + repr([str(ROOT / "scripts"), str(ROOT / "ingestion")]),
        "from legacy_index_pack import Pack,specification",
        "pack=Pack(" + repr(str(destination)) + ",specification({'synthetic':True}))",
        "pack.append(1," + repr(chunk) + "," + repr(paper) + ")",
        "pack.db.commit()",
        "pack.append(2," + repr(second) + "," + repr(paper) + ")",
        "os._exit(23)",  # No context-manager rollback or normal connection close.
    ])
    env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "TIKTOKEN_CACHE_DIR") if name in os.environ}
    process = subprocess.run([sys.executable, "-c", script], capture_output=True, env=env, timeout=20)
    assert process.returncode == 23
    recovered = Pack(destination, specification({"synthetic": True}), resume=True)
    try:
        assert recovered.source_count == recovered.member_count == 1
        assert recovered.append(1, chunk, paper) is False
        recovered.append(2, second, paper)
        assert recovered.seal(2)["sources"] == 2
    finally:
        recovered.close()


def test_bounded_partitions_accept_more_than_pilot_limit(destination):
    pack = create(destination)
    try:
        for n in range(1, 2003):
            pack.append(n, *inputs(n))
        report = pack.seal(2002)
        assert report["partitions"] == 3 and report["members"] == 2002
        assert pack.db.execute("SELECT count(*) FROM papers").fetchone()[0] == 1
    finally:
        pack.close()


@pytest.mark.parametrize("sql", [
    "UPDATE sources SET body=replace(body,'Retained','Changed')",
    "UPDATE papers SET body=replace(body,'Synthetic paper','Changed paper')",
    "DELETE FROM members",
    "UPDATE members SET body=replace(body,'char_start\":0','char_start\":1')",
    "UPDATE members SET partition_id=4",
])
def test_every_retained_byte_and_membership_is_rechecked(destination, sql):
    pack = create(destination)
    try:
        pack.append(1, *inputs())
        pack.seal(1)
        pack.db.execute(sql)
        pack.db.commit()
        with pytest.raises(PackError):
            pack.verify(1)
    finally:
        pack.close()


@pytest.mark.parametrize("case", ["source_gap", "paper_change", "empty", "wrong_paper", "control_id"])
def test_invalid_source_inputs_fail_without_sealing(destination, case):
    pack = create(destination)
    try:
        chunk, paper = inputs()
        seq = 1
        if case == "source_gap":
            seq = 2
        elif case == "paper_change":
            pack.append(1, chunk, paper)
            chunk, paper = inputs(2)
            paper["title"] = "drift"
            seq = 2
        elif case == "empty":
            chunk["text"] = ""
        elif case == "wrong_paper":
            chunk["paper_id"] = "wrong"
        else:
            chunk["id"] = "bad\nidentity"
        with pytest.raises(PackError):
            pack.append(seq, chunk, paper)
        assert pack.sealed is None
    finally:
        pack.close()


def test_private_destinations_and_exact_provenance_required(destination):
    pack = create(destination)
    pack.close()
    with pytest.raises(FileExistsError):
        create(destination)
    with pytest.raises(PackError, match="provenance_changed"):
        Pack(destination, specification({"synthetic": False}), resume=True)
    link = destination.with_name("link")
    link.symlink_to(destination)
    with pytest.raises(PackError, match="unsafe"):
        Pack(link, readonly=True)
    destination.chmod(0o644)
    with pytest.raises(PackError, match="unsafe"):
        Pack(destination, readonly=True)


def test_cli_withholds_private_driver_error(monkeypatch, capsys, destination):
    import prepare_legacy_index_pack as cli
    def fail(_args):
        raise RuntimeError("PRIVATE_DSN_AND_SOURCE_TEXT")
    monkeypatch.setattr(cli, "build", fail)
    assert cli.main(["build", "--pack", str(destination), "--backup-sha256", "a" * 64,
                     "--restored-database", "sclib_upgrade", "--schema", "0078_fixture"]) == 1
    stderr = capsys.readouterr().err
    assert "PRIVATE" not in stderr and "legacy_pack_operation_failed" in stderr
