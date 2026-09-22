"""Retrieval identity is closed and cannot masquerade as scientific approval."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from models.index_read import IndexReadMetadata, generation_read_metadata


def test_legacy_has_no_invented_generation_and_empty_pins_are_not_legacy():
    assert generation_read_metadata().model_dump() == {
        "version": "index-read/1.0.0", "mode": "legacy_lexical_only",
        "generation_id": None, "activation_event_id": None, "manifest_sha256": None,
    }
    with pytest.raises(KeyError):
        generation_read_metadata({})


def test_public_pin_discards_private_resource_and_retains_exact_generation():
    pin = {"generation_id": str(uuid4()), "activation_event_id": str(uuid4()),
           "manifest_sha256": "a" * 64, "resource": {"project": "private-project"}}
    value = generation_read_metadata(pin).model_dump()
    assert value["mode"] == "generation_snapshot"
    assert value["generation_id"] == pin["generation_id"]
    assert value["activation_event_id"] == pin["activation_event_id"]
    assert "private-project" not in str(value) and "resource" not in value


@pytest.mark.parametrize("change", [
    {"generation_id": None}, {"activation_event_id": None}, {"manifest_sha256": None},
    {"generation_id": "not-a-uuid"}, {"manifest_sha256": "A" * 64},
    {"mode": "legacy_lexical_only"}, {"scientific_acceptance": True},
    {"permission_granted": True}, {"mode": "verified"}, {"generation_id": True},
])
def test_missing_malformed_or_authority_bearing_fields_are_rejected(change):
    value = {"mode": "generation_snapshot", "generation_id": str(uuid4()),
             "activation_event_id": str(uuid4()), "manifest_sha256": "b" * 64}
    with pytest.raises(ValidationError):
        IndexReadMetadata(**(value | change))
