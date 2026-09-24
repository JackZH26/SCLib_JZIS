"""Bounded immutable-generation vector transport; never count-based parity.

Public Vertex supports expected-ID readback, not full inventory enumeration.
Complete declared-member verification is separate from unknown orphan extent.
The disposable adapter enumerates a target generation for offline rehearsals. No path
here deletes datapoints or infers source rights, scientific truth, or recall.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

# Import the locked SDK during service startup, outside the first request's
# provider deadline. This constructs no client and performs no network I/O.
from google.cloud import aiplatform_v1

from config import get_settings
from services.genai_client import public_credentials as _public_credentials
from services.embedding_contract import (
    DIMENSION,
    LOCAL_QUERY_COUNT_METHOD,
    LOCAL_QUERY_INPUT_LIMIT,
    LOCAL_QUERY_REQUEST_LIMIT,
    MODEL,
    content_sha256,
    validate_embedding_inputs,
    validate_embedding_response,
    validate_vector,
    vector_sha256,
)

ADAPTER_VERSION = "sclib-index-vector-adapter/1.0.0"
OBSERVATION_VERSION = "sclib-index-observation/1.0.0"
PROFILE = {"version": "sclib-index-profile/1.0.0", "provider": "google-vertex-ai",
           "model": MODEL, "output_dimensionality": DIMENSION,
           "document_task": "RETRIEVAL_DOCUMENT", "query_task": "RETRIEVAL_QUERY"}
MAX_MEMBERS = 1000
BATCH_SIZE = 100  # SCLib bound; provider readback permits at most 1000 IDs.
# Vertex lists every absent ID in its gRPC error metadata. A 100-ID miss
# with our 102-byte immutable IDs exceeds gRPC's default 8 KiB metadata cap
# before NotFound can be decoded. Keep read misses below that transport bound;
# write batches and the shared operation deadline remain unchanged.
READ_BATCH_SIZE = 50
MAX_QUERY_BATCH = 20
MAX_EXCLUDED_REVISIONS = 20000
MAX_QUERY_RPC_BYTES = 2 * 1024 * 1024
# Vertex's float32 cosine calculation can put identical vectors a few ULPs
# below zero. Accept only roundoff at the mathematical [0, 2] boundaries.
COSINE_ROUNDOFF = 1e-6
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")
_RESOURCE_FIELDS = {"backend", "project", "location", "index_resource", "endpoint_resource",
                    "deployed_index_id", "distance_measure", "feature_norm"}
_NAMESPACES = {"sclib_generation", "sclib_space", "sclib_revision", "sclib_content", "sclib_vector"}
_DISPOSABLE = {}


class IndexVectorError(ValueError):
    """A bounded generation transport operation cannot be verified."""


@dataclass(frozen=True)
class Neighbor:
    vector_id: str
    distance: float
    content_sha256: str
    vector_sha256: str
    chunk_revision_sha256: str


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise IndexVectorError("Invalid generation binding hash")
    return value


def _vector_id(generation, revision):
    return "ig62_" + UUID(str(generation)).hex + "_" + _sha(revision)


def _space(pin):
    return hashlib.sha256(_canonical({"profile": pin["profile"],
        "distance_measure": pin["resource"]["distance_measure"],
        "feature_norm": pin["resource"]["feature_norm"]})).hexdigest()


def _pin(value):
    try:
        result = copy.deepcopy(value)
        result["generation_id"] = str(UUID(str(result["generation_id"])))
        _sha(result["manifest_sha256"])
        profile, resource = result["profile"], result["resource"]
        if (type(profile) is not dict or profile != PROFILE
                or type(profile["output_dimensionality"]) is not int
                or type(resource) is not dict or set(resource) != _RESOURCE_FIELDS
                or resource["backend"] not in {"vertex-public", "disposable"}
                or resource["distance_measure"] != "COSINE_DISTANCE" or resource["feature_norm"] not in {"NONE", "UNIT_L2_NORM"}):
            raise ValueError
        if any(type(value) is not str or len(value) > 500 for value in resource.values()):
            raise ValueError
        for name in ("project", "location", "deployed_index_id"):
            if type(resource[name]) is not str or not _TOKEN.fullmatch(resource[name]):
                raise ValueError
        # SDK resource names often contain a project number, whereas the query
        # embedding project setting is a project ID. Exact endpoint configuration
        # and the actual deployment binding remain authoritative; never guess a
        # number-to-ID mapping. Both vector resources must use the same segment.
        endpoint_match = re.fullmatch(r"projects/([^/]+)/locations/([^/]+)/indexEndpoints/[^/]+",
                                     resource["endpoint_resource"])
        if (not endpoint_match or endpoint_match[2] != resource["location"]
                or not _TOKEN.fullmatch(endpoint_match[1])
                or (endpoint_match[1] != resource["project"] and not endpoint_match[1].isdigit())):
            raise ValueError
        prefix = f"projects/{endpoint_match[1]}/locations/{resource['location']}/"
        for name, collection in (("index_resource", "indexes"), ("endpoint_resource", "indexEndpoints")):
            if (type(resource[name]) is not str or not resource[name].startswith(prefix + collection + "/")
                    or not _TOKEN.fullmatch(resource[name][len(prefix + collection + "/"):])):
                raise ValueError
        if resource["backend"] == "vertex-public":
            settings = get_settings()
            if (settings.embedding_model != profile["model"]
                    or type(settings.embedding_output_dimensionality) is not int
                    or settings.embedding_output_dimensionality != DIMENSION
                    or settings.gcp_project != resource["project"] or settings.gcp_region != resource["location"]
                    or settings.vertex_ai_index_endpoint != resource["endpoint_resource"]
                    or settings.vertex_ai_deployed_index_id != resource["deployed_index_id"]):
                raise ValueError
        return result
    except (ValueError, TypeError, KeyError, AttributeError):
        raise IndexVectorError("Pinned index profile or runtime resource is incompatible") from None


class _Deadline:
    def __init__(self, seconds=12):
        self.end = time.monotonic() + seconds

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise IndexVectorError("Index operation deadline exceeded")
        return min(remaining, 5.0)


def _restricts(pin, revision, content, vector):
    values = {"sclib_generation": pin["generation_id"], "sclib_space": _space(pin),
              "sclib_revision": revision, "sclib_content": content, "sclib_vector": vector}
    return [{"namespace": name, "allow_list": [value], "deny_list": []}
            for name, value in sorted(values.items())]


def _member_points(pin, members):
    if type(members) not in {list, tuple} or not 1 <= len(members) <= MAX_MEMBERS:
        raise IndexVectorError("Bounded nonempty generation members are required")
    points = []
    seen = set()
    for member in members:
        try:
            revision = _sha(member["chunk_revision_sha256"])
            identifier = _vector_id(pin["generation_id"], revision)
            raw = member["vector_bytes"]
            if (str(member["generation_id"]) != pin["generation_id"] or member["vector_id"] != identifier
                    or identifier in seen or type(raw) not in {bytes, memoryview}
                    or len(raw) != DIMENSION * 4):
                raise ValueError
            vector = validate_vector(list(struct.unpack(">" + "f" * DIMENSION, bytes(raw))))
            vector_hash = vector_sha256(vector)
            content_hash = content_sha256(member["snapshot_json"]["text"])
            if vector_hash != _sha(member["vector_sha256"]) or content_hash != _sha(member["content_sha256"]):
                raise ValueError
            numeric = []
            paper = member.get("paper_snapshot_json", {})
            date = paper.get("date_submitted") or paper.get("date_published")
            if type(date) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
                numeric = [{"namespace": "year", "value_int": int(date[:4])}]
            points.append({"datapoint_id": identifier, "feature_vector": vector,
                "restricts": _restricts(pin, revision, content_hash, vector_hash),
                "numeric_restricts": numeric})
            seen.add(identifier)
        except (KeyError, TypeError, ValueError, struct.error):
            raise IndexVectorError("Generation member content or vector binding is invalid") from None
    from services.index_generations import manifest_sha256
    if manifest_sha256(members) != pin["manifest_sha256"]:
        raise IndexVectorError("Generation manifest does not match its complete members")
    return points


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _tags(point):
    tags = {}
    restricts = _field(point, "restricts", [])
    if len(restricts) > 32:
        raise IndexVectorError("Malformed vector restrictions")
    for restriction in restricts:
        name = _field(restriction, "namespace")
        if name in _NAMESPACES:
            allow, deny = list(_field(restriction, "allow_list", [])), list(_field(restriction, "deny_list", []))
            if name in tags or len(allow) != 1 or deny or type(allow[0]) is not str:
                raise IndexVectorError("Malformed vector restrictions")
            tags[name] = allow[0]
    if set(tags) != _NAMESPACES:
        raise IndexVectorError("Required vector bindings are unavailable")
    return tags


def _verified_point(pin, point):
    try:
        tags = _tags(point)
        identifier = _field(point, "datapoint_id")
        revision = _sha(tags["sclib_revision"])
        content_hash, vector_hash = _sha(tags["sclib_content"]), _sha(tags["sclib_vector"])
        vector = validate_vector(list(_field(point, "feature_vector", [])))
        if (tags["sclib_generation"] != pin["generation_id"] or tags["sclib_space"] != _space(pin)
                or identifier != _vector_id(pin["generation_id"], revision)
                or vector_sha256(vector) != vector_hash):
            raise ValueError
        return {"vector_id": identifier, "content_sha256": content_hash, "vector_sha256": vector_hash}, revision
    except (TypeError, ValueError, KeyError):
        raise IndexVectorError("Returned vector generation, space or hash is invalid") from None


def _numeric(point):
    """Exact stored year metadata, including protobuf oneof presence."""
    result = []
    for item in _field(point, "numeric_restricts", []):
        if isinstance(item, dict):
            if set(item) != {"namespace", "value_int"}:
                raise IndexVectorError("Returned numeric restrictions are invalid")
        elif item._pb.WhichOneof("Value") != "value_int" or item.op != 0:
            raise IndexVectorError("Returned numeric restrictions are invalid")
        value = _field(item, "value_int")
        if _field(item, "namespace") != "year" or type(value) is not int or not 1 <= value <= 9999:
            raise IndexVectorError("Returned numeric restrictions are invalid")
        result.append(value)
    if len(result) > 1:
        raise IndexVectorError("Returned numeric restrictions are invalid")
    return result


class DisposableIndex:
    """In-memory fixture transport. Query order is synthetic, not model recall."""
    def __init__(self):
        self.points = {}

    def read(self, ids, deadline):
        deadline.remaining()
        return [copy.deepcopy(self.points[key]) for key in ids if key in self.points]

    def upsert(self, points, deadline):
        deadline.remaining()
        for point in points:
            self.points[point["datapoint_id"]] = copy.deepcopy(point)

    def inventory(self, pin):
        prefix = "ig62_" + UUID(pin["generation_id"]).hex + "_"
        return [copy.deepcopy(point) for key, point in self.points.items()
                if key.startswith(prefix) or any(_field(r, "namespace") == "sclib_generation"
                    and pin["generation_id"] in _field(r, "allow_list", [])
                    for r in _field(point, "restricts", []))]

    def search(self, pin, vectors, top_k, year_min, year_max, deadline, *, excluded_revisions=()):
        deadline.remaining()
        points = sorted(self.inventory(pin), key=lambda point: point["datapoint_id"])
        excluded = set(excluded_revisions)
        points = [point for point in points if _tags(point)["sclib_revision"] not in excluded]
        if year_min is not None or year_max is not None:
            def admitted(point):
                years = [_field(r, "value_int") for r in point.get("numeric_restricts", [])
                         if _field(r, "namespace") == "year"]
                return len(years) == 1 and (year_min is None or years[0] >= year_min) and (year_max is None or years[0] <= year_max)
            points = [point for point in points if admitted(point)]
        return [[(point, 0.0) for point in points[:top_k]] for _ in vectors]


def register_disposable(resource, adapter=None):
    if type(resource) is not dict or resource.get("backend") != "disposable":
        raise IndexVectorError("Only an explicit disposable resource may be registered")
    selected = adapter or DisposableIndex()
    if type(selected) is not DisposableIndex:
        raise IndexVectorError("A disposable adapter is required")
    _DISPOSABLE[_canonical(resource)] = selected
    return selected


def clear_disposable():
    _DISPOSABLE.clear()


def _public_clients(resource):
    options = {"api_endpoint": f"{resource['location']}-aiplatform.googleapis.com"}
    credentials = _public_credentials()
    return (aiplatform_v1.IndexServiceClient(client_options=options, credentials=credentials),
            aiplatform_v1.IndexEndpointServiceClient(client_options=options, credentials=credentials))


def _public_match_client(host):
    return aiplatform_v1.MatchServiceClient(client_options={"api_endpoint": host}, credentials=_public_credentials())


class _PublicIndex:
    def __init__(self, pin, deadline):
        self.resource = resource = pin["resource"]
        self.index, endpoints = _public_clients(resource)
        index = self.index.get_index(name=resource["index_resource"], timeout=deadline.remaining(), retry=None)
        endpoint = endpoints.get_index_endpoint(name=resource["endpoint_resource"], timeout=deadline.remaining(), retry=None)
        config = index.metadata.get("config", {})
        bindings = [entry.index for entry in endpoint.deployed_indexes if entry.id == resource["deployed_index_id"]]
        host = endpoint.public_endpoint_domain_name
        if (index.name != resource["index_resource"] or endpoint.name != resource["endpoint_resource"]
                or bindings != [resource["index_resource"]] or not endpoint.public_endpoint_enabled
                or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.vdb\.vertexai\.goog", host or "")
                or index.index_update_method != 2 or config.get("dimensions") != DIMENSION
                or config.get("distanceMeasureType") != "COSINE_DISTANCE"
                or config.get("featureNormType", "NONE") != resource["feature_norm"]):
            raise IndexVectorError("Actual public index resource is incompatible")
        # Model is checked in the frozen profile/runtime contract, NEVER inferred
        # from index dimensions, labels or a human-authored description.
        self.match = _public_match_client(host)

    def read(self, ids, deadline):
        from google.api_core.exceptions import NotFound
        pending = list(ids)
        while pending:
            try:
                response = self.match.read_index_datapoints(request=aiplatform_v1.ReadIndexDatapointsRequest(
                    index_endpoint=self.resource["endpoint_resource"],
                    deployed_index_id=self.resource["deployed_index_id"], ids=pending),
                    timeout=deadline.remaining(), retry=None)
                if any(point.datapoint_id not in pending for point in response.datapoints):
                    raise IndexVectorError("Readback returned an unrequested member")
                return list(response.datapoints)
            except NotFound as exc:
                # Actual Vertex readback rejects an entire mixed batch when one
                # requested datapoint is absent. Admit only this exact observed
                # per-ID diagnostic. A missing endpoint/deployment, an unknown
                # ID or a changed provider diagnostic remains a hard failure.
                suffix = " entity does not exist in the dataset"
                message = exc.message
                missing = message[:-len(suffix)].split(",") if type(message) is str and message.endswith(suffix) else []
                if (not missing or len(missing) > len(pending) or len(set(missing)) != len(missing)
                        or any(key not in pending for key in missing)):
                    raise IndexVectorError("Vector readback absence is unverifiable") from None
                pending = [key for key in pending if key not in missing]
                # All attempts share the original deadline; no unbounded retry.
                deadline.remaining()
        return []

    def upsert(self, points, deadline):
        self.index.upsert_datapoints(request=aiplatform_v1.UpsertDatapointsRequest(
            index=self.resource["index_resource"], datapoints=points), timeout=deadline.remaining(), retry=None)

    def search(self, pin, vectors, top_k, year_min, year_max, deadline, *, excluded_revisions=()):
        restricts = [{"namespace": "sclib_generation", "allow_list": [pin["generation_id"]]},
                     {"namespace": "sclib_space", "allow_list": [_space(pin)]}]
        if excluded_revisions:
            # Existing immutable revision tags permit complete source-paper
            # exclusion before ANN selection, without republishing vectors.
            restricts.append({"namespace": "sclib_revision", "deny_list": list(excluded_revisions)})
        numeric = []
        if year_min is not None:
            numeric.append({"namespace": "year", "value_int": year_min, "op": "GREATER_EQUAL"})
        if year_max is not None:
            numeric.append({"namespace": "year", "value_int": year_max, "op": "LESS_EQUAL"})
        def request():
            return aiplatform_v1.FindNeighborsRequest(index_endpoint=self.resource["endpoint_resource"],
                deployed_index_id=self.resource["deployed_index_id"], return_full_datapoint=True)

        # Large source exclusions repeat in every query. Bound each serialized
        # RPC instead of truncating the exclusion set or increasing deadlines.
        requests, current = [], request()
        for vector in vectors:
            query = {"datapoint": {"feature_vector": vector, "restricts": restricts,
                                  "numeric_restricts": numeric}, "neighbor_count": top_k}
            current.queries.append(query)
            if current._pb.ByteSize() > MAX_QUERY_RPC_BYTES:
                del current.queries[-1]
                if not current.queries:
                    raise IndexVectorError("Query exclusion request exceeds its byte limit")
                requests.append(current)
                current = request()
                current.queries.append(query)
                if current._pb.ByteSize() > MAX_QUERY_RPC_BYTES:
                    raise IndexVectorError("Query exclusion request exceeds its byte limit")
        requests.append(current)
        result = []
        def find(batch, shared_deadline):
            return self.match.find_neighbors(request=batch[0], timeout=shared_deadline.remaining(), retry=None)

        # At most two independent read RPCs per wave, sharing the original
        # deadline. Drain every submitted call before failing the whole query.
        for batches, response in _rpc_batches(find, requests, 1, deadline, parallel=True):
            batch = batches[0]
            # Actual Vertex omits all groups for a successful empty single
            # query. Missing groups in a batch have no unambiguous mapping.
            if len(batch.queries) == 1 and not response.nearest_neighbors:
                result.append([])
                continue
            if len(response.nearest_neighbors) != len(batch.queries):
                raise IndexVectorError("Query result inventory is malformed")
            result.extend([[(hit.datapoint, hit.distance) for hit in row.neighbors]
                           for row in response.nearest_neighbors])
        return result


def _transport(pin, deadline):
    if pin["resource"]["backend"] == "disposable":
        selected = _DISPOSABLE.get(_canonical(pin["resource"]))
        if selected is None:
            raise IndexVectorError("Disposable index has not been registered")
        return selected
    return _PublicIndex(pin, deadline)


def _rpc_batches(call, values, size, deadline, *, parallel=False):
    """At most two operator RPCs in flight, with one unchanged deadline.

    Dispatch one wave at a time and drain its running calls before returning
    an error. No queued later waves, retries, or extended RPC budgets.
    """
    batches = [values[offset:offset + size] for offset in range(0, len(values), size)]
    if not parallel or len(batches) < 2:
        return [(batch, call(batch, deadline)) for batch in batches]
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for offset in range(0, len(batches), 2):
            deadline.remaining()
            wave = batches[offset:offset + 2]
            pending = [pool.submit(call, batch, deadline) for batch in wave]
            try:
                results.extend((batch, future.result()) for batch, future in zip(wave, pending))
            finally:
                for future in pending:
                    future.cancel()
    return results


def _read(transport, ids, deadline, *, parallel=False):
    out = {}
    for batch, rows in _rpc_batches(transport.read, ids, READ_BATCH_SIZE, deadline, parallel=parallel):
        if len(rows) > len(batch):
            raise IndexVectorError("Readback inventory is malformed")
        for point in rows:
            identifier = _field(point, "datapoint_id")
            if identifier not in batch or identifier in out:
                raise IndexVectorError("Readback inventory is malformed")
            out[identifier] = point
    return out


class CorpusTransportSession:
    """Reuse clients for one operator corpus; recheck deployment every minute.

    Each partition retains its own original deadline and complete manifest.
    Request handlers never use this operator session.
    """
    def __init__(self, pin):
        self.pin = _pin(pin)
        self.current = None
        self.expires = 0

    def prepare(self):
        """Bounded operator setup before a separately bounded partition RPC.

        Resolve the actual deployment and refreshable identity without writing
        vectors. Public request handlers never use this operator-only phase.
        """
        self.transport(self.pin, _Deadline())

    def transport(self, pin, deadline):
        if any(pin[key] != self.pin[key] for key in ("generation_id", "resource", "profile")):
            raise IndexVectorError("Corpus transport session identity changed")
        if self.current is None or time.monotonic() >= self.expires:
            self.current = _transport(pin, deadline)
            self.expires = time.monotonic() + 60
        return self.current


def publish(pin, members, *, session=None):
    """Upsert immutable known IDs only. An acknowledgement is NOT activation."""
    try:
        pin = _pin(pin)
        points = _member_points(pin, members)
        deadline = _Deadline()
        if session is not None and type(session) is not CorpusTransportSession:
            raise IndexVectorError("Invalid corpus operator transport session")
        transport = session.transport(pin, deadline) if session else _transport(pin, deadline)
        parallel = session is not None and type(transport) is _PublicIndex
        existing = _read(transport, [point["datapoint_id"] for point in points], deadline, parallel=parallel)
        missing = []
        for point in points:
            identifier = point["datapoint_id"]
            if identifier in existing:
                if (_verified_point(pin, existing[identifier])[0] != _verified_point(pin, point)[0]
                        or _numeric(existing[identifier]) != _numeric(point)):
                    raise IndexVectorError("Immutable vector ID conflicts with existing content")
            else:
                missing.append(point)
        _rpc_batches(transport.upsert, missing, BATCH_SIZE, deadline, parallel=parallel)
        deadline.remaining()
        return {"adapter_version": ADAPTER_VERSION, "acknowledged_count": len(missing),
                "already_present_count": len(existing), "publication_verified": False,
                "active_generation_changed": False}
    except IndexVectorError:
        raise
    except Exception:
        raise IndexVectorError("Vector publication is unavailable or unverifiable") from None


def preview(pin, members):
    """Validate a complete immutable selection without constructing any client."""
    try:
        pin = _pin(pin)
        points = _member_points(pin, members)
        return {"member_count": len(points), "manifest_sha256": pin["manifest_sha256"],
                "adapter_version": ADAPTER_VERSION, "provider_io_performed": False}
    except IndexVectorError:
        raise
    except Exception:
        raise IndexVectorError("Generation publication preview is incompatible") from None


def observe(pin, members, *, session=None):
    """Return closed readback observations; Vertex can never claim full inventory."""
    try:
        pin = _pin(pin)
        points = _member_points(pin, members)
        deadline = _Deadline()
        if session is not None and type(session) is not CorpusTransportSession:
            raise IndexVectorError("Invalid corpus operator transport session")
        transport = session.transport(pin, deadline) if session else _transport(pin, deadline)
        full = type(transport) is DisposableIndex and session is None
        rows = transport.inventory(pin) if full else list(_read(
            transport, [point["datapoint_id"] for point in points], deadline,
            parallel=session is not None and type(transport) is _PublicIndex).values())
        if len(rows) > MAX_MEMBERS:
            raise IndexVectorError("Observed inventory exceeds the bounded limit")
        vectors = [_verified_point(pin, point)[0] for point in rows]
        expected = {point["datapoint_id"]: point for point in points}
        for point in rows:
            identifier = _field(point, "datapoint_id")
            numeric = _numeric(point)
            if identifier in expected and numeric != _numeric(expected[identifier]):
                raise IndexVectorError("Readback numeric metadata differs from the retained member")
        if len({row["vector_id"] for row in vectors}) != len(vectors):
            raise IndexVectorError("Observed inventory contains duplicate IDs")
        deadline.remaining()
        return {"version": OBSERVATION_VERSION, "observation_id": str(uuid4()),
                "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "resource": pin["resource"], "profile": pin["profile"],
                "adapter_version": ADAPTER_VERSION, "full_inventory_observed": full,
                "vectors": sorted(vectors, key=lambda row: row["vector_id"])}
    except IndexVectorError:
        raise
    except Exception:
        raise IndexVectorError("Vector readback is unavailable or unverifiable") from None


def repair_plan(pin, members, observation):
    """Pure dry-run plan over known IDs only; no deletion or repair execution."""
    pin = _pin(pin)
    expected = {_verified_point(pin, point)[0]["vector_id"]: _verified_point(pin, point)[0]
                for point in _member_points(pin, members)}
    if (type(observation) is not dict or observation.get("version") != OBSERVATION_VERSION
            or set(observation) != {"version", "observation_id", "observed_at", "resource", "profile", "adapter_version",
                                    "full_inventory_observed", "vectors"}
            or observation.get("adapter_version") != ADAPTER_VERSION
            or observation.get("resource") != pin["resource"] or observation.get("profile") != pin["profile"]
            or type(observation.get("full_inventory_observed")) is not bool
            or type(observation.get("vectors")) is not list or len(observation["vectors"]) > MAX_MEMBERS):
        raise IndexVectorError("Reconciliation observation is incompatible")
    try:
        UUID(observation["observation_id"])
        observed_at = observation["observed_at"]
        if (type(observed_at) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", observed_at)
                or datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%dT%H:%M:%S.%fZ") != observed_at):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise IndexVectorError("Reconciliation observation is incompatible") from None
    observed = {}
    for row in observation["vectors"]:
        if type(row) is not dict or set(row) != {"vector_id", "content_sha256", "vector_sha256"}:
            raise IndexVectorError("Reconciliation observation is malformed")
        identifier = row["vector_id"]
        if type(identifier) is not str or len(identifier) > 200 or identifier in observed:
            raise IndexVectorError("Reconciliation observation is malformed")
        _sha(row["content_sha256"])
        _sha(row["vector_sha256"])
        observed[identifier] = row
    missing = sorted(set(expected) - set(observed))
    mismatched = sorted(key for key in set(expected) & set(observed) if expected[key] != observed[key])
    orphan = sorted(set(observed) - set(expected))
    full = observation["full_inventory_observed"] and pin["resource"]["backend"] == "disposable"
    complete = not (missing or mismatched or orphan)
    return {"dry_run": True, "validation_scope": "declared_generation_members",
            "missing_ids": missing, "hash_mismatch_ids": mismatched,
            "observed_orphan_ids": orphan, "unknown_orphan_absence_verified": full,
            "pending_known_ids": missing, "upsert_candidate_ids": missing,
            "delete_candidate_ids": [], "declared_members_complete": complete,
            "promotion_ready": complete, "requires_fresh_db_validation": True,
            "production_promotion_supported": True}


def _check_cancel(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise IndexVectorError("Generation query was cancelled")


def _embed(pin, texts, deadline, stop_event=None):
    from google.genai import types

    from services.genai_client import embedding_client
    vectors = []
    for text in texts:
        _check_cancel(stop_event)
        arguments = {"model": pin["profile"]["model"], "dimension": DIMENSION,
            "task_type": "RETRIEVAL_QUERY", "local_counts": [len(text.encode("utf-8"))],
            "local_count_method": LOCAL_QUERY_COUNT_METHOD, "local_input_limit": LOCAL_QUERY_INPUT_LIMIT,
            "local_request_limit": LOCAL_QUERY_REQUEST_LIMIT}
        config = types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=DIMENSION,
            auto_truncate=False, http_options=types.HttpOptions(timeout=int(deadline.remaining() * 1000),
                retry_options=types.HttpRetryOptions(attempts=1)))
        if getattr(config, "auto_truncate", None) is not False:
            raise IndexVectorError("Embedding SDK cannot disable input truncation")
        response = embedding_client().models.embed_content(model=pin["profile"]["model"], contents=[text], config=config)
        vectors.append(validate_embedding_response([text], response, **arguments)[0][0])
    return vectors


def _query(pin, texts, top_k, year_min, year_max, stop_event=None, *, members=None, excluded_revisions=()):
    try:
        pin = _pin(pin)
        if (type(excluded_revisions) not in {list, tuple} or len(excluded_revisions) > MAX_EXCLUDED_REVISIONS
                or any(type(value) is not str or not _SHA.fullmatch(value) for value in excluded_revisions)
                or len(set(excluded_revisions)) != len(excluded_revisions)):
            raise IndexVectorError("Invalid excluded revision inventory")
        excluded = set(excluded_revisions)
        points = None
        if members is not None:
            if type(members) not in {list, tuple} or not 1 <= len(members) <= MAX_QUERY_BATCH:
                raise IndexVectorError("Document similarity selection exceeds its bound")
            from services.index_generations import manifest_sha256
            # This manifest verifies a selected bounded cohort, not a complete
            # generation. SQL hydration has already verified its membership.
            points = _member_points({**pin, "manifest_sha256": manifest_sha256(members)}, members)
            texts = [member["snapshot_json"]["text"] for member in members]
        if (type(texts) not in {list, tuple} or not 1 <= len(texts) <= MAX_QUERY_BATCH
                or type(top_k) is not int or not 1 <= top_k <= 100):
            raise IndexVectorError("Query inventory exceeds the bounded limit")
        for year in (year_min, year_max):
            if year is not None and (type(year) is not int or not 1 <= year <= 9999):
                raise IndexVectorError("Invalid query year bound")
        if year_min is not None and year_max is not None and year_min > year_max:
            raise IndexVectorError("Invalid query year interval")
        for text in texts if points is None else []:
            validate_embedding_inputs([text], model=MODEL, dimension=DIMENSION, task_type="RETRIEVAL_QUERY",
                local_counts=[len(text.encode("utf-8")) if type(text) is str else 0],
                local_count_method=LOCAL_QUERY_COUNT_METHOD, local_input_limit=LOCAL_QUERY_INPUT_LIMIT,
                local_request_limit=LOCAL_QUERY_REQUEST_LIMIT)
        deadline = _Deadline()
        _check_cancel(stop_event)
        transport = _transport(pin, deadline)
        vectors = ([point["feature_vector"] for point in points] if points is not None else
                   [[0.0] for _ in texts] if type(transport) is DisposableIndex else _embed(pin, texts, deadline, stop_event))
        _check_cancel(stop_event)
        rows = transport.search(pin, vectors, top_k, year_min, year_max, deadline,
                                excluded_revisions=excluded_revisions)
        deadline.remaining()
        _check_cancel(stop_event)
        if len(rows) != len(texts):
            raise IndexVectorError("Query result inventory is malformed")
        result = []
        for row in rows:
            if len(row) > top_k:
                raise IndexVectorError("Query result inventory is malformed")
            neighbors, seen = [], set()
            for point, distance in row:
                verified, revision = _verified_point(pin, point)
                if revision in excluded:
                    raise IndexVectorError("Query returned an excluded source revision")
                years = _numeric(point)
                if ((year_min is not None or year_max is not None) and
                        (not years or year_min is not None and years[0] < year_min
                         or year_max is not None and years[0] > year_max)):
                    raise IndexVectorError("Query result year metadata is incompatible")
                if (verified["vector_id"] in seen or type(distance) not in {int, float}
                        or not math.isfinite(distance) or not -COSINE_ROUNDOFF <= distance <= 2 + COSINE_ROUNDOFF):
                    raise IndexVectorError("Query result distance or identity is malformed")
                neighbors.append(Neighbor(distance=min(2.0, max(0.0, float(distance))), chunk_revision_sha256=revision, **verified))
                seen.add(verified["vector_id"])
            result.append(neighbors)
        return result
    except IndexVectorError:
        raise
    except Exception:
        raise IndexVectorError("Generation query is unavailable or unverifiable") from None


# Immutable-generation ANN candidates only, never hydrated text or rights.
# SQL member bindings, live lifecycle/evidence and the current pin are still
# checked on each request. A generation/runtime change selects a new key.
_QUERY_CACHE_TTL = 60.0
_QUERY_CACHE_MAX = 128
_query_cache = OrderedDict()
_query_cache_lock = threading.Lock()


def query(pin, query_text, *, top_k, year_min=None, year_max=None):
    checked = _pin(pin)  # runtime identity remains authoritative on cache hits
    key = hashlib.sha256(_canonical([checked, query_text, top_k, year_min, year_max])).digest()
    # Disposables remain uncached: tests/operators can mutate their transport.
    cacheable = checked["resource"]["backend"] == "vertex-public"
    if cacheable:
        with _query_cache_lock:
            entry = _query_cache.get(key)
            if entry is not None and entry[0] > time.monotonic():
                _query_cache.move_to_end(key)
                return list(entry[1])
            _query_cache.pop(key, None)
    result = _query(checked, [query_text], top_k, year_min, year_max)[0]
    if cacheable:
        with _query_cache_lock:
            _query_cache[key] = (time.monotonic() + _QUERY_CACHE_TTL, tuple(result))
            _query_cache.move_to_end(key)
            while len(_query_cache) > _QUERY_CACHE_MAX:
                _query_cache.popitem(last=False)
    return result


def query_many(pin, texts, *, top_k, stop_event=None):
    return _query(pin, texts, top_k, None, None, stop_event)


def query_members(pin, members, *, top_k, stop_event=None, excluded_revisions=()):
    """Document-to-document similarity from exact retained document vectors.

    No new embedding is needed, and long document inputs are not mislabeled as
    RETRIEVAL_QUERY. User-entered Search/Ask queries keep their separate task.
    """
    return _query(pin, None, top_k, None, None, stop_event, members=members,
                  excluded_revisions=excluded_revisions)
