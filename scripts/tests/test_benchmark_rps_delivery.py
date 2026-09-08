"""Bounded deterministic local service benchmark; no production or cloud I/O."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/benchmark_rps_delivery.py"
SPEC = importlib.util.spec_from_file_location("benchmark_rps_delivery", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.parametrize("options", [
    {"releases": 3}, {"releases": 17}, {"releases": True}, {"releases": "4"},
    {"iterations": 0}, {"iterations": 101}, {"workers": 0}, {"workers": 9},
])
def test_resource_configuration_rejected_before_fixture_or_service_import(monkeypatch, options):
    monkeypatch.setattr(benchmark, "_services", lambda: pytest.fail("invalid config imported services"))
    with pytest.raises(ValueError, match="invalid_arguments"):
        benchmark.run_benchmark(**options)


@pytest.mark.parametrize("args", [["--unknown", "PRIVATE-CANARY"], ["--releases", "1"],
    ["--workers", "NaN"], ["--iterations", "1.5"]])
def test_bad_cli_is_static_json_not_an_argument_or_traceback_leak(args, capsys):
    assert benchmark.main(args) == 2
    output = capsys.readouterr()
    assert output.err == "" and "PRIVATE-CANARY" not in output.out and "Traceback" not in output.out
    assert json.loads(output.out)["status"] == "rejected"


def test_unexpected_service_failure_does_not_echo_exception_or_internal_paths(monkeypatch, capsys):
    def unavailable(**kwargs):
        raise RuntimeError("PRIVATE-CANARY /private/production/releases")
    monkeypatch.setattr(benchmark, "run_benchmark", unavailable)
    assert benchmark.main([]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"version": benchmark.VERSION, "status": "unavailable", "reason_code": "benchmark_failed"}


def test_actual_benchmark_is_offline_deterministic_and_measures_zero_warm_reverification(tmp_path):
    bootstrap = """
import sys, runpy
sys.dont_write_bytecode = True
def no_network(event, args):
    if event.startswith('socket.') or event in {'sqlite3.connect', 'subprocess.Popen'}:
        raise RuntimeError('Network/provider/database calls are forbidden in this fixture benchmark')
sys.addaudithook(no_network)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    env = {**os.environ, "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
        "REDIS_URL": "redis://127.0.0.1:1/0", "TMPDIR": str(tmp_path)}
    reports = []
    for _ in range(2):
        process = subprocess.run([sys.executable, "-c", bootstrap, str(SCRIPT), "--releases", "4",
            "--iterations", "2", "--workers", "4"], capture_output=True, text=True, timeout=30,
            check=False, env=env)
        assert process.returncode == 0, process.stdout + process.stderr
        assert process.stderr == ""
        report = json.loads(process.stdout)
        assert report["synthetic_only"] is True and report["offline"] is True
        assert report["scientific_acceptance"] is False and report["production_sla_established"] is False
        assert report["measurement_scope"] == "local_verified_service_threadpool_not_http_or_production"
        assert report["release_count"] == report["assessment_count"] == 4
        assert len(report["fixture_inventory"]) == 4
        for phase in ("catalog_cold", "bundle_cold"):
            assert report["phases"][phase]["verification_count"] == 8
            assert report["phases"][phase]["cached_entries"] == 8
        for phase in ("catalog_warm", "bundle_warm"):
            measured = report["phases"][phase]
            assert measured["verification_count"] == 0 and measured["cache_hits"] == 16
            assert measured["response_identity_count"] == 1
            assert len(measured["round_latency_ms"]) == 2
            assert all(value >= 0 for value in measured["round_latency_ms"])
            assert measured["p95_round_ms"] == max(measured["round_latency_ms"])
            assert measured["cached_bytes_approximate"] <= report["cache_limits"]["cached_bytes"]
        assert report["memory_methods"]["process_peak_rss_after_bytes"] > 0
        reports.append(report)
    assert reports[0]["fixture_inventory_sha256"] == reports[1]["fixture_inventory_sha256"]
    assert reports[0]["fixture_inventory"] == reports[1]["fixture_inventory"]
    assert list(tmp_path.iterdir()) == [], "Synthetic temporary files leaked after benchmark completion"
