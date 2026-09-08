"""Explicit, bounded operator workflow; no outer commit or implicit cloud I/O."""
from __future__ import annotations

import asyncio
import time

from models.index_read import generation_read_metadata
from services import index_generations as generations
from services import index_vector_adapter as vectors


async def run_operation(db, request, *, apply=False, read_remote=False):
    """Caller owns commit. Default invocations only inspect/preview SQL state.

    ``publish + apply`` explicitly authorizes remote upserts, not SQL activation.
    ``observe + read_remote`` authorizes billed remote reads; ``apply`` separately
    retains their validation. No source text, embedding bytes or credentials leave
    this function's response. Duration is local wall time, not cost or recall.
    """
    started = time.monotonic()
    if type(apply) is not bool or type(read_remote) is not bool or type(request) is not dict:
        raise ValueError("Exact operator flags and request fields are required")
    command = request.get("command")
    fields = {
        "inspect": {"command", "generation_id"},
        "stage": {"command", "generation_id", "logical_index", "resource", "items"},
        "publish": {"command", "generation_id"},
        "observe": {"command", "generation_id"},
        "activate": {"command", "generation_id", "validation_id", "expected_event_id", "idempotency_key", "action"},
    }
    if type(command) is not str or command not in fields or set(request) != fields[command]:
        raise ValueError("Exact operator request fields are required")
    if read_remote and command != "observe" or command == "inspect" and apply:
        raise ValueError("Operator flags do not match the requested operation")
    if command == "observe" and apply and not read_remote:
        raise ValueError("Validation requires an explicitly requested fresh remote observation")
    if db.new or db.dirty or db.deleted:
        raise ValueError("Operator requires a clean caller-owned session")
    result = {"command": command, "dry_run": not apply, "committed": False,
              "provider_io_performed": False, "estimated_cost": None,
              "full_corpus_coverage_verified": False}
    if command == "stage":
        staged = await generations.stage_generation(db, **{k: v for k, v in request.items() if k != "command"}, dry_run=not apply)
        result.update(generation_id=staged["generation_id"], manifest_sha256=staged["manifest_sha256"],
                      member_count=staged["member_count"])
    else:
        pin = await generations.load_generation(db, generation_id=request["generation_id"])
        if pin is None:
            raise ValueError("Requested generation is unavailable")
        members = await generations.load_generation_members(db, generation_id=pin["generation_id"])
        # Every operator command rejects partial/invalid declared inventory before
        # any network call, including a preview of publication or reconciliation.
        if generations.manifest_sha256(members) != pin["manifest_sha256"]:
            raise ValueError("Declared generation inventory is incomplete")
        if command != "inspect":
            vectors.preview(pin, members)
        result.update(generation_id=pin["generation_id"], manifest_sha256=pin["manifest_sha256"], member_count=len(members))
        if command == "inspect":
            status = await generations.inspect_generation(db, generation_id=pin["generation_id"])
            result.update(logical_index=status["logical_index"], is_current=status["is_current"],
                current_active_generation=generation_read_metadata(status["current_active_pin"]).model_dump())
        elif command == "publish" and apply:
            result["publication"] = await asyncio.to_thread(vectors.publish, pin, members)
            result["provider_io_performed"] = pin["resource"]["backend"] != "disposable"
        elif command == "observe" and read_remote:
            observation = await asyncio.to_thread(vectors.observe, pin, members)
            result["provider_io_performed"] = pin["resource"]["backend"] != "disposable"
            result["observation_id"] = observation["observation_id"]
            result["reconciliation"] = vectors.repair_plan(pin, members, observation)
            result["validation"] = await generations.record_validation(db, generation_id=pin["generation_id"],
                observation=observation, dry_run=not apply)
        elif command == "activate":
            before = await generations.inspect_generation(db, generation_id=pin["generation_id"])
            activated = await generations.activate_generation(db,
                **{k: v for k, v in request.items() if k != "command"}, dry_run=not apply)
            after = await generations.inspect_generation(db, generation_id=pin["generation_id"])
            # Exact replay can return an older receipt after another activation.
            # Never label that receipt as the currently serving generation.
            result["activation_receipt"] = generation_read_metadata(activated).model_dump()
            result["current_active_generation"] = generation_read_metadata(after["current_active_pin"]).model_dump()
            result["active_generation_changed"] = before["current_active_pin"] != after["current_active_pin"]
            result["receipt_is_current"] = (after["current_active_pin"] is not None
                and after["current_active_pin"]["activation_event_id"] == activated["activation_event_id"])
        elif command in {"publish", "observe"}:
            result["remote_operation_planned"] = True
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result
