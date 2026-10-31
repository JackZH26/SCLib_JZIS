"""Failed graphs stay quarantined; diagnostics expose only finite graph codes."""
import json

import pytest
from pydantic import BaseModel, ValidationError, model_validator

from ingestion.materials_ner.sources import save_bundle, sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one, schema_error_records
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_relations import fixture


@pytest.mark.parametrize("mutation,code", [
    ("dangling_context", "native_context_target_invalid"),
    ("self_component", "invalid_component_relation"),
])
def test_invalid_graph_retains_raw_output_and_has_actionable_failure_code(tmp_path, mutation, code):
    bundle, inventory, raw = fixture()
    if mutation == "dangling_context":
        inventory["context_assertions"].append({"id": "extra-context", "kind": "condition",
            "description": "Synthetic context only.", "span_ids": ["S1"]})
        raw["context_dispositions"].append({"context_id": "extra-context", "resolution": "carried",
            "explanation": None, "bindings": [{"entity": "condition_support", "entity_id": "absent", "field": "/relation_raw"}]})
    else:
        raw["sample_relations"][0]["from_sample_id"] = raw["sample_relations"][0]["to_sample_id"]
    store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration(workflow="inventory_v8"))
    provider = SequenceProvider([inventory, raw])
    result = run_one(store, job_id=job, provider_override=provider)
    assert result["state"] == "quarantined" and result["error_code"] == "output_schema_invalid"
    receipt_path = tmp_path / store.results()[0]["result_path"]
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["schema_errors"] == [{"location": [], "type": "value_error", "code": code}]
    retained_output = receipt_path.with_name("output.json").read_bytes()
    assert json.loads(retained_output) == raw
    assert sha(retained_output) == receipt["raw_output_sha256"]
    assert "extraction" not in receipt and provider.calls == 2
    assert not receipt["scientific_acceptance"] and not receipt["retryable"]


def test_arbitrary_validator_message_is_not_copied_into_diagnostics():
    class UntrustedMessage(BaseModel):
        text: str

        @model_validator(mode="after")
        def fail(self):
            raise ValueError(self.text)

    try:
        UntrustedMessage.model_validate({"text": "arbitrary source contents or private identifiers"})
    except ValidationError as error:
        assert schema_error_records(error) == [{"location": [], "type": "value_error"}]
    else:
        raise AssertionError("fixture should fail validation")
