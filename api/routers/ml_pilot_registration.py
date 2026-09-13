"""Default-off private prospective registration and each participant's own act."""

from __future__ import annotations

import asyncio
import re
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.db import get_engine
from routers import ml_use_preflight as private
from routers.ml_use_governance import Identifier, Sha, _session_actor
from routers.ml_use_rights import body
from routers.ml_use_submissions import Lookup
from routers.research_distributions import _request_schema
from services import ml_pilot_attestation_contract as declaration_contract
from services import ml_pilot_attestations as attestations
from services import ml_pilot_registration as service
from services import ml_pilot_registration_documents as documents
from services import ml_pilot_registration_worker as worker
from services import ml_pilot_review_admission as review_admission
from services import ml_pilot_review_documents as review_documents
from services import ml_pilot_review_worker as review_worker
from services.ml_pilot_documents import canonical
from services.ml_use_access import HEADERS
from services.ml_use_preflight import match
from services.research_access import active_grant


class PilotRoute(private.PrivateRoute):
    timeout_seconds = 60

    def get_route_handler(self):
        parent = super().get_route_handler()

        async def guarded(request):
            try:
                return await parent(request)
            except HTTPException as exc:
                if exc.status_code == 503 and getattr(
                    request.state, "pilot_commit_attempted", False
                ):
                    raise HTTPException(
                        503,
                        "ML pilot outcome unknown; recover the exact request",
                        headers={**HEADERS, "X-Operation-State": "unknown"},
                    ) from None
                raise

        return guarded


def enabled():
    if not get_settings().ml_pilot_registration_enabled:
        raise private.rejected(404)


router = APIRouter(
    prefix="/ml/pilots",
    tags=["ml-pilot-registration"],
    route_class=PilotRoute,
    dependencies=[Depends(enabled)],
)


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    expected_intent_sha256: Sha | None = None
    dry_run: bool = True


class RegisterControl(Control):
    curator_grant_id: Identifier


class AcceptControl(Control):
    participant_id: Identifier
    participant_sha256: Sha
    registration_sha256: Sha
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,159}$")
    supersedes_id: Identifier | None
    supersedes_sha256: Sha | None


class ProtectiveDecision(AcceptControl):
    decision: Literal["decline", "withdraw"]


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reviewer_alias: str = Field(min_length=1, max_length=200)
    user_id: Identifier
    reviewer_grant_id: Identifier


class Files(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["ml08-registration-upload/1.0.0"]
    selection_file_sha256: Sha
    protocol_file_sha256: Sha
    selection_sha256: Sha
    selection_base64: str = Field(min_length=1, max_length=11184812)
    protocol_base64: str = Field(min_length=1, max_length=11184812)


class RegisterUpload(Files):
    operation: Literal["register"]
    parameters: RegisterControl
    bindings: list[Binding] = Field(min_length=2, max_length=30)


class AcceptUpload(Files):
    operation: Literal["accept"]
    parameters: AcceptControl


class RegistrationRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    registration_id: Identifier
    registration_sha256: Sha


class ReviewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    participant_id: Identifier
    participant_sha256: Sha
    registration_sha256: Sha


class ReviewUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["ml08-review-upload/1.0.0"]
    parameters: ReviewReference
    selection_file_sha256: Sha
    protocol_file_sha256: Sha
    reviews_file_sha256: Sha
    conclusion_file_sha256: Sha
    selection_sha256: Sha
    review_log_sha256: Sha
    selection_base64: str = Field(min_length=1, max_length=11184812)
    protocol_base64: str = Field(min_length=1, max_length=11184812)
    reviews_base64: str = Field(min_length=1, max_length=11184812)
    conclusion_base64: str = Field(min_length=1, max_length=11184812)


class AttestationControl(AcceptControl):
    expected_intent_sha256: Sha | None = Field(...)
    dry_run: bool = Field(..., strict=True)
    declaration_version: Literal["ml08-own-review-declaration/1.0.0"]
    declaration_sha256: Sha
    declaration_acknowledged: bool = Field(..., strict=True)


class AttestationUpload(ReviewUpload):
    version: Literal["ml08-review-attestation-upload/1.0.0"]
    parameters: AttestationControl


def attestations_enabled():
    if not get_settings().ml_pilot_attestations_enabled:
        raise private.rejected(404)


def review_enabled():
    if not get_settings().ml_pilot_review_intake_enabled:
        raise private.rejected(404)


def response(value):
    raw = canonical(value)
    if len(raw) > 128 * 1024:
        raise ValueError("pilot_response_limit")
    return Response(raw, media_type="application/json", headers=HEADERS)


async def read(user, function=None, args=None, *, registrar=False):
    async with AsyncSession(
        get_engine().execution_options(isolation_level="REPEATABLE READ")
    ) as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await _session_actor(db, user, admin=registrar)
            try:
                if function is not None:
                    return await function(db, actor_user_id=user.id, **(args or {}))
                return (
                    await service.registrar_admission(db, user.id)
                    if registrar
                    else {"actor_user_id": str(user.id)}
                )
            except service.PilotNotObserved:
                raise private.rejected(404) from None


async def write(request, user, function, args, *, version=service.VERSION):
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as db:
        async with db.begin():
            await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
            await _session_actor(db, user, lock=True)
            try:
                result = await function(db, actor_user_id=user.id, **args)
            except service.PilotNotObserved:
                raise private.rejected(404) from None
            prepared = response(
                {"version": version, "committed": not args["dry_run"], "result": result}
            )
            if args["dry_run"] or result["replayed"]:
                await db.rollback()
            else:
                request.state.pilot_commit_attempted = True
    return prepared


async def upload(request, *, limit=documents.MAX_ENVELOPE_BYTES):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
        or request.headers.get("content-encoding", "identity") != "identity"
    ):
        raise private.rejected(415)
    length = request.headers.get("content-length")
    if length is not None and (not re.fullmatch(r"[0-9]{1,8}", length) or int(length) > limit):
        raise private.rejected(413)
    raw, chunks = bytearray(), 0
    async with asyncio.timeout(10):
        async for part in request.stream():
            chunks += 1
            if chunks > 4096 or len(raw) + len(part) > limit:
                raise private.rejected(413)
            raw.extend(part)
    return bytes(raw)


async def acceptance_admission(db, *, actor_user_id, participant_id, participant_sha256):
    member, reg = await service.own_participant(
        db, actor_user_id, participant_id, participant_sha256
    )
    await active_grant(db, actor_user_id, role="reviewer", grant_id=member["reviewer_grant_id"])
    await service.registrar_admission(db, reg["actor_user_id"], reg["curator_grant_id"])
    return {
        "participant_id": str(member["id"]),
        "participant_sha256": member["record_sha256"],
        "registration_sha256": reg["record_sha256"],
    }


@router.get("/participant-access")
async def participant_access(user: private.AuthenticatedUser):
    # Active session only: exact invitation admission remains separate, and
    # protective decisions must remain accessible after reviewer-role revocation.
    return response({"version": service.VERSION, **await read(user), **service.boundary()})


@router.get("/registrar-access")
async def access(user: private.AuthenticatedUser):
    return response(
        {"version": service.VERSION, **await read(user, registrar=True), **service.boundary()}
    )


@router.post("/registrations", openapi_extra=_request_schema(RegisterUpload))
async def register(request: Request, user: private.AuthenticatedUser):
    await read(user, registrar=True)
    raw = await upload(request)
    await read(user, registrar=True)
    checked = await worker.check_in_worker(raw)
    match(checked["operation"] == "register")
    args = RegisterControl.model_validate(checked["parameters"]).model_dump()
    return await write(
        request,
        user,
        service.register,
        {
            **args,
            "commitment": checked["document_check"],
            "implementation": checked["implementation"],
        },
    )


@router.post("/participation/accept", openapi_extra=_request_schema(AcceptUpload))
async def accept(request: Request, user: private.AuthenticatedUser):
    # Own exact invitation is admitted before receiving private document bytes.
    reference = {}
    for header, key in (
        ("X-SCLib-Participant-Id", "participant_id"),
        ("X-SCLib-Participant-Sha256", "participant_sha256"),
    ):
        values = request.headers.getlist(header)
        if len(values) != 1:
            raise private.rejected(400)
        reference[key] = values[0]
    await read(user, acceptance_admission, reference)
    raw = await upload(request)
    await read(user, acceptance_admission, reference)
    checked = await worker.check_in_worker(raw)
    match(checked["operation"] == "accept")
    args = AcceptControl.model_validate(checked["parameters"]).model_dump()
    match(all(args[k] == v for k, v in reference.items()))
    return await write(
        request,
        user,
        service.decide,
        {**args, "decision": "accept", "document_check": checked["document_check"]},
    )


@router.post("/participation/decisions", openapi_extra=_request_schema(ProtectiveDecision))
async def protect(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return await write(request, user, service.decide, await body(request, ProtectiveDecision))


@router.post(
    "/review-preflight",
    dependencies=[Depends(review_enabled)],
    openapi_extra=_request_schema(ReviewUpload),
)
async def review_preflight(request: Request, user: private.AuthenticatedUser):
    # Authenticate this exact participant before receiving any source-bearing
    # files. This read-only endpoint cannot record a scientific endorsement.
    reference = {}
    for header, key in (
        ("X-SCLib-Participant-Id", "participant_id"),
        ("X-SCLib-Participant-Sha256", "participant_sha256"),
    ):
        values = request.headers.getlist(header)
        if len(values) != 1:
            raise private.rejected(400)
        reference[key] = values[0]
    await read(user, acceptance_admission, reference)
    raw = await upload(request, limit=review_documents.MAX_ENVELOPE_BYTES)
    await read(user, acceptance_admission, reference)
    checked = await review_worker.check_in_worker(raw)
    args = ReviewReference.model_validate(checked["parameters"]).model_dump()
    match(all(args[k] == value for k, value in reference.items()))
    return response(
        await read(
            user,
            review_admission.inspect,
            {
                **args,
                "document_check": checked["document_check"],
                "implementation": checked["implementation"],
            },
        )
    )


@router.get("/review-attestations/declaration", dependencies=[Depends(attestations_enabled)])
async def declaration_wording(user: private.AuthenticatedUser):
    actor = await read(user)
    return response(
        {
            "version": attestations.VERSION,
            **actor,
            "declaration_version": declaration_contract.VERSION,
            "declaration_text": declaration_contract.TEXT,
            "declaration_sha256": declaration_contract.SHA256,
            **attestations.boundary(),
        }
    )


@router.post(
    "/review-attestations",
    dependencies=[Depends(review_enabled), Depends(attestations_enabled)],
    openapi_extra=_request_schema(AttestationUpload),
)
async def attest_review(request: Request, user: private.AuthenticatedUser):
    reference = {}
    for header, key in (
        ("X-SCLib-Participant-Id", "participant_id"),
        ("X-SCLib-Participant-Sha256", "participant_sha256"),
    ):
        values = request.headers.getlist(header)
        if len(values) != 1:
            raise private.rejected(400)
        reference[key] = values[0]
    await read(user, acceptance_admission, reference)
    raw = await upload(request, limit=review_documents.MAX_ENVELOPE_BYTES)
    await read(user, acceptance_admission, reference)
    checked = await review_worker.check_in_worker(raw, attestation=True)
    args = AttestationControl.model_validate(checked["parameters"]).model_dump()
    match(all(args[key] == value for key, value in reference.items()))
    return await write(
        request,
        user,
        attestations.decide,
        {
            **args,
            "action": "attest",
            "document_check": checked["document_check"],
            "implementation": checked["implementation"],
        },
        version=attestations.VERSION,
    )


@router.post(
    "/review-attestations/withdraw",
    dependencies=[Depends(attestations_enabled)],
    openapi_extra=_request_schema(AttestationControl),
)
async def withdraw_attestation(request: Request, user: private.AuthenticatedUser):
    # No source upload or current reviewer grant is required for a protective act.
    await read(user)
    return await write(
        request,
        user,
        attestations.decide,
        {**await body(request, AttestationControl), "action": "withdraw"},
        version=attestations.VERSION,
    )


@router.post(
    "/review-attestations/inspect",
    dependencies=[Depends(attestations_enabled)],
    openapi_extra=_request_schema(ReviewReference),
)
async def inspect_attestation(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return response(await read(user, attestations.inspect, await body(request, ReviewReference)))


@router.post(
    "/review-attestations/outcome",
    dependencies=[Depends(attestations_enabled)],
    openapi_extra=_request_schema(Lookup),
)
async def attestation_outcome(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return response(
        {
            "version": attestations.VERSION,
            "committed": True,
            "result": await read(user, attestations.outcome, await body(request, Lookup)),
        }
    )


@router.post("/inspect", openapi_extra=_request_schema(RegistrationRef))
async def inspect(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return response(await read(user, service.inspect, await body(request, RegistrationRef)))


@router.post("/registrations/outcome", openapi_extra=_request_schema(Lookup))
async def registration_outcome(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return response(
        {
            "version": service.VERSION,
            "committed": True,
            "result": await read(
                user, service.outcome, {**await body(request, Lookup), "kind": "registration"}
            ),
        }
    )


@router.post("/participation/outcome", openapi_extra=_request_schema(Lookup))
async def participation_outcome(request: Request, user: private.AuthenticatedUser):
    await read(user)
    return response(
        {
            "version": service.VERSION,
            "committed": True,
            "result": await read(
                user, service.outcome, {**await body(request, Lookup), "kind": "participation"}
            ),
        }
    )
