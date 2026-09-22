"""Real streaming children with synthetic evidence; never scientific acceptance."""

from __future__ import annotations

import asyncio
import io
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from services import ml_pilot_canary as canary
from services import ml_pilot_documents as documents
from services import ml_pilot_evidence_worker as worker

from scripts.tests.test_ml_pilot_documents import inputs
from scripts.tests.test_ml_pilot_review_documents import revised


def frame(meta, originals, contexts):
    raw = documents.canonical(meta)
    return (
        worker.MAGIC
        + f"{len(raw):08x}\n".encode()
        + raw
        + b"".join(
            originals[row["key"]] if i < 5 else contexts[row["sha256"]]
            for i, row in enumerate(meta["files"])
        )
    )


def assemble(args, params, contexts):
    """Explicit synthetic bundle/conclusion construction, never production resealing."""
    rows = documents.review_records(args["reviews_raw"])
    selected = documents.json_value(args["selection_raw"])
    bundle = canary.compile_canary(
        selected,
        rows,
        selection_sha256=args["selection_sha256"],
        review_log_sha256=args["review_log_sha256"],
        input_pins={
            k + "_file_sha256": args[k + "_file_sha256"]
            for k in ("selection", "reviews", "protocol")
        },
        source=canary.implementation(),
        evidence=[
            {"sha256": pin, "size_bytes": len(contexts[pin])}
            for pin in sorted(contexts)
        ],
    )
    originals = {name: args[name + "_raw"] for name in worker.ORIGINALS[:4]}
    originals["canary"] = canary.canonical(bundle)
    conclusion = documents.json_value(originals["conclusion"])
    conclusion["canary_bundle_sha256"] = canary.sha(originals["canary"])
    originals["conclusion"] = documents.canonical(conclusion)
    meta = {
        "version": worker.VERSION,
        "parameters": params,
        "selection_sha256": args["selection_sha256"],
        "review_log_sha256": args["review_log_sha256"],
        "files": [
            {
                "key": name,
                "sha256": canary.sha(originals[name]),
                "size_bytes": len(originals[name]),
            }
            for name in worker.ORIGINALS
        ]
        + [
            {"key": pin + ".bin", "sha256": pin, "size_bytes": len(raw)}
            for pin, raw in sorted(contexts.items())
        ],
    }
    return meta, originals, contexts


def fixture(*, size=55, superseded=False, empty=False):
    args = inputs()
    raw = b"SYNTHETIC ONLY: no genuine scientific source.\n".ljust(size, b"x")
    contexts = {} if empty else {canary.sha(raw): raw}
    rows = documents.review_records(args["reviews_raw"])
    for row in rows:
        if empty:
            row.update(outcome="inaccessible", results=[])
        else:
            for result in row["results"]:
                result["source"]["context_sha256"] = canary.sha(raw)
    if superseded:
        old = rows[3]
        amendment = deepcopy(old)
        amendment.update(
            review_id="SYNTHETIC-amendment",
            revision=2,
            supersedes_review_id=old["review_id"],
        )
        replacement = b"SYNTHETIC replacement context, not evidence."
        contexts[canary.sha(replacement)] = replacement
        amendment["results"][0]["source"]["context_sha256"] = canary.sha(replacement)
        rows.append(amendment)
    revised(args, rows)
    return assemble(
        args,
        {
            "participant_id": str(uuid4()),
            "participant_sha256": "a" * 64,
            "registration_sha256": "b" * 64,
        },
        contexts,
    )


async def chunks(raw, step=32749):
    for offset in range(0, len(raw), step):
        yield raw[offset : offset + step]


@pytest.mark.parametrize("empty", [False, True])
def test_actual_child_replays_exact_canary_without_source_text_or_authority(empty):
    value = fixture(empty=empty)
    raw = frame(*value)
    expected = worker.checked(worker.prepare(io.BytesIO(raw)))
    actual = asyncio.run(worker.check_in_worker(chunks(raw)))
    assert actual == expected and actual["input_sha256"] == canary.sha(raw)
    proof = actual["canary_check"]
    assert proof["context_file_count"] == (0 if empty else 1)
    assert proof["context_bytes_checked"] and proof["canary_replay_verified"]
    assert not proof["context_bytes_embedded"]
    assert b"SYNTHETIC" not in documents.canonical(actual)


def test_actual_eight_mib_context_is_streamed_in_small_reads():
    value = fixture(size=canary.MAX_CONTEXT_BYTES)
    raw = frame(*value)

    class SmallReads(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= worker.BLOCK
            return super().read(min(size, 997))

    expected = worker.prepare(SmallReads(raw))
    actual = asyncio.run(worker.check_in_worker(chunks(raw)))
    assert actual == expected
    assert actual["canary_check"]["context_bytes_hashed"] == canary.MAX_CONTEXT_BYTES


def test_all_superseded_contexts_remain_required():
    meta, originals, contexts = fixture(superseded=True)
    raw = frame(meta, originals, contexts)
    checked = worker.prepare(io.BytesIO(raw))
    assert checked["canary_check"]["context_file_count"] == 2
    meta["files"].pop()
    with pytest.raises(ValueError, match="inventory_mismatch"):
        worker.prepare(io.BytesIO(frame(meta, originals, contexts)))


def test_actual_full_64_mib_inventory_is_streamed_without_silent_truncation():
    args = inputs()
    contexts = {}
    for i in range(8):
        raw = (f"SYNTHETIC CONTEXT {i}; no scientific evidence.\n".encode()).ljust(
            canary.MAX_CONTEXT_BYTES, b"x"
        )
        contexts[canary.sha(raw)] = raw
    pins = sorted(contexts)
    rows = documents.review_records(args["reviews_raw"])
    candidate_pins = {
        cid: pins[i % 8]
        for i, cid in enumerate(dict.fromkeys(row["candidate_id"] for row in rows))
    }
    for row in rows:
        for result in row["results"]:
            result["source"]["context_sha256"] = candidate_pins[row["candidate_id"]]
    revised(args, rows)
    values = assemble(
        args,
        {
            "participant_id": str(uuid4()),
            "participant_sha256": "a" * 64,
            "registration_sha256": "b" * 64,
        },
        contexts,
    )
    raw = frame(*values)
    result = asyncio.run(worker.check_in_worker(chunks(raw)))
    assert result["canary_check"]["context_file_count"] == 8
    assert result["canary_check"]["context_bytes_hashed"] == canary.MAX_EVIDENCE_BYTES
    # The ninth declared leaf exceeds the combined bound before any leaf is read.
    metadata = values[0]
    pin = "f" * 64
    metadata["files"].append({"key": pin + ".bin", "sha256": pin, "size_bytes": 1})
    metadata["files"][5:] = sorted(metadata["files"][5:], key=lambda row: row["sha256"])
    with pytest.raises(ValueError):
        worker.metadata(documents.canonical(metadata))


def test_evidence_ceiling_and_inherited_private_transport_remain_scoped():
    root = Path(__file__).resolve().parents[2]
    source = (root / "nginx/sclib.conf").read_text()
    policy = (root / "nginx/private-intake.conf").read_text()
    path = "/sclib/v1/ml/pilots/review-attestations/evidence"
    location = source.split("location = " + path + " {", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 130m;" in location
    assert "limit_req zone=sclib_evidence burst=2 nodelay;" in location
    for directive in (
        "proxy_request_buffering off;",
        "proxy_buffering off;",
        "proxy_max_temp_file_size 0;",
        "proxy_http_version 1.1;",
        "access_log off;",
    ):
        assert directive in policy
    parent = source.split("location ^~ /sclib/v1/ml/pilots/ {", 1)[1].split(
        "location ^~ /sclib/v1/ml/use/", 1
    )[0]
    assert "include /etc/nginx/snippets/sclib-private-intake.conf;" in parent
    assert "proxy_pass http://127.0.0.1:8000/v1/ml/pilots/;" in parent
    assert (
        source.count("client_max_body_size 130m;") == 1
        and "client_max_body_size 20m;" in source
    )


@pytest.mark.parametrize(
    "case",
    [
        "magic",
        "length",
        "metadata",
        "truncated",
        "trailing",
        "context",
        "original",
        "canary",
        "legacy",
        "conclusion",
        "duplicate",
        "unlisted",
        "reference",
        "boolean_size",
        "context_limit",
    ],
)
def test_closed_frame_refuses_corrupt_or_unbound_inputs(case):
    meta, originals, contexts = fixture()
    if case == "metadata":
        meta["document_check"] = {}
    if case == "context":
        pin = next(iter(contexts))
        contexts[pin] = b"!" + contexts[pin][1:]
    if case == "original":
        originals["protocol"] = b"!" + originals["protocol"][1:]
    if case in {"canary", "legacy"}:
        bundle = canary.loads(originals["canary"])
        if case == "legacy":
            bundle["version"] = "ml08-canary/1.1.0"
        else:
            bundle["accounting"]["scientific_acceptance"] = True
        originals["canary"] = canary.canonical(bundle)
        meta["files"][4].update(
            sha256=canary.sha(originals["canary"]), size_bytes=len(originals["canary"])
        )
        conclusion = documents.json_value(originals["conclusion"])
        conclusion["canary_bundle_sha256"] = canary.sha(originals["canary"])
        originals["conclusion"] = documents.canonical(conclusion)
        meta["files"][3].update(
            sha256=canary.sha(originals["conclusion"]),
            size_bytes=len(originals["conclusion"]),
        )
    if case == "conclusion":
        c = documents.json_value(originals["conclusion"])
        c["canary_bundle_sha256"] = "d" * 64
        originals["conclusion"] = documents.canonical(c)
        meta["files"][3].update(
            sha256=canary.sha(originals["conclusion"]),
            size_bytes=len(originals["conclusion"]),
        )
    if case == "duplicate":
        meta["files"].append(meta["files"][-1])
    if case == "unlisted":
        extra = b"SYNTHETIC unrelated context"
        pin = canary.sha(extra)
        contexts[pin] = extra
        meta["files"].append(
            {"key": pin + ".bin", "sha256": pin, "size_bytes": len(extra)}
        )
        meta["files"][5:] = sorted(meta["files"][5:], key=lambda row: row["sha256"])
    if case == "reference":
        meta["parameters"]["participant_sha256"] = 1
    if case == "boolean_size":
        meta["files"][-1]["size_bytes"] = True
    if case == "context_limit":
        meta["files"][-1]["size_bytes"] = canary.MAX_CONTEXT_BYTES + 1
    raw = frame(meta, originals, contexts)
    if case == "magic":
        raw = b"!" + raw[1:]
    if case == "length":
        raw = worker.MAGIC + b"FFFFFFFF\n" + raw[len(worker.MAGIC) + 9 :]
    if case == "truncated":
        raw = raw[:-1]
    if case == "trailing":
        raw += b"!"
    with pytest.raises(ValueError):
        worker.prepare(io.BytesIO(raw))


@pytest.mark.parametrize(
    "case", ["proof", "parameter", "inventory", "bool_count", "size", "version"]
)
def test_parent_rechecks_closed_worker_output(case):
    value = worker.prepare(io.BytesIO(frame(*fixture())))
    if case == "proof":
        value["canary_check"]["context_bytes_checked"] = False
    if case == "parameter":
        value["parameters"]["grant"] = "forbidden"
    if case == "inventory":
        value["evidence_implementation"]["worker_sha256"] = "e" * 64
    if case == "bool_count":
        value["canary_check"]["context_file_count"] = True
    if case == "size":
        value["canary_check"]["context_bytes_hashed"] = 0
    if case == "version":
        value["canary_check"]["canary_version"] = "old"
    with pytest.raises(ValueError):
        worker.checked(value)


@pytest.mark.parametrize("mode", ["cancel", "timeout", "limit", "malformed", "output"])
def test_owned_child_is_reaped_on_interruption_or_bad_transport(monkeypatch, mode):
    create = asyncio.create_subprocess_exec
    processes = []

    async def scenario():
        spawned = asyncio.Event()

        async def observed(*args, **kwargs):
            if mode in {"cancel", "timeout"}:
                args = (*args[:-1], "import time;time.sleep(30)")
            elif mode == "output":
                args = (
                    *args[:-1],
                    f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'x'*{worker.MAX_OUTPUT_BYTES + 1});sys.stdout.flush()",
                )
            process = await create(*args, **kwargs)
            processes.append(process)
            spawned.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observed)
        if mode == "timeout":
            monkeypatch.setattr(worker, "WALL_SECONDS", 0.2)
        if mode == "limit":
            monkeypatch.setattr(worker, "MAX_CHUNKS", 1)
        raw = b"malformed" if mode == "malformed" else frame(*fixture())
        task = asyncio.create_task(worker.check_in_worker(chunks(raw)))
        await spawned.wait()
        if mode == "cancel":
            task.cancel()
        error = {
            "cancel": asyncio.CancelledError,
            "timeout": TimeoutError,
            "limit": worker.EvidenceLimitError,
            "malformed": ValueError,
            "output": ValueError,
        }[mode]
        with pytest.raises(error):
            await task
        assert len(processes) == 1 and processes[0].returncode is not None

    asyncio.run(scenario())
