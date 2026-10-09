"""Runner configuration safety with fake Docker/sudo; no services or sockets."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure_ci_docker_mirror as mirror


class CIDockerMirrorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / "daemon.json"
        self.calls = []
        self.endpoint = "unix:///var/run/docker.sock"
        self.context = "default"
        self.active = ""
        self.paused = ""
        self.restarting = ""
        self.server_mirrors = []
        self.validate_error = None
        self.restart_error = None
        self.after_validation = lambda: None
        self.after_restart = lambda: None
        environment = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"}
        for context in (patch.object(mirror, "CONFIG", self.config),
                        patch.object(mirror.platform, "system", return_value="Linux"),
                        patch.dict(os.environ, environment, clear=True),
                        patch.object(mirror, "run", side_effect=self.fake_run),
                        patch("socket.socket", side_effect=AssertionError("network forbidden"))):
            context.start()
            self.addCleanup(context.stop)

    def fake_run(self, command, *, timeout=20):
        self.calls.append((command, timeout))
        if command == ["docker", "context", "show"]:
            return self.context
        if command[:5] == mirror.DOCKER + ["context", "inspect"]:
            return json.dumps(self.endpoint)
        if command[:4] == mirror.DOCKER + ["ps"]:
            return {"status=running": self.active, "status=paused": self.paused,
                    "status=restarting": self.restarting}[command[-1]]
        if command[:4] == mirror.DOCKER + ["info"]:
            return json.dumps(self.server_mirrors)
        if command[:4] == ["sudo", "-n", "dockerd", "--validate"]:
            if self.validate_error:
                raise self.validate_error
            self.after_validation()
            return ""
        if command[:3] == ["sudo", "-n", "install"]:
            shutil.copyfile(command[-2], command[-1])
            self.config.chmod(int(command[4], 8))
            return ""
        if command == ["sudo", "-n", "systemctl", "restart", "docker"]:
            if self.restart_error:
                raise self.restart_error
            self.server_mirrors = json.loads(self.config.read_text())["registry-mirrors"]
            self.after_restart()
            return ""
        raise AssertionError("unexpected operation")

    def mutations(self):
        return [cmd for cmd, _ in self.calls if cmd[:3] == ["sudo", "-n", "install"] or "restart" in cmd]

    def test_preserves_unrelated_config_mirrors_and_permissions_before_one_restart(self):
        original = {"log-driver": "local", "features": {"buildkit": True}, "registry-mirrors": ["https://prior.invalid"], "private-value": "secret-marker"}
        self.config.write_text(json.dumps(original))
        self.config.chmod(0o640)
        report = mirror.configure()
        self.assertEqual(json.loads(self.config.read_text()), {**original, "registry-mirrors": [mirror.MIRROR, "https://prior.invalid"]})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(report, {"mirror": mirror.MIRROR, "endpoint": self.endpoint, "restarted": True})
        validate = next(i for i, (cmd, _) in enumerate(self.calls) if "--validate" in cmd)
        install = next(i for i, (cmd, _) in enumerate(self.calls) if "install" in cmd)
        self.assertLess(validate, install)
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual([timeout for cmd, timeout in self.calls if "restart" in cmd], [60])

    def test_missing_file_creates_only_mirror_configuration(self):
        mirror.configure()
        self.assertEqual(json.loads(self.config.read_text()), {"registry-mirrors": [mirror.MIRROR]})

    def test_configured_daemon_is_noop_preserving_exact_bytes(self):
        original = b'{ "registry-mirrors" : ["https://mirror.gcr.io"], "debug":false }\n'
        self.config.write_bytes(original)
        self.server_mirrors = [mirror.MIRROR + "/"]
        self.assertFalse(mirror.configure()["restarted"])
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse(any(cmd[0] == "sudo" for cmd, _ in self.calls))

    def test_present_but_inactive_mirror_validates_and_restarts_without_rewrite(self):
        original = b'{ "registry-mirrors": ["https://mirror.gcr.io"] }'
        self.config.write_bytes(original)
        self.assertTrue(mirror.configure()["restarted"])
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(len(self.mutations()), 1)

    def test_non_hosted_or_non_linux_is_refused_before_commands(self):
        for key, value in (("GITHUB_ACTIONS", "false"), ("RUNNER_ENVIRONMENT", "self-hosted"), ("RUNNER_OS", "macOS")):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                mirror.configure()
        with patch.object(mirror.platform, "system", return_value="Darwin"), self.assertRaises(ValueError):
            mirror.configure()
        self.assertEqual(self.calls, [])

    def test_docker_overrides_are_refused_before_commands(self):
        for key in mirror.OVERRIDES:
            with self.subTest(key=key), patch.dict(os.environ, {key: "private-value"}), self.assertRaises(ValueError):
                mirror.configure()
        self.assertEqual(self.calls, [])

    def test_nondefault_or_remote_or_non_system_socket_refused_before_mutation(self):
        for context, endpoint in (("other", self.endpoint), ("default", "tcp://remote:2376"), ("default", "unix:///private/daemon.sock")):
            with self.subTest(context=context, endpoint=endpoint):
                self.context, self.endpoint = context, endpoint
                with self.assertRaises(ValueError):
                    mirror.configure()
        self.assertEqual(self.mutations(), [])

    def test_running_paused_and_restarting_containers_refused(self):
        for active, paused, restarting in (("container", "", ""), ("", "container", ""), ("", "", "container")):
            self.active, self.paused, self.restarting = active, paused, restarting
            with self.assertRaises(ValueError):
                mirror.configure()
        self.assertEqual(self.mutations(), [])

    def test_invalid_config_is_not_replaced(self):
        for original in (b'[]', b'{', b'{"registry-mirrors":false}', b'{"registry-mirrors":[1]}', b'{"debug":true,"debug":false}'):
            with self.subTest(original=original):
                self.config.write_bytes(original)
                with self.assertRaises(ValueError):
                    mirror.configure()
                self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.mutations(), [])

    def test_symlink_and_oversized_config_refused(self):
        target = self.config.with_name("target.json")
        target.write_text('{}')
        self.config.symlink_to(target)
        with self.assertRaises(ValueError):
            mirror.configure()
        self.config.unlink()
        self.config.write_bytes(b' ' * 1_048_577)
        with self.assertRaises(ValueError):
            mirror.configure()
        self.assertEqual(self.mutations(), [])

    def test_validation_failure_keeps_original_file_and_does_not_restart(self):
        self.config.write_text('{}')
        self.validate_error = subprocess.CalledProcessError(1, "private command", stderr="secret-marker")
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            mirror.configure()
        self.assertIs(caught.exception, self.validate_error)
        self.assertEqual(self.config.read_text(), '{}')
        self.assertEqual(self.mutations(), [])

    def test_changed_config_or_new_active_container_after_validation_refused(self):
        for change in (lambda: self.config.write_text('{"debug":true}'), lambda: setattr(self, "paused", "new")):
            with self.subTest(change=change):
                self.config.write_text('{}')
                self.paused = ""
                self.after_validation = change
                with self.assertRaises(ValueError):
                    mirror.configure()
        self.assertEqual(self.mutations(), [])

    def test_context_change_after_validation_refused(self):
        self.after_validation = lambda: setattr(self, "endpoint", "tcp://remote:2376")
        with self.assertRaises(ValueError):
            mirror.configure()
        self.assertEqual(self.mutations(), [])

    def test_restart_failure_is_not_retried_or_claimed_success(self):
        self.restart_error = subprocess.TimeoutExpired("private command", 60, stderr="secret-marker")
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            mirror.configure()
        self.assertIs(caught.exception, self.restart_error)
        self.assertEqual(len([cmd for cmd, _ in self.calls if "restart" in cmd]), 1)

    def test_failed_post_restart_activation_or_changed_endpoint_is_failure(self):
        for change in (lambda: setattr(self, "server_mirrors", []), lambda: setattr(self, "endpoint", "tcp://remote:2376")):
            self.endpoint = "unix:///var/run/docker.sock"
            self.server_mirrors = []
            self.after_restart = change
            with self.assertRaises(ValueError):
                mirror.configure()

    def test_main_never_exposes_error_or_config_data(self):
        error = subprocess.CalledProcessError(7, ["secret-command"], output="secret-output", stderr="secret-stderr")
        with patch.object(mirror, "configure", side_effect=error), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(mirror.main(), 1)
        self.assertEqual(output.getvalue(), "CI Docker mirror setup failed\n")


if __name__ == "__main__":
    unittest.main()
