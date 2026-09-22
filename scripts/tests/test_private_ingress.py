"""Source/safety contracts; actual Nginx behavior uses the separate owned drill."""

from __future__ import annotations

import ast
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "private_ingress", ROOT / "nginx/rehearse_private_intake.py"
)
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


def constant(path, name, references=None):
    references = references or {}

    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return references[node.value.id + "." + node.attr]
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
        raise ValueError("Unsupported source constant")

    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return value(node.value)
    raise ValueError("Source constant missing")


class PrivateIngressTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "nginx/sclib.conf").read_text()
        self.policy = (ROOT / "nginx/private-intake.conf").read_text()

    def test_actual_application_budgets_match_exact_proxy_routes_without_imports(self):
        file_limit = constant("api/services/ml_pilot_accounting.py", "MAX_BYTES")
        refs = {"documents.MAX_BYTES": file_limit}
        two = constant(
            "api/services/ml_pilot_registration_documents.py",
            "MAX_ENVELOPE_BYTES",
            refs,
        )
        four = constant(
            "api/services/ml_pilot_review_documents.py", "MAX_ENVELOPE_BYTES", refs
        )
        reconstruction = constant(
            "api/services/ml_use_reconstruction.py", "MAX_ENVELOPE_BYTES"
        )
        native_import = constant(
            "api/routers/scientific_program_imports.py", "MAX_REQUEST_BYTES"
        )
        for key, limit in drill.LIMITS.items():
            with self.subTest(route=key):
                expected = (
                    two
                    if key in ("pilots/registrations", "pilots/participation/accept")
                    else 130 * drill.MIB
                    if key.endswith("/evidence")
                    else four
                    if key.startswith("pilots/")
                    else reconstruction
                    if key.startswith("use/")
                    else native_import
                )
                self.assertEqual(limit, expected)
                self.assertGreater(limit, 20 * drill.MIB)
        self.assertEqual(len(drill.LIMITS), 11)
        drill.source_contract(self.source, self.policy)

    def test_contract_rejects_missing_or_commented_privacy_guards(self):
        for line in self.policy.splitlines():
            if line.startswith(
                (
                    "proxy_request_buffering ",
                    "proxy_buffering ",
                    "proxy_cache ",
                    "proxy_store ",
                    "access_log ",
                    "error_log ",
                    "proxy_next_upstream ",
                    "proxy_http_version ",
                    "proxy_read_timeout ",
                )
            ):
                with self.subTest(directive=line), self.assertRaises(ValueError):
                    drill.source_contract(
                        self.source, self.policy.replace(line, "# " + line)
                    )

    def test_wrong_ceiling_or_expanded_upload_path_is_rejected(self):
        for old, new in (
            ("22435160", "22435159"),
            ("44804784", "44804783"),
            ("client_max_body_size 20m;", "client_max_body_size 130m;"),
            (
                "location = /sclib/v1/ml/use/requests {",
                "location /sclib/v1/ml/use/requests {",
            ),
            ("location ^~ /sclib/v1/ml/pilots/", "location /sclib/v1/ml/pilots/"),
        ):
            with self.subTest(change=old), self.assertRaises(ValueError):
                drill.source_contract(self.source.replace(old, new), self.policy)
        with self.assertRaises(ValueError):
            drill.source_contract(
                self.source, self.policy + "\nclient_max_body_size 130m;\n"
            )

    def test_materialization_uses_only_owned_targets_and_preserves_route_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            pin = drill.materialize(self.source, self.policy, root, 32111, 32112, 32113)
            rendered = (root / "nginx.conf").read_text()
            active = "\n".join(line.split("#", 1)[0] for line in rendered.splitlines())
            self.assertNotIn("/etc/", active)
            self.assertNotIn("127.0.0.1:8000", active)
            self.assertIn("listen 127.0.0.1:32111 ssl;", active)
            self.assertIn("listen 127.0.0.1:32112;", active)
            for route in drill.LIMITS:
                self.assertIn("location = " + drill.PREFIX + route, active)
            self.assertIn("client_max_body_size 20m;", active)
            self.assertIn("daemon off; master_process off;", active)
            self.assertEqual(pin, drill.sha(rendered.encode()))
            self.assertEqual((root / "private-intake.conf").read_text(), self.policy)

    def test_observer_detects_an_open_unlinked_owned_body_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "client_temp").mkdir()
            (root / "proxy_temp").mkdir()
            path = root / "client_temp" / "synthetic"
            with path.open("wb") as handle:
                handle.write(b"SYNTHETIC observer control")
                handle.flush()
                path.unlink()
                self.assertFalse(drill.body_files(root))
                self.assertTrue(drill.body_files(root, os.getpid()))
            self.assertFalse(drill.body_files(root, os.getpid()))

    def test_drifted_deployment_include_fails_before_configuration_use(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            drill.materialize(
                self.source.replace("ssl_dhparam", "changed_directive"),
                self.policy,
                Path(temp).resolve(),
                32111,
                32112,
                32113,
            )

    def test_explicit_child_proxy_handler_is_required(self):
        for route in drill.LIMITS:
            with self.subTest(route=route), self.assertRaises(ValueError):
                line = "proxy_pass http://127.0.0.1:8000/v1/ml/" + route + ";"
                drill.source_contract(
                    self.source.replace(line, "# " + line), self.policy
                )

    def test_non_owned_materialization_targets_are_refused(self):
        for ports in (
            (443, 32112, 32113),
            (32111, 32112, 8000),
            (32111, 32111, 32113),
            (32111, 32112, "evil.invalid"),
        ):
            with (
                tempfile.TemporaryDirectory() as temp,
                self.subTest(ports=ports),
                self.assertRaises(ValueError),
            ):
                drill.materialize(
                    self.source, self.policy, Path(temp).resolve(), *ports
                )

    def test_unexpected_config_targets_are_refused_before_starting_nginx(self):
        for addition in (
            "\nserver { listen 9999; }",
            "\ninclude /tmp/unowned.conf;",
            "\nserver { location / { proxy_pass https://example.invalid/; } }",
        ):
            with (
                tempfile.TemporaryDirectory() as temp,
                self.subTest(addition=addition),
                self.assertRaises(ValueError),
            ):
                drill.materialize(
                    self.source + addition,
                    self.policy,
                    Path(temp).resolve(),
                    32111,
                    32112,
                    32113,
                )

    def test_bootstrap_and_ci_keep_the_new_policy_and_actual_rehearsal_together(self):
        bootstrap = (ROOT / "scripts/setup_vps2.sh").read_text()
        self.assertIn(
            "install -m 0644 nginx/private-intake.conf /etc/nginx/snippets/sclib-private-intake.conf",
            bootstrap,
        )
        self.assertLess(
            bootstrap.index("install -m 0644 nginx/private-intake.conf"),
            bootstrap.index("cp nginx/sclib.conf"),
        )
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for required in (
            "nginx-1.30.4.tar.gz",
            "4261dc90e9e47c1c4041276e9aaa3d48ebe2e664f728e14fa95ae6c67d57a08b",
            "sha256sum --check",
            "--no-same-owner",
            "python nginx/rehearse_private_intake.py",
            "private-ingress-rehearsal-attempt-${{ github.run_attempt }}",
        ):
            self.assertIn(required, workflow)

    def test_deployment_guide_preserves_migration_only_ordering(self):
        guide = (ROOT / "docs/DEPLOYMENT.md").read_text()
        self.assertNotIn("docker compose exec api alembic", guide)
        self.assertLess(
            guide.index("test -s /etc/sclib/credentials/migration-database-url"),
            guide.index('"${compose[@]}" run --rm --no-deps migration'),
        )
        self.assertIn(
            '"${compose[@]}" run --rm --no-deps migration &&\n'
            '   "${compose[@]}" run --rm --no-deps api '
            "python -m services.schema_lifecycle check &&\n"
            '   "${compose[@]}" up -d --no-build --wait --wait-timeout 180',
            guide,
        )


if __name__ == "__main__":
    unittest.main()
