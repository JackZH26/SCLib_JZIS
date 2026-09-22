"""Synthetic orchestration regressions: no Docker, services or sockets are used."""
from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
