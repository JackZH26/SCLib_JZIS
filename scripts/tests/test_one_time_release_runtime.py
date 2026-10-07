"""Synthetic offline checks; never GitHub, Docker, registry or deployment I/O."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "verify_one_time_release_runtime.py"
spec = importlib.util.spec_from_file_location("one_time_runtime_offline_tests", SOURCE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def environment(event):
    return {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": gate.REPOSITORY,
            "GITHUB_API_URL": "https://api.github.com", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_WORKFLOW_REF": gate.WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_EVENT_PATH": str(event)}


def fixture(project="api"):
    expected = {"source_revision": gate.PAYLOAD, "lock_sha256": "b" * 64,
                "pyproject_sha256": "c" * 64, "collector_sha256": "d" * 64,
                "dockerfile_sha256": "e" * 64, "parity_source_sha256": "f" * 64}
    inventory = {"schema": "sclib-runtime-inventory/v2", "python_minor": "3.11",
        "python_version": "3.11.15", "implementation": "CPython", "system": "Linux", "machine": "x86_64",
        **{k: expected[k] for k in ("source_revision", "lock_sha256", "pyproject_sha256", "collector_sha256")},
        "project_name": "sclib-" + project, "project_version": "0.1.0",
        "packages": {"sclib-" + project: "0.1.0", "example-runtime": "2.0.0"}}
    digest = "sha256:" + "1" * 64
    image = f"ghcr.io/jackzh26/sclib-{project}@{digest}"
    detail = {"Id": "sha256:" + "2" * 64, "RepoDigests": [image], "Os": "linux", "Architecture": "amd64",
              "Config": {"Labels": {"org.opencontainers.image.revision": gate.PAYLOAD,
                                     "org.opencontainers.image.source": "https://github.com/" + gate.REPOSITORY}}}
    return expected, inventory, digest, image, detail


class OneTimeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.event = self.root / "event.json"
        self.event.write_bytes(gate.encoded({"repository": {"full_name": gate.REPOSITORY, "id": 1210057429}}))
        guard = patch.dict(os.environ, environment(self.event), clear=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.expected, self.inventory, self.digest, self.image, self.detail = fixture()
        self.locked = self.root / "locked.json"
        self.locked.write_bytes(gate.encoded(self.inventory))
        self.output = self.root / "result"
        self.calls = []

    def fake_command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:5] == ["docker", "--context", "default", "context", "inspect"]:
            return json.dumps("unix:///var/run/docker.sock")
        if args[:4] == ["docker", "--context", "default", "pull"]:
            return "synthetic pull"
        if args[:5] == ["docker", "--context", "default", "image", "inspect"]:
            return json.dumps([self.detail])
        if args[:4] == ["docker", "--context", "default", "run"]:
            self.assertIn("none", args)
            self.assertIn("--read-only", args)
            self.assertIn("--no-healthcheck", args)
            self.assertIn("/opt/venv/bin/python", args)
            self.assertNotIn("--env", args)
            self.assertNotIn("--volume", args)
            self.assertEqual(kwargs["stdin"], "# synthetic collector\n")
            return gate.encoded(self.runtime).decode().strip()
        self.fail("Unexpected external operation in synthetic command: " + repr(args))

    def run_check(self, runtime=None, checkout_effect=None):
        self.runtime = copy.deepcopy(self.inventory if runtime is None else runtime)
        with patch.object(gate, "checkout", side_effect=checkout_effect,
                          return_value=(self.expected, b"# synthetic collector\n")), \
             patch.object(gate, "command", side_effect=self.fake_command):
            return gate.check(project="api", image_digest=self.digest, locked_inventory=self.locked, output=self.output)

    def test_final_digest_parity_is_not_Test_success(self):
        report = self.run_check()
        self.assertTrue(report["matches"])
        self.assertEqual(report["source_revision"], gate.PAYLOAD)
        self.assertEqual(report["control_revision"], "a" * 40)
        self.assertEqual(report["scope"], gate.SCOPE)
        self.assertFalse(report["claims_Test_success"])
        self.assertFalse(report["claims_application_execution"])
        self.assertIn("pending_waived", report["api_regression"])
        self.assertEqual(report["inventory_source"], "fresh_uv_locked_dev_venv_not_Test_artifacts")
        self.assertEqual(len([c for c, _ in self.calls if c[3] == "pull"]), 1)
        self.assertEqual(len([c for c, _ in self.calls if c[3] == "run"]), 1)
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {"started.json", "locked-runtime.json", "release-runtime.json", "release-parity-report.json"})

    def test_wrong_dispatch_or_retry_refused_before_registry(self):
        for key, value in (("GITHUB_EVENT_NAME", "workflow_run"), ("GITHUB_REF", "refs/heads/branch"),
                           ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REPOSITORY", "other/repo"),
                           ("GITHUB_WORKFLOW_REF", gate.WORKFLOW_REF.replace("release-images.yml", "other.yml"))):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), \
                 patch.object(gate, "command", side_effect=AssertionError("No external commands allowed")), \
                 self.assertRaises(gate.RuntimeGateError):
                gate.check(project="api", image_digest=self.digest, locked_inventory=self.locked, output=self.output)
        self.assertFalse(self.output.exists())

    def test_dispatch_repository_event_cannot_be_forged_by_environment_alone(self):
        self.event.write_bytes(gate.encoded({"repository": {"full_name": gate.REPOSITORY, "id": 1}}))
        with self.assertRaises(gate.RuntimeGateError): gate.dispatch_identity()

    def test_wrong_locked_revision_or_collector_fails_before_pull(self):
        self.inventory["source_revision"] = "b" * 40
        self.locked.write_bytes(gate.encoded(self.inventory))
        with self.assertRaises(gate.RuntimeGateError): self.run_check()
        self.assertEqual(self.calls, [])
        self.assertEqual(gate.decode((self.output / "first-failure.json").read_bytes())["code"], "locked_inventory_input_pin")

    def test_wrong_OCI_digest_platform_source_and_revision_rejected(self):
        for key, value in (("Os", "other"), ("Architecture", "arm64"), ("RepoDigests", [])):
            detail = copy.deepcopy(self.detail); detail[key] = value
            with self.subTest(key=key), self.assertRaises(gate.RuntimeGateError):
                gate.validate_image(detail, self.image, gate.PAYLOAD)
        for key in ("org.opencontainers.image.revision", "org.opencontainers.image.source"):
            detail = copy.deepcopy(self.detail); detail["Config"]["Labels"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(gate.RuntimeGateError):
                gate.validate_image(detail, self.image, gate.PAYLOAD)

    def test_package_mismatch_retains_negative_report(self):
        runtime = copy.deepcopy(self.inventory); runtime["packages"]["example-runtime"] = "3.0.0"
        report = self.run_check(runtime)
        self.assertFalse(report["matches"])
        self.assertEqual(report["reason_codes"], ["runtime_inventory_mismatch"])
        self.assertEqual(report["mismatch_count"], 1)
        self.assertFalse(report["claims_Test_success"])

    def test_changed_payload_inputs_fail_and_first_failure_remains(self):
        changed = dict(self.expected); changed["lock_sha256"] = "0" * 64
        with self.assertRaises(gate.RuntimeGateError):
            self.run_check(checkout_effect=[(self.expected, b"# synthetic collector\n"), (changed, b"# synthetic collector\n")])
        failed = gate.decode((self.output / "first-failure.json").read_bytes())
        self.assertEqual(failed["code"], "inputs_changed")
        self.assertFalse(failed["automatic_retry"])

    def test_existing_output_never_overwritten(self):
        self.output.mkdir(); marker = self.output / "marker"; marker.write_text("preserve")
        with self.assertRaises(gate.RuntimeGateError): self.run_check()
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(self.calls, [])

    def test_inventory_sandbox_preserves_payload_original_command(self):
        args = gate.inventory_command("sha256:" + "2" * 64, self.root / "cid", "owned", self.expected)
        for token in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
                      "no-new-privileges", "--memory", "256m", "--entrypoint", "-I", "-B"):
            self.assertIn(token, args)
        self.assertNotIn("--env", args); self.assertNotIn("--mount", args)

    def test_checkout_payload_and_custom_Docker_endpoint_rejected(self):
        with patch.object(gate.platform, "system", return_value="Linux"), \
             patch.object(gate.platform, "machine", return_value="x86_64"), \
             patch.object(gate, "command", return_value="a" * 40), self.assertRaises(gate.RuntimeGateError):
            gate.checkout("api")
        with patch.object(gate.platform, "system", return_value="Linux"), \
             patch.object(gate.platform, "machine", return_value="x86_64"), \
             patch.dict(os.environ, {"DOCKER_HOST": "tcp://other"}), \
             patch.object(gate, "command", side_effect=AssertionError("Must refuse before external command")), \
             self.assertRaises(gate.RuntimeGateError): gate.checkout("api")

    def test_cleanup_only_exact_owned_container(self):
        cid = self.root / "cid"; cid.write_text("3" * 64)
        with patch.object(gate, "command", side_effect=["3" * 64, json.dumps([{
                "Id": "3" * 64, "Config": {"Labels": {gate.RUN_LABEL: "other"}}}])]) as call, \
             self.assertRaises(gate.RuntimeGateError): gate.cleanup(cid, "owned")
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
