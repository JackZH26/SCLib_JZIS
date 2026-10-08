"""Loopback-only staging API with distinct operator and node principals.

Production mode trusts a verified certificate ONLY from an authenticated local
TLS terminator. Uvicorn must run with proxy_headers=False. No scientific DB access.
"""
import hashlib
import hmac
import ipaddress
import ssl
from typing import Annotated, Literal, Optional
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from .contracts import (
    Claim,
    Closed,
    Completion,
    Drain,
    Failure,
    Heartbeat,
    Identifier,
    JobKind,
    JobSpec,
    NodeRegistration,
    Sha256,
)
from .store import ComputeError, Limits, Store


class Principal(Closed):
    role: Literal["operator", "node"]
    node_id: Optional[Identifier] = None  # noqa: UP045 - local Python 3.9 compatibility
    runtime_id: Optional[Identifier] = None  # noqa: UP045
    capabilities: list[JobKind] = Field(default_factory=list)

    @model_validator(mode="after")
    def node_grant(self):
        if self.role == "node" and (not self.node_id or not self.runtime_id or not self.capabilities):
            raise ValueError("node grant requires fixed identity, runtime and capabilities")
        if self.role == "operator" and (self.node_id or self.runtime_id or self.capabilities):
            raise ValueError("operator cannot impersonate a worker")
        return self


class AuthConfig(Closed):
    mode: Literal["mtls_proxy", "loopback_test"] = "mtls_proxy"
    proxy_token_sha256: Optional[Sha256] = None  # noqa: UP045
    certificate_sha256_principals: dict[str, Principal] = Field(default_factory=dict)
    test_bearer_sha256_principals: dict[str, Principal] = Field(default_factory=dict)

    @model_validator(mode="after")
    def closed_auth(self):
        mappings = [self.certificate_sha256_principals, self.test_bearer_sha256_principals]
        if any(len(key) != 64 or any(char not in "0123456789abcdef" for char in key) for mapping in mappings for key in mapping):
            raise ValueError("identity map keys must be lowercase SHA-256 digests")
        if self.mode == "mtls_proxy" and (not self.proxy_token_sha256 or not self.certificate_sha256_principals or self.test_bearer_sha256_principals):
            raise ValueError("mTLS mode needs proxy authentication and certificate pins; test tokens forbidden")
        if self.mode == "loopback_test" and (not self.test_bearer_sha256_principals or self.certificate_sha256_principals or self.proxy_token_sha256):
            raise ValueError("test mode must be explicit and cannot mix with proxy credentials")
        return self


class ServiceConfig(Closed):
    auth: AuthConfig
    # Enabling a kind does not install a solver. Initial deployment is dummy only.
    enabled_job_kinds: list[JobKind] = Field(default_factory=lambda: ["dummy"])
    limits: dict[str, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)


class BodyLimit:
    """Bound request bytes even with no or dishonest Content-Length header."""
    def __init__(self, app, binary_limit: int):
        self.app, self.binary_limit = app, binary_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        binary = scope["method"] == "PUT" and ("/inputs/" in scope["path"] or "/outputs/" in scope["path"])
        limit = self.binary_limit if binary else 65536
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        await self.app(scope, bounded_receive, send)


def create_app(store: Store, config: ServiceConfig) -> FastAPI:
    app = FastAPI(title="SCLib compute staging", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit, binary_limit=store.limits.max_artifact_bytes)
    app.state.store, app.state.config = store, config

    @app.exception_handler(ComputeError)
    async def compute_error(_request, exc: ComputeError):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    def loopback(request: Request):
        try:
            valid = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            valid = False
        if not valid:
            raise ComputeError("loopback_peer_required", 403)

    def principal(request: Request) -> Principal:
        loopback(request)
        auth = config.auth
        if auth.mode == "loopback_test":
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer ") or len(authorization) > 512:
                raise ComputeError("authentication_required", 401)
            identity = auth.test_bearer_sha256_principals.get(hashlib.sha256(authorization[7:].encode()).hexdigest())
        else:
            token = request.headers.get("x-sclib-proxy-token", "")
            if not token or len(token) > 512 or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), auth.proxy_token_sha256 or ""):
                raise ComputeError("proxy_authentication_required", 401)
            if request.headers.get("x-sclib-client-verify") != "SUCCESS":
                raise ComputeError("verified_client_certificate_required", 401)
            escaped = request.headers.get("x-sclib-client-certificate", "")
            if not escaped or len(escaped) > 16384:
                raise ComputeError("client_certificate_invalid", 401)
            try:
                pem = unquote(escaped, errors="strict")
                if pem.count("-----BEGIN CERTIFICATE-----") != 1 or pem.count("-----END CERTIFICATE-----") != 1:
                    raise ValueError("certificate chain not accepted as an identity")
                der = ssl.PEM_cert_to_DER_cert(pem)
            except (ValueError, UnicodeError):
                raise ComputeError("client_certificate_invalid", 401) from None
            identity = auth.certificate_sha256_principals.get(hashlib.sha256(der).hexdigest())
        if identity is None:
            raise ComputeError("identity_not_authorized", 403)
        return identity

    def operator(identity: Annotated[Principal, Depends(principal)]):
        if identity.role != "operator":
            raise ComputeError("operator_required", 403)
        return identity

    def node(identity: Annotated[Principal, Depends(principal)]):
        if identity.role != "node":
            raise ComputeError("node_required", 403)
        return identity

    Op = Annotated[Principal, Depends(operator)]
    Node = Annotated[Principal, Depends(node)]
    Token = Annotated[int, Header(alias="X-SCLib-Fencing-Token", ge=1)]
    Checksum = Annotated[Sha256, Header(alias="X-SCLib-Content-SHA256")]

    @app.get("/health")
    def health(request: Request):
        loopback(request)
        return {"status": "ok", "protocol": "sclib-compute/1", "mode": "private_staging", "scientific_publication_authority": False}

    @app.put("/compute/v1/inputs/{sha256}")
    async def stage_input(sha256: Sha256, request: Request, _identity: Op):
        return store.put_blob(await request.body(), sha256)

    @app.post("/compute/v1/jobs")
    def enqueue(spec: JobSpec, _identity: Op):
        if spec.kind not in config.enabled_job_kinds:
            raise ComputeError("job_kind_disabled", 422)
        return store.enqueue(spec)

    @app.post("/compute/v1/nodes/register")
    def register(registration: NodeRegistration, identity: Node):
        if registration.runtime_id != identity.runtime_id or not set(registration.capabilities) <= set(identity.capabilities):
            raise ComputeError("registration_exceeds_identity_grant", 403)
        return store.register(identity.node_id, registration)

    @app.post("/compute/v1/jobs/claim")
    def claim(body: Claim, identity: Node):
        return store.claim(identity.node_id, body.claim_request_id)

    @app.get("/compute/v1/attempts/{attempt_id}")
    def attempt(attempt_id: Identifier, identity: Node):
        return store.get_attempt(identity.node_id, attempt_id)

    @app.post("/compute/v1/attempts/{attempt_id}/heartbeat")
    def heartbeat(attempt_id: Identifier, beat: Heartbeat, identity: Node):
        return store.heartbeat(identity.node_id, attempt_id, beat)

    @app.get("/compute/v1/attempts/{attempt_id}/inputs/{name}")
    def download(attempt_id: Identifier, name: Identifier, token: Token, identity: Node):
        return Response(store.input_file(identity.node_id, attempt_id, name, token), media_type="application/octet-stream")

    @app.put("/compute/v1/attempts/{attempt_id}/outputs/{name}")
    async def upload(attempt_id: Identifier, name: Identifier, token: Token, checksum: Checksum, request: Request, identity: Node):
        return store.attach_output(identity.node_id, attempt_id, name, token, await request.body(), checksum)

    @app.post("/compute/v1/attempts/{attempt_id}/complete")
    def complete(attempt_id: Identifier, completion: Completion, identity: Node):
        return store.complete(identity.node_id, attempt_id, completion)

    @app.post("/compute/v1/attempts/{attempt_id}/fail")
    def fail(attempt_id: Identifier, failure: Failure, identity: Node):
        return store.fail(identity.node_id, attempt_id, failure)

    @app.post("/compute/v1/jobs/{job_id}/cancel")
    def cancel(job_id: Identifier, _identity: Op):
        return store.cancel(job_id)

    @app.post("/compute/v1/nodes/{node_id}/drain")
    def drain(node_id: Identifier, body: Drain, _identity: Op):
        return store.drain(node_id, body.enabled)

    @app.post("/compute/v1/reconcile")
    def reconcile(_identity: Op):
        return store.reconcile()

    @app.get("/compute/v1/status")
    def status(_identity: Op):
        return store.status()

    @app.get("/compute/v1/events")
    def events(identity: Annotated[Principal, Depends(principal)], after: Annotated[int, Query(ge=0)] = 0):
        return store.events(identity.node_id if identity.role == "node" else None, after)

    return app


def configured_store(root, config: ServiceConfig) -> Store:
    return Store(root, Limits(**config.limits))
