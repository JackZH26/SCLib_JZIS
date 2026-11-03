"""Query embedding only; no Matching Engine resource, ANN or document upload."""
from __future__ import annotations

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor

from google.genai import types

from config import get_settings
from models.index_read import RetrievalEmbeddingProfile
from services.embedding_contract import (
    DIMENSION, LOCAL_QUERY_COUNT_METHOD, LOCAL_QUERY_INPUT_LIMIT,
    LOCAL_QUERY_REQUEST_LIMIT, validate_embedding_inputs, validate_embedding_response,
)
from services.genai_client import embedding_client


class QueryEmbeddingUnavailable(ValueError):
    """Static messages only: provider failures may contain input or secrets."""


class QueryEmbeddingWorkers:
    """Bound both active SDK calls and pending submissions across cancellations.

    Cancellation cannot kill a synchronous SDK call. Its permit stays held
    until the actual worker completes, rather than admitting another call.
    """
    def __init__(self,workers=4):
        if type(workers) is not int or not 1<=workers<=4:raise ValueError('Bounded worker inventory required')
        self._executor=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='sclib-query-embedding')
        self._slots=asyncio.Semaphore(workers)
        self._pending=set()
        self._closed=False

    async def run(self,operation):
        await self._slots.acquire()
        try:
            if self._closed:raise QueryEmbeddingUnavailable('Query embedding workers closed')
            future=asyncio.get_running_loop().run_in_executor(self._executor,operation)
        except BaseException:
            self._slots.release();raise
        self._pending.add(future)
        def completed(future):
            self._pending.discard(future)
            self._slots.release()
            if not future.cancelled():future.exception() # Retrieve failures even after caller cancellation.
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    async def close(self):
        self._closed=True
        self._executor.shutdown(wait=False,cancel_futures=True)
        if self._pending:
            # No new work can enter. SDK deadlines remain in force, and an
            # abnormal provider cannot block service teardown indefinitely.
            await asyncio.wait(tuple(self._pending),timeout=6)


def embed_query(profile, query, *, timeout_seconds=5.0):
    """Preserve 005 RETRIEVAL_QUERY and explicit no-truncation statistics.

    The caller owns async scheduling/circuit/deadline control. The SDK itself
    receives a bounded timeout and one attempt, including after task cancellation.
    No endpoint/deployed-index setting is read or verified by this transport.
    """
    try:
        checked=RetrievalEmbeddingProfile.model_validate(profile,strict=True)
        settings=get_settings()
        if (settings.embedding_model!=checked.model
                or type(settings.embedding_output_dimensionality) is not int
                or settings.embedding_output_dimensionality!=DIMENSION
                or type(timeout_seconds) not in {int,float} or not math.isfinite(timeout_seconds)
                or not .001<=timeout_seconds<=5):
            raise ValueError
        arguments={'model':checked.model,'dimension':DIMENSION,'task_type':checked.query_task,
            'local_counts':[len(query.encode('utf-8')) if type(query) is str else 0],
            'local_count_method':LOCAL_QUERY_COUNT_METHOD,'local_input_limit':LOCAL_QUERY_INPUT_LIMIT,
            'local_request_limit':LOCAL_QUERY_REQUEST_LIMIT}
        validate_embedding_inputs([query],**arguments)
        config=types.EmbedContentConfig(task_type=checked.query_task,output_dimensionality=DIMENSION,
            auto_truncate=False,http_options=types.HttpOptions(timeout=max(1,int(timeout_seconds*1000)),
                retry_options=types.HttpRetryOptions(attempts=1)))
        if getattr(config,'auto_truncate',None) is not False:raise ValueError
        # Concurrent cold cache misses can return an uncached SDK client.
        # Keep its owner alive until the model call and validation complete.
        client=embedding_client()
        response=client.models.embed_content(model=checked.model,contents=[query],config=config)
        return validate_embedding_response([query],response,**arguments)[0][0]
    except Exception:
        raise QueryEmbeddingUnavailable('Query embedding unavailable or incompatible') from None
