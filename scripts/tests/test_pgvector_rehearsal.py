"""Rehearsal admission refuses production before opening SQL."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pgvector_rehearsal import Rehearsal

CID = "a" * 64
IMAGE = "sha256:" + "b" * 64


@pytest.fixture
def target(tmp_path, monkeypatch):
    receipt = {"status": "restored_and_readable", "target": {
        "container_id": CID, "image": IMAGE, "volume": "owned-restore"}}
    path = tmp_path / "restore.json"
    path.write_text(json.dumps(receipt))
    container = {"Id": CID, "Image": IMAGE, "State": {"Running": True},
        "Config": {"Labels": {"org.jzis.sclib.purpose": "pgvector-production-backup-drill", "org.jzis.sclib.run": "run"}},
        "HostConfig": {"NetworkMode": "none"}, "Mounts": [{"Type": "volume", "Name": "owned-restore"}]}
    volume = {"Labels": deepcopy(container["Config"]["Labels"])}
    def docker(args):
        assert args[0] == "docker"
        return json.dumps([volume if args[1] == "volume" else container]).encode()
    monkeypatch.setattr("pgvector_rehearsal.subprocess.check_output", docker)
    calls = []
    monkeypatch.setattr(Rehearsal, "json_sql", lambda self, sql: calls.append(sql) or {
        "manifest_sha256": "f" * 64, "root": "f" * 64,
        "profile": {"model": "text-embedding-005", "output_dimensionality": 768}})
    args = SimpleNamespace(restore_report=path, source_generation="00000000-0000-0000-0000-000000000001", manifest="f" * 64)
    return args, container, volume, calls


@pytest.mark.parametrize("mutation", ["network", "image", "container_id", "label", "volume_label", "mount", "stopped"])
def test_rejects_unowned_or_production_target_before_sql(target, mutation):
    args, c, v, calls = target
    if mutation == "network":
        c["HostConfig"]["NetworkMode"] = "bridge"
    elif mutation == "image":
        c["Image"] = "sha256:" + "c" * 64
    elif mutation == "container_id":
        c["Id"] = "d" * 64
    elif mutation == "label":
        c["Config"]["Labels"] = {}
    elif mutation == "volume_label":
        v["Labels"] = {}
    elif mutation == "mount":
        c["Mounts"] = []
    else:
        c["State"]["Running"] = False
    with pytest.raises(ValueError):
        Rehearsal(args)
    assert calls == []


def test_admits_only_exact_owned_restored_source(target):
    args, _, _, calls = target
    assert Rehearsal(args).identifier == CID
    assert len(calls) == 1


def test_parallel_build_refuses_small_shared_memory_before_any_ddl(target, monkeypatch):
    args, container, _, calls = target
    container["HostConfig"]["ShmSize"] = 1024**3
    run = Rehearsal(args)
    monkeypatch.setattr(run, "verify", lambda: pytest.fail("Build admission must run before SQL"))
    with pytest.raises(RuntimeError, match="5 GiB shared memory"):
        run.build()
    assert len(calls) == 1  # The constructor's read-only source identity check.
