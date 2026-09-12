"""Dependency-free source and executable entrypoint guards for EN02."""
from __future__ import annotations

import ast
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SchemaLifecycleBoundaryTests(unittest.TestCase):
    def test_ml_roles_are_checked_empty_before_older_history_guards_and_seeded_last(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        empty = source.split("def _assert_empty_discovery_projections", 1)[1].split("def _pre_answer_evidence_rows", 1)[0]
        self.assertIn("_assert_empty_ml_use_roles(connection)", empty)
        main = source.split("def main()", 1)[1]
        markers = (
            "_discovery_main_barrier_downgrade_guard(capability, engine, config, barrier_package_ids)",
            "_ml_use_roles_empty_roundtrip(capability, engine, config)",
            "_ml_use_roles_on_migrated_schema(capability)",
            "_ml_use_roles_downgrade_guard(capability, engine, config, role_decision_ids)",
            'recorder.phase(connection, "final")',
        )
        self.assertEqual([main.index(marker) for marker in markers], sorted(main.index(marker) for marker in markers))

    def test_ml_role_roundtrip_preserves_all_prior_rows_and_refuses_old_head(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        block = source.split("def _ml_use_roles_empty_roundtrip", 1)[1].split("async def _ml_use_roles_on_migrated_schema", 1)[0]
        for marker in ('command.downgrade(config, "0070_discovery_main_barrier")',
                       'command.upgrade(config, "head")', "check_connection_schema(connection)",
                       "_assert_empty_ml_use_roles(connection)", "FUNCTION_SIGNATURES", "to_regprocedure"):
            self.assertIn(marker, block)
        self.assertEqual(block.count("assert snapshot(connection) == before"), 2)
        self.assertIn('if name not in {"alembic_version", _ML_USE_ROLE_TABLE}', block)
        self.assertIn('assert "exact revision" in str(exc)', block)
        for connection in block.split("with engine.connect() as connection:")[1:]:
            self.assertLess(connection.index("check_connection_schema(connection)"),
                            connection.index("verify_postgres_identity(connection, capability)"))

    def test_ml_role_native_replay_and_nonempty_downgrade_preserve_history(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        seeded = source.split("async def _ml_use_roles_on_migrated_schema", 1)[1].split("def _ml_use_roles_downgrade_guard", 1)[0]
        for marker in ("decide(session, args)", 'action="revoke"', "service.active_ml_role",
                       "await session.commit()", "assert await state(session) == before",
                       'SET TRANSACTION READ ONLY', "service.ml_role_outcome", "no_authority(info)"):
            self.assertIn(marker, seeded)
        guard = source.split("def _ml_use_roles_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn("immutable authorization history", guard)
        self.assertIn("assert snapshot(connection) == before", guard)
        self.assertIn("== set(decision_ids)", guard)
        final = guard.rsplit("with engine.connect() as connection:", 1)[1]
        self.assertLess(final.index("check_connection_schema(connection)"),
                        final.index("verify_postgres_identity(connection, capability)"))

    def test_ml_role_migration_adds_no_membership_and_guards_destructive_downgrade(self):
        source = (ROOT / "api/alembic/versions/0071_ml_use_roles.py").read_text()
        upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        self.assertIn("_table().create(op.get_bind())", upgrade)
        self.assertNotIn("INSERT", upgrade)
        downgrade = source.split("def downgrade()", 1)[1]
        self.assertLess(downgrade.index("IN ACCESS EXCLUSIVE MODE"), downgrade.index("SELECT EXISTS"))
        self.assertLess(downgrade.index("raise RuntimeError"), downgrade.index("_table().drop"))
        self.assertIn("reversed(FUNCTION_SIGNATURES)", downgrade)

    def test_main_barrier_history_cannot_mask_the_original_0069_downgrade_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        main = ast.get_source_segment(source, functions["main"])
        markers = (
            "_discovery_projection_empty_roundtrip(capability, engine, config)",
            "_discovery_main_barrier_roundtrip(capability, engine, config)",
            "_discovery_projection_on_migrated_schema(capability, api_root)",
            "_discovery_projection_downgrade_guard(capability, engine, config, discovery_package_id)",
            "_discovery_main_barrier_roundtrip(capability, engine, config, package_id=discovery_package_id)",
            "_discovery_projection_replays_on_migrated_schema(capability, (discovery_package_id,))",
            "_discovery_main_barrier_on_migrated_schema(capability, discovery_package_id)",
            "_discovery_main_barrier_downgrade_guard(capability, engine, config, barrier_package_ids)",
            "_discovery_projection_replays_on_migrated_schema(capability, (discovery_package_id, *barrier_package_ids))",
        )
        self.assertEqual([main.index(marker) for marker in markers], sorted(main.index(marker) for marker in markers))
        original = ast.get_source_segment(source, functions["_discovery_projection_downgrade_guard"])
        self.assertIn('command.downgrade(config, "0068_answer_evidence")', original)
        self.assertIn('assert "retained immutable governance" in str(exc)', original)
        self.assertNotIn("retained immutable v2 governance", original)

    def test_main_barrier_roundtrip_retains_every_v1_byte_and_the_exact_frozen_function(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("def _discovery_main_barrier_roundtrip", 1)[1].split("async def _discovery_projection_replays_on_migrated_schema", 1)[0]
        for marker in ('if name not in {"alembic_version", _ML_USE_ROLE_TABLE}', "_assert_empty_discovery_projections(connection)",
            'all(before[name] for name in _DISCOVERY_PROJECTION_TABLES)',
            'command.downgrade(config, "0069_discovery_projection")', 'assert "exact revision" in str(exc)',
            'frozen_insert_statement().split("AS $$", 1)', 'SELECT prosrc FROM pg_proc',
            'command.upgrade(config, "head")', '"0071_ml_use_roles"', "_assert_empty_ml_use_roles(connection)",
            "assert functions(connection) == before_functions"):
            self.assertIn(marker, body)
        self.assertEqual(body.count("assert snapshot(connection) == before"), 2)
        self.assertNotIn("_pre_answer_evidence_rows", body)
        self.assertIn("scalar_one() is None", body)

    def test_main_barrier_replays_are_real_original_key_noops_and_preserve_v1_and_v2(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _discovery_projection_replays_on_migrated_schema", 1)[1].split("async def _discovery_main_barrier_on_migrated_schema", 1)[0]
        for marker in ("await service._package(session, package_id)", '"request_key": row["request_key"]',
            "await service.register_projection(session, **arguments, dry_run=False)",
            'expected_request_sha256=row["request_sha256"]', 'assert replay == outcome and replay["replayed"] is True',
            'replay["record_sha256"] == row["record_sha256"]', "assert await state(session) == before", "await session.rollback()"):
            self.assertIn(marker, body)
        self.assertNotIn("await session.commit()", body)

    def test_main_barrier_rehearsal_uses_native_preview_commit_and_independent_v2_refusal(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _discovery_main_barrier_on_migrated_schema", 1)[1].split("def _discovery_main_barrier_downgrade_guard", 1)[0]
        for marker in ('{"status": "not_declared"}', '"status": "declared", "category": "evidence_gap"',
            'selected["version"] = projection.SELECTION_VERSION_V2', "expected_selection_sha256=digest(selected)",
            "assert await state(session) == before", 'expected_payload_sha256=preview["payload_sha256"], dry_run=False',
            "await session.commit()", 'payload["version"] == projection.VERSION_V2',
            'stored["public_bundle_json"] == original["public_bundle_json"]',
            'stored["scientific_pins_json"] == original["scientific_pins_json"]',
            "assert all(payload[key] is False for key in projection.AUTHORITY)",
            "assert await service._package(session, package_id) == original"):
            self.assertIn(marker, body)
        guard = source.split("def _discovery_main_barrier_downgrade_guard", 1)[1].split("def _ml_use_roles_empty_roundtrip", 1)[0]
        self.assertIn('command.downgrade(config, "0069_discovery_projection")', guard)
        self.assertIn('assert "retained immutable v2 governance" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)
        self.assertIn("scalar_one() == before_function", guard)
        self.assertNotIn("if name not in", guard)

    def test_main_barrier_migration_is_additive_and_refuses_v2_before_restoring_v1(self):
        source = (ROOT / "api/alembic/versions/0070_discovery_main_barrier.py").read_text()
        self.assertIn('down_revision = "0069_discovery_projection"', source)
        self.assertNotIn("CASCADE", source)
        self.assertNotIn("DELETE", source)
        self.assertNotIn("UPDATE", source)
        refusal = source.index("retained immutable v2 governance")
        self.assertLess(refusal, source.index("op.execute(frozen_insert_statement())"))
        self.assertLess(refusal, source.index("reversed(FUNCTION_SIGNATURES)"))
        self.assertIn("payload_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-projection/1.0.0'", source)
        self.assertIn("selection_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-selection/1.0.0'", source)

    def test_discovery_projection_history_is_last_and_older_empty_exclusions_are_narrow(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        main = ast.get_source_segment(source, functions["main"])
        markers = ("_answer_evidence_downgrade_guard(capability", "_discovery_projection_empty_roundtrip(capability",
            "_discovery_projection_on_migrated_schema(capability", "_discovery_projection_downgrade_guard(capability")
        self.assertEqual([main.index(item) for item in markers], sorted(main.index(item) for item in markers))
        empty = ast.get_source_segment(source, functions["_discovery_projection_empty_roundtrip"])
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)
        self.assertIn('before["answer_evidence_receipts"] and before["scientific_result_decisions"]', empty)
        self.assertIn('command.downgrade(config, "0068_answer_evidence")', empty)
        self.assertIn('assert "exact revision" in str(exc)', empty)
        self.assertIn("scalar_one() is None", empty)
        self.assertIn("scalar_one() is not None", empty)
        for name, node in functions.items():
            body = ast.get_source_segment(source, node)
            if name.endswith("downgrade_guard"):
                self.assertNotIn('if name not in', body)
            elif name != "_pre_answer_evidence_rows" and "_pre_answer_evidence_rows(connection, name)" in body:
                self.assertIn("*_DISCOVERY_PROJECTION_TABLES", body)
        self.assertIn("_assert_empty_discovery_projections(connection)",
            ast.get_source_segment(source, functions["_assert_empty_answer_evidence"]))

    def test_discovery_migrated_guard_preserves_real_committed_governance(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _discovery_projection_on_migrated_schema", 1)[1].split("def _discovery_projection_downgrade_guard", 1)[0]
        for marker in ("await register(session)", "service.review_projection(session", "service.projection_action(session",
            'kind="withdraw"', "await session.commit()", "await state(session) == before", 'replay["replayed"] is True'):
            self.assertIn(marker, body)
        guard = source.split("def _discovery_projection_downgrade_guard", 1)[1].split("def main", 1)[0]
        self.assertIn("retained immutable governance", guard)
        self.assertIn("assert snapshot(connection) == before", guard)
        migration = (ROOT / "api/alembic/versions/0069_discovery_projection.py").read_text()
        self.assertNotIn("CASCADE", migration)
        self.assertLess(migration.index("retained immutable governance"), migration.index("tables[name].drop"))
        self.assertIn("reversed(FUNCTION_SIGNATURES)", migration)

    def test_answer_receipt_history_is_last_and_old_roundtrip_exclusion_is_narrow(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        main = ast.get_source_segment(source, functions["main"])
        markers = ("_adjudication_downgrade_guard(capability", "_answer_evidence_empty_roundtrip(capability",
                   "_answer_evidence_on_migrated_schema(capability", "_answer_evidence_downgrade_guard(capability")
        self.assertEqual([main.index(item) for item in markers], sorted(main.index(item) for item in markers))
        helper = ast.get_source_segment(source, functions["_pre_answer_evidence_rows"])
        self.assertIn('name == "ask_history"', helper)
        self.assertIn("to_jsonb(item)-'evidence_receipt_version'", helper)
        self.assertIn('else "to_jsonb(item)"', helper)
        old_roundtrips = ("_source_impact_indexes_on_migrated_schema", "_background_jobs_empty_roundtrip",
            "_rag_evidence_empty_roundtrip", "_embedding_receipts_empty_roundtrip", "_index_generations_empty_roundtrip",
            "_distributions_empty_roundtrip", "_ml_feature_bindings_empty_roundtrip", "_scientific_imports_empty_roundtrip",
            "_result_impact_indexes_roundtrip", "_adjudications_empty_roundtrip")
        for name in old_roundtrips:
            body = ast.get_source_segment(source, functions[name])
            self.assertIn("_pre_answer_evidence_rows(connection, name)", body)
            self.assertIn("_ANSWER_EVIDENCE_TABLE", body)
            self.assertIn("assert snapshot(connection) == before", body)
        for name, node in functions.items():
            if name.endswith("downgrade_guard"):
                self.assertNotIn("_pre_answer_evidence_rows", ast.get_source_segment(source, node))
        empty = ast.get_source_segment(source, functions["_assert_empty_answer_evidence"])
        self.assertIn("FROM public.answer_evidence_receipts", empty)
        self.assertIn("evidence_receipt_version IS NOT NULL", empty)
        chain = ast.get_source_segment(source, functions["_assert_empty_adjudications"])
        self.assertIn("_assert_empty_answer_evidence(connection)", chain)

    def test_answer_receipt_migrated_fixture_proves_atomicity_history_and_durable_cascade(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        empty = source.split("def _answer_evidence_empty_roundtrip", 1)[1].split("async def _answer_evidence_on_migrated_schema", 1)[0]
        self.assertLess(empty.index('command.downgrade(config, "0067_scientific_adjudication")'), empty.index("INSERT INTO ask_history"))
        self.assertLess(empty.index("INSERT INTO ask_history"), empty.index('command.upgrade(config, "head")'))
        self.assertNotIn("with engine.begin()", empty)
        self.assertIn('assert "exact revision" in str(exc)', empty)
        upgraded = empty.split('command.upgrade(config, "head")', 1)[1]
        self.assertLess(upgraded.index("check_connection_schema(connection)"), upgraded.index("verify_postgres_identity(connection, capability)"))
        self.assertIn("scalar_one() is None", empty)
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)
        body = source.split("async def _answer_evidence_on_migrated_schema", 1)[1].split("def _answer_evidence_downgrade_guard", 1)[0]
        for marker in ("service.capture_inputs(", "service.finish_capture(", "service.receipt_fields(",
                       "append(receipt=False)", "complete_receipt_required", "await session.rollback()",
                       "assert await state(session) == before", "assert await state(session) == written",
                       "await service.verify_historical(session, stored) == verified", "== legacy_before",
                       "await append(identifier=deleted_id)", "DELETE FROM ask_history WHERE id=:id AND user_id=:owner"):
            self.assertIn(marker, body)
        guard = source.split("def _answer_evidence_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn("retained immutable saved answers", guard)
        self.assertIn("assert snapshot(connection) == before", guard)
        after = guard.split('raise AssertionError("Nonempty saved-answer downgrade must fail closed")', 1)[1]
        self.assertLess(after.index("check_connection_schema(connection)"), after.index("verify_postgres_identity(connection, capability)"))

    def test_answer_receipt_migration_removes_only_own_empty_objects(self):
        source = (ROOT / "api/alembic/versions/0068_answer_evidence.py").read_text()
        self.assertIn('down_revision = "0067_scientific_adjudication"', source)
        self.assertLess(source.index("retained immutable saved answers"), source.index("DROP TRIGGER ae68_complete"))
        self.assertNotIn("CASCADE", source)
        self.assertIn('op.drop_column("ask_history", "evidence_receipt_version")', source)
        self.assertIn("reversed(FUNCTION_SIGNATURES)", source)

    def test_adjudication_history_is_populated_after_every_old_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        markers = ("_ml_feature_binding_downgrade_guard(capability", "_scientific_imports_empty_roundtrip(capability",
                   "_scientific_import_downgrade_guard(capability", "_result_impact_indexes_roundtrip(capability, engine, config, populated=True)",
                   "_adjudications_empty_roundtrip(capability", "_adjudications_on_migrated_schema(capability",
                   "_adjudication_downgrade_guard(capability")
        positions = [main.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        body = source.split("async def _adjudications_on_migrated_schema", 1)[1].split("def _adjudication_downgrade_guard", 1)[0]
        for marker in ("capture_result_subject(session", "service.adjudicate(session", "assert await state(session) == before",
                       "await session.commit()", 'assert replay["replayed"] is True', "assert await state(session) == after"):
            self.assertIn(marker, body)
        guard = source.split("def _adjudication_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn("retained exact review history", guard)
        self.assertIn("assert snapshot(connection) == before", guard)

    def test_adjudication_migration_removes_only_own_empty_objects(self):
        source = (ROOT / "api/alembic/versions/0067_scientific_adjudication.py").read_text()
        self.assertIn('down_revision = "0066_result_impact_indexes"', source)
        self.assertLess(source.index("retained exact review history"), source.index("DROP TRIGGER sa67_catalogue_writer"))
        self.assertNotIn("CASCADE", source)
        self.assertIn("reversed(FUNCTION_SIGNATURES)", source)

    def test_entrypoint_never_migrates_and_executes_only_after_admission(self):
        entrypoint = ROOT / "api/entrypoint.sh"
        source = entrypoint.read_text()
        self.assertNotIn("alembic", source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {
                "python": '#!/bin/sh\nprintf "check:%s\\n" "$*" >> "$SCLIB_TEST_LOG"\nexit "${SCLIB_TEST_CHECK_EXIT:-0}"\n',
                "uvicorn": '#!/bin/sh\nprintf "serve:%s\\n" "$*" >> "$SCLIB_TEST_LOG"\n',
            }.items():
                path = root / name
                path.write_text(body)
                path.chmod(0o700)
            log = root / "calls"
            environment = {"PATH": f"{root}:/usr/bin:/bin", "SCLIB_TEST_LOG": str(log)}
            success = subprocess.run(["/bin/sh", str(entrypoint), "uvicorn", "main:app"], env=environment, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["check:-m services.schema_lifecycle check", "serve:main:app"])
            log.unlink()
            rejected = subprocess.run(["/bin/sh", str(entrypoint), "uvicorn", "main:app"], env={**environment, "SCLIB_TEST_CHECK_EXIT": "1"}, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["check:-m services.schema_lifecycle check"])

    def test_deployment_orders_credential_backup_signature_migration_admission_cutover(self):
        source = (ROOT / ".github/workflows/deploy.yml").read_text()
        positions = [source.index(value) for value in (
            "test -s /etc/sclib/credentials/migration-database-url",
            "bash scripts/backup_postgres.sh",
            "cosign verify",
            'run --rm --no-deps migration',
            'python -m services.schema_lifecycle check',
            'up -d --no-build --wait --wait-timeout 180',
        )]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("api alembic", source)
        self.assertIn("set -euo pipefail", source)

    def test_migration_service_does_not_inherit_api_env_or_cloud_credentials(self):
        base = (ROOT / "docker-compose.yml").read_text().split("\n  migration:\n", 1)[1].split("\n  ingestion:\n", 1)[0]
        production = (ROOT / "docker-compose.prod.yml").read_text().split("\n  migration:\n", 1)[1].split("\n  ingestion:\n", 1)[0]
        self.assertNotIn("\n    env_file:", base)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", base + production)
        self.assertNotIn("\n    ports:", base + production)
        self.assertIn('profiles: ["tools"]', base)
        self.assertIn('restart: "no"', base)
        self.assertIn('DATABASE_URL: ""', production)
        self.assertIn("SCLIB_MIGRATION_DATABASE_URL_FILE:", production)
        self.assertIn("image: ${SCLIB_API_IMAGE:?", production)
        self.assertIn(":/run/secrets/sclib-migration-database-url:ro", production)

    def test_startup_gate_precedes_all_background_tasks(self):
        source = (ROOT / "api/main.py").read_text().split("async def lifespan", 1)[1]
        self.assertLess(source.index("await check_application_schema"), source.index("asyncio.create_task"))
        environment = (ROOT / "api/alembic/env.py").read_text().split("def run_migrations_online", 1)[1]
        self.assertLess(environment.index("acquire_migration_lock"), environment.index("context.run_migrations"))
        self.assertIn("pool.NullPool", environment)

    def test_populated_task_history_does_not_mask_independent_older_guards(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        tree = ast.parse(source)
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        called = sorted((node.lineno, node.func.id) for node in ast.walk(main)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
        positions = {name: line for line, name in called}
        ordered = [positions[name] for name in (
            "_freeze_on_migrated_schema", "_publication_on_migrated_schema",
            "_source_lifecycle_on_migrated_schema", "_source_impact_indexes_on_migrated_schema",
            "_source_tasks_on_migrated_schema", "_source_task_downgrade_guard",
            "_background_jobs_empty_roundtrip", "_background_jobs_on_migrated_schema", "_background_job_downgrade_guard",
            "_rag_evidence_empty_roundtrip", "_rag_evidence_on_migrated_schema", "_rag_evidence_downgrade_guard",
            "_embedding_receipts_empty_roundtrip", "_embedding_receipts_on_migrated_schema", "_embedding_receipt_downgrade_guard",
        )]
        self.assertEqual(ordered, sorted(ordered))
        for marker in ("preserve scientific correction proposals", "registry contains records",
                       "shadow history contains records", "release history contains records",
                       "governance history contains records"):
            self.assertLess(source.index(marker), source.index("request_id = asyncio.run(_source_tasks_on_migrated_schema"))

    def test_migrated_task_checks_exercise_effect_and_rollback_not_only_metadata(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _source_tasks_on_migrated_schema", 1)[1].split("\ndef _source_task_downgrade_guard", 1)[0]
        for marker in ("enqueue_source_task(session", "execute_source_task(session", "record_source_task_failure(session",
                       "assert await state(session) == before_request", "assert await state(session) == before_attempt",
                       'assert after_attempt["timeline_projection_state"] == expected_state',
                       'assert replay["replayed"] is True', 'assert await state(session) == after_attempt'):
            self.assertIn(marker, body)

    def test_background_history_is_populated_only_after_every_prior_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(value) for value in (
            "_source_impact_indexes_on_migrated_schema(capability", "_source_tasks_on_migrated_schema(capability",
            "_source_task_downgrade_guard(capability", "_background_jobs_empty_roundtrip(capability",
            "_background_jobs_on_migrated_schema(capability", "_background_job_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('assert before["background_job_cycles"] == []', source)
        self.assertGreaterEqual(source.count('SELECT count(*) FROM background_job_cycles'), 5)

    def test_migrated_background_service_proves_effect_rollback_and_exact_replay(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _background_jobs_on_migrated_schema", 1)[1].split("\ndef _background_job_downgrade_guard", 1)[0]
        for marker in ("run_background_cycle(", "insert(AuditReport)", 'assert failed["status"] == "failed"',
                       'assert after_failure["audit_reports"] == before["audit_reports"]',
                       'assert succeeded["status"] == "succeeded"', 'assert len(reports) == 1',
                       'assert replay["status"] == "already_succeeded"', "assert await snapshot() == after_success",
                       "run_sync(check_connection_schema)", "pg_locks"):
            self.assertIn(marker, body)

    def test_rag_history_never_masks_older_guards_and_empty_roundtrip_preserves_rows(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(value) for value in (
            "_source_task_downgrade_guard(capability", "_background_jobs_empty_roundtrip(capability",
            "_background_job_downgrade_guard(capability", "_rag_evidence_empty_roundtrip(capability",
            "_rag_evidence_on_migrated_schema(capability", "_rag_evidence_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('_RAG_EVIDENCE_TABLES = ("rag_extraction_revisions", "rag_evidence_revisions", "chunk_evidence_current")', source)
        for function, end in (("_source_impact_indexes_on_migrated_schema", "async def _freeze_on_migrated_schema"),
                              ("_background_jobs_empty_roundtrip", "async def _background_jobs_on_migrated_schema")):
            body = source.split("def " + function, 1)[1].split(end, 1)[0]
            self.assertIn("*_RAG_EVIDENCE_TABLES", body)
            self.assertEqual(body.count("_assert_empty_rag_evidence(connection)"), 2)
        body = source.split("def _rag_evidence_empty_roundtrip", 1)[1].split("async def _rag_evidence_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0059_background_jobs")', body)
        self.assertEqual(body.count("assert snapshot(connection) == before"), 2)
        self.assertEqual(body.count("_assert_empty_rag_evidence(connection)"), 2)

    def test_real_migrated_rag_service_proves_projection_rollback_invalidation_and_replay(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _rag_evidence_on_migrated_schema", 1)[1].split("\ndef _rag_evidence_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "register_chunk_evidence(session",
                       "assert await state(session) == before", "assert replay == first",
                       'assert invalidated["chunk_evidence_current"] == []', "await session.rollback()",
                       "assert await state(session) == written", 'assert "exact_live_chunk" in str(exc)',
                       'assert [len(final[name]) for name in _RAG_EVIDENCE_TABLES] == [1, 2, 1]',
                       "assert await state(session) == final", '"PRIVATE ORIGINAL WORDING" not in str(parent)'):
            self.assertIn(marker, body)
        guard = source.split("def _rag_evidence_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn('"lineage history contains records" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)

    def test_embedding_receipts_only_populate_after_every_old_guard_and_preserve_empty_roundtrip(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(value) for value in (
            "_rag_evidence_downgrade_guard(capability", "_embedding_receipts_empty_roundtrip(capability",
            "_embedding_receipts_on_migrated_schema(capability", "_embedding_receipt_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        for function, end in (("_source_impact_indexes_on_migrated_schema", "async def _freeze_on_migrated_schema"),
                              ("_background_jobs_empty_roundtrip", "async def _background_jobs_on_migrated_schema"),
                              ("_rag_evidence_empty_roundtrip", "async def _rag_evidence_on_migrated_schema")):
            body = source.split("def " + function, 1)[1].split(end, 1)[0]
            self.assertIn("_EMBEDDING_RECEIPT_TABLE", body)
        body = source.split("def _embedding_receipts_empty_roundtrip", 1)[1].split("async def _embedding_receipts_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0060_rag_evidence")', body)
        self.assertEqual(body.count("assert snapshot(connection) == before"), 2)
        self.assertEqual(body.count("_assert_empty_embedding_receipts(connection)"), 2)

    def test_actual_migrated_embedding_receipt_validates_real_vector_and_full_state_replay(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _embedding_receipts_on_migrated_schema", 1)[1].split("def _embedding_receipt_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "vector, receipt = completion(", "append_embedding_receipt(session",
                       "assert await state(session) == before", "await session.rollback()", "assert replay == first",
                       "assert await state(session) == written", 'stored["metadata_json"]["provider_truncated"] is False'):
            self.assertIn(marker, body)
        guard = source.split("def _embedding_receipt_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn('"receipt history contains records" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)

    def test_generation_history_is_independently_empty_until_all_older_guards_pass(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(marker) for marker in ("_embedding_receipt_downgrade_guard(capability",
            "_index_generations_empty_roundtrip(capability", "_index_generations_on_migrated_schema(capability",
            "_index_generation_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        empty = source.split("def _index_generations_empty_roundtrip", 1)[1].split("async def _index_generations_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0061_embedding_receipts")', empty)
        self.assertEqual(empty.count("_assert_empty_index_generations(connection)"), 2)
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)

    def test_migrated_generation_rehearsal_uses_actual_bytes_and_monotonic_rollback(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _index_generations_on_migrated_schema", 1)[1].split("def _index_generation_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "stage_generation(session", "record_validation(session",
                       "activate_generation(session", "assert replay == first", "assert await state(session) == before",
                       "assert await state(session) == written", "assert await state(session) == active_state",
                       'retained[0]["snapshot_json"]["text"] == chunk["text"]', 'len(retained[0]["vector_bytes"]) == 3072',
                       'action="rollback"'):
            self.assertIn(marker, body)

    def test_distribution_history_cannot_mask_any_earlier_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(marker) for marker in (
            "_index_generation_downgrade_guard(capability", "_distributions_empty_roundtrip(capability",
            "_distributions_on_migrated_schema(capability", "_distribution_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        chain = source.split("def _assert_empty_index_generations", 1)[1].split("def _assert_empty_embedding_receipts", 1)[0]
        self.assertIn("_assert_empty_distributions(connection)", chain)
        for name, end in (("_source_impact_indexes_on_migrated_schema", "async def _freeze_on_migrated_schema"),
                          ("_background_jobs_empty_roundtrip", "async def _background_jobs_on_migrated_schema"),
                          ("_rag_evidence_empty_roundtrip", "async def _rag_evidence_on_migrated_schema"),
                          ("_embedding_receipts_empty_roundtrip", "async def _embedding_receipts_on_migrated_schema"),
                          ("_index_generations_empty_roundtrip", "async def _index_generations_on_migrated_schema")):
            body = source.split("def " + name, 1)[1].split(end, 1)[0]
            self.assertIn("*_DISTRIBUTION_TABLES", body)
        empty = source.split("def _distributions_empty_roundtrip", 1)[1].split("async def _distributions_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0062_index_generations")', empty)
        self.assertEqual(empty.count("_assert_empty_distributions(connection)"), 2)
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)

    def test_migrated_distribution_proves_actual_roots_permissions_rollback_and_noop(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _distributions_on_migrated_schema", 1)[1].split("def _distribution_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "distribution_inputs(session", "publish_distribution(session",
                       "service.register_distribution(session", "service.decide_distribution_permission(session",
                       "service.review_distribution(session", "service.distribution_action(session",
                       "service.admitted_distribution(session", "assert await state(session) == before",
                       "assert await state(session) == published", "assert await state(session) == withdrawn",
                       "await session.rollback()", '"replayed": True'):
            self.assertIn(marker, body)
        guard = source.split("def _distribution_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn('"retained governance history" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)


    def test_feature_companion_never_masks_earlier_guards_and_empty_roundtrip_preserves_rows(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(marker) for marker in (
            "_distribution_downgrade_guard(capability", "_ml_feature_bindings_empty_roundtrip(capability",
            "_ml_feature_bindings_on_migrated_schema(capability", "_ml_feature_binding_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        chain = source.split("def _assert_empty_distributions", 1)[1].split("def _assert_empty_index_generations", 1)[0]
        self.assertIn("_assert_empty_ml_feature_bindings(connection)", chain)
        for name, end in (("_source_impact_indexes_on_migrated_schema", "async def _freeze_on_migrated_schema"),
                          ("_background_jobs_empty_roundtrip", "async def _background_jobs_on_migrated_schema"),
                          ("_rag_evidence_empty_roundtrip", "async def _rag_evidence_on_migrated_schema"),
                          ("_embedding_receipts_empty_roundtrip", "async def _embedding_receipts_on_migrated_schema"),
                          ("_index_generations_empty_roundtrip", "async def _index_generations_on_migrated_schema"),
                          ("_distributions_empty_roundtrip", "async def _distributions_on_migrated_schema")):
            self.assertIn("_ML_FEATURE_BINDING_TABLE", source.split("def " + name, 1)[1].split(end, 1)[0])
        empty = source.split("def _ml_feature_bindings_empty_roundtrip", 1)[1].split("async def _ml_feature_bindings_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0063_research_distribution")', empty)
        self.assertEqual(empty.count("_assert_empty_ml_feature_bindings(connection)"), 2)
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)

    def test_migrated_feature_companion_proves_actual_bytes_timing_and_complete_state_replay(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _ml_feature_bindings_on_migrated_schema", 1)[1].split("def _ml_feature_binding_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "feature_fixture(session)",
                       "service.register_feature_source_binding(session", "companion(session, fixture)",
                       "verify(retained, fixture)", "assert await state(session) == before",
                       "await session.rollback()", '"replayed": True', "assert await state(session) == written",
                       '"2020-01-01T00:00:00Z"', '"2026-01-01T00:00:00Z"',
                       "service.decode_companion_artifacts(retained)"):
            self.assertIn(marker, body)
        guard = source.split("def _ml_feature_binding_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn('"retained source binding history" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)


    def test_scientific_imports_follow_every_prior_independent_guard(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        positions = [main.index(marker) for marker in (
            "_source_task_downgrade_guard(capability", "_background_job_downgrade_guard(capability",
            "_rag_evidence_downgrade_guard(capability", "_embedding_receipt_downgrade_guard(capability",
            "_index_generation_downgrade_guard(capability", "_distribution_downgrade_guard(capability",
            "_ml_feature_binding_downgrade_guard(capability", "_scientific_imports_empty_roundtrip(capability",
            "_scientific_imports_on_migrated_schema(capability", "_scientific_import_downgrade_guard(capability")]
        self.assertEqual(positions, sorted(positions))
        chain = source.split("def _assert_empty_ml_feature_bindings", 1)[1].split("def _assert_empty_distributions", 1)[0]
        self.assertIn("_assert_empty_scientific_imports(connection)", chain)
        empty_helper = source.split("def _assert_empty_scientific_imports", 1)[1].split("def _assert_empty_ml_feature_bindings", 1)[0]
        self.assertIn("for name in _SCIENTIFIC_IMPORT_TABLES", empty_helper)
        self.assertIn(".scalar_one() == 0", empty_helper)
        for name, end in (("_source_impact_indexes_on_migrated_schema", "async def _freeze_on_migrated_schema"),
                          ("_background_jobs_empty_roundtrip", "async def _background_jobs_on_migrated_schema"),
                          ("_rag_evidence_empty_roundtrip", "async def _rag_evidence_on_migrated_schema"),
                          ("_embedding_receipts_empty_roundtrip", "async def _embedding_receipts_on_migrated_schema"),
                          ("_index_generations_empty_roundtrip", "async def _index_generations_on_migrated_schema"),
                          ("_distributions_empty_roundtrip", "async def _distributions_on_migrated_schema"),
                          ("_ml_feature_bindings_empty_roundtrip", "async def _ml_feature_bindings_on_migrated_schema")):
            self.assertIn("*_SCIENTIFIC_IMPORT_TABLES", source.split("def " + name, 1)[1].split(end, 1)[0])
        empty = source.split("def _scientific_imports_empty_roundtrip", 1)[1].split("async def _scientific_imports_on_migrated_schema", 1)[0]
        self.assertIn('command.downgrade(config, "0064_ml_feature_companion")', empty)
        self.assertEqual(empty.count("_assert_empty_scientific_imports(connection)"), 2)
        self.assertEqual(empty.count("assert snapshot(connection) == before"), 2)

    def test_migrated_scientific_import_preserves_durable_unknown_start_and_full_state(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        body = source.split("async def _scientific_imports_on_migrated_schema", 1)[1].split("def _scientific_import_downgrade_guard", 1)[0]
        for marker in ("run_sync(check_connection_schema)", "seed_import(session)",
                       "service.compile_input(fixture", "service.preview_import(session", "_start(session",
                       "_finish(session", "service.inspect_import(session", "await session.rollback()",
                       '"outcome_unknown"', '"success_pending"', '"scientific_import_blobs"',
                       "assert await state(session) == before", "assert await state(session) == durable_start",
                       "assert await state(session) == written", 'replay["replayed"]'):
            self.assertIn(marker, body)
        self.assertGreaterEqual(body.count("await session.commit()"), 4)
        guard = source.split("def _scientific_import_downgrade_guard", 1)[1].split("def main()", 1)[0]
        self.assertIn('"retained source or attempt history" in str(exc)', guard)
        self.assertIn("assert snapshot(connection) == before", guard)


    def test_result_impact_index_only_roundtrip_preserves_all_histories(self):
        source = (ROOT / "scripts/run_test_migrations.py").read_text()
        main = source.split("def main()", 1)[1]
        empty = "_result_impact_indexes_roundtrip(capability, engine, config, populated=False)"
        populated = "_result_impact_indexes_roundtrip(capability, engine, config, populated=True)"
        self.assertLess(main.index(empty), main.index("_scientific_imports_on_migrated_schema(capability"))
        self.assertGreater(main.index(populated), main.index("_scientific_import_downgrade_guard(capability"))
        body = source.split("def _result_impact_indexes_roundtrip", 1)[1].split("def _adjudications_empty_roundtrip", 1)[0]
        self.assertIn('command.downgrade(config, "0065_scientific_import")', body)
        self.assertIn("_assert_result_impact_indexes(connection, present=False)", body)
        self.assertEqual(body.count("assert snapshot(connection) == before"), 3)
        self.assertIn('before["scientific_import_outcomes"]', body)
        self.assertIn('EXPLAIN (FORMAT JSON)', body)
        migration = (ROOT / "api/alembic/versions/0066_result_impact_indexes.py").read_text()
        self.assertIn("index.create(op.get_bind())", migration)
        self.assertIn("index.drop(op.get_bind())", migration)
        for forbidden in ("UPDATE ", "DELETE ", "TRUNCATE ", "ALTER TABLE", "CONCURRENTLY"):
            self.assertNotIn(forbidden, migration)


if __name__ == "__main__":
    unittest.main()
