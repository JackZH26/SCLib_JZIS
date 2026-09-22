"""Measure one fixed synthetic index migration on freshly owned services.

No existing database/index, DSN, corpus, model, baseline-code path or arbitrary
command is accepted. Provider requests and source redistribution are excluded.
Only verified execution followed by owned cleanup can publish a success report.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from index_migration_contract import (
    IndexMigrationDestination,
    IndexMigrationError,
    build_report,
    capture_provenance,
    read_private_stage,
    require,
    source_unchanged,
)
from run_disposable_tests import DisposableServices
from schema_rehearsal_report import (
    ReportError,
    SafeParser,
    timestamp,
)
from test_safety import (
    UnsafeTestEnvironment,
    validate_test_environment,
    verify_postgres_identity,
)

REPO = Path(__file__).resolve().parents[1]
STAGE_TIMEOUT = 240
ROOT_PREFIX = "sclib-tests-index-measurement-"


def _identity_probe(env, *, empty=False):
    capability = validate_test_environment(env)
    # No database client exists before the parent's private capability/runtime
    # gate. These URLs were created here; inherited connection settings are not
    # forwarded or treated as disposable merely because their names look safe.
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(capability.database_url, connect_args={
        "connect_timeout": 5, "options": "-c statement_timeout=5000 -c TimeZone=UTC",
    })
    try:
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            if empty:
                require(not inspect(connection).get_table_names(schema="public"), "index_measurement_database_not_empty")
            return int(connection.execute(text("SHOW server_version_num")).scalar_one())
    finally:
        engine.dispose()


def _private_output(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "wb")


def _worker(stage, env, root):
    require(stage in {"migrate", "measure"}, "invalid_index_measurement_stage")
    capability = validate_test_environment(env)
    require(Path(capability.manifest["root"]) == root, "index_measurement_worker_root_mismatch")
    _identity_probe(env)
    try:
        with _private_output(root / ("index-worker-" + stage + ".log")) as output:
            result = subprocess.run([sys.executable, str(REPO / "scripts/index_migration_worker.py"),
                "--stage", stage], cwd=REPO / "api", env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, timeout=STAGE_TIMEOUT, check=False)
        require(result.returncode == 0, "index_measurement_worker_" + stage + "_failed")
        receipt = read_private_stage(root / ("index-migration-" + stage + ".json"), stage)
        require(receipt["run_id"] == capability.run_id, "index_measurement_worker_run_mismatch")
        _identity_probe(env)
        return receipt
    except (OSError, subprocess.SubprocessError):
        raise IndexMigrationError("index_measurement_worker_unavailable_or_timed_out") from None


def _new_root():
    # Resolve the short system temp root so macOS PostgreSQL socket paths stay
    # within the native limit. Never attach to a named preexisting directory.
    root = Path(tempfile.mkdtemp(prefix=ROOT_PREFIX, dir=Path("/tmp").resolve(strict=True))).resolve()
    os.chmod(root, 0o700)
    info = root.lstat()
    return root, (info.st_dev, info.st_ino)


def _remove_owned_root(root, identity):
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        and (info.st_dev, info.st_ino) == identity and info.st_uid == os.getuid()
        and root.name.startswith(ROOT_PREFIX), "index_measurement_owned_directory_changed")
    shutil.rmtree(root)


def _create_services(args, owned):
    root, identity = _new_root()
    try:
        services = DisposableServices(root, args.backend, args.postgres_bin, args.redis_bin)
    except BaseException:
        # Construction starts no processes. Clean up the exact new directory
        # even when construction fails before an instance can be registered.
        _remove_owned_root(root, identity)
        raise
    owned.append((services, identity))
    return services


def _cleanup(owned):
    for services, _identity in reversed(owned):
        try:
            services.close()
        except BaseException:
            # Preserve private diagnostics if an owned runtime cannot be
            # confirmed stopped; never publish success or delete its root.
            raise IndexMigrationError("index_measurement_owned_service_cleanup_failed") from None
    for services, identity in reversed(owned):
        try:
            _remove_owned_root(services.root, identity)
        except (OSError, IndexMigrationError):
            raise IndexMigrationError("index_measurement_owned_directory_cleanup_failed") from None


def _main(args):
    destination = IndexMigrationDestination(args.report)
    owned, stages, durations = [], {}, {}
    started_at, started = timestamp(), time.monotonic_ns()
    try:
        provenance = capture_provenance(REPO)
        def measured(label, action):
            before = time.monotonic_ns()
            value = action()
            durations[label] = (time.monotonic_ns() - before) // 1_000_000
            print("Synthetic index measurement stage verified: " + label, flush=True)
            return value
        try:
            def setup():
                services = _create_services(args, owned)
                environment = services.start()
                version = _identity_probe(environment, empty=True)
                return services, environment, version
            services, env, postgres_version = measured("setup", setup)
            for stage in ("migrate", "measure"):
                stages[stage] = measured(stage, lambda selected=stage: _worker(selected, env, services.root))
        finally:
            before = time.monotonic_ns()
            _cleanup(owned)
            durations["cleanup"] = (time.monotonic_ns() - before) // 1_000_000
        print("Removed only this measurement's owned services and temporary data.", flush=True)
        source_unchanged(provenance, capture_provenance(REPO))
        report = build_report(provenance=provenance, backend=args.backend, postgres_version_num=postgres_version,
            started_at=started_at, completed_at=timestamp(), duration_ms=(time.monotonic_ns() - started) // 1_000_000,
            phase_durations_ms=durations, stages=stages, cleanup_verified=True)
        destination.publish(report)
        print("Retained synthetic index-migration measurements; no scientific or production approval.", flush=True)
        return 0
    finally:
        destination.close()


def main(argv=None):
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--backend", choices=("docker", "native"), default="docker")
        parser.add_argument("--postgres-bin", type=Path)
        parser.add_argument("--redis-bin", type=Path)
        parser.add_argument("--report", type=Path, required=True)
        return _main(parser.parse_args(argv))
    except KeyboardInterrupt:
        print("Index migration measurement interrupted; no success report published.", file=sys.stderr)
        return 130
    except (IndexMigrationError, ReportError, UnsafeTestEnvironment, RuntimeError, OSError):
        print("Index migration measurement failed; no success report published. Details withheld.", file=sys.stderr)
        return 2
    except Exception:
        print("Index migration measurement failed; no success report published. Details withheld.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
