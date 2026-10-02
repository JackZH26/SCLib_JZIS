"""Actual native DTO shapes for independent frontend parity; all data is synthetic."""
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from services import material_field_review as review
from services.research_release_manifest import digest
from tests.test_material_field_review import fixture, sibling
from tests.test_research_freeze import db_session as _owned_db_session

db_session = _owned_db_session


@pytest.mark.asyncio
@pytest.mark.parametrize("field,kind", [
    ("tc_criterion", "condition"), ("measurement_method", "condition"),
    ("pressure_gpa", "condition"), ("measurement_method", "value"),
])
async def test_native_review_dtos_keep_component_specific_author_pins_and_exact_receipts(db_session, field, kind):
    curator, reviewer, _, _, _, target, _, expression_id, index = await fixture(
        db_session, field, extra_kind="method" if kind == "value" else None)
    companion = expression_id if kind == "value" else None
    if kind == "value":
        expression_id = await sibling(db_session, expression_id)
    context = await review.context(db_session, actor_user_id=reviewer["id"],
        target_id=target["target_id"], field_id=field, expression_revision_id=expression_id,
        component_kind=kind, component_index=index, tc_expression_revision_id=companion)
    assert context["subject"]["eligible"]
    assert context["subject"]["target_user_id"] == str(curator["id"])
    assert context["subject"]["association_user_id"] is None
    assert context["subject"]["tc_importer_user_id"] == (str(curator["id"]) if companion else None)
    assert digest(json.loads(context["subject_canonical_json"])) == context["subject_sha256"]
    cap = await review.capabilities(db_session, actor_user_id=reviewer["id"])
    initial = await review.effective(db_session, actor_user_id=reviewer["id"],
        target_id=target["target_id"], field_id=field)
    item = deepcopy(context["item_template"])
    item.update(decision="accept", source_inspection_attested=True,
        checks={k: "satisfied" for k in review.contract.CHECKS},
        rationale="Synthetic native byte-contract proof: exact field and retained result window inspected.")
    request = {"version": review.contract.VERSION, "profile_version": review.contract.PROFILE,
        "request_key": "synthetic:wire-review:"+uuid4().hex, "items": [item]}
    preview = await review.operate(db_session, actor_user_id=reviewer["id"], request=request)
    saved = await review.operate(db_session, actor_user_id=reviewer["id"], request=request,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    accepted = await review.effective(db_session, actor_user_id=reviewer["id"],
        target_id=target["target_id"], field_id=field)
    assert accepted["field_fidelity_accepted"] and not accepted["scientific_acceptance"]
    assert saved["receipt_sha256"] == preview["receipt_sha256"]
    directory = os.environ.get("SCLIB_FIELD_REVIEW_WIRE_ORACLE_DIR")
    if directory:
        output = Path(directory).resolve()
        assert output.is_dir() and output.stat().st_uid == os.getuid()
        assert output.stat().st_mode & 0o777 == 0o700
        assert str(output).startswith("/private/tmp/sclib-material-field-wire-oracle-")
        packet = {"fixture": "explicitly synthetic owned native database DTO; no scientific observation",
            "selector": {"targetId": target["target_id"], "fieldId": field, "expressionId": expression_id,
                "componentKind": kind, "componentIndex": index,
                **({"tcExpressionId": companion} if companion else {})},
            "capabilities": cap, "context": context, "initial_effective": initial,
            "request": request, "preview": preview, "saved": saved, "accepted_effective": accepted}
        path = output/(field+"-"+kind+".json")
        with path.open("x") as file:
            os.chmod(path, 0o600)
            json.dump(packet, file, ensure_ascii=False, indent=2)
            file.write("\n")
