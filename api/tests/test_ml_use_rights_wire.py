"""Actual native HTTP compatibility capture; synthetic inputs, not real rights."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_rights import BASE, fixture, inspect_args
from tests.test_ml_use_submissions import db_session as db_session
from tests.test_research_distribution_operators import auth


async def test_independent_rights_workbench_native_wire(client, db_session, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    paths = sorted({*(repo / "api/models").glob("*.py"), *(repo / "api/services").glob("*.py"),
                    *(repo / "api/routers").glob("*.py"), *(repo / "api/tests").glob("*.py"),
                    *(repo / "scripts").glob("*.py"), repo / "api/main.py", repo / "api/config.py"})
    def pins():
        return [{"path": str(p.relative_to(repo)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    source = pins()
    _, _, _, _, _, args = await fixture(db_session)
    await db_session.commit()
    headers, query = auth(args["actor_user_id"]), inspect_args(args)
    capture = {"fixture_notice": "Actual guarded native HTTP; synthetic intake compiler double; no real rights, legal review or training.",
               "capture_test_path": "api/tests/test_ml_use_rights_wire.py", "query": query, "source_pins": source}

    async def read(name, body=None, endpoint="/inspect"):
        response = await (client.get(BASE + endpoint, headers=headers) if body is None
                          else client.post(BASE + endpoint, json=body, headers=headers))
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        capture[name] = response.text
        return response.json()

    await read("access", endpoint="/access")
    first = await read("unreviewed", query)
    assert first["resources"][0]["resource_id"] == args["resource_id"]
    assert first["next_after"] is not None
    await read("next_page", {**query, "after": first["next_after"]})
    original = {key: value for key, value in args.items() if key != "actor_user_id"}
    original["purpose"] = "private_baseline_evaluation"
    head = None
    for kind in ("allow", "revoke", "deny"):
        request = dict(original)
        if kind != "allow":
            assert head is not None
            request.update(request_key="synthetic-wire-" + kind, decision=kind, basis_code="withdrawn",
                           expires_epoch=None, evidence_sha256=None,
                           supersedes_id=head["id"], supersedes_sha256=head["record_sha256"])
        capture[kind + "_input"] = request
        preview = await read(kind + "_preview", {**request, "dry_run": True}, "/decisions")
        assert not preview["committed"] and preview["result"]["decision"] is None
        pin = preview["result"]["intent_sha256"]
        committed = await read(kind + "_committed", {**request, "dry_run": False, "expected_intent_sha256": pin}, "/decisions")
        head = committed["result"]["decision"]
        await read(kind + "_page", query)
        outcome = await read(kind + "_outcome", {"request_key": request["request_key"], "expected_intent_sha256": pin}, "/outcome")
        assert outcome["result"]["decision"] == head and outcome["result"]["replayed"]
    assert pins() == source
    (tmp_path / "ml-rights-wire.json").write_text(json.dumps(capture, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
