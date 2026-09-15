"""No-network acceptance tests; safe to run without the API conftest."""
from __future__ import annotations

import builtins
import copy
import json
import os
import runpy
import sys
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import test_safety as safety


class TestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sclib-tests-")
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.path = self.root / "capability.json"
        self.run_id = "a" * 32
        self.name = "test_" + self.run_id[:16]
        self.password = "b" * 48
        db = f"postgresql://{self.name}:{self.password}@127.0.0.1:25432/{self.name}"
        redis = f"redis://{self.name}:{self.password}@127.0.0.1:26379/0"
        self.env = {"ENVIRONMENT": "test", "SCLIB_TEST_RUN_ID": self.run_id,
                    "SCLIB_TEST_CAPABILITY": str(self.path), "DATABASE_URL": db,
                    "REDIS_URL": redis}
        self.manifest = {
            "schema": safety.SCHEMA, "backend": "native", "run_id": self.run_id,
            "root": str(self.root), "runner_pid": os.getpid(),
            "created_at": time.time() - 1, "expires_at": time.time() + 600,
            "postgres": {"port": 25432, "dsn_sha256": safety.digest(db),
                         "runtime": {"pid": 100, "executable": "/fixture/postgres"}},
            "redis": {"port": 26379, "dsn_sha256": safety.digest(redis),
                      "server_run_id": "c" * 40,
                      "runtime": {"pid": 101, "executable": "/fixture/redis-server"}},
        }
        self.write_manifest()
        self.process_mock = patch.object(safety, "process_identity", side_effect=self.process)
        self.process_mock.start()
        # Guard tests must never create any network socket, including on success.
        self.socket_mock = patch("socket.socket", side_effect=AssertionError("network forbidden"))
        self.socket_mock.start()

    def tearDown(self):
        self.socket_mock.stop()
        self.process_mock.stop()
        self.temporary.cleanup()

    def process(self, pid):
        command = (f"/fixture/postgres -D {self.root}/postgres -h 127.0.0.1 -p 25432"
                   if pid == 100 else "/fixture/redis-server 127.0.0.1:26379")
        return os.getpid(), command

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.path.chmod(0o600)

    def assert_refused(self, env=None):
        with self.assertRaises(safety.UnsafeTestEnvironment) as caught:
            safety.validate_test_environment(self.env if env is None else env)
        message = str(caught.exception)
        self.assertNotIn(self.password, message)
        self.assertNotIn("postgresql://", message)
        self.assertNotIn("redis://", message)

    def test_valid_capability_checks_runtime_without_network(self):
        result = safety.validate_test_environment(self.env)
        self.assertEqual(result.run_id, self.run_id)

    def test_missing_sentinel_refuses_even_with_test_database_name(self):
        self.path.unlink()
        self.assert_refused()

    def test_missing_run_id_and_non_test_environment_refuse(self):
        for change in ({"SCLIB_TEST_RUN_ID": ""}, {"ENVIRONMENT": "production"}):
            with self.subTest(change=change):
                self.assert_refused({**self.env, **change})

    def test_changed_postgres_target_refused_before_runtime_inspection(self):
        with patch.object(safety, "assert_service_runtime") as runtime:
            self.assert_refused({**self.env, "DATABASE_URL":
                                 "postgresql://production:never-print@db.example/production_test"})
            runtime.assert_not_called()

    def test_changed_redis_target_refused_before_runtime_inspection(self):
        with patch.object(safety, "assert_service_runtime") as runtime:
            self.assert_refused({**self.env, "REDIS_URL": "redis://private:never-print@redis.example/0"})
            runtime.assert_not_called()

    def test_malformed_port_does_not_leak_through_exception_chaining(self):
        value = self.env["DATABASE_URL"].replace(":25432/", ":never-print-this-secret/")
        with self.assertRaises(safety.UnsafeTestEnvironment) as caught:
            safety.validate_test_environment({**self.env, "DATABASE_URL": value})
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("never-print-this-secret", rendered)
        self.assertNotIn(self.password, rendered)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_recomputed_hash_does_not_authorize_unsafe_dsn_grammar(self):
        for service, key, original in (
            ("postgres", "DATABASE_URL", self.env["DATABASE_URL"]),
            ("redis", "REDIS_URL", self.env["REDIS_URL"]),
        ):
            for value in (original.replace("127.0.0.1", "localhost"),
                          original.replace("127.0.0.1", "198.51.100.1"),
                          original + "?host=production.example", original + "#override",
                          original.replace(self.name, "postgres"),
                          original.replace(self.password, "shared-test-password")):
                with self.subTest(service=service, case=value[-18:]):
                    self.manifest[service]["dsn_sha256"] = safety.digest(value)
                    self.write_manifest()
                    self.assert_refused({**self.env, key: value})
            self.manifest[service]["dsn_sha256"] = safety.digest(original)
            self.write_manifest()

    def test_default_ports_and_nonzero_redis_db_are_rejected(self):
        for service, key, port in (("postgres", "DATABASE_URL", 5432),
                                   ("redis", "REDIS_URL", 6379)):
            saved = copy.deepcopy(self.manifest)
            old = str(self.manifest[service]["port"])
            value = self.env[key].replace(":" + old, ":" + str(port))
            self.manifest[service].update(port=port, dsn_sha256=safety.digest(value))
            self.write_manifest()
            self.assert_refused({**self.env, key: value})
            self.manifest = saved
        value = self.env["REDIS_URL"].removesuffix("/0") + "/1"
        self.manifest["redis"]["dsn_sha256"] = safety.digest(value)
        self.write_manifest()
        self.assert_refused({**self.env, "REDIS_URL": value})

    def test_public_sentinel_and_parent_permissions_are_rejected(self):
        self.path.chmod(0o644)
        self.assert_refused()
        self.path.chmod(0o600)
        self.root.chmod(0o755)
        self.assert_refused()
        self.root.chmod(0o700)

    def test_symlink_capability_is_rejected(self):
        actual = self.root / "other.json"
        self.path.rename(actual)
        self.path.symlink_to(actual)
        self.assert_refused()

    def test_expired_or_different_run_capability_is_rejected(self):
        for changes in ({"expires_at": time.time() - 1}, {"run_id": "d" * 32},
                        {"created_at": time.time() + 100}, {"runner_pid": 0}):
            saved = copy.deepcopy(self.manifest)
            self.manifest.update(changes)
            self.write_manifest()
            self.assert_refused()
            self.manifest = saved

    def test_cached_settings_cannot_point_elsewhere(self):
        with self.assertRaises(safety.UnsafeTestEnvironment):
            safety.validate_test_environment(self.env, database_url="postgresql://other")
        with self.assertRaises(safety.UnsafeTestEnvironment):
            safety.validate_test_environment(self.env, redis_url="redis://other")

    def test_identity_and_lifetime_reasons_are_static_and_precede_runtime_checks(self):
        baseline = {**self.manifest, "created_at": 900.0, "expires_at": 1500.0}
        cases = (
            ({"run_id": "d" * 32}, "sentinel-identity-invalid"),
            ({"root": "/not-this-owned-root"}, "sentinel-identity-invalid"),
            ({"runner_pid": 0}, "sentinel-identity-invalid"),
            ({"created_at": 1000.001}, "sentinel-not-yet-valid"),
            ({"expires_at": 999.999}, "sentinel-expired"),
            ({"created_at": 999.0, "expires_at": 8200.0}, "sentinel-lifetime-too-long"),
            ({"created_at": float("nan")}, "sentinel-lifetime-invalid"),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                self.manifest = {**baseline, **changes}
                self.write_manifest()
                with (patch.object(safety.time, "time", return_value=1000.0),
                      patch.object(safety, "assert_service_runtime") as runtime,
                      self.assertRaises(safety.UnsafeTestEnvironment) as caught):
                    safety.validate_test_environment(self.env)
                runtime.assert_not_called()
                self.assertEqual(
                    str(caught.exception),
                    f"Unsafe test environment [{reason}]. Use scripts/run_disposable_tests.py; "
                    "no database or Redis connection is permitted.",
                )
                self.assertNotIn(self.password, str(caught.exception))

    def test_lifetime_boundaries_remain_inclusive_without_any_grace_period(self):
        self.manifest.update(created_at=900.0, expires_at=1500.0)
        self.write_manifest()
        for now in (900.0, 1500.0):
            with self.subTest(now=now), patch.object(safety.time, "time", return_value=now):
                self.assertEqual(safety.validate_test_environment(self.env).run_id, self.run_id)

    def test_unowned_process_wrong_data_directory_and_wrong_port_fail(self):
        for identity in ((1, self.process(100)[1]),
                         (os.getpid(), "/fixture/postgres -D /existing/data -p 25432"),
                         (os.getpid(), f"/fixture/postgres -D {self.root}/postgres -p 5432")):
            with patch.object(safety, "process_identity", return_value=identity):
                self.assert_refused()

    def test_docker_owner_port_and_id_validation(self):
        self.manifest["backend"] = "docker"
        for service in ("postgres", "redis"):
            self.manifest[service]["runtime"] = {"container_id": ("1" if service == "postgres" else "2") * 64}
        self.write_manifest()

        def inspect(arguments):
            identifier = arguments[-1]
            service = "postgres" if identifier.startswith("1") else "redis"
            return [{"Id": identifier, "State": {"Running": True},
                     "Config": {"Labels": {safety.LABEL: self.run_id}},
                     "NetworkSettings": {"Ports": {
                         ("5432/tcp" if service == "postgres" else "6379/tcp"):
                         [{"HostIp": "127.0.0.1", "HostPort": str(self.manifest[service]["port"])}]}}}]
        with patch.object(safety, "docker_json", side_effect=inspect):
            safety.validate_test_environment(self.env)
        for change in ("owner", "port", "id"):
            rows = inspect(["inspect", "1" * 64])
            if change == "owner":
                rows[0]["Config"]["Labels"][safety.LABEL] = "foreign"
            elif change == "port":
                rows[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = "0.0.0.0"
            else:
                rows[0]["Id"] = "3" * 64
            with patch.object(safety, "docker_json", return_value=rows):
                self.assert_refused()

    def test_api_and_migration_bootstraps_refuse_before_client_imports(self):
        original_import = builtins.__import__
        forbidden = ("sqlalchemy", "redis", "config", "models", "main", "alembic", "httpx",
                     "pytest_asyncio")
        imported_clients = []

        def instrumented_import(name, *args, **kwargs):
            if name.split(".")[0] in forbidden:
                imported_clients.append(name)
                raise AssertionError("client imported before safety refusal")
            return original_import(name, *args, **kwargs)

        for path in (ROOT / "api/tests/conftest.py", ROOT / "api/tests_capacity/conftest.py",
                     ROOT / "scripts/run_test_migrations.py"):
            for changed in ({"DATABASE_URL": "postgresql://private:never-print@db.example/sclib_test"},
                            {"REDIS_URL": "redis://private:never-print@cache.example/0"},
                            {"SCLIB_TEST_CAPABILITY": "/missing/capability.json"}):
                with self.subTest(entrypoint=str(path.relative_to(ROOT)), field=next(iter(changed))):
                    with (patch.dict(os.environ, {**self.env, **changed}, clear=True),
                          patch.object(sys, "path", [str(ROOT / "api"), *sys.path]),
                          patch("builtins.__import__", side_effect=instrumented_import),
                          self.assertRaises(safety.UnsafeTestEnvironment) as caught):
                        runpy.run_path(str(path), run_name="__main__")
                    self.assertNotIn("never-print", str(caught.exception))
        self.assertEqual(imported_clients, [])


if __name__ == "__main__":
    unittest.main()
