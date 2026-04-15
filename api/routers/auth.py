"""Auth router: register / verify / login / me / keys / keys/{id}.

All six endpoints from PROJECT_SPEC.md section 7. The flow is:
  register (user created, is_active=False, verification token emailed)
    -> verify (is_active=True, first API key issued, welcome email)
    -> login (JWT for session management, e.g. dashboard)
  Other API calls authenticate via X-API-Key header (see deps below).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

from models import get_db
from models.db import ApiKey, EmailVerification, User
from models.user import (
    ApiKeyCreate,
    ApiKeyWithSecret,
    LoginRequest,
    MessageResponse,
    RegisterResponse,
    TokenResponse,
    UserCreate,
    UserRead,
    VerifyResponse,
)
from services import auth_service
from services.email import send_verification, send_welcome

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Dependencies (re-exported so Phase 3 routers can enforce auth via X-API-Key)
# ---------------------------------------------------------------------------

async def current_user_from_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve X-API-Key header to an active User.

    Raises 401 if missing/invalid/revoked. Phase 3 routers will Depend on
    this; routers that also allow guests will have their own guarded
    dependency that tolerates a missing header.
    """
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key")
    key_hash = auth_service.hash_api_key(x_api_key)
    q = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked.is_(False))
    )
    ak = q.scalar_one_or_none()
    if ak is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    user = await db.get(User, ak.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    # Targeted UPDATE to avoid the read-modify-write race when the
    # same key is used concurrently from multiple requests. SQLAlchemy's
    # ORM update on a detached attribute would serialize on the row
    # version; an explicit UPDATE … WHERE id= is atomic at the DB level.
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == ak.id)
        .values(last_used=datetime.now(timezone.utc))
    )
    await db.commit()
    return user


async def current_user_from_jwt(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = auth_service.decode_access_token(token)
    except Exception as e:  # jwt.PyJWTError and variants
        # Never leak the exception class / message to the client — it
        # discloses whether the token is expired vs. signature-invalid.
        log.info("JWT decode failed: %s", e)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from e
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        age=body.age,
        institution=body.institution,
        country=body.country,
        research_area=body.research_area,
        purpose=body.purpose,
        password_hash=auth_service.hash_password(body.password),
        is_active=False,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email already registered") from None

    token = auth_service.generate_verification_token()
    db.add(EmailVerification(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ))
    await db.commit()
    await db.refresh(user)

    await send_verification(user.email, user.name, token)

    return RegisterResponse(
        user=UserRead.model_validate(user),
        message="Verification email sent. Check your inbox (and spam).",
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify(token: str, db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(EmailVerification).where(EmailVerification.token == token))
    ev = q.scalar_one_or_none()
    if ev is None or ev.used:
        raise HTTPException(400, "Invalid or already-used verification token")
    if ev.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Verification token expired")

    user = await db.get(User, ev.user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    user.email_verified = True
    user.is_active = True
    ev.used = True

    plain, key_hash, key_prefix = auth_service.generate_api_key()
    db.add(ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name="Default (created on verification)",
    ))
    await db.commit()
    await db.refresh(user)

    await send_welcome(user.email, user.name, plain)

    return VerifyResponse(user=UserRead.model_validate(user), api_key=plain)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(User).where(User.email == body.email))
    user = q.scalar_one_or_none()
    # Constant-time branch: run a bcrypt compare even when the user
    # does not exist, so attackers cannot enumerate valid emails by
    # measuring response latency.
    if user is None:
        auth_service.verify_password_dummy(body.password)
        raise HTTPException(401, "Invalid email or password")
    if not auth_service.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "Email not verified")
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    token, expires_in = auth_service.create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(current_user_from_jwt)):
    return UserRead.model_validate(user)


@router.post("/keys", response_model=ApiKeyWithSecret, status_code=201)
async def create_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    plain, key_hash, key_prefix = auth_service.generate_api_key()
    ak = ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
    )
    db.add(ak)
    await db.commit()
    await db.refresh(ak)
    return ApiKeyWithSecret(
        id=ak.id,
        key_prefix=ak.key_prefix,
        name=ak.name,
        created_at=ak.created_at,
        last_used=ak.last_used,
        revoked=ak.revoked,
        key=plain,
    )


@router.delete("/keys/{key_id}", response_model=MessageResponse)
async def revoke_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    ak = await db.get(ApiKey, key_id)
    if ak is None or ak.user_id != user.id:
        raise HTTPException(404, "Key not found")
    ak.revoked = True
    await db.commit()
    return MessageResponse(message="Key revoked")
