"""Opt-in genuine upstream bytes, only against the guarded disposable database.

These three cases remain in the denominator, including missing/unsupported
inputs. They do not attest native execution, source rights, expert review or ML
admission. Without explicit local paths all three are reported as skipped.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from scientific_program_preflight import capture_package

from models.db import Base
from services import scientific_pending_import as service
from services.research_release_manifest import digest
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors

db_session = _serializable_db_session
CASES = (
    ("al-example14", "Al", "2b558caaff631dcf64903f20b1db22af8b768860aba2dceb750bce8360d523d4",
     None, None, None, "quarantined", "force_constants_unavailable"),
    ("alas-grid-recover", "AlAs", "3a174f442e90bceb11df01111a0952381a79eb61d3e5a0df9aa4c5b770025f0d",
     "alas.444.fc", "b683e6fa7b6182c25ed5a25ee61038f10841d5e4827b7c6396a33b6ca4cc2047", 77388,
     "success_pending", None),
    ("bn-example17-2d", "BN", "766672823aef629ac55a91be219c0a186cf82ecb34ce66fdb0fdf7c1f9ec6311",
     "bn881.fc", "34945d97a3458ea6833df66485feb4ab09e6c9b65f022e99ff7387dae87e3bde", 77384,
     "quarantined", "unsupported_ibrav_coordinate_convention"),
)


def read_force_constants(root, checksum, expected_size):
    path = Path(root).absolute() / (checksum + ".bin")
    assert all(not parent.is_symlink() for parent in path.parents)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == expected_size
        with os.fdopen(os.dup(fd), "rb") as source:
            data = source.read(expected_size + 1)
        after = os.fstat(fd)
        assert (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    finally:
        os.close(fd)
    assert len(data) == expected_size and hashlib.sha256(data).hexdigest() == checksum
    return data


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
async def test_genuine_source_bytes_pending_import_and_exact_replay(db_session, pytestconfig, case):
    capsule_root = pytestconfig.getoption("--scientific-reference-capsules", default=None)
    fc_root = pytestconfig.getoption("--scientific-force-constants", default=None)
    if not capsule_root or not fc_root:
        pytest.skip("Explicit pinned local reference paths not supplied; no download attempted")
    name, formula, manifest_sha, fc_name, fc_sha, fc_size, expected_status, expected_reason = case
    captured, _ = capture_package(Path(capsule_root).absolute() / name / "manifest.json")
    manifest_bytes = captured["manifest.json"]
    assert hashlib.sha256(manifest_bytes).hexdigest() == manifest_sha
    manifest = json.loads(manifest_bytes)
    people = await actors(db_session)
    material_id = "reference-canary:" + uuid4().hex
    await add(db_session, "materials", id=material_id, formula=formula, formula_normalized=formula,
              records=[{"reference_canary_only": True}], needs_review=True)
    binding = await service.material_binding(db_session, actor_user_id=people["curator"], material_id=material_id)
    fc_bytes = None if fc_sha is None else read_force_constants(fc_root, fc_sha, fc_size)
    context = {"version": "scientific-import-context/1.0.0", "material_id": material_id,
        "expected_material_row_sha256": binding["material_row_sha256"], "force_constants": None if fc_sha is None else {
            "logical_name": fc_name, "sha256": fc_sha, "size_bytes": fc_size}}
    package = service.prepare_input(manifest=manifest, expected_manifest_sha256=manifest_sha, context=context,
        artifact_bytes={entry["sha256"]: captured[entry["sha256"] + ".bin"] for entry in manifest["files"]},
        force_constants_bytes=fc_bytes)
    prepared = service.compile_input(package)
    key = "reference-canary:" + uuid4().hex
    before = await state(db_session)
    preview = await service.preview_import(db_session, actor_user_id=people["curator"], request_key=key, prepared=prepared)
    assert preview["status"] == expected_status
    assert await state(db_session) == before
    started = await service.start_import(db_session, actor_user_id=people["curator"], request_key=key,
                                        package=package, dry_run=False)
    await db_session.commit()
    terminal = await service.finish_import(db_session, actor_user_id=people["curator"],
        attempt_id=started["attempt_id"], prepared=prepared, dry_run=False)
    await db_session.commit()
    assert terminal["status"] == expected_status
    if expected_reason:
        assert expected_reason in terminal["report"]["reason_codes"]
        assert terminal["row_ids"] is None
    else:
        assert terminal["report"]["force_constants"]["inventory"]["entry_count"] == 2304
        assert terminal["report"]["coordinate_sha256"] == "3afa668279d90e9d877200f0fa7c2733b39723725d09e5744e59286716b921cf"
    after = await state(db_session)
    replay = await service.start_import(db_session, actor_user_id=people["curator"], request_key=key,
                                       package=package, dry_run=False)
    assert replay == {**terminal, "replayed": True}
    assert await state(db_session) == after
    for untouched in ("materials", "material_claims", "source_snapshots", "ml_examples", "ml_example_inputs"):
        assert before[untouched] == after[untouched]
    blobs = Base.metadata.tables["scientific_import_blobs"]
    saved = set((await db_session.execute(sa.select(blobs.c.bytes_sha256))).scalars())
    assert {checksum for _, _, checksum, _ in package.sources} <= saved
    assert set(terminal["authority"].values()) == {False}
    assert all(terminal["costs"][key] is None for key in
               ("calculation_cpu_seconds", "calculation_wall_seconds", "calculation_monetary_cost"))
    print(json.dumps({"case": name, "status": terminal["status"], "reasons": terminal["report"]["reason_codes"],
        "manifest_sha256": manifest_sha, "force_constants_sha256": fc_sha,
        "compiler_sha256": package.request["compiler_sha256"], "report_sha256": terminal["report_sha256"],
        "source_file_count": len(package.sources), "costs": terminal["costs"],
        "scientifically_accepted": 0, "ml_admitted": 0, "database_replay_unchanged": True,
        "full_state_after_sha256": digest(after)}, sort_keys=True))
