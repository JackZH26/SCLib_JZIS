"""Run maintenance entrypoint checks with private synthetic commands only."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_paused_entrypoint_never_executes_and_resume_preserves_arguments(tmp_path):
    directory = tmp_path / "scripts with spaces"
    directory.mkdir()
    guard = directory / "ingestion_pause_guard.sh"
    shutil.copy2(ROOT / "scripts/ingestion_pause_guard.sh", guard)
    marker = directory / ".sclib-ingestion-paused"
    marker.touch()
    result_file = directory / "executed.json"
    command = [
        "/bin/sh", str(guard), sys.executable, "-c",
        "import json,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:])); sys.exit(17)",
        str(result_file), "argument with spaces", "literal $value; no shell expansion",
    ]
    paused = subprocess.run(command, capture_output=True, text=True, check=False)
    assert paused.returncode == 0 and "paused" in paused.stdout
    assert not result_file.exists()
    marker.unlink()
    resumed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert resumed.returncode == 17
    assert json.loads(result_file.read_text()) == command[-2:]


def test_production_guard_precedes_credentials_and_local_command():
    import yaml

    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        ingestion = yaml.safe_load((ROOT / name).read_text())["services"]["ingestion"]
        assert ingestion["entrypoint"][:2] == [
            "/bin/sh", "/app/scripts/ingestion_pause_guard.sh",
        ]
        if name.endswith(".prod.yml"):
            assert ingestion["entrypoint"][2:] == [
                "python", "/app/scripts/validate_gcp_credentials.py", "exec", "--",
            ]
        else:
            assert ingestion["command"] == ["sclib-ingest", "--mode", "smoke", "--limit", "30"]
            assert "./scripts:/app/scripts:ro" in ingestion["volumes"]
