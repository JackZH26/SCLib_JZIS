"""Explicit private coordinator; public selected_reader refuses this type."""
import asyncio
from types import MappingProxyType

from services.content_retrieval import ContentRetriever,ContentRetrievalUnavailable
from services.pgvector_query import QueryBudget
from services.retrieval_candidate import EngineeringCandidatePin,load_candidate
from models.retrieval_policy_v4 import POLICY_SHA256
from services.embedding_contract import validate_vector


class CandidateRetriever(ContentRetriever):
    def __init__(self,session_factory,transport,*,build_id,validation_id,expected_database='sclib_restore_drill',replay_vectors=None):
        super().__init__(session_factory,transport)
        self._build_id=build_id
        self._validation_id=validation_id
        self._expected_database=expected_database
        if replay_vectors is not None and (type(replay_vectors) is not dict or not 1<=len(replay_vectors)<=1000
                or any(type(query) is not str or not 2<=len(query)<=2000 for query in replay_vectors)):
            raise ContentRetrievalUnavailable('A bounded exact embedding replay inventory is required')
        self._replay=None if replay_vectors is None else MappingProxyType({
            query:tuple(validate_vector(vector)) for query,vector in replay_vectors.items()})

    @property
    def query_embedding_mode(self):return 'live_provider' if self._replay is None else 'frozen_replay_excludes_provider_latency'

    async def _semantic(self,pin,query,*,top_k,year_min,year_max):
        if self._replay is None:
            return await super()._semantic(pin,query,top_k=top_k,year_min=year_min,year_max=year_max)
        if query not in self._replay:raise ContentRetrievalUnavailable('Query absent from exact frozen replay inventory')
        return await self._transport.query(pin.projection,self._replay[query],top_k=top_k,year_min=year_min,year_max=year_max)

    def _pin(self,pin):
        if (type(pin) is not EngineeringCandidatePin or pin.build_id!=self._build_id
                or pin.validation_id!=self._validation_id or pin.database_name!=self._expected_database
                or pin.policy_artifact_sha256!=POLICY_SHA256 or self._transport.budget!=QueryBudget()):
            raise ContentRetrievalUnavailable('An exact non-serving engineering candidate is required')

    async def pin(self,*,logical_index='sclib-main'):
        async def resolve(db):
            pin=await load_candidate(db,build_id=self._build_id,validation_id=self._validation_id,
                expected_database=self._expected_database)
            self._pin(pin)
            if pin.logical_index!=logical_index:raise ContentRetrievalUnavailable('Candidate logical index mismatch')
            return pin
        async with asyncio.timeout(3):return await self._read(resolve)
