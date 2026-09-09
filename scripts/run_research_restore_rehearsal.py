"""Restore one fixed synthetic scientific release into a second owned instance.

No DSN, existing dump, bucket, arbitrary command or attach/reuse input is accepted.
Existing backups and retention are untouched. A success report is published only
after actual dump/restore, dependency checks, source invariance and owned cleanup.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from research_restore_contract import (
    RestoreContractError,
    RestoreReportDestination,
    build_report,
    capture_provenance,
    copy_recovery_inputs,
    loads_stage,
    source_unchanged,
)
from run_disposable_tests import DisposableServices
from schema_rehearsal_report import (
    ReportError,
    SafeParser,
    read_private_report,
    timestamp,
)
from test_safety import (
    UnsafeTestEnvironment,
    validate_test_environment,
    verify_postgres_identity,
)

REPO = Path(__file__).resolve().parents[1]
STAGE_TIMEOUT = 180
DATABASE_TIMEOUT = 90
MAX_DUMP_BYTES = 128 * 1024 * 1024


def _identity_probe(env, *, empty=False):
    """Two safety barriers before any SQL/migration/dump/restore operation."""
    capability = validate_test_environment(env)
    # Importing and creating a client is allowed only AFTER capability/runtime
    # validation. The URL comes exclusively from this process's owned service.
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(capability.database_url, connect_args={
        "connect_timeout": 5, "options": "-c statement_timeout=5000 -c TimeZone=UTC",
    })
    try:
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            if empty and inspect(connection).get_table_names(schema="public"):
                raise RestoreContractError("restore_target_not_empty")
            return int(connection.execute(text("SHOW server_version_num")).scalar_one())
    finally:
        engine.dispose()


def _private_output(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "wb")


def _worker(stage, env, root):
    capability = validate_test_environment(env)
    if Path(capability.manifest["root"]) != root:
        raise RestoreContractError("restore_worker_root_mismatch")
    _identity_probe(env)
    log = root / ("worker-" + stage + ".log")
    try:
        with _private_output(log) as output:
            result = subprocess.run([sys.executable, str(REPO / "scripts/research_restore_worker.py"),
                "--stage", stage], cwd=REPO / "api", env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, timeout=STAGE_TIMEOUT, check=False)
        if result.returncode != 0:
            raise RestoreContractError("restore_worker_" + stage.replace("-", "_") + "_failed")
        receipt = loads_stage(read_private_report(root / ("stage-" + stage + ".json")), stage)
        if receipt["run_id"] != capability.run_id:
            raise RestoreContractError("restore_worker_run_mismatch")
        return receipt
    except (OSError, subprocess.SubprocessError):
        raise RestoreContractError("restore_worker_unavailable_or_timed_out") from None


def _database_command(services, env, command):
    validate_test_environment(env)
    environment = {**services.env, "PGPASSWORD": services.pg_password,
                   "PGCONNECT_TIMEOUT": "5", "PGAPPNAME": "sclib-owned-research-restore"}
    if services.backend == "native":
        binary = (services.postgres_bin / command).resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RestoreContractError("restore_database_tool_unavailable")
        argv = [str(binary), "--host=127.0.0.1", "--port=" + str(services.manifest["postgres"]["port"])]
    else:
        # No credential appears in argv; Docker reads the variable from the
        # deliberately clean client environment. Runtime ownership was checked.
        docker = shutil.which("docker")
        if docker is None:
            raise RestoreContractError("restore_database_tool_unavailable")
        argv = [docker, "--context", "default", "exec", "--interactive", "--env", "PGPASSWORD",
                services.manifest["postgres"]["runtime"]["container_id"], command,
                "--host=127.0.0.1", "--port=5432"]
    return [*argv, "--username=" + services.name, "--dbname=" + services.name], environment


def _dump(services, env, path):
    _identity_probe(env)
    command, environment = _database_command(services, env, "pg_dump")
    command.extend(["--format=custom", "--compress=0", "--no-owner", "--no-acl",
                    "--exclude-schema=sclib_test_guard"])
    try:
        with _private_output(path) as output, _private_output(path.parent / "pg-dump.log") as log:
            result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=log, timeout=DATABASE_TIMEOUT, check=False)
        if result.returncode != 0:
            raise RestoreContractError("research_dump_failed")
        return _dump_fingerprint(path)
    except (OSError, subprocess.SubprocessError):
        raise RestoreContractError("research_dump_unavailable_or_timed_out") from None


def _dump_fingerprint(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            return _fingerprint_handle(handle)
    except OSError:
        raise RestoreContractError("research_dump_unavailable") from None


def _fingerprint_handle(handle):
    handle.seek(0)
    before = os.fstat(handle.fileno())
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600 or not 1 <= before.st_size <= MAX_DUMP_BYTES):
        raise RestoreContractError("unsafe_research_dump")
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: handle.read(256 * 1024), b""):
        size += len(block)
        if size > MAX_DUMP_BYTES:
            raise RestoreContractError("research_dump_limit")
        digest.update(block)
    after = os.fstat(handle.fileno())
    if _stat(before) != _stat(after) or size != before.st_size:
        raise RestoreContractError("research_dump_changed")
    handle.seek(0)
    return {"dump_sha256": digest.hexdigest(), "dump_bytes": size}


def _stat(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _restore(services, env, path, fingerprint):
    _identity_probe(env, empty=True)
    if _dump_fingerprint(path) != fingerprint:
        raise RestoreContractError("research_dump_changed")
    command, environment = _database_command(services, env, "pg_restore")
    command.extend(["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl"])
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source, _private_output(services.root / "pg-restore.log") as log:
            before = os.fstat(source.fileno())
            # Bind the actual descriptor passed as stdin, not merely a path
            # checked earlier and reopened after an attacker swaps it.
            if _fingerprint_handle(source) != fingerprint:
                raise RestoreContractError("research_dump_changed")
            result = subprocess.run(command, env=environment, stdin=source, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=DATABASE_TIMEOUT, check=False)
            after = os.fstat(source.fileno())
            if _fingerprint_handle(source) != fingerprint:
                raise RestoreContractError("research_dump_changed")
        if result.returncode != 0 or _stat(before) != _stat(after):
            raise RestoreContractError("research_restore_failed")
        if _dump_fingerprint(path) != fingerprint:
            raise RestoreContractError("research_dump_changed")
        _identity_probe(env)
    except (OSError, subprocess.SubprocessError):
        raise RestoreContractError("research_restore_unavailable_or_timed_out") from None


def _new_root(label):
    # macOS's default per-user TMPDIR makes these descriptive owned paths
    # exceed PostgreSQL's Unix-socket address limit. Use the resolved short
    # system temporary parent; mkdtemp still creates a fresh private directory.
    parent = Path("/tmp").resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="sclib-tests-research-restore-" + label + "-", dir=parent)).resolve()
    os.chmod(root, 0o700)
    info = root.lstat()
    return root, (info.st_dev, info.st_ino)


def _remove_owned_root(root, identity):
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or (info.st_dev, info.st_ino) != identity or info.st_uid != os.getuid()
            or not root.name.startswith("sclib-tests-research-restore-")):
        raise RestoreContractError("research_restore_owned_directory_changed")
    shutil.rmtree(root)


def _create_services(label, args, owned):
    root, identity = _new_root(label)
    try:
        services = DisposableServices(root, args.backend, args.postgres_bin, args.redis_bin)
    except BaseException:
        # Construction starts no processes. Even failure before the instance can
        # be registered must remove only this exact, just-created directory.
        _remove_owned_root(root, identity)
        raise
    owned.append((services, identity))
    return services


def _cleanup(owned):
    failed = False
    for services, _identity in reversed(owned):
        try:
            services.close()
        except BaseException:
            failed = True
    if failed:
        # Retain private directories for diagnosis if a runtime cannot be
        # confirmed stopped. Never publish success or remove somebody else's dir.
        raise RestoreContractError("research_restore_owned_service_cleanup_failed")
    for services, identity in reversed(owned):
        try:
            _remove_owned_root(services.root, identity)
        except (OSError, RestoreContractError):
            failed = True
    if failed:
        raise RestoreContractError("research_restore_owned_directory_cleanup_failed")


def _main(args):
    destination = RestoreReportDestination(args.report)
    owned = []
    started_at, started = timestamp(), time.monotonic_ns()
    durations, results = {}, {}
    try:
        provenance = capture_provenance(REPO)

        def measured(name, action):
            before = time.monotonic_ns()
            value = action()
            durations[name] = (time.monotonic_ns() - before) // 1_000_000
            print("Synthetic research restore stage verified: " + name, flush=True)
            return value

        try:
            source = _create_services("source", args, owned)
            source_root = source.root
            source_env = source.start()
            target = _create_services("target", args, owned)
            target_root = target.root
            target_env = target.start()
            if source.run_id == target.run_id or source_root == target_root:
                raise RestoreContractError("restore_instances_not_independent")
            source_version = _identity_probe(source_env, empty=True)
            target_version = _identity_probe(target_env, empty=True)
            results["migrate"] = measured("migrate", lambda: _worker("migrate", source_env, source_root))
            results["seed"] = measured("seed", lambda: _worker("seed", source_env, source_root))
            descriptor_pin = results["seed"]["descriptor_sha256"]
            # This pin comes from the successful source worker, never inherited
            # environment or the target's copied, self-describing JSON.
            pinned_source_env = {**source_env, "SCLIB_RESTORE_EXPECTED_DESCRIPTOR_SHA256": descriptor_pin}
            pinned_target_env = {**target_env, "SCLIB_RESTORE_EXPECTED_DESCRIPTOR_SHA256": descriptor_pin}
            dump_path = source_root / "research-release.dump"
            dump = measured("dump", lambda: _dump(source, source_env, dump_path))
            copied = measured("copy", lambda: copy_recovery_inputs(source_root, target_root,
                expected_descriptor_sha256=descriptor_pin))
            measured("restore", lambda: _restore(target, target_env, dump_path, dump))
            results["verify"] = measured("verify", lambda: _worker("verify", pinned_target_env, target_root))
            results["source-check"] = measured("source_check", lambda: _worker("source-check", pinned_source_env, source_root))
        finally:
            before = time.monotonic_ns()
            _cleanup(owned)
            durations["cleanup"] = (time.monotonic_ns() - before) // 1_000_000
        print("Removed only this rehearsal's two owned instances and temporary data.", flush=True)
        source_unchanged(provenance, capture_provenance(REPO))
        report = build_report(provenance=provenance, backend=args.backend, started_at=started_at,
            completed_at=timestamp(), duration_ms=(time.monotonic_ns() - started) // 1_000_000,
            stage_results=results, stage_durations_ms=durations, transfer={**copied, **dump},
            cleanup_verified=True, source_postgres_version_num=source_version,
            target_postgres_version_num=target_version)
        destination.publish(report)
        print("Retained verified synthetic research-release recovery report; no production or scientific approval.", flush=True)
        return 0
    finally:
        destination.close()


def main():
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--backend", choices=("docker", "native"), default="docker")
        parser.add_argument("--postgres-bin", type=Path)
        parser.add_argument("--redis-bin", type=Path)
        parser.add_argument("--report", type=Path, required=True)
        args = parser.parse_args()
        return _main(args)
    except (RestoreContractError, ReportError, UnsafeTestEnvironment, RuntimeError, OSError):
        print("Research restore rehearsal failed; no success report published. Details withheld.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Research restore rehearsal interrupted; no success report published.", file=sys.stderr)
        return 130
    except Exception:
        # Database/client exceptions may embed generated DSNs or SQL. Never
        # forward them as a traceback or a user-visible diagnostic string.
        print("Research restore rehearsal failed; no success report published. Details withheld.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
