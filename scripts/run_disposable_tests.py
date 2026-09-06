"""Run API/migration tests only against services created for this invocation.

Default: preinstalled Docker images, no Compose/project volumes. Native mode
requires explicit preinstalled binaries and creates a fresh private PG cluster.
No reuse/attach mode exists. No input DSN is accepted or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from test_safety import (
    LABEL,
    SCHEMA,
    UnsafeTestEnvironment,
    assert_service_runtime,
    digest,
    docker_json,
    validate_test_environment,
)

REPO = Path(__file__).resolve().parents[1]


def child_environment() -> dict[str, str]:
    # Never inherit DSNs, cloud credentials, mail credentials or pytest options.
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "TERM"}
    return {key: value for key, value in os.environ.items() if key in keep}


def private_write(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        handle.write(content)


def run_quiet(command: list[str], *, env: dict[str, str], input: str | None = None,
              timeout: int = 30) -> str:
    try:
        result = subprocess.run(command, env=env, input=input, capture_output=True,
                                text=True, timeout=timeout, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        # A subprocess error may contain SQL credentials or a supplied URL.
        raise RuntimeError("Disposable service setup command failed; output withheld.") from None


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class DisposableServices:
    def __init__(self, root: Path, backend: str, postgres_bin: Path | None,
                 redis_bin: Path | None):
        self.root, self.backend = root, backend
        self.postgres_bin, self.redis_bin = postgres_bin, redis_bin
        self.env = child_environment()
        self.run_id = secrets.token_hex(16)
        self.name = "test_" + self.run_id[:16]
        self.pg_password, self.redis_password = secrets.token_hex(24), secrets.token_hex(24)
        self.children: list[subprocess.Popen] = []
        self.containers: list[str] = []
        self.logs = []
        self.manifest = {
            "schema": SCHEMA, "run_id": self.run_id, "backend": backend,
            "root": str(root), "runner_pid": os.getpid(), "created_at": time.time(),
            "expires_at": time.time() + 3600,
        }

    def docker(self, arguments: list[str], *, input: str | None = None) -> str:
        binary = shutil.which("docker")
        if binary is None:
            raise RuntimeError("Docker is unavailable; no service was attached or installed.")
        return run_quiet([binary, "--context", "default", *arguments],
                         env=self.env, input=input, timeout=45)

    def _native_start(self, service: str, command: list[str], port: int) -> None:
        log = (self.root / f"{service}.log").open("x", encoding="utf-8")
        os.chmod(log.name, 0o600)
        self.logs.append(log)
        process = subprocess.Popen(command, env=self.env, stdout=log, stderr=log)
        self.children.append(process)
        self.manifest[service] = {
            "port": port, "runtime": {"pid": process.pid, "executable": command[0]},
        }

    def _docker_start(self, service: str, arguments: list[str]) -> None:
        name = f"sclib-tests-{self.run_id}-{service}"
        identifier = self.docker([
            "run", "--detach", "--pull", "never", "--name", name,
            "--label", f"{LABEL}={self.run_id}", *arguments,
        ])
        self.containers.append(identifier)
        rows = docker_json(["inspect", identifier])
        internal = "5432/tcp" if service == "postgres" else "6379/tcp"
        bindings = rows[0]["NetworkSettings"]["Ports"][internal]
        self.manifest[service] = {
            "port": int(bindings[0]["HostPort"]),
            "runtime": {"container_id": identifier},
        }

    def start(self) -> dict[str, str]:
        redis_config = self.root / "redis.conf"
        if self.backend == "native":
            if self.postgres_bin is None or self.redis_bin is None:
                raise RuntimeError("Native mode requires explicit PostgreSQL and Redis binaries.")
            tools = [self.postgres_bin / name for name in ("postgres", "initdb", "psql")]
            if any(not path.is_file() or not os.access(path, os.X_OK) for path in tools):
                raise RuntimeError("Required preinstalled PostgreSQL tools are unavailable.")
            if not self.redis_bin.is_file() or not os.access(self.redis_bin, os.X_OK):
                raise RuntimeError("Required preinstalled Redis binary is unavailable.")
            postgres = str(tools[0].resolve())
            self.psql = str(tools[2].resolve())
            pgdata = self.root / "postgres"
            self.socket_dir = self.root / "socket"
            self.socket_dir.mkdir(mode=0o700)
            run_quiet([str(tools[1].resolve()), "-D", str(pgdata), "--username=bootstrap",
                       "--auth-local=trust", "--auth-host=scram-sha-256", "--no-locale",
                       "--encoding=UTF8"], env=self.env)
            pg_port = unused_port()
            self._native_start("postgres", [postgres, "-D", str(pgdata), "-h", "127.0.0.1",
                               "-p", str(pg_port), "-k", str(self.socket_dir),
                               "-c", "max_connections=30"], pg_port)
            redis_port = unused_port()
            if redis_port == pg_port:
                raise RuntimeError("Ephemeral port allocation collided; retry the runner.")
            private_write(redis_config, self.redis_configuration("127.0.0.1", redis_port))
            self._native_start("redis", [str(self.redis_bin.resolve()), str(redis_config)],
                               redis_port)
        else:
            # docker_json verifies the default context is a local Unix socket.
            docker_json(["image", "inspect", "postgres:16-alpine"])
            docker_json(["image", "inspect", "redis:7-alpine"])
            env_file = self.root / "postgres.env"
            private_write(env_file, "POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n")
            self._docker_start("postgres", [
                "--publish", "127.0.0.1::5432", "--env-file", str(env_file),
                "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=512m", "postgres:16-alpine",
            ])
            private_write(redis_config, self.redis_configuration("0.0.0.0", 6379))
            # The only bind mount is this run's generated private configuration.
            self._docker_start("redis", [
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--publish", "127.0.0.1::6379", "--tmpfs", "/data:rw,nosuid,size=128m",
                "--mount", f"type=bind,source={redis_config},target=/run/redis-test.conf,readonly",
                "redis:7-alpine", "redis-server", "/run/redis-test.conf",
            ])

        self.wait_postgres()
        self.bootstrap_postgres()
        for service in ("postgres", "redis"):
            assert_service_runtime(self.manifest, service)
        pg_port = self.manifest["postgres"]["port"]
        redis_port = self.manifest["redis"]["port"]
        db_url = f"postgresql://{self.name}:{self.pg_password}@127.0.0.1:{pg_port}/{self.name}"
        redis_url = f"redis://{self.name}:{self.redis_password}@127.0.0.1:{redis_port}/0"
        self.manifest["postgres"]["dsn_sha256"] = digest(db_url)
        self.manifest["redis"]["dsn_sha256"] = digest(redis_url)
        # Only the just-created, process/container-verified Redis is contacted.
        import redis

        redis_client = redis.Redis.from_url(redis_url, socket_connect_timeout=2,
                                           socket_timeout=2, decode_responses=True)
        try:
            self.manifest["redis"]["server_run_id"] = redis_client.info("server")["run_id"]
        finally:
            redis_client.close()
        capability_path = self.root / "capability.json"
        private_write(capability_path, json.dumps(self.manifest, sort_keys=True))
        env = {
            **self.env, "DATABASE_URL": db_url, "REDIS_URL": redis_url,
            "ENVIRONMENT": "test", "EMAIL_BACKEND": "stdout",
            "JWT_SECRET": "disposable_test_jwt_not_valid_outside_this_run_" + self.run_id,
            "ML_FOUNDATION_PUBLIC_ENABLED": "true", "SCLIB_TEST_RUN_ID": self.run_id,
            "SCLIB_TEST_CAPABILITY": str(capability_path), "PYTHONNOUSERSITE": "1",
            "GOOGLE_APPLICATION_CREDENTIALS": str(self.root / "no-cloud-credentials.json"),
            "GCP_PROJECT": "sclib-disposable-tests", "GCS_BUCKET": "sclib-disposable-tests",
            "VERTEX_AI_INDEX_ENDPOINT": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
            "RESEND_API_KEY": "", "INTERNAL_API_KEY": "", "GOOGLE_CLIENT_SECRET": "",
        }
        validate_test_environment(env)
        return env

    def redis_configuration(self, bind: str, port: int) -> str:
        # One DB in a dedicated process; no FLUSHALL, CONFIG, ACL or SHUTDOWN.
        return (
            f"bind {bind}\nport {port}\nprotected-mode yes\nsave \"\"\nappendonly no\n"
            "databases 1\nuser default off\n"
            f"user {self.name} on >{self.redis_password} ~* &* +@all -@admin -@dangerous "
            "+flushdb +info\n"
        )

    def pg_command(self, database: str = "postgres") -> list[str]:
        if self.backend == "native":
            return [self.psql, "-h", str(self.socket_dir), "-p",
                    str(self.manifest["postgres"]["port"]), "-U", "bootstrap", "-d", database,
                    "-v", "ON_ERROR_STOP=1", "-X"]
        return [shutil.which("docker"), "--context", "default", "exec", "-i", "--user", "postgres",
                self.manifest["postgres"]["runtime"]["container_id"],
                "psql", "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", "-X"]

    def wait_postgres(self) -> None:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                assert_service_runtime(self.manifest, "postgres")
                run_quiet(self.pg_command(), env=self.env, input="SELECT 1;", timeout=3)
                return
            except (RuntimeError, UnsafeTestEnvironment):
                if any(child.poll() is not None for child in self.children):
                    raise RuntimeError("A newly created test service exited during startup.") from None
                time.sleep(0.2)
        raise RuntimeError("Disposable PostgreSQL did not become ready before the deadline.")

    def bootstrap_postgres(self) -> None:
        # All identifiers/passwords are generated hex; no user SQL is accepted.
        run_quiet(self.pg_command(), env=self.env, input=(
            f"CREATE ROLE {self.name} LOGIN PASSWORD '{self.pg_password}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;\n"
            f"CREATE DATABASE {self.name} OWNER {self.name};\n"
            "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;\n"
        ))
        run_quiet(self.pg_command(self.name), env=self.env, input=(
            "CREATE SCHEMA sclib_test_guard;\n"
            "CREATE TABLE sclib_test_guard.run_identity "
            "(run_id text PRIMARY KEY, expires_at timestamptz NOT NULL);\n"
            f"INSERT INTO sclib_test_guard.run_identity VALUES ('{self.run_id}', now() + interval '1 hour');\n"
            f"GRANT USAGE ON SCHEMA sclib_test_guard TO {self.name};\n"
            f"GRANT SELECT ON sclib_test_guard.run_identity TO {self.name};\n"
        ))

    def close(self) -> None:
        # Only Popen children/full container IDs created by this instance.
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for identifier in reversed(self.containers):
            rows = docker_json(["inspect", identifier])
            if (len(rows) != 1 or rows[0].get("Id") != identifier
                    or rows[0].get("Config", {}).get("Labels", {}).get(LABEL) != self.run_id):
                raise RuntimeError("Cleanup refused an unowned container.")
            self.docker(["rm", "--force", identifier])
        for log in self.logs:
            log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("docker", "native"), default="docker")
    parser.add_argument("--suite", choices=("api", "migrations"), required=True)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--redis-bin", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pytest_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    if args.suite == "migrations" and pytest_args:
        parser.error("Migration verification does not accept arbitrary commands.")
    with tempfile.TemporaryDirectory(prefix="sclib-tests-") as temporary:
        root = Path(temporary).resolve()
        os.chmod(root, 0o700)
        services = DisposableServices(root, args.backend, args.postgres_bin, args.redis_bin)
        try:
            env = services.start()
            print(f"Disposable {args.backend} services verified; running {args.suite}.", flush=True)
            if args.suite == "api":
                command = [sys.executable, "-m", "pytest", *(pytest_args or ["-q"])]
            else:
                command = [sys.executable, str(REPO / "scripts/run_test_migrations.py")]
            return subprocess.run(command, cwd=REPO / "api", env=env, check=False).returncode
        except (RuntimeError, OSError) as exc:
            # Controlled setup errors only. Avoid traceback/command/DSN disclosure.
            message = str(exc) if isinstance(exc, RuntimeError) else "Local setup failed."
            print(message, file=sys.stderr)
            return 2
        finally:
            services.close()
            print("Removed only this run's disposable services and temporary test data.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
