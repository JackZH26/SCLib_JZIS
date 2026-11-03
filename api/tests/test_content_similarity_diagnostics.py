"""Failure diagnostics preserve bounded responses and do not expose payloads."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import content_similarity as service
from services.request_context import bind_request_id, reset_request_id


@pytest.mark.asyncio
async def test_timeout_records_stage_and_suppressed_cause_without_sensitive_text(caplog):
    secret='postgresql://private-user:private-password@private-host/private-database'
    cause=asyncio.CancelledError(secret)
    failure=TimeoutError(secret)
    failure.__context__=cause
    reader=SimpleNamespace(_pin=lambda pin:None,_readiness=SimpleNamespace(ready=AsyncMock(return_value=True)),
                           _read=AsyncMock(side_effect=failure))
    token=bind_request_id('diagnostic-test-request')
    try:
        with caplog.at_level(logging.WARNING,logger=service.log.name):
            with pytest.raises(service.ContentSimilarityUnavailable,match='Complete content-pinned similarity unavailable'):
                await service.similar(reader,object(),'private-paper-input',top_k=10)
    finally:
        reset_request_id(token)
    record=next(record for record in caplog.records if record.name==service.log.name)
    assert 'stage=source' in record.getMessage()
    assert 'error_types=TimeoutError,CancelledError' in record.getMessage()
    assert 'request_id=diagnostic-test-request' in record.getMessage()
    assert 'private-' not in record.getMessage()
    assert record.exc_info is None


@pytest.mark.asyncio
async def test_not_ready_is_distinguished_from_query_failure(caplog):
    reader=SimpleNamespace(_pin=lambda pin:None,_readiness=SimpleNamespace(ready=AsyncMock(return_value=False)),
                           _read=AsyncMock())
    with caplog.at_level(logging.WARNING,logger=service.log.name):
        with pytest.raises(service.ContentSimilarityUnavailable):
            await service.similar(reader,object(),'source',top_k=10)
    assert 'stage=readiness' in caplog.text
    assert 'error_types=ContentSimilarityUnavailable' in caplog.text
    reader._read.assert_not_awaited()


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_converted_to_an_availability_error(caplog):
    reader=SimpleNamespace(_pin=lambda pin:None,_readiness=SimpleNamespace(ready=AsyncMock(side_effect=asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError):
        await service.similar(reader,object(),'source',top_k=10)
    assert not [record for record in caplog.records if record.name==service.log.name]
