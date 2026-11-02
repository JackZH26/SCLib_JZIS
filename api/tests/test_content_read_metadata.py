"""Explicit public v2 identity; retained v1 serialization stays unchanged."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from models.index_generations_v1 import PROFILE
from models.index_read import (
    ContentReadMetadata, IndexReadMetadata, RetrievalReadMetadata,
    generation_read_metadata, retrieval_read_metadata,
)
from models.retrieval_backend_v2 import POLICY_SHA256
from services.retrieval_activation import RetrievalPinV2


def private_pin():
    return RetrievalPinV2('sclib-main', str(uuid4()), str(uuid4()), str(uuid4()),
        'a' * 64, POLICY_SHA256, json.dumps(PROFILE, sort_keys=True, separators=(',', ':')))


def test_v2_explicit_content_and_build_without_fake_generation_or_private_details():
    pin = private_pin()
    public = retrieval_read_metadata(pin)
    assert type(public) is ContentReadMetadata
    assert public.content_id == pin.content_id and public.build_id == pin.build_id
    body = public.model_dump(mode='json')
    assert body['version'] == 'index-read/2.0.0' and body['profile'] == PROFILE
    assert not {'generation_id', 'resource', 'logical_index', 'image_digest', 'scientific_acceptance'} & body.keys()
    assert TypeAdapter(RetrievalReadMetadata).validate_python(body, strict=True) == public


def test_v1_formatter_and_legacy_bytes_stay_unchanged():
    pin = {'generation_id': str(uuid4()), 'activation_event_id': str(uuid4()),
        'manifest_sha256': 'a' * 64, 'resource': {'private': 'never exposed'}}
    for value in (None, pin):
        before = generation_read_metadata(value)
        after = retrieval_read_metadata(value)
        assert type(after) is IndexReadMetadata and before.model_dump_json() == after.model_dump_json()
        assert TypeAdapter(RetrievalReadMetadata).validate_python(after.model_dump(), strict=True) == before


@pytest.mark.parametrize('change', [
    {'generation_id': str(uuid4())}, {'resource': {}}, {'permission_granted': True},
    {'scientific_acceptance': True}, {'mode': 'generation_snapshot'}, {'version': 'index-read/1.0.0'},
    {'content_id': None}, {'build_id': 'NOT-A-UUID'}, {'activation_event_id': 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'},
    {'manifest_sha256': 'A' * 64}, {'policy_artifact_sha256': None}, {'profile': {}},
])
def test_mixed_missing_or_authority_bearing_public_v2_fields_are_rejected(change):
    body = retrieval_read_metadata(private_pin()).model_dump(mode='json')
    with pytest.raises(ValidationError):
        TypeAdapter(RetrievalReadMetadata).validate_python(body | change, strict=True)


@pytest.mark.parametrize('key,value', [('model', 'other-768-model'), ('query_task', 'RETRIEVAL_DOCUMENT'),
    ('document_task', 'RETRIEVAL_QUERY'), ('output_dimensionality', 1536),
    ('output_dimensionality', 768.0), ('provider', 'other-provider')])
def test_equal_dimension_does_not_permit_another_embedding_space(key, value):
    body = retrieval_read_metadata(private_pin()).model_dump(mode='json')
    body['profile'] = deepcopy(body['profile']) | {key: value}
    with pytest.raises(ValidationError):
        ContentReadMetadata.model_validate(body, strict=True)


def test_formatter_rejects_a_public_or_caller_mapping_as_internal_v2_authority():
    with pytest.raises(ValueError, match='database-resolved'):
        retrieval_read_metadata(private_pin().metadata())
