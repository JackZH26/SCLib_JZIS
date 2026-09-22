"""Closed consent envelope and actual owned worker, with synthetic documents."""

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from services import ml_pilot_attestation_contract as contract
from services import ml_pilot_review_worker as worker
from services.ml_pilot_documents import canonical

from scripts.tests.test_ml_pilot_review_documents import envelope


def upload():
    value = envelope()
    value["version"] = worker.ATTESTATION_VERSION
    value["parameters"].update(
        request_key="synthetic-attestation",
        reason_code="synthetic_review",
        supersedes_id=None,
        supersedes_sha256=None,
        declaration_version=contract.VERSION,
        declaration_sha256=contract.SHA256,
        declaration_acknowledged=True,
        expected_intent_sha256=None,
        dry_run=True,
    )
    return value


def test_exact_english_declaration_is_hash_pinned():
    from hashlib import sha256

    assert sha256(contract.TEXT.encode()).hexdigest() == contract.SHA256
    assert "all revisions, failures and unresolved cases" in contract.TEXT
    assert "withdraw" in contract.TEXT and "source permissions" in contract.TEXT
    assert contract.VERSION == "ml08-own-review-declaration/1.0.0"
    assert not any("\u4e00" <= c <= "\u9fff" for c in contract.TEXT)


def test_actual_worker_checks_all_files_and_fixed_consent_without_importing_orm():
    raw = canonical(upload())
    result = asyncio.run(worker.check_in_worker(raw, attestation=True))
    assert result == worker.prepare(raw, attestation=True)
    assert result["document_check"]["selected_candidates"] == 60
    assert result["parameters"]["declaration_sha256"] == contract.SHA256
    assert "ml_pilot_attestation_contract.py" in result["implementation"]["files"]
    source = Path(worker.__file__).read_text()
    assert "from models" not in source and "from config" not in source


@pytest.mark.parametrize(
    "kind",
    [
        "old_route",
        "new_route",
        "consent",
        "declaration_hash",
        "declaration_version",
        "actor",
        "key",
        "reason",
        "dry_type",
        "unpreviewed_commit",
        "predecessor",
        "expected_hash",
        "removed_file",
        "extra",
    ],
)
def test_cross_operation_and_mutated_consent_are_rejected(kind):
    value = upload()
    params = value["parameters"]
    if kind == "old_route":
        with pytest.raises(ValueError):
            worker.prepare(canonical(value))
        return
    if kind == "new_route":
        value = envelope()
    if kind == "consent":
        params["declaration_acknowledged"] = 1
    if kind == "declaration_hash":
        params["declaration_sha256"] = "0" * 64
    if kind == "declaration_version":
        params["declaration_version"] = "changed"
    if kind == "actor":
        params["actor_user_id"] = params["participant_id"]
    if kind == "key":
        params["request_key"] = "private input !"
    if kind == "reason":
        params["reason_code"] = "PRIVATE SOURCE TEXT"
    if kind == "dry_type":
        params["dry_run"] = 0
    if kind == "unpreviewed_commit":
        params["dry_run"] = False
    if kind == "predecessor":
        params["supersedes_sha256"] = "1" * 64
    if kind == "expected_hash":
        params["expected_intent_sha256"] = "x"
    if kind == "removed_file":
        del value["reviews_base64"]
    if kind == "extra":
        value["scientific_acceptance"] = True
    with pytest.raises(ValueError):
        worker.prepare(canonical(value), attestation=True)


def test_valid_commit_preserves_exact_references_in_owned_output():
    value = upload()
    previous = deepcopy(value)
    value["parameters"].update(
        dry_run=False,
        expected_intent_sha256="a" * 64,
        supersedes_id=value["parameters"]["participant_id"],
        supersedes_sha256="b" * 64,
    )
    checked = worker.prepare(canonical(value), attestation=True)
    assert checked["parameters"] == value["parameters"]
    assert (
        checked["document_check"]
        == worker.prepare(canonical(previous), attestation=True)["document_check"]
    )
    # UUID existence, account ownership and exact predecessor state are checked by SQL/HTTP, not this pure worker.
