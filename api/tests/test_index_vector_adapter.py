"""Generation transport contracts using actual SDK messages and offline doubles."""
from __future__ import annotations

import copy
import hashlib
import struct
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.api_core.exceptions import NotFound, ResourceExhausted
from google.cloud import aiplatform_v1 as sdk

from services import index_vector_adapter as adapter
from services.index_generations import manifest_sha256, vector_id_for


def fixture_generation(count=3, *, backend="disposable", generation=None):
    generation = str(generation or uuid4())
    resource = {"backend": backend, "project": "fixture-project", "location": "us-central1",
        "index_resource": "projects/fixture-project/locations/us-central1/indexes/123",
        "endpoint_resource": "projects/fixture-project/locations/us-central1/indexEndpoints/456",
        "deployed_index_id": "fixture", "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE"}
    members = []
    for index in range(count):
        text = f"Synthetic complete scientific text {index}"
        revision = hashlib.sha256(f"revision/{index}".encode()).hexdigest()
        raw = struct.pack(">768f", *([0.25 + index / 1024] * 768))
        members.append({"generation_id": generation, "vector_id": vector_id_for(generation, revision),
            "chunk_revision_sha256": revision, "vector_bytes": raw,
            "snapshot_json": {"text": text}, "paper_snapshot_json": {"date_submitted": "2021-01-02"},
            "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "vector_sha256": hashlib.sha256(raw).hexdigest()})
    pin = {"generation_id": generation, "activation_event_id": None, "resource": resource,
           "profile": copy.deepcopy(adapter.PROFILE), "manifest_sha256": manifest_sha256(members)}
    return pin, members


@pytest.fixture(autouse=True)
def offline_registry():
    adapter.clear_disposable()
    yield
    adapter.clear_disposable()


def test_actual_sdk_transports_share_one_refreshable_adc_identity(monkeypatch):
    import google.auth
    from google.auth.credentials import AnonymousCredentials

    credential = AnonymousCredentials()
    resolutions = []

    def resolve(**kwargs):
        resolutions.append(kwargs)
        return credential, "fixture-project"

    adapter._public_credentials.cache_clear()
    monkeypatch.setattr(google.auth, "default", resolve)
    clients = []
    try:
        clients.extend(adapter._public_clients({"location": "us-central1"}))
        clients.append(adapter._public_match_client("fixture.us-central1-456.vdb.vertexai.goog"))
        assert resolutions == [{"scopes": ["https://www.googleapis.com/auth/cloud-platform"]}]
        # Real SDK transports retain the same object; tokens and expiry are
        # still managed/refreshed by google-auth, not copied into static keys.
        assert all(client.transport._credentials is credential for client in clients)
    finally:
        for client in clients:
            client.transport.close()
        adapter._public_credentials.cache_clear()


class PublicDouble:
    def __init__(self, monkeypatch, pin):
        resource = pin["resource"]
        self.calls = []
        self.points = {}
        self.index = sdk.Index(name=resource["index_resource"], index_update_method="STREAM_UPDATE",
            metadata={"config": {"dimensions": 768, "distanceMeasureType": "COSINE_DISTANCE", "featureNormType": "NONE"}})
        self.endpoint = sdk.IndexEndpoint(name=resource["endpoint_resource"], public_endpoint_enabled=True,
            public_endpoint_domain_name="123.us-central1-456.vdb.vertexai.goog",
            deployed_indexes=[{"id": "fixture", "index": resource["index_resource"]}])
        self.read_override = None
        self.query_override = None
        self.query_request = None
        self.factory_calls = 0
        monkeypatch.setattr(adapter, "get_settings", lambda: SimpleNamespace(
            embedding_model="text-embedding-005", embedding_output_dimensionality=768,
            gcp_project="fixture-project", gcp_region="us-central1",
            vertex_ai_index_endpoint=resource["endpoint_resource"], vertex_ai_deployed_index_id="fixture"))
        def factory(resource):
            self.factory_calls += 1
            return self, self
        monkeypatch.setattr(adapter, "_public_clients", factory)
        monkeypatch.setattr(adapter, "_public_match_client", lambda host: self)
        monkeypatch.setattr(adapter, "_embed", lambda pin, texts, deadline, stop_event=None: [[0.25] * 768 for _ in texts])

    def _record(self, operation, **kwargs):
        assert kwargs["retry"] is None
        assert 0 < kwargs["timeout"] <= 5
        self.calls.append((operation, kwargs))

    def get_index(self, **kwargs):
        self._record("index", **kwargs)
        return self.index

    def get_index_endpoint(self, **kwargs):
        self._record("endpoint", **kwargs)
        return self.endpoint

    def read_index_datapoints(self, **kwargs):
        self._record("read", **kwargs)
        request = kwargs["request"]
        assert isinstance(request, sdk.ReadIndexDatapointsRequest)
        assert len(request.ids) <= 100
        rows = [self.points[key] for key in request.ids if key in self.points]
        if self.read_override is not None:
            rows = self.read_override(rows)
        return sdk.ReadIndexDatapointsResponse(datapoints=rows)

    def upsert_datapoints(self, **kwargs):
        self._record("upsert", **kwargs)
        request = kwargs["request"]
        assert isinstance(request, sdk.UpsertDatapointsRequest)
        assert len(request.datapoints) <= 100
        assert not request.update_mask.paths
        for point in request.datapoints:
            self.points[point.datapoint_id] = copy.deepcopy(point)

    def find_neighbors(self, **kwargs):
        self._record("query", **kwargs)
        request = self.query_request = kwargs["request"]
        assert isinstance(request, sdk.FindNeighborsRequest)
        assert request.return_full_datapoint is True
        if self.query_override is not None:
            return self.query_override(request)
        return sdk.FindNeighborsResponse(nearest_neighbors=[{"neighbors": [
            {"datapoint": point, "distance": 0.25} for point in list(self.points.values())[:query.neighbor_count]]}
            for query in request.queries])


def _actual_missing_behavior(monkeypatch, transport, *, aggregate=False):
    read = transport.read_index_datapoints
    def vertex_read(**kwargs):
        missing = [key for key in kwargs["request"].ids if key not in transport.points]
        if missing:
            transport._record("read_missing", **kwargs)
            reported = ",".join(missing) if aggregate else missing[0]
            raise NotFound(f"{reported} entity does not exist in the dataset")
        return read(**kwargs)
    monkeypatch.setattr(transport, "read_index_datapoints", vertex_read)


@pytest.mark.parametrize("aggregate", [False, True])
def test_public_mixed_missing_ids_can_publish_then_read_back(monkeypatch, aggregate):
    pin, members = fixture_generation(3, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    points = adapter._member_points(pin, members)
    transport.points[points[1]["datapoint_id"]] = sdk.IndexDatapoint(**points[1])
    _actual_missing_behavior(monkeypatch, transport, aggregate=aggregate)
    result = adapter.publish(pin, members)
    assert result["already_present_count"] == 1 and result["acknowledged_count"] == 2
    assert len(adapter.observe(pin, members)["vectors"]) == 3
    assert len([call for call in transport.calls if call[0] == "read_missing"]) == (1 if aggregate else 2)


def test_full_partition_misses_fit_grpc_error_metadata_before_any_write(monkeypatch):
    pin, members = fixture_generation(500, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    read = transport.read_index_datapoints

    def bounded_missing_metadata(**kwargs):
        missing = [key for key in kwargs["request"].ids if key not in transport.points]
        if missing:
            message = ",".join(missing) + " entity does not exist in the dataset"
            # The actual 500-vector cloud probe hit 10,853 vs. 8,192 bytes
            # on a 100-ID miss; allow conservative metadata framing overhead.
            if len(message.encode()) + 1024 > 8192:
                raise ResourceExhausted("received metadata size exceeds hard limit")
            transport._record("read_missing", **kwargs)
            raise NotFound(message)
        return read(**kwargs)

    monkeypatch.setattr(transport, "read_index_datapoints", bounded_missing_metadata)
    assert adapter.publish(pin, members)["acknowledged_count"] == 500
    assert len(adapter.observe(pin, members)["vectors"]) == 500
    assert [len(call[1]["request"].ids) for call in transport.calls if call[0] == "read_missing"] == [50] * 10
    assert [len(call[1]["request"].datapoints) for call in transport.calls if call[0] == "upsert"] == [100] * 5


def test_resource_exhaustion_is_never_treated_as_missing_vectors(monkeypatch):
    pin, members = fixture_generation(100, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)

    def unavailable(**kwargs):
        raise ResourceExhausted("upstream quota exhausted")

    monkeypatch.setattr(transport, "read_index_datapoints", unavailable)
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert not any(operation == "upsert" for operation, _ in transport.calls)


def test_public_missing_batch_preserves_conflicting_member(monkeypatch):
    pin, members = fixture_generation(3, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    point = sdk.IndexDatapoint(**adapter._member_points(pin, members)[-1])
    point.feature_vector[0] = 0.9
    transport.points[point.datapoint_id] = point
    _actual_missing_behavior(monkeypatch, transport)
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert not any(operation == "upsert" for operation, _ in transport.calls)


@pytest.mark.parametrize("message", ["endpoint not found", "unknown entity does not exist in the dataset",
                                    "SECRET source text", "datapoint does not exist"])
def test_other_not_found_errors_never_authorize_writes(monkeypatch, message):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    def fail(**kwargs):
        raise NotFound(message)
    monkeypatch.setattr(transport, "read_index_datapoints", fail)
    with pytest.raises(adapter.IndexVectorError) as caught:
        adapter.publish(pin, members)
    assert message not in str(caught.value)
    assert not any(operation == "upsert" for operation, _ in transport.calls)


def test_missing_ids_share_deadline(monkeypatch):
    pin, members = fixture_generation(3, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    _actual_missing_behavior(monkeypatch, transport)
    class Budget:
        remaining_calls = 0
        def remaining(self):
            self.remaining_calls += 1
            if self.remaining_calls > 4:
                raise adapter.IndexVectorError("budget exhausted")
            return 1
    with pytest.raises(adapter.IndexVectorError, match="budget exhausted"):
        adapter._PublicIndex(pin, Budget()).read([m["vector_id"] for m in members], Budget())
    assert not any(operation == "upsert" for operation, _ in transport.calls)


def test_missing_retry_cannot_return_a_removed_identity(monkeypatch):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    point = sdk.IndexDatapoint(**adapter._member_points(pin, members)[0])
    calls = 0
    def malformed(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise NotFound(f"{point.datapoint_id} entity does not exist in the dataset")
        return sdk.ReadIndexDatapointsResponse(datapoints=[point])
    monkeypatch.setattr(transport, "read_index_datapoints", malformed)
    with pytest.raises(adapter.IndexVectorError, match="unrequested"):
        adapter.publish(pin, members)
    assert not any(operation == "upsert" for operation, _ in transport.calls)


def test_disposable_five_to_three_keeps_old_namespace_and_full_inventory():
    old, old_members = fixture_generation(5)
    index = adapter.register_disposable(old["resource"])
    assert adapter.publish(old, old_members)["acknowledged_count"] == 5
    new, new_members = fixture_generation(3)
    adapter.publish(new, new_members)
    assert len(index.points) == 8
    old_observation = adapter.observe(old, old_members)
    current = adapter.observe(new, new_members)
    assert len(current["vectors"]) == 3 and current["full_inventory_observed"] is True
    assert len(old_observation["vectors"]) == 5
    assert adapter.repair_plan(new, new_members, current)["promotion_ready"] is True
    assert {hit.vector_id for hit in adapter.query(old, "rollback", top_k=10)} == {row["vector_id"] for row in old_members}
    assert {hit.vector_id for hit in adapter.query(new, "current", top_k=10)} == {row["vector_id"] for row in new_members}


def test_public_full_declared_readback_does_not_claim_full_inventory(monkeypatch):
    pin, members = fixture_generation(101, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    assert adapter.publish(pin, members)["acknowledged_count"] == 101
    assert [len(call[1]["request"].datapoints) for call in transport.calls if call[0] == "upsert"] == [100, 1]
    first = adapter.observe(pin, members)
    assert first["full_inventory_observed"] is False
    plan = adapter.repair_plan(pin, members, first)
    assert plan["promotion_ready"] is True and plan["declared_members_complete"] is True
    assert plan["unknown_orphan_absence_verified"] is False
    assert plan["validation_scope"] == "declared_generation_members"
    assert plan["delete_candidate_ids"] == []
    assert adapter.observe(pin, members)["observation_id"] != first["observation_id"]
    count = len([call for call in transport.calls if call[0] == "upsert"])
    assert adapter.publish(pin, members)["already_present_count"] == 101
    assert len([call for call in transport.calls if call[0] == "upsert"]) == count


def test_sql_only_vector_only_and_changed_position_have_distinct_reconciliation():
    pin, members = fixture_generation(5)
    index = adapter.register_disposable(pin["resource"])
    adapter.publish(pin, members)
    missing = members[0]["vector_id"]
    index.points.pop(missing)
    _, extra = fixture_generation(6, generation=pin["generation_id"])
    larger = {**pin, "manifest_sha256": manifest_sha256(extra)}
    orphan_point = adapter._member_points(larger, extra)[-1]
    index.points[orphan_point["datapoint_id"]] = orphan_point
    report = adapter.repair_plan(pin, members, adapter.observe(pin, members))
    assert report["missing_ids"] == report["pending_known_ids"] == [missing]
    assert report["observed_orphan_ids"] == [orphan_point["datapoint_id"]]
    assert report["promotion_ready"] is False
    assert report["upsert_candidate_ids"] == [missing] and report["delete_candidate_ids"] == []
    replacement = copy.deepcopy(members[1])
    replacement["chunk_revision_sha256"] = hashlib.sha256(b"changed position and content").hexdigest()
    replacement["vector_id"] = vector_id_for(pin["generation_id"], replacement["chunk_revision_sha256"])
    assert replacement["vector_id"] != members[1]["vector_id"]


@pytest.mark.parametrize("fault", ["model", "dimension", "project", "endpoint", "deployed", "distance", "norm"])
def test_runtime_or_pin_mismatch_refuses_before_any_provider(monkeypatch, fault):
    pin, members = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    if fault in {"model", "dimension"}:
        pin["profile"]["model" if fault == "model" else "output_dimensionality"] = "wrong" if fault == "model" else 769
    else:
        field = {"project": "project", "endpoint": "endpoint_resource", "deployed": "deployed_index_id", "distance": "distance_measure", "norm": "feature_norm"}[fault]
        pin["resource"][field] = "wrong"
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert transport.factory_calls == 0


@pytest.mark.parametrize("fault", ["private", "binding", "dimensions", "distance", "norm", "batch", "host"])
def test_actual_resource_is_verified_before_embedding_or_upsert(monkeypatch, fault):
    pin, members = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    if fault == "private":
        transport.endpoint.public_endpoint_enabled = False
    elif fault == "binding":
        transport.endpoint.deployed_indexes[0].index = "wrong"
    elif fault == "batch":
        transport.index.index_update_method = "BATCH_UPDATE"
    elif fault == "host":
        transport.endpoint.public_endpoint_domain_name = "localhost"
    else:
        key = {"dimensions": "dimensions", "distance": "distanceMeasureType", "norm": "featureNormType"}[fault]
        transport.index.metadata["config"][key] = 10 if fault == "dimensions" else "wrong"
    with pytest.raises(adapter.IndexVectorError):
        adapter.query(pin, "synthetic question", top_k=3)
    assert not any(name in {"query", "upsert", "read"} for name, _ in transport.calls)


@pytest.mark.parametrize("fault", ["generation", "space", "revision", "content", "vector", "missing", "no_vector", "numeric"])
def test_public_readback_rejects_binding_or_metadata_omission(monkeypatch, fault):
    pin, members = fixture_generation(1, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    point = transport.points[members[0]["vector_id"]]
    if fault == "missing":
        point.restricts.pop()
    elif fault == "no_vector":
        point.feature_vector = []
    elif fault == "numeric":
        point.numeric_restricts = []
    else:
        restriction = next(item for item in point.restricts if item.namespace == "sclib_" + fault)
        restriction.allow_list = [str(uuid4()) if fault == "generation" else "wrong"]
    with pytest.raises(adapter.IndexVectorError):
        adapter.observe(pin, members)


@pytest.mark.parametrize("fault", ["manifest", "text", "bytes", "vector_hash", "duplicate"])
def test_entire_input_inventory_validates_before_provider(monkeypatch, fault):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    if fault == "manifest":
        pin["manifest_sha256"] = "f" * 64
    elif fault == "text":
        members[-1]["snapshot_json"]["text"] = "changed"
    elif fault == "bytes":
        members[-1]["vector_bytes"] = b"bad"
    elif fault == "vector_hash":
        members[-1]["vector_sha256"] = "f" * 64
    else:
        members[-1] = members[0]
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert transport.factory_calls == 0


def test_query_full_datapoint_restricts_deadline_and_three_hashes(monkeypatch):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    hits = adapter.query(pin, "Tc and pressure", top_k=2, year_min=2020, year_max=2022)
    assert hits[0].vector_id == members[0]["vector_id"]
    for field in ("content_sha256", "vector_sha256", "chunk_revision_sha256"):
        assert getattr(hits[0], field) == members[0][field]
    request = transport.query_request
    tags = {r.namespace: list(r.allow_list) for r in request.queries[0].datapoint.restricts}
    assert tags == {"sclib_generation": [pin["generation_id"]], "sclib_space": [adapter._space(pin)]}
    years = request.queries[0].datapoint.numeric_restricts
    assert [(r.value_int, int(r.op)) for r in years] == [(2020, 4), (2022, 2)]
    assert len(adapter.query_many(pin, ["one", "two"], top_k=2)) == 2


@pytest.mark.parametrize("fault", ["missing_vector", "hash_changed", "duplicate", "nan", "extra_query", "wrong_generation"])
def test_query_does_not_release_partial_unverified_hits(monkeypatch, fault):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    def returned(request):
        first, second = [copy.deepcopy(value) for value in transport.points.values()]
        distance = 0.2
        if fault == "missing_vector":
            second.feature_vector = []
        elif fault == "hash_changed":
            second.feature_vector = [0.5] * 768
        elif fault == "duplicate":
            second = first
        elif fault == "nan":
            distance = float("nan")
        elif fault == "wrong_generation":
            next(r for r in second.restricts if r.namespace == "sclib_generation").allow_list = [str(uuid4())]
        rows = [{"neighbors": [{"datapoint": first, "distance": 0.2}, {"datapoint": second, "distance": distance}]}]
        if fault == "extra_query":
            rows.append(rows[0])
        return sdk.FindNeighborsResponse(nearest_neighbors=rows)
    transport.query_override = returned
    with pytest.raises(adapter.IndexVectorError):
        adapter.query(pin, "query", top_k=2)


def test_cancelled_batch_and_invalid_later_input_make_no_provider_calls(monkeypatch):
    pin, _ = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    stop = threading.Event()
    stop.set()
    with pytest.raises(adapter.IndexVectorError, match="cancelled"):
        adapter.query_many(pin, ["one", "two"], top_k=2, stop_event=stop)
    with pytest.raises(adapter.IndexVectorError):
        adapter.query_many(pin, ["one", "x" * 10000], top_k=2)
    assert transport.factory_calls == 0


def test_provider_errors_never_expose_query_or_credentials(monkeypatch):
    pin, members = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    transport.read_override = lambda _: (_ for _ in ()).throw(RuntimeError("SECRET access token and source text"))
    with pytest.raises(adapter.IndexVectorError) as error:
        adapter.publish(pin, members)
    assert "SECRET" not in str(error.value)


def test_numeric_project_names_still_require_exact_configured_resources(monkeypatch):
    pin, members = fixture_generation(1, backend="vertex-public")
    for key in ("index_resource", "endpoint_resource"):
        pin["resource"][key] = pin["resource"][key].replace("projects/fixture-project/", "projects/123456789/")
    transport = PublicDouble(monkeypatch, pin)
    assert adapter.publish(pin, members)["acknowledged_count"] == 1
    assert adapter.observe(pin, members)["full_inventory_observed"] is False
    pin["resource"]["index_resource"] = pin["resource"]["index_resource"].replace("123456789", "99999999")
    calls = transport.factory_calls
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert transport.factory_calls == calls


def test_interrupted_publication_resumes_known_ids_and_never_promotes_partial(monkeypatch):
    pin, members = fixture_generation(101, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    original = transport.upsert_datapoints
    def fail_second(**kwargs):
        if len(transport.points) == 100:
            raise RuntimeError("interrupted provider write")
        original(**kwargs)
    monkeypatch.setattr(transport, "upsert_datapoints", fail_second)
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert len(transport.points) == 100
    report = adapter.repair_plan(pin, members, adapter.observe(pin, members))
    assert report["promotion_ready"] is False and len(report["missing_ids"]) == 1
    assert report["unknown_orphan_absence_verified"] is False
    monkeypatch.setattr(transport, "upsert_datapoints", original)
    assert adapter.publish(pin, members)["already_present_count"] == 100
    assert adapter.repair_plan(pin, members, adapter.observe(pin, members))["declared_members_complete"] is True


@pytest.mark.parametrize("fault", ["content", "numeric", "vector"])
def test_same_id_conflict_is_not_overwritten(monkeypatch, fault):
    pin, members = fixture_generation(1, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    point = transport.points[members[0]["vector_id"]]
    if fault == "numeric":
        point.numeric_restricts[0].value_int = 2010
    else:
        value = "f" * 64
        if fault == "vector":
            point.feature_vector = [0.75] * 768
            value = hashlib.sha256(struct.pack(">768f", *point.feature_vector)).hexdigest()
        next(r for r in point.restricts if r.namespace == "sclib_" + fault).allow_list = [value]
    count = len([call for call in transport.calls if call[0] == "upsert"])
    with pytest.raises(adapter.IndexVectorError):
        adapter.publish(pin, members)
    assert len([call for call in transport.calls if call[0] == "upsert"]) == count
    if fault != "numeric":
        plan = adapter.repair_plan(pin, members, adapter.observe(pin, members))
        assert plan["hash_mismatch_ids"] == [members[0]["vector_id"]]
        assert plan["promotion_ready"] is False


@pytest.mark.parametrize("fault", ["duplicate", "unknown"])
def test_public_readback_rejects_duplicate_or_unsolicited_rows(monkeypatch, fault):
    pin, members = fixture_generation(2, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    def malformed(rows):
        rows[1] = copy.deepcopy(rows[0])
        if fault == "unknown":
            rows[1].datapoint_id = "unrequested"
        return rows
    transport.read_override = malformed
    with pytest.raises(adapter.IndexVectorError):
        adapter.observe(pin, members)


@pytest.mark.parametrize("fault", ["no_year", "wrong_year", "float_year", "duplicate_year"])
def test_query_years_are_verified_not_only_provider_filtered(monkeypatch, fault):
    pin, members = fixture_generation(1, backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    point = transport.points[members[0]["vector_id"]]
    if fault == "no_year":
        point.numeric_restricts = []
    elif fault == "wrong_year":
        point.numeric_restricts[0].value_int = 2000
    elif fault == "float_year":
        point.numeric_restricts[0].value_float = 2021.0
    else:
        point.numeric_restricts.append({"namespace": "year", "value_int": 2021})
    with pytest.raises(adapter.IndexVectorError):
        adapter.query(pin, "year query", top_k=1, year_min=2020, year_max=2022)


def test_query_embedding_sdk_contract_and_cancel_between_inputs(monkeypatch):
    from services import genai_client
    pin, _ = fixture_generation(backend="vertex-public")
    stop = threading.Event()
    calls = []
    def embed_content(**kwargs):
        calls.append(kwargs)
        stop.set()
        return {"embeddings": [{"values": [0.25] * 768,
                               "statistics": {"truncated": False, "token_count": 2}}]}
    monkeypatch.setattr(genai_client, "embedding_client", lambda: SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)))
    with pytest.raises(adapter.IndexVectorError, match="cancelled"):
        adapter._embed(pin, ["first", "second"], adapter._Deadline(), stop)
    assert len(calls) == 1
    config = calls[0]["config"]
    assert config.task_type == "RETRIEVAL_QUERY" and config.output_dimensionality == 768
    assert config.auto_truncate is False and 0 < config.http_options.timeout <= 5000
    assert config.http_options.retry_options.attempts == 1


def test_batch_cancel_after_embedding_prevents_ann(monkeypatch):
    pin, _ = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    stop = threading.Event()
    def embed(pin, texts, deadline, stop_event=None):
        stop.set()
        return [[0.25] * 768 for _ in texts]
    monkeypatch.setattr(adapter, "_embed", embed)
    with pytest.raises(adapter.IndexVectorError, match="cancelled"):
        adapter.query_many(pin, ["first", "second"], top_k=2, stop_event=stop)
    assert not any(operation == "query" for operation, _ in transport.calls)


def test_deadline_rechecked_after_last_sdk_call(monkeypatch):
    pin, members = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    clock = [10.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    def too_late(rows):
        clock[0] = 30.0
        return rows
    transport.read_override = too_late
    with pytest.raises(adapter.IndexVectorError, match="deadline"):
        adapter.observe(pin, members)


@pytest.mark.parametrize("top_k", [True, 0, 101, 1.0, "1"])
def test_strict_query_limit_types_precede_provider(monkeypatch, top_k):
    pin, _ = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    with pytest.raises(adapter.IndexVectorError):
        adapter.query(pin, "bounded query", top_k=top_k)
    assert transport.factory_calls == 0


def test_preview_validates_manifest_without_any_client_construction(monkeypatch):
    pin, members = fixture_generation(backend="vertex-public")
    transport = PublicDouble(monkeypatch, pin)
    result = adapter.preview(pin, members)
    assert result["member_count"] == 3 and result["manifest_sha256"] == pin["manifest_sha256"]
    assert result["provider_io_performed"] is False and transport.factory_calls == 0
    members[-1]["snapshot_json"]["text"] = "modified"
    with pytest.raises(adapter.IndexVectorError):
        adapter.preview(pin, members)
    assert transport.factory_calls == 0


@pytest.mark.parametrize("value", [None, True, "2026-09-08", "2026-09-08T01:02:03Z",
    "2026-09-08T01:02:03.123456+00:00", "2026-02-30T01:02:03.123456Z", "2026-09-08T01:02:60.123456Z"])
def test_reconciliation_requires_exact_canonical_observation_time(value):
    pin, members = fixture_generation(1)
    adapter.register_disposable(pin["resource"])
    adapter.publish(pin, members)
    observation = adapter.observe(pin, members)
    assert observation["observed_at"].endswith("Z") and len(observation["observed_at"]) == 27
    observation["observed_at"] = value
    with pytest.raises(adapter.IndexVectorError):
        adapter.repair_plan(pin, members, observation)


def test_corpus_session_keeps_partition_deadlines_and_rechecks_resource(monkeypatch):
    pin,members=fixture_generation(3,backend='vertex-public')
    public=PublicDouble(monkeypatch,pin)
    session=adapter.CorpusTransportSession(pin)
    session.prepare()
    assert [operation for operation, _ in public.calls] == ['index', 'endpoint']
    for member in members:
        selected={**pin,'manifest_sha256':manifest_sha256([member])}
        adapter.publish(selected,[member],session=session)
        observed=adapter.observe(selected,[member],session=session)
        assert len(observed['vectors'])==1 and observed['full_inventory_observed'] is False
    assert public.factory_calls==1
    session.expires=0
    adapter.observe(pin,members,session=session)
    assert public.factory_calls==2
    other,others=fixture_generation(1,backend='vertex-public')
    with pytest.raises(adapter.IndexVectorError,match='identity changed'):
        adapter.publish(other,others,session=session)


def test_operator_setup_does_not_extend_a_late_partition_deadline(monkeypatch):
    pin, members = fixture_generation(1, backend="vertex-public")
    public = PublicDouble(monkeypatch, pin)
    clock = [10.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    factory = adapter._public_clients

    def slow_setup(resource):
        clock[0] += 8
        return factory(resource)

    monkeypatch.setattr(adapter, "_public_clients", slow_setup)
    session = adapter.CorpusTransportSession(pin)
    session.prepare()
    assert not public.points
    assert adapter.publish(pin, members, session=session)["acknowledged_count"] == 1

    def late_read(rows):
        clock[0] += 13
        return rows

    public.read_override = late_read
    with pytest.raises(adapter.IndexVectorError, match="deadline"):
        adapter.observe(pin, members, session=session)


@pytest.mark.parametrize(('distance', 'expected'), [(-2.384185791015625e-7, 0.0), (2.000000238418579, 2.0), (0.4, 0.4)])
def test_cosine_float32_boundary_roundoff_is_clamped(monkeypatch, distance, expected):
    pin, members = fixture_generation(backend='vertex-public')
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    point = next(iter(transport.points.values()))
    transport.query_override = lambda request: sdk.FindNeighborsResponse(nearest_neighbors=[{'neighbors': [{'datapoint': point, 'distance': distance}]}])
    result = adapter.query(pin, 'query', top_k=1)
    assert len(result) == 1 and result[0].distance == pytest.approx(expected)


@pytest.mark.parametrize('distance', [-1e-4, 2.0001, float('inf'), float('-inf')])
def test_cosine_invalid_distance_still_rejects_entire_response(monkeypatch, distance):
    pin, members = fixture_generation(backend='vertex-public')
    transport = PublicDouble(monkeypatch, pin)
    adapter.publish(pin, members)
    point = next(iter(transport.points.values()))
    transport.query_override = lambda request: sdk.FindNeighborsResponse(nearest_neighbors=[{'neighbors': [{'datapoint': point, 'distance': distance}]}])
    with pytest.raises(adapter.IndexVectorError, match='distance or identity'):
        adapter.query(pin, 'query', top_k=1)


def test_embedding_client_region_is_independent_of_answer_routing(monkeypatch):
    from services import genai_client
    calls = []
    credential = object()
    genai_client.dispose()
    monkeypatch.setattr(genai_client, 'get_settings', lambda: SimpleNamespace(gcp_project='fixture', gcp_region='us-central1', gemini_use_enterprise=True, gemini_location='global', gemini_api_version='v1'))
    monkeypatch.setattr(genai_client, 'public_credentials', lambda: credential)
    monkeypatch.setattr(genai_client.genai, 'Client', lambda **kw: calls.append(kw) or SimpleNamespace())
    try:
        genai_client.client()
        first = genai_client.embedding_client()
        assert genai_client.embedding_client() is first
        assert len(calls) == 2
        assert calls[0]['enterprise'] is True and calls[0]['location'] == 'global'
        assert calls[1]['vertexai'] is True and calls[1]['location'] == 'us-central1'
        assert calls[1]['credentials'] is credential and calls[1]['http_options'].api_version == 'v1'
    finally:
        genai_client.client.cache_clear()
        genai_client.embedding_client.cache_clear()
