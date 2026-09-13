"""Native run-workbench HTTP archive; synthetic identities/compiler, no runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from routers import ml_use_runs as router
from tests.test_ml_use_preflight import enabled as enabled
from tests.test_ml_use_runs import BASE, fixture, plan_ref, review_args, successor
from tests.test_ml_use_submissions import db_session as db_session
from tests.test_research_distribution_operators import auth


async def test_run_workbench_native_wire(client, db_session, monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    paths = sorted({*(repo / "api/models").glob("*.py"), *(repo / "api/services").glob("*.py"),
                    *(repo / "api/services").glob("*.schema.json"),
                    *(repo / "api/routers").glob("*.py"), *(repo / "api/tests").glob("*.py"),
                    *(repo / "scripts").glob("*.py"), repo / "api/main.py", repo / "api/config.py"})
    def pins():
        return [{"path": str(p.relative_to(repo)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    source = pins()
    _, compiled, _, receipt, actor, args = await fixture(db_session)
    await db_session.commit()
    capture = {"fixture_notice": "Actual guarded native SQL and HTTP; synthetic identities and explicit intake compiler double; no real approval or execution.",
        "capture_test_path": "api/tests/test_ml_use_runs_wire.py", "source_pins": source}
    owner_headers, review_headers = auth(compiled["actor_user_id"]), auth(actor["actor_user_id"])

    async def read(name, endpoint, body=None, *, reviewer=False):
        headers = review_headers if reviewer else owner_headers
        response = await (client.get(BASE + endpoint, headers=headers) if body is None
                          else client.post(BASE + endpoint, json=body, headers=headers))
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        capture[name] = response.text
        return response.json()

    await read("requester_access", "/requester-access")
    await read("approver_access", "/approver-access", reviewer=True)
    capture["submission_query"] = {key: args[key] for key in ("submission_id", "submission_sha256", "inventory_sha256")}
    await read("context", "/context", capture["submission_query"])
    request = {key: value for key, value in args.items() if key != "actor_user_id"}
    capture["plan_input"] = request
    preview = await read("plan_preview", "/plans", request)
    saved = await read("plan_committed", "/plans", {**request, "dry_run": False,
        "expected_intent_sha256": preview["result"]["intent_sha256"]})
    await read("plan_outcome", "/plans/outcome", {"request_key": request["request_key"],
        "expected_intent_sha256": preview["result"]["intent_sha256"]})
    plan = saved["result"]["plan"]
    capture["plan_query"] = plan_ref(plan)
    await read("unreviewed", "/inspect", capture["plan_query"], reviewer=True)

    async def rebuilt(_user, raw):
        return raw, {}, compiled["reconstruction"]
    monkeypatch.setattr(router.preflight, "_rebuild_bytes", rebuilt)
    await read("readiness_unreviewed", "/check", capture["plan_query"])
    original = review_args(actor, plan, receipt)
    original.pop("actor_user_id")
    head = None
    for decision in ("approve", "revoke", "deny"):
        request = original if head is None else successor(original, head, decision=decision, expires_epoch=None)
        capture[decision + "_input"] = request
        preview = await read(decision + "_preview", "/decisions", request, reviewer=True)
        committed = await read(decision + "_committed", "/decisions", {**request, "dry_run": False,
            "expected_intent_sha256": preview["result"]["intent_sha256"]}, reviewer=True)
        head = committed["result"]["decision"]
        await read(decision + "_inspection", "/inspect", capture["plan_query"], reviewer=True)
        await read(decision + "_outcome", "/decisions/outcome", {"request_key": request["request_key"],
            "expected_intent_sha256": preview["result"]["intent_sha256"]}, reviewer=True)
        readiness = await read("readiness_" + decision, "/check", capture["plan_query"])
        assert not readiness["ready_for_execution"] and not readiness["source_permission_granted"]
        assert readiness["conditional_run_approval_current"] is (decision == "approve")
        if decision == "approve":
            capture["evidence_query"] = {"decision_id": head["id"], "decision_sha256": head["record_sha256"]}
            document = await read("evidence_read", "/evidence/read", capture["evidence_query"], reviewer=True)
            assert document["text"] == request["evidence_text"] and document["decision"] == head
            await read("evidence_purge", "/evidence/purge", capture["evidence_query"], reviewer=True)
            replay = await read("evidence_purge_replay", "/evidence/purge", capture["evidence_query"], reviewer=True)
            assert replay["result"]["replayed"]
            missing = await read("evidence_missing_inspection", "/inspect", capture["plan_query"], reviewer=True)
            assert missing["recorded_approval_status"] == "evidence_unavailable"
            await read("readiness_evidence_missing", "/check", capture["plan_query"])
    assert pins() == source
    (tmp_path / "ml-runs-wire.json").write_text(json.dumps(capture, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
