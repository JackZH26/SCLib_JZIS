"""Export and verify a stable PostgreSQL snapshot for the ML foundation planner.

The exporter is intentionally read-only.  It reads the legacy ``materials``
and ``papers`` tables inside one PostgreSQL ``REPEATABLE READ READ ONLY``
transaction, streams rows through server-side cursors, and publishes a bundle
only after every artifact and checksum has been written successfully.

``DATABASE_URL`` is read exclusively from the environment and is never written
to logs or manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

EXPORT_SCHEMA_VERSION = "sclib-source-export/v1"
EXPORTER_VERSION = "sclib-ml-source-exporter/v1"
LICENSE_SCHEMA_VERSION = "sclib-license-manifest/v1"
SCIENTIFIC_SEMANTICS = {
    "material_row": "catalogue_summary_not_joint_observation",
    "records": "source_occurrences_require_result_state_and_method_review",
    "legacy_summary_fields_exported": False,
    "joint_feature_rows_exported": False,
    "scientific_acceptance": "not_implied_by_export_or_verification",
}

MATERIALS_FILE = "materials.jsonl"
PAPERS_FILE = "papers.jsonl"
PAPER_WORK_MAP_FILE = "paper_work_map.jsonl"
LICENSE_FILE = "license_manifest.json"
MANIFEST_FILE = "export_manifest.json"
MANIFEST_HASH_FILE = "export_manifest.sha256"
CHECKSUMS_FILE = "checksums.sha256"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DATASET_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")
_URL_PASSWORD_RE = re.compile(
    r"((?:postgres(?:ql)?)(?:\+[a-z0-9_]+)?://[^\s:/@]+:)[^\s@]+@",
    re.IGNORECASE,
)
_KEY_VALUE_PASSWORD_RE = re.compile(
    r"(?i)\b(password|passwd|pwd)\s*=\s*([^\s]+)",
)

_PUBLIC_MATERIAL_PREDICATE = """
    m.needs_review IS FALSE
    AND m.total_papers > 0
    AND (
        m.review_reason IS NULL
        OR m.review_reason <> 'provenance_quarantine_nims'
    )
""".strip()

# This is the single source of truth for both the PostgreSQL projections and
# the verifier's exact egress schema.  Every key is required to be present,
# including nullable paper fields, and no additional top-level key is allowed.
_JSONL_EXPORT_FIELDS: dict[str, tuple[str, ...]] = {
    "materials": ("id", "formula", "formula_normalized", "records"),
    "papers": (
        "id",
        "source",
        "arxiv_id",
        "doi",
        "related_paper_id",
        "title",
        "date_submitted",
        "date_published",
        "status",
        "paper_type",
    ),
    "paper_work_map": (
        "paper_id",
        "work_id",
        "relation_type",
        "match_method",
        "review_status",
    ),
}
_JSONL_ORDER_KEYS = {
    "materials": "id",
    "papers": "id",
    "paper_work_map": "paper_id",
}


def _build_jsonl_query(
    *,
    dataset_key: str,
    table: str,
    alias: str,
    predicate: str | None = None,
) -> str:
    """Build the fixed JSON projection from the shared egress contract."""
    fields = _JSONL_EXPORT_FIELDS[dataset_key]
    projection = ",\n".join(f"    '{field}', {alias}.{field}" for field in fields)
    where_clause = f"\nWHERE {predicate}" if predicate is not None else ""
    order_key = _JSONL_ORDER_KEYS[dataset_key]
    return (
        "SELECT jsonb_build_object(\n"
        f"{projection}\n"
        ")\n"
        f"FROM {table} AS {alias}"
        f"{where_clause}\n"
        f'ORDER BY {alias}.{order_key} COLLATE "C"'
    )


_MATERIALS_QUERY_TEMPLATE = _build_jsonl_query(
    dataset_key="materials",
    table="materials",
    alias="m",
    predicate="{predicate}",
)
_PAPERS_QUERY = _build_jsonl_query(
    dataset_key="papers",
    table="papers",
    alias="p",
)
_PAPER_WORK_MAP_QUERY = _build_jsonl_query(
    dataset_key="paper_work_map",
    table="paper_work_map",
    alias="pwm",
)

_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "materials": frozenset(_JSONL_EXPORT_FIELDS["materials"])
    | frozenset(
        {
            "updated_at",
            "needs_review",
            "total_papers",
            "review_reason",
        }
    ),
    "papers": frozenset(_JSONL_EXPORT_FIELDS["papers"]) | frozenset({"updated_at"}),
    "chunks": frozenset({"id", "paper_id"}),
    "paper_work_map": frozenset(_JSONL_EXPORT_FIELDS["paper_work_map"]),
}


class ExportError(RuntimeError):
    """The source database or output bundle violates the export contract."""


class VerificationError(ValueError):
    """A published export bundle is malformed or has been modified."""


@dataclass(frozen=True)
class QuerySpec:
    key: str
    file_name: str
    query: str
    order_key: str


@dataclass(frozen=True)
class SnapshotState:
    database_watermark: str
    database_name: str
    postgres_version: str
    transaction_isolation: str
    transaction_read_only: str
    transaction_snapshot: str
    wal_lsn: str | None
    alembic_revision: str
    paper_work_map_table_present: bool
    counts: dict[str, int]
    max_material_updated_at: str | None
    max_paper_updated_at: str | None
    paper_source_counts: dict[str, int]
    material_record_source_counts: dict[str, int]
    material_record_count: int


def _to_sync_dsn(dsn: str) -> str:
    """Translate SQLAlchemy's asyncpg URL into a psycopg2 URL."""
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql://" + dsn[len("postgresql+asyncpg://") :]
    return dsn


def safe_error_message(exc: BaseException, database_url: str | None = None) -> str:
    """Return an operator-facing message with connection secrets removed."""
    message = str(exc)
    if database_url:
        message = message.replace(database_url, "<redacted-database-url>")
    message = _URL_PASSWORD_RE.sub(r"\1<redacted>@", message)
    message = _KEY_VALUE_PASSWORD_RE.sub(r"\1=<redacted>", message)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize one deterministic, UTF-8 JSON value without a trailing LF."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        resolved = value.astimezone(UTC) if value.tzinfo is not None else value
        return resolved.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be exported")
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _write_bytes(path: Path, payload: bytes) -> dict[str, Any]:
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "path": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "rows": 1,
        "bytes": len(payload),
    }


def _write_json_document(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = (
        json.dumps(
            value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default
        )
        + "\n"
    ).encode("utf-8")
    return _write_bytes(path, payload)


def _table_exists(cursor: Any, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table_name}",))
    row = cursor.fetchone()
    return bool(row and row[0])


def validate_source_schema(cursor: Any, *, material_scope: str) -> bool:
    """Validate required legacy columns and return whether work-map exists."""
    table_present: dict[str, bool] = {}
    for table_name in ("materials", "papers", "chunks", "paper_work_map"):
        table_present[table_name] = _table_exists(cursor, table_name)

    for required_table in ("materials", "papers", "chunks"):
        if not table_present[required_table]:
            raise ExportError(f"required source table is missing: {required_table}")

    for table_name in ("materials", "papers", "chunks"):
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        columns = {row[0] for row in cursor.fetchall()}
        required = set(_REQUIRED_COLUMNS[table_name])
        if material_scope == "all" and table_name == "materials":
            required -= {"needs_review", "total_papers", "review_reason"}
        missing = sorted(required - columns)
        if missing:
            raise ExportError(
                f"source table {table_name} is missing required columns: {', '.join(missing)}"
            )

    if table_present["paper_work_map"]:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'paper_work_map'
            """
        )
        columns = {row[0] for row in cursor.fetchall()}
        missing = sorted(_REQUIRED_COLUMNS["paper_work_map"] - columns)
        if missing:
            raise ExportError(
                "paper_work_map exists but is missing required columns: "
                + ", ".join(missing)
            )
    return table_present["paper_work_map"]


def _material_predicate(material_scope: str) -> str:
    if material_scope == "public":
        return _PUBLIC_MATERIAL_PREDICATE
    if material_scope == "all":
        return "TRUE"
    raise ValueError("material_scope must be 'public' or 'all'")


def _count_rows(cursor: Any, query: str) -> int:
    cursor.execute(query)
    row = cursor.fetchone()
    if row is None:
        raise ExportError("count query did not return a row")
    return int(row[0])


def _grouped_counts(cursor: Any, query: str) -> dict[str, int]:
    cursor.execute(query)
    return {str(key): int(count) for key, count in cursor.fetchall()}


def capture_snapshot_state(
    cursor: Any,
    *,
    material_scope: str,
    include_paper_work_map: bool,
    paper_work_map_table_present: bool,
) -> SnapshotState:
    """Capture metadata and exact counts from the already-open snapshot."""
    cursor.execute(
        """
        SELECT
            transaction_timestamp(),
            current_database(),
            current_setting('server_version'),
            current_setting('transaction_isolation'),
            current_setting('transaction_read_only'),
            txid_current_snapshot()::text,
            pg_current_wal_lsn()::text
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise ExportError("database metadata query returned no row")
    (
        database_watermark,
        database_name,
        postgres_version,
        transaction_isolation,
        transaction_read_only,
        transaction_snapshot,
        wal_lsn,
    ) = row
    if str(transaction_isolation).lower() != "repeatable read":
        raise ExportError("export transaction is not REPEATABLE READ")
    if str(transaction_read_only).lower() not in {"on", "true"}:
        raise ExportError("export transaction is not READ ONLY")

    # ``create_all``-managed development databases can legitimately lack an
    # Alembic stamp.  Keep that state explicit instead of emitting JSON null,
    # so every downstream snapshot still has a stable schema provenance token.
    alembic_revision = "unversioned"
    if _table_exists(cursor, "alembic_version"):
        cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
        revisions = [str(item[0]) for item in cursor.fetchall()]
        if revisions:
            alembic_revision = ",".join(revisions)

    predicate = _material_predicate(material_scope)
    counts = {
        "materials": _count_rows(
            cursor,
            f"SELECT count(*) FROM materials AS m WHERE {predicate}",
        ),
        "papers": _count_rows(cursor, "SELECT count(*) FROM papers"),
        "chunks": _count_rows(cursor, "SELECT count(*) FROM chunks"),
        "paper_work_map": 0,
    }
    if include_paper_work_map and paper_work_map_table_present:
        counts["paper_work_map"] = _count_rows(
            cursor, "SELECT count(*) FROM paper_work_map"
        )

    cursor.execute(f"SELECT max(m.updated_at) FROM materials AS m WHERE {predicate}")
    max_material_updated_at = cursor.fetchone()[0]
    cursor.execute("SELECT max(updated_at) FROM papers")
    max_paper_updated_at = cursor.fetchone()[0]

    paper_source_counts = _grouped_counts(
        cursor,
        """
        SELECT source_name, count(*)
        FROM (
            SELECT COALESCE(NULLIF(btrim(source), ''), 'unknown') AS source_name
            FROM papers
        ) AS paper_sources
        GROUP BY source_name
        ORDER BY source_name COLLATE "C"
        """,
    )
    material_record_source_counts = _grouped_counts(
        cursor,
        f"""
        SELECT source_name, count(*)
        FROM (
            SELECT
                CASE
                    WHEN NULLIF(btrim(record->>'source'), '') IS NOT NULL
                        THEN lower(btrim(record->>'source'))
                    WHEN record->>'paper_id' LIKE 'aps:%' THEN 'aps'
                    WHEN record->>'paper_id' LIKE 'arxiv:%' THEN 'arxiv_ner'
                    ELSE 'unknown'
                END AS source_name
            FROM materials AS m
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(m.records) = 'array' THEN m.records
                    ELSE '[]'::jsonb
                END
            ) AS record
            WHERE {predicate}
        ) AS material_record_sources
        GROUP BY source_name
        ORDER BY source_name COLLATE "C"
        """,
    )
    material_record_count = sum(material_record_source_counts.values())
    return SnapshotState(
        database_watermark=_iso_utc(database_watermark) or "",
        database_name=str(database_name),
        postgres_version=str(postgres_version),
        transaction_isolation=str(transaction_isolation),
        transaction_read_only=str(transaction_read_only),
        transaction_snapshot=str(transaction_snapshot),
        wal_lsn=str(wal_lsn) if wal_lsn is not None else None,
        alembic_revision=alembic_revision,
        paper_work_map_table_present=paper_work_map_table_present,
        counts=counts,
        max_material_updated_at=_iso_utc(max_material_updated_at),
        max_paper_updated_at=_iso_utc(max_paper_updated_at),
        paper_source_counts=paper_source_counts,
        material_record_source_counts=material_record_source_counts,
        material_record_count=material_record_count,
    )


def stream_query_jsonl(
    connection: Any,
    spec: QuerySpec,
    output_path: Path,
    *,
    batch_size: int,
) -> dict[str, Any]:
    """Stream one ordered query through a PostgreSQL server-side cursor."""
    digest = hashlib.sha256()
    byte_count = 0
    row_count = 0
    previous_key: str | None = None
    cursor_name = f"sclib_ml_export_{spec.key}_{uuid.uuid4().hex}"
    with output_path.open("xb") as handle:
        os.chmod(output_path, 0o600)
        with connection.cursor(name=cursor_name) as cursor:
            cursor.itersize = batch_size
            cursor.arraysize = batch_size
            cursor.execute(spec.query)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    payload = row[0]
                    if not isinstance(payload, Mapping):
                        raise ExportError(f"{spec.key} query returned a non-object row")
                    order_value = payload.get(spec.order_key)
                    if order_value is None:
                        raise ExportError(
                            f"{spec.key} query returned a row without {spec.order_key}"
                        )
                    rendered_key = str(order_value)
                    if previous_key is not None and rendered_key <= previous_key:
                        raise ExportError(
                            f"{spec.key} rows are not strictly ordered by {spec.order_key}"
                        )
                    previous_key = rendered_key
                    encoded = canonical_json_bytes(payload) + b"\n"
                    handle.write(encoded)
                    digest.update(encoded)
                    byte_count += len(encoded)
                    row_count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "path": output_path.name,
        "sha256": digest.hexdigest(),
        "rows": row_count,
        "bytes": byte_count,
    }


def build_license_manifest(
    *,
    source_snapshot_id: uuid.UUID,
    dataset_version: str,
    database_watermark: str,
    material_scope: str,
    paper_source_counts: Mapping[str, int],
    material_record_source_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Build an explicit license/provenance declaration."""
    contains_nims = any(
        "nims" in source.lower() and count > 0
        for source, count in material_record_source_counts.items()
    )
    return {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "source_snapshot_id": str(source_snapshot_id),
        "dataset_version": dataset_version,
        "database_watermark": database_watermark,
        "material_scope": material_scope,
        "distribution_status": "not_cleared_for_public_release",
        "contains_nims_records": contains_nims,
        "paper_source_counts": dict(sorted(paper_source_counts.items())),
        "material_record_source_counts": dict(
            sorted(material_record_source_counts.items())
        ),
        "source_terms": {
            "sclib": "CC BY 4.0 for SCLib-produced and curated data",
            "arxiv": "upstream paper-specific terms remain applicable",
            "aps": "derived structured data only; no licensed full text is exported",
            "nims": (
                "CC BY 4.0; NIMS SuperCon v22.12.03, DOI 10.48505/nims.3735; "
                "NIMS attribution required"
            ),
            "materials_project": "CC BY 4.0; Materials Project attribution required",
        },
        "content_policy": {
            "paper_abstracts_exported": False,
            "paper_authors_exported": False,
            "chunk_payloads_exported": False,
            "vector_index_frozen": False,
            "legacy_material_records_exported": True,
        },
    }


def build_export_manifest(
    *,
    source_snapshot_id: uuid.UUID,
    dataset_version: str,
    site_git_sha: str,
    material_scope: str,
    state: SnapshotState,
    files: Mapping[str, Mapping[str, Any]],
    queries: Mapping[str, str],
    include_paper_work_map: bool,
) -> dict[str, Any]:
    license_hash = str(files["license_manifest"]["sha256"])
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exporter_version": EXPORTER_VERSION,
        "source_snapshot_id": str(source_snapshot_id),
        "dataset_version": dataset_version,
        "site_git_sha": site_git_sha,
        "database_watermark": state.database_watermark,
        "alembic_revision": state.alembic_revision,
        "chunk_count": state.counts["chunks"],
        "license_manifest_sha256": license_hash,
        "material_scope": material_scope,
        "scientific_semantics": dict(SCIENTIFIC_SEMANTICS),
        "files": {key: dict(value) for key, value in files.items()},
        "counts": {
            **state.counts,
            "material_records": state.material_record_count,
        },
        "queries": {
            key: _query_sha256(query) for key, query in sorted(queries.items())
        },
        "database": {
            "name": state.database_name,
            "postgres_version": state.postgres_version,
            "transaction_isolation": state.transaction_isolation,
            "transaction_read_only": state.transaction_read_only,
            "transaction_snapshot": state.transaction_snapshot,
            "wal_lsn": state.wal_lsn,
        },
        "metadata": {
            "max_material_updated_at": state.max_material_updated_at,
            "max_paper_updated_at": state.max_paper_updated_at,
            "paper_source_counts": state.paper_source_counts,
            "material_record_source_counts": state.material_record_source_counts,
            "paper_work_map_table_present": state.paper_work_map_table_present,
            "paper_work_map_included": include_paper_work_map,
            "chunk_inventory_exported": False,
            "vector_index_frozen": False,
        },
    }


def _validate_export_arguments(
    *,
    output_dir: Path,
    dataset_version: str,
    site_git_sha: str,
    source_snapshot_id: uuid.UUID | str | None,
    batch_size: int,
    material_scope: str,
) -> tuple[Path, str, str, uuid.UUID]:
    if not _DATASET_VERSION_RE.fullmatch(dataset_version):
        raise ValueError(
            "dataset_version must be 1-50 characters using letters, digits, '.', '_' or '-'"
        )
    normalized_sha = site_git_sha.strip().lower()
    if not _GIT_SHA_RE.fullmatch(normalized_sha):
        raise ValueError("site_git_sha must be a full 40-character hexadecimal Git SHA")
    try:
        snapshot_id = (
            uuid.uuid4()
            if source_snapshot_id is None
            else uuid.UUID(str(source_snapshot_id))
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("source_snapshot_id must be a valid UUID") from exc
    if not 1 <= batch_size <= 10_000:
        raise ValueError("batch_size must be between 1 and 10000")
    _material_predicate(material_scope)
    resolved_output = output_dir.expanduser().resolve(strict=False)
    if not resolved_output.name or resolved_output == resolved_output.parent:
        raise ValueError("output_dir must name a dedicated bundle directory")
    return resolved_output, dataset_version, normalized_sha, snapshot_id


def _connect(database_url: str) -> Any:
    try:
        import psycopg2

        connection = psycopg2.connect(
            _to_sync_dsn(database_url),
            application_name="sclib-ml-source-exporter",
        )
        connection.set_session(
            isolation_level="REPEATABLE READ",
            readonly=True,
            autocommit=False,
        )
        return connection
    except Exception:  # noqa: BLE001 - sanitize before crossing CLI boundary
        raise ExportError("database connection failed") from None


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_checksum_files(bundle_dir: Path, artifact_names: list[str]) -> None:
    checksums = {
        name: file_sha256(bundle_dir / name) for name in sorted(artifact_names)
    }
    checksum_payload = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(checksums.items())
    ).encode("utf-8")
    _write_bytes(bundle_dir / CHECKSUMS_FILE, checksum_payload)
    manifest_digest = checksums[MANIFEST_FILE]
    _write_bytes(
        bundle_dir / MANIFEST_HASH_FILE,
        f"{manifest_digest}  {MANIFEST_FILE}\n".encode(),
    )


def export_snapshot(
    *,
    database_url: str,
    output_dir: Path,
    dataset_version: str,
    site_git_sha: str,
    source_snapshot_id: uuid.UUID | str | None = None,
    material_scope: str = "public",
    include_paper_work_map: bool = True,
    batch_size: int = 1000,
    snapshot_hook: Callable[[SnapshotState], None] | None = None,
) -> dict[str, Any]:
    """Create one atomically published source bundle and return its manifest.

    ``snapshot_hook`` exists for integration testing of MVCC behavior.  It is
    called only after the transaction snapshot and counts have been captured.
    """
    (
        final_dir,
        dataset_version,
        site_git_sha,
        snapshot_id,
    ) = _validate_export_arguments(
        output_dir=output_dir,
        dataset_version=dataset_version,
        site_git_sha=site_git_sha,
        source_snapshot_id=source_snapshot_id,
        batch_size=batch_size,
        material_scope=material_scope,
    )
    if not database_url.strip():
        raise ValueError("DATABASE_URL is required")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists() or final_dir.is_symlink():
        raise ExportError(f"output bundle already exists: {final_dir}")
    partial_dir = final_dir.parent / f".{final_dir.name}.partial-{uuid.uuid4().hex}"
    partial_dir.mkdir(mode=0o700)

    connection: Any | None = None
    try:
        connection = _connect(database_url)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '15min'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            map_table_present = validate_source_schema(
                cursor,
                material_scope=material_scope,
            )
            resolved_include_map = include_paper_work_map and map_table_present
            lock_tables = ["materials", "papers", "chunks"]
            if resolved_include_map:
                lock_tables.append("paper_work_map")
            cursor.execute(
                "LOCK TABLE "
                + ", ".join(f'public."{name}"' for name in lock_tables)
                + " IN ACCESS SHARE MODE"
            )
            state = capture_snapshot_state(
                cursor,
                material_scope=material_scope,
                include_paper_work_map=resolved_include_map,
                paper_work_map_table_present=map_table_present,
            )

        if snapshot_hook is not None:
            snapshot_hook(state)

        predicate = _material_predicate(material_scope)
        material_query = _MATERIALS_QUERY_TEMPLATE.format(predicate=predicate)
        query_specs = [
            QuerySpec("materials", MATERIALS_FILE, material_query, "id"),
            QuerySpec("papers", PAPERS_FILE, _PAPERS_QUERY, "id"),
        ]
        if resolved_include_map:
            query_specs.append(
                QuerySpec(
                    "paper_work_map",
                    PAPER_WORK_MAP_FILE,
                    _PAPER_WORK_MAP_QUERY,
                    "paper_id",
                )
            )

        files: dict[str, dict[str, Any]] = {}
        queries: dict[str, str] = {}
        for spec in query_specs:
            artifact = stream_query_jsonl(
                connection,
                spec,
                partial_dir / spec.file_name,
                batch_size=batch_size,
            )
            expected_rows = state.counts[spec.key]
            if artifact["rows"] != expected_rows:
                raise ExportError(
                    f"{spec.key} row count changed inside stable snapshot: "
                    f"expected {expected_rows}, wrote {artifact['rows']}"
                )
            files[spec.key] = artifact
            queries[spec.key] = spec.query

        license_manifest = build_license_manifest(
            source_snapshot_id=snapshot_id,
            dataset_version=dataset_version,
            database_watermark=state.database_watermark,
            material_scope=material_scope,
            paper_source_counts=state.paper_source_counts,
            material_record_source_counts=state.material_record_source_counts,
        )
        files["license_manifest"] = _write_json_document(
            partial_dir / LICENSE_FILE,
            license_manifest,
        )
        manifest = build_export_manifest(
            source_snapshot_id=snapshot_id,
            dataset_version=dataset_version,
            site_git_sha=site_git_sha,
            material_scope=material_scope,
            state=state,
            files=files,
            queries=queries,
            include_paper_work_map=resolved_include_map,
        )
        _write_json_document(partial_dir / MANIFEST_FILE, manifest)
        _write_checksum_files(
            partial_dir,
            [entry["path"] for entry in files.values()] + [MANIFEST_FILE],
        )
        connection.rollback()
        connection.close()
        connection = None

        verify_export_bundle(partial_dir)
        _fsync_directory(partial_dir)
        os.replace(partial_dir, final_dir)
        _fsync_directory(final_dir.parent)
        return manifest
    except BaseException:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()
        if partial_dir.exists() and partial_dir.parent == final_dir.parent:
            shutil.rmtree(partial_dir)
        raise


def _safe_relative_file_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError("manifest file path must be a non-empty string")
    if "\\" in value:
        raise VerificationError("manifest file path must use a plain relative filename")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or len(parsed.parts) != 1 or parsed.name in {".", ".."}:
        raise VerificationError("manifest file path must be a plain relative filename")
    return parsed.name


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path.name} must contain a JSON object")
    return value


def _require_aware_timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerificationError(f"{field} must include a timezone offset")
    return value


def _verify_jsonl(path: Path, *, dataset_key: str, order_key: str) -> int:
    try:
        expected_fields = frozenset(_JSONL_EXPORT_FIELDS[dataset_key])
    except KeyError as exc:
        raise VerificationError(
            f"unsupported JSONL field contract: {dataset_key}"
        ) from exc
    rows = 0
    previous_key: str | None = None
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n"):
                raise VerificationError(
                    f"{path.name}:{line_number} lacks a trailing newline"
                )
            raw = line[:-1]
            if not raw:
                raise VerificationError(f"{path.name}:{line_number} is blank")
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise VerificationError(
                    f"{path.name}:{line_number} contains invalid JSON"
                ) from exc
            if not isinstance(value, dict):
                raise VerificationError(f"{path.name}:{line_number} is not an object")
            actual_fields = frozenset(value)
            missing_fields = sorted(expected_fields - actual_fields)
            unknown_fields = sorted(actual_fields - expected_fields)
            if missing_fields or unknown_fields:
                violations = []
                if missing_fields:
                    violations.append("missing fields: " + ", ".join(missing_fields))
                if unknown_fields:
                    violations.append("unknown fields: " + ", ".join(unknown_fields))
                raise VerificationError(
                    f"{path.name}:{line_number} violates exact {dataset_key} "
                    f"field contract ({'; '.join(violations)})"
                )
            if canonical_json_bytes(value) != raw:
                raise VerificationError(
                    f"{path.name}:{line_number} is not canonical JSON"
                )
            key = value.get(order_key)
            if key is None:
                raise VerificationError(f"{path.name}:{line_number} lacks {order_key}")
            rendered = str(key)
            if previous_key is not None and rendered <= previous_key:
                raise VerificationError(
                    f"{path.name} is not strictly ordered by {order_key}"
                )
            previous_key = rendered
            rows += 1
    return rows


def _parse_checksum_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if match is None:
            raise VerificationError(f"{path.name}:{line_number} is malformed")
        digest, name = match.groups()
        _safe_relative_file_name(name)
        if name in values:
            raise VerificationError(f"{path.name} contains duplicate entry {name}")
        values[name] = digest
    return values


def verify_export_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Verify hashes, sizes, row counts, ordering and safe bundle paths."""
    supplied_root = bundle_dir.expanduser()
    if supplied_root.is_symlink():
        raise VerificationError("bundle path must not be a symlink")
    root = supplied_root.resolve(strict=True)
    if not root.is_dir():
        raise VerificationError("bundle path must be a real directory")
    manifest_path = root / MANIFEST_FILE
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VerificationError(f"missing {MANIFEST_FILE}")
    manifest = _load_json_object(manifest_path)
    if manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise VerificationError("unsupported export manifest schema")
    if manifest.get("exporter_version") != EXPORTER_VERSION:
        raise VerificationError("unsupported exporter version")
    # Historical v1 bundles predate this explicit annotation, but already use
    # the same strict id/formula/records-only egress schema. Never reinterpret
    # either generation as a joint observed feature row. A supplied declaration
    # must not claim stronger scientific semantics than the exporter provides.
    if "scientific_semantics" in manifest and manifest["scientific_semantics"] != SCIENTIFIC_SEMANTICS:
        raise VerificationError("source export cannot declare joint-observation or accepted-label semantics")
    try:
        uuid.UUID(str(manifest["source_snapshot_id"]))
    except (KeyError, ValueError) as exc:
        raise VerificationError("manifest source_snapshot_id is invalid") from exc
    if not _GIT_SHA_RE.fullmatch(str(manifest.get("site_git_sha") or "")):
        raise VerificationError("manifest site_git_sha is invalid")
    if not _DATASET_VERSION_RE.fullmatch(str(manifest.get("dataset_version") or "")):
        raise VerificationError("manifest dataset_version is invalid")
    _require_aware_timestamp(
        manifest.get("database_watermark"), field="manifest database_watermark"
    )
    if (
        not isinstance(manifest.get("alembic_revision"), str)
        or not manifest["alembic_revision"].strip()
    ):
        raise VerificationError("manifest alembic_revision is missing")
    if manifest.get("material_scope") not in {"public", "all"}:
        raise VerificationError("manifest material_scope is invalid")

    database = manifest.get("database")
    if not isinstance(database, dict):
        raise VerificationError("manifest database must be an object")
    if str(database.get("transaction_isolation") or "").lower() != "repeatable read":
        raise VerificationError("manifest transaction isolation is not repeatable read")
    if str(database.get("transaction_read_only") or "").lower() not in {"on", "true"}:
        raise VerificationError("manifest transaction is not read only")
    if (
        not isinstance(database.get("transaction_snapshot"), str)
        or not database["transaction_snapshot"]
    ):
        raise VerificationError("manifest transaction snapshot is missing")

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise VerificationError("manifest counts must be an object")
    for key in ("materials", "papers", "chunks", "paper_work_map", "material_records"):
        value = counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise VerificationError(f"manifest count {key} is invalid")

    queries = manifest.get("queries")
    if not isinstance(queries, dict):
        raise VerificationError("manifest queries must be an object")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise VerificationError("manifest files must be an object")
    for required in ("materials", "papers", "license_manifest"):
        if required not in files:
            raise VerificationError(f"manifest files is missing {required}")

    expected_checksums: dict[str, str] = {}
    order_keys = _JSONL_ORDER_KEYS
    for key, raw_entry in files.items():
        if key not in {*order_keys, "license_manifest"}:
            raise VerificationError(f"manifest contains unsupported file key {key}")
        if not isinstance(raw_entry, dict):
            raise VerificationError(f"manifest file entry {key} must be an object")
        file_name = _safe_relative_file_name(raw_entry.get("path"))
        if file_name in expected_checksums:
            raise VerificationError(f"duplicate artifact path in manifest: {file_name}")
        artifact_path = root / file_name
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise VerificationError(f"missing regular artifact {file_name}")
        expected_hash = raw_entry.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(
            expected_hash
        ):
            raise VerificationError(f"manifest hash for {key} is invalid")
        actual_hash = file_sha256(artifact_path)
        if actual_hash != expected_hash:
            raise VerificationError(f"checksum mismatch for {file_name}")
        if artifact_path.stat().st_size != raw_entry.get("bytes"):
            raise VerificationError(f"byte count mismatch for {file_name}")
        if key in order_keys:
            actual_rows = _verify_jsonl(
                artifact_path,
                dataset_key=key,
                order_key=order_keys[key],
            )
            if actual_rows != raw_entry.get("rows"):
                raise VerificationError(f"row count mismatch for {file_name}")
            if counts.get(key) != actual_rows:
                raise VerificationError(f"top-level count mismatch for {key}")
            query_hash = queries.get(key)
            if not isinstance(query_hash, str) or not _SHA256_RE.fullmatch(query_hash):
                raise VerificationError(f"query hash for {key} is missing or invalid")
        else:
            license_manifest = _load_json_object(artifact_path)
            if raw_entry.get("rows") != 1:
                raise VerificationError("license manifest rows must equal 1")
            if license_manifest.get("schema_version") != LICENSE_SCHEMA_VERSION:
                raise VerificationError("license manifest schema is invalid")
            for field in (
                "source_snapshot_id",
                "dataset_version",
                "database_watermark",
            ):
                if license_manifest.get(field) != manifest.get(field):
                    raise VerificationError(
                        f"license manifest {field} does not match export manifest"
                    )
            if license_manifest.get("material_scope") != manifest.get("material_scope"):
                raise VerificationError(
                    "license manifest material_scope does not match"
                )
            if license_manifest.get("distribution_status") != (
                "not_cleared_for_public_release"
            ):
                raise VerificationError(
                    "license manifest distribution policy is unsafe"
                )
            content_policy = license_manifest.get("content_policy")
            if not isinstance(content_policy, dict):
                raise VerificationError("license manifest content_policy is missing")
            for field in (
                "paper_abstracts_exported",
                "paper_authors_exported",
                "chunk_payloads_exported",
                "vector_index_frozen",
            ):
                if content_policy.get(field) is not False:
                    raise VerificationError(f"license manifest requires {field}=false")
        expected_checksums[file_name] = actual_hash

    license_entry = files["license_manifest"]
    if manifest.get("license_manifest_sha256") != license_entry.get("sha256"):
        raise VerificationError(
            "top-level license manifest hash does not match file entry"
        )
    if manifest.get("chunk_count") != manifest.get("counts", {}).get("chunks"):
        raise VerificationError("top-level chunk_count does not match counts.chunks")
    expected_query_keys = {key for key in files if key != "license_manifest"}
    if set(queries) != expected_query_keys:
        raise VerificationError("manifest query keys do not match exported data files")

    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise VerificationError("manifest metadata must be an object")
    included_map = "paper_work_map" in files
    if metadata.get("paper_work_map_included") is not included_map:
        raise VerificationError("paper_work_map inclusion metadata is inconsistent")
    if not included_map and counts.get("paper_work_map") != 0:
        raise VerificationError("paper_work_map count is nonzero without an artifact")
    if metadata.get("chunk_inventory_exported") is not False:
        raise VerificationError("chunk inventory must not be exported")
    if metadata.get("vector_index_frozen") is not False:
        raise VerificationError("vector index must not be claimed frozen")

    manifest_hash = file_sha256(manifest_path)
    expected_checksums[MANIFEST_FILE] = manifest_hash
    hash_file = root / MANIFEST_HASH_FILE
    expected_hash_line = f"{manifest_hash}  {MANIFEST_FILE}\n"
    if (
        hash_file.is_symlink()
        or hash_file.read_text(encoding="utf-8") != expected_hash_line
    ):
        raise VerificationError(f"{MANIFEST_HASH_FILE} does not match manifest")
    checksum_path = root / CHECKSUMS_FILE
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise VerificationError(f"missing {CHECKSUMS_FILE}")
    if _parse_checksum_file(checksum_path) != expected_checksums:
        raise VerificationError(f"{CHECKSUMS_FILE} does not match bundle artifacts")

    allowed_names = {
        *expected_checksums,
        MANIFEST_HASH_FILE,
        CHECKSUMS_FILE,
    }
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != allowed_names:
        unexpected = sorted(actual_names - allowed_names)
        missing = sorted(allowed_names - actual_names)
        raise VerificationError(
            f"bundle file inventory mismatch; unexpected={unexpected}, missing={missing}"
        )
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser(
        "export", help="create a stable read-only source bundle"
    )
    export.add_argument("--output-dir", required=True, type=Path)
    export.add_argument("--dataset-version", required=True)
    export.add_argument("--site-git-sha", required=True)
    export.add_argument("--source-snapshot-id", type=uuid.UUID)
    export.add_argument("--material-scope", choices=("public", "all"), default="public")
    export.add_argument("--batch-size", type=int, default=1000)
    export.add_argument("--without-paper-work-map", action="store_true")
    verify = commands.add_parser("verify", help="verify an existing source bundle")
    verify.add_argument("--bundle", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        if args.command == "verify":
            manifest = verify_export_bundle(args.bundle)
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "source_snapshot_id": manifest["source_snapshot_id"],
                        "dataset_version": manifest["dataset_version"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        manifest = export_snapshot(
            database_url=database_url,
            output_dir=args.output_dir,
            dataset_version=args.dataset_version,
            site_git_sha=args.site_git_sha,
            source_snapshot_id=args.source_snapshot_id,
            material_scope=args.material_scope,
            include_paper_work_map=not args.without_paper_work_map,
            batch_size=args.batch_size,
        )
        print(
            json.dumps(
                {
                    "status": "exported",
                    "output_dir": str(args.output_dir),
                    "source_snapshot_id": manifest["source_snapshot_id"],
                    "dataset_version": manifest["dataset_version"],
                    "manifest_sha256": file_sha256(args.output_dir / MANIFEST_FILE),
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed and redact secrets
        print(
            "ML source export error: " + safe_error_message(exc, database_url),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
