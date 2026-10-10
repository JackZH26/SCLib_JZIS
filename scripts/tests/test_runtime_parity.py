"""Synthetic orchestration regressions: no Docker, services or sockets are used."""
from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_runtime_parity as parity
from runtime_inventory import SCHEMA, digest


class RuntimeParityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "api").mkdir()
        (self.root / "scripts").mkdir()
        for name in ("uv.lock", "pyproject.toml", "Dockerfile"):
            (self.root / "api" / name).write_text("synthetic " + name)
        (self.root / "scripts/runtime_inventory.py").write_text("# synthetic collector\n")
        self.inventory = {
            "schema": SCHEMA, "source_revision": "a" * 40,
            "python_minor": "3.11", "python_version": "3.11.14", "implementation": "CPython",
            "system": "Linux", "machine": "x86_64", "project_name": "sclib-api", "project_version": "0.1.0",
            "packages": {"sclib-api": "0.1.0", "sqlalchemy": "2.0.49"},
            "lock_sha256": digest((self.root / "api/uv.lock").read_bytes()),
            "pyproject_sha256": digest((self.root / "api/pyproject.toml").read_bytes()),
            "collector_sha256": digest((self.root / "scripts/runtime_inventory.py").read_bytes()),
        }
        self.tests_path = self.root / "test-runtime.json"
        self.tests_path.write_text(json.dumps(self.inventory))
        self.calls = []
        self.labels = {}
        self.image_id = "sha256:" + "b" * 64
        self.cid = "c" * 64
        self.runtime = dict(self.inventory)
        self.endpoint = "unix:///var/run/docker.sock"
        self.untracked = ""
        for context in (patch.object(parity, "ROOT", self.root),
                        patch.object(parity.platform, "system", return_value="Linux"),
                        patch.dict(os.environ, {}, clear=True),
                        patch("socket.socket", side_effect=AssertionError("network forbidden")),
                        patch.object(parity, "run", side_effect=self.fake_run)):
            context.start()
            self.addCleanup(context.stop)

    def fake_run(self, command, *, stdin=None, timeout=120):
        self.calls.append((command, stdin, timeout))
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "a" * 40
        if command[:2] == ["git", "diff"]:
            return ""
        if command[:2] == ["git", "ls-files"]:
            return self.untracked
        if command[3:5] == ["context", "inspect"]:
            return json.dumps(self.endpoint)
        if command[3] == "build":
            Path(command[command.index("--iidfile") + 1]).write_text(self.image_id)
            self.labels = dict(command[index + 1].split("=", 1) for index, item in enumerate(command) if item == "--label")
            return ""
        if command[3:5] == ["image", "inspect"]:
            return json.dumps([{"Id": self.image_id, "Os": "linux", "Architecture": "amd64", "Config": {"Labels": self.labels}}])
        if command[3] == "run":
            return json.dumps(self.runtime)
        raise AssertionError(f"unexpected operation: {command[:5]}")

    def test_build_and_capture_only_then_compare_and_persist_provenance(self):
        report = parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertTrue(report["matches"])
        self.assertEqual(report["image_id"], self.image_id)
        build = next(cmd for cmd, _, _ in self.calls if cmd[3:4] == ["build"])
        self.assertEqual(build[build.index("--platform") + 1], "linux/amd64")
        capture = next(call for call in self.calls if call[0][3:4] == ["run"])
        command, stdin, _ = capture
        for option, value in (("--network", "none"), ("--pull", "never"),
                              ("--cap-drop", "ALL"), ("--entrypoint", "/opt/venv/bin/python"),
                              ("--security-opt", "no-new-privileges"), ("--user", "1001:1001")):
            self.assertEqual(command[command.index(option) + 1], value)
        self.assertIn("--read-only", command)
        self.assertIn("--no-healthcheck", command)
        self.assertIn("-I", command)
        self.assertIn("-B", command)
        self.assertEqual(stdin, "# synthetic collector\n")
        for forbidden in ("--mount", "-v", "--env", "-e", "--env-file", "--privileged", "--publish"):
            self.assertNotIn(forbidden, command)
        self.assertFalse(any("push" in cmd or "compose" in cmd for cmd, _, _ in self.calls))
        self.assertEqual(json.loads((self.root / "artifacts/parity-report.json").read_text()), report)

    def test_changed_runtime_dependency_is_a_failed_report(self):
        self.runtime["packages"] = {"sclib-api": "0.1.0", "sqlalchemy": "9.0"}
        report = parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertFalse(report["matches"])
        self.assertIn("runtime package mismatch: sqlalchemy", report["failures"])

    def test_stale_test_inputs_fail_before_docker_build(self):
        self.inventory["pyproject_sha256"] = "e" * 64
        self.tests_path.write_text(json.dumps(self.inventory))
        with self.assertRaises(ValueError):
            parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertFalse(any(command[0] == "docker" for command, _, _ in self.calls))

    def test_untracked_build_input_or_remote_daemon_fails_before_build(self):
        for untracked, endpoint in (("api/untracked.py", self.endpoint), ("", "tcp://host:2376")):
            self.calls.clear()
            self.untracked, self.endpoint = untracked, endpoint
            with self.assertRaises(ValueError):
                parity.check("api", self.tests_path, self.root / "artifacts")
            self.assertFalse(any("build" in command for command, _, _ in self.calls))

    def test_custom_daemon_environment_is_refused(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://private:2376"}), self.assertRaises(ValueError):
            parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertEqual(self.calls, [])

    def test_wrong_test_project_or_release_architecture_is_refused(self):
        for field, value in (("project_name", "sclib-ingestion"), ("machine", "aarch64")):
            with self.subTest(field=field):
                inventory = {**self.inventory, field: value}
                with self.assertRaises(ValueError):
                    parity.provenance("api", inventory)

    def test_tracked_build_changes_and_docker_errors_fail_without_capture(self):
        fake = self.fake_run
        for failed_operation in ("diff", "build"):
            self.calls.clear()
            def failure(command, failed_operation=failed_operation, **kwargs):
                if failed_operation in command:
                    raise subprocess.CalledProcessError(1, command)
                return fake(command, **kwargs)
            with patch.object(parity, "run", side_effect=failure), self.assertRaises(subprocess.CalledProcessError):
                parity.check("api", self.tests_path, self.root / "artifacts")
            self.assertFalse(any(cmd[3:4] == ["run"] for cmd, _, _ in self.calls))

    def test_bad_inventory_or_mutable_image_reference_is_refused(self):
        self.tests_path.write_text("{}")
        with self.assertRaises(ValueError):
            parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertEqual(self.calls, [])
        with self.assertRaises(ValueError):
            parity.inventory_command("latest", self.root / "cid", "run", self.inventory)

    def test_image_metadata_cannot_mismatch_build_inputs(self):
        fake = self.fake_run
        def altered(command, **kwargs):
            result = fake(command, **kwargs)
            if command[3:5] == ["image", "inspect"]:
                value = json.loads(result)
                value[0]["Config"]["Labels"] = {}
                return json.dumps(value)
            return result
        with patch.object(parity, "run", side_effect=altered), self.assertRaises(ValueError):
            parity.check("api", self.tests_path, self.root / "artifacts")
        self.assertFalse(any(cmd[3:4] == ["run"] for cmd, _, _ in self.calls))

    def test_cleanup_only_removes_exact_owned_container(self):
        cidfile = self.root / "cid"
        cidfile.write_text(self.cid)
        details = [{"Id": self.cid, "Config": {"Labels": {parity.RUN_LABEL: "owned"}}}]
        with patch.object(parity, "run", side_effect=[json.dumps(self.cid), json.dumps(details), ""]) as runner:
            parity.clean_owned_container(cidfile, "owned")
        self.assertEqual(runner.call_args.args[0][-3:], ["rm", "--force", self.cid])
        with patch.object(parity, "run", side_effect=[json.dumps(self.cid), json.dumps(details)]) as runner, self.assertRaises(ValueError):
            parity.clean_owned_container(cidfile, "not-owner")
        self.assertEqual(runner.call_count, 2)

    def test_subprocess_environment_cannot_forward_provider_settings(self):
        # Exercise the real wrapper with the OS subprocess entirely mocked.
        import importlib.util
        spec = importlib.util.spec_from_file_location("parity_env_test", ROOT / "scripts/run_runtime_parity.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, {"DATABASE_URL": "private", "GOOGLE_APPLICATION_CREDENTIALS": "private"}), patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok\n")) as runner:
            self.assertEqual(module.run(["synthetic-command"]), "ok")
        self.assertEqual(set(runner.call_args.kwargs["env"]), {"PATH", "LANG"})
        self.assertNotIn("shell", runner.call_args.kwargs)

    def cli_failure(self):
        output = self.root / "artifacts"
        argv = ["run_runtime_parity.py", "--project", "api", "--tests", str(self.tests_path),
                "--output", str(output)]
        with patch.object(sys, "argv", argv), patch("sys.stdout", new_callable=io.StringIO) as stdout, patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(parity.main(), 1)
        self.assertEqual(stderr.getvalue(), "")
        text = stdout.getvalue()
        self.assertNotIn("PRIVATE", text)
        report = json.loads(text)
        self.assertEqual(set(report), {"schema", "matches", "project", "stage", "cause",
                                      "error_kind", "subprocess_exit_code", "observed_build_signals"})
        self.assertEqual(report["schema"], "sclib-runtime-parity-failure/v2")
        self.assertFalse(report["matches"])
        self.assertEqual(json.loads((output / "failure-report.json").read_text()), report)
        self.assertNotIn("PRIVATE", (output / "failure-report.json").read_text())
        return report

    def test_subprocess_failures_preserve_exception_identity_and_record_exact_stage(self):
        cases = [
            (["git", "diff"], "provenance"),
            (["docker", "--context", "default", "context"], "docker_context"),
            (["docker", "--context", "default", "build"], "build"),
            (["docker", "--context", "default", "image"], "image_validation"),
            (["docker", "--context", "default", "run"], "capture"),
        ]
        for prefix, stage in cases:
            with self.subTest(stage=stage):
                error = subprocess.CalledProcessError(
                    125, ["PRIVATE_COMMAND"], output="PRIVATE_STDOUT",
                    stderr="PRIVATE_DSN PRIVATE_TOKEN toomanyrequests: pull rate limit",
                )
                def failure(command, **kwargs):
                    if command[:len(prefix)] == prefix:
                        raise error
                    return self.fake_run(command, **kwargs)
                with patch.object(parity, "run", side_effect=failure):
                    with self.assertRaises(subprocess.CalledProcessError) as caught:
                        parity.check("api", self.tests_path, self.root / "artifacts")
                    self.assertIs(caught.exception, error)
                    report = self.cli_failure()
                self.assertEqual(report["stage"], stage)
                self.assertEqual(report["cause"], "registry_pull_rate_limit" if stage == "build" else "unknown")

    def test_invalid_input_and_provenance_have_safe_different_stages(self):
        self.tests_path.write_text("PRIVATE_INVALID_JSON")
        self.assertEqual(self.cli_failure()["stage"], "inputs")
        self.tests_path.write_text(json.dumps(self.inventory))
        with patch.dict(os.environ, {"DOCKER_HOST": "PRIVATE_REMOTE_DAEMON"}):
            report = self.cli_failure()
        self.assertEqual(report["stage"], "provenance")
        self.assertEqual(report["cause"], "unknown")
        self.assertEqual(self.calls, [])

    def test_cleanup_still_runs_and_original_cleanup_exception_takes_precedence(self):
        capture_error = subprocess.TimeoutExpired(["PRIVATE_COMMAND"], 1, stderr=b"PRIVATE_STDERR")
        cleanup_error = ValueError("PRIVATE_CLEANUP_FAILURE")
        def capture_failure(command, **kwargs):
            if command[3:4] == ["run"]:
                raise capture_error
            return self.fake_run(command, **kwargs)
        with patch.object(parity, "run", side_effect=capture_failure), patch.object(parity, "clean_owned_container") as cleanup:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                parity.check("api", self.tests_path, self.root / "artifacts")
            self.assertIs(caught.exception, capture_error)
            self.assertEqual(parity.failure_report("api", caught.exception)["stage"], "capture")
            cleanup.assert_called_once()
        with patch.object(parity, "run", side_effect=capture_failure), patch.object(parity, "clean_owned_container", side_effect=cleanup_error) as cleanup:
            with self.assertRaises(ValueError) as caught:
                parity.check("api", self.tests_path, self.root / "artifacts")
            self.assertIs(caught.exception, cleanup_error)
            self.assertIs(caught.exception.__context__, capture_error)
            self.assertEqual(self.cli_failure()["stage"], "cleanup")
            self.assertEqual(cleanup.call_count, 2)

    def test_comparison_failure_does_not_become_a_pass_or_expose_message(self):
        error = ValueError("PRIVATE_COMPARISON")
        with patch.object(parity, "compare", side_effect=error):
            report = self.cli_failure()
        self.assertEqual((report["stage"], report["cause"]), ("comparison", "unknown"))

    def test_classification_is_bounded_and_does_not_infer_from_other_streams(self):
        bound = parity.MAX_DIAGNOSTIC_STREAM
        cases = [
            ("toomanyrequests PRIVATE", "registry_pull_rate_limit"),
            (b"PRIVATE You have reached your unauthenticated pull rate limit", "registry_pull_rate_limit"),
            ("toomanyrequests" + "x" * bound, "unknown"),
            ("PRIVATE unrelated HTTP 429", "unknown"),
            (None, "unknown"),
        ]
        for stderr, expected in cases:
            error = subprocess.CalledProcessError(1, ["PRIVATE toomanyrequests"], output="PRIVATE toomanyrequests", stderr=stderr)
            error._runtime_parity_stage = "build"
            report = parity.failure_report("api", error)
            self.assertEqual(report["cause"], expected)
            self.assertNotIn("PRIVATE", json.dumps(report))
        for error in (ValueError("PRIVATE toomanyrequests"), subprocess.TimeoutExpired("PRIVATE", 1, stderr=b"toomanyrequests")):
            error._runtime_parity_stage = "build"
            self.assertEqual(parity.failure_report("api", error)["cause"], "unknown")

    def test_unknown_stage_and_project_cannot_inject_report_fields(self):
        for stage in ("PRIVATE_STAGE", ["PRIVATE_STAGE"], None):
            error = ValueError("PRIVATE_MESSAGE")
            error._runtime_parity_stage = stage
            report = parity.failure_report("PRIVATE_PROJECT", error)
            self.assertEqual((report["stage"], report["project"], report["cause"]), ("unknown", "unknown", "unknown"))
            self.assertNotIn("PRIVATE", json.dumps(report))

    def test_failure_artifact_write_error_remains_sanitized_and_nonzero(self):
        output = self.root / "artifacts"
        output.write_text("not a directory")
        argv = ["run_runtime_parity.py", "--project", "api", "--tests", str(self.tests_path), "--output", str(output)]
        with patch.object(sys, "argv", argv), patch("sys.stdout", new_callable=io.StringIO) as stdout, patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(parity.main(), 1)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(lines[0], "Runtime parity failure artifact unavailable.")
        self.assertEqual(json.loads(lines[1])["stage"], "artifacts")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(str(output), stdout.getvalue())

    def test_success_and_scientific_mismatch_do_not_create_failure_diagnostics(self):
        for packages, expected in ((self.inventory["packages"], True), ({"sclib-api": "0.1.0", "sqlalchemy": "9.0"}, False)):
            self.runtime["packages"] = packages
            report = parity.check("api", self.tests_path, self.root / "artifacts")
            self.assertEqual(report["matches"], expected)
            self.assertFalse((self.root / "artifacts/failure-report.json").exists())

    def test_build_stdout_and_stderr_observations_are_fixed_ids_without_private_text(self):
        error = subprocess.CalledProcessError(
            17, ["PRIVATE_CMD", "PRIVATE_ENV"],
            output="PRIVATE_DSN $HOME is not defined\nCannot connect to the Docker daemon PRIVATE_HOST\n",
            stderr=b"PRIVATE_TOKEN failed to resolve source metadata\n429 Too Many Requests PRIVATE_URL",
        )
        error._runtime_parity_stage = "build"
        report = parity.failure_report("api", error)
        self.assertEqual(report["error_kind"], "called_process_error")
        self.assertEqual(report["subprocess_exit_code"], 17)
        self.assertEqual(report["cause"], "unknown")
        self.assertEqual(report["observed_build_signals"], [
            "docker_daemon_unavailable", "home_unset", "http_429", "source_metadata_resolution_failed",
        ])
        self.assertNotIn("PRIVATE", json.dumps(report))
        def build_failure(command, **kwargs):
            if command[3:4] == ["build"]:
                raise error
            return self.fake_run(command, **kwargs)
        with patch.object(parity, "run", side_effect=build_failure):
            self.assertEqual(self.cli_failure(), report)

    def test_signal_markers_are_bounded_per_stream_and_never_read_command_or_exception_text(self):
        bound = parity.MAX_DIAGNOSTIC_STREAM
        error = subprocess.CalledProcessError(
            1, ["no space left on device", "PRIVATE_COMMAND"],
            output="$HOME is not defined" + "x" * bound,
            stderr=b"toomanyrequests" + b"x" * bound,
        )
        error._runtime_parity_stage = "build"
        report = parity.failure_report("api", error)
        self.assertEqual(report["observed_build_signals"], [])
        self.assertEqual(report["cause"], "unknown")
        error.output, error.stderr = "toomany", "requests"
        self.assertEqual(parity.failure_report("api", error)["observed_build_signals"], [])
        error.output, error.stderr = "toomanyrequests PRIVATE", "unrelated PRIVATE"
        report = parity.failure_report("api", error)
        self.assertEqual(report["observed_build_signals"], ["registry_pull_quota"])
        self.assertEqual(report["cause"], "unknown")
        error._runtime_parity_stage = "capture"
        self.assertEqual(parity.failure_report("api", error)["observed_build_signals"], [])

    def test_concrete_build_signals_do_not_infer_from_command_names(self):
        cases = [
            ("manifest unknown", ["manifest_missing"]),
            ("pull access denied", ["registry_auth_denied"]),
            ("Temporary failure in name resolution", ["dns_resolution_failed"]),
            ("certificate verify failed", ["tls_verification_failed"]),
            ("i/o timeout", ["transport_timeout"]),
            ("No space left on device", ["disk_full"]),
            ("No solution found when resolving dependencies", ["dependency_resolution_failed"]),
            ("Failed to download package", ["dependency_fetch_failed"]),
            ("E: Unable to locate package", ["apt_failed"]),
            ("buildx component is missing or broken", ["buildx_missing"]),
            ("unknown flag: --PRIVATE", ["unsupported_flag"]),
            ("apt-get uv pip buildx Dockerfile PRIVATE", []),
        ]
        for text, signals in cases:
            with self.subTest(signals=signals):
                error = subprocess.CalledProcessError(1, ["PRIVATE"], output=text + " PRIVATE", stderr="")
                error._runtime_parity_stage = "build"
                report = parity.failure_report("api", error)
                self.assertEqual(report["observed_build_signals"], signals)
                self.assertEqual(report["cause"], "unknown")
                self.assertNotIn("PRIVATE", json.dumps(report))

    def test_error_kinds_and_exit_codes_are_allowlisted_even_for_malformed_exceptions(self):
        for code in (True, "PRIVATE", None, 2**80):
            error = subprocess.CalledProcessError(code, "PRIVATE")
            self.assertIsNone(parity.failure_report("api", error)["subprocess_exit_code"])
        for error, kind in (
            (subprocess.TimeoutExpired("PRIVATE", 1, output=b"i/o timeout PRIVATE"), "timeout"),
            (ValueError("PRIVATE"), "validation"),
            (OSError("PRIVATE"), "io"),
            (RuntimeError("PRIVATE"), "unknown"),
        ):
            error._runtime_parity_stage = "build"
            report = parity.failure_report("api", error)
            self.assertEqual(report["error_kind"], kind)
            self.assertIsNone(report["subprocess_exit_code"])
            self.assertEqual(report["cause"], "unknown")
            self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
