"""Auth router: register / verify / login / me / keys / keys/{id} / google.

Endpoints from PROJECT_SPEC.md section 7, extended with Google OAuth.
The flow is:
  register (user created, is_active=False, verification token emailed)
    -> verify (is_active=True, first API key issued, welcome email)
    -> /login (bearer JWT for non-browser clients)
    -> /session/login (HttpOnly browser session for the dashboard)
  Google OAuth:
    -> /google/login (redirect to Google consent screen)
    -> /google/callback (handle Google redirect, establish browser session)
  Other API calls authenticate via X-API-Key header (see deps below).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import RedirectResponse

from config import allowed_browser_origins, get_settings
from models import get_db
from models.db import (
    ApiKey,
    AskHistory,
    AuthAuditEvent,
    Bookmark,
    EmailVerification,
    PasswordResetToken,
    User,
)
from models.privacy import AccountDataExport, AccountDeletionRequest
from models.user import (
    ApiKeyCreate,
    ApiKeyRead,
    ApiKeyWithSecret,
    BrowserSessionResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterResponse,
    TokenResponse,
    UsageStats,
    UserCreate,
    UserRead,
    UserUpdate,
    VerifyResponse,
)
from services import auth_service
from services.auth_audit import add_auth_audit
from services.auth_security import (
    AuthRateLimited,
    AuthSecurityUnavailable,
    clear_login_failures,
    enforce_auth_attempt,
    normalize_account,
    record_login_failure,
)
from services.email import send_password_reset, send_verification, send_welcome
from services.google_oauth import get_oauth
from services.rate_limit import (
    get_user_remaining,
    get_user_today_used,
    get_user_week_used,
)
from services.request_context import client_ip
from services.session_config import (
    BrowserSessionConfig,
    build_browser_session_config,
    clear_browser_session_cookie,
    set_browser_session_cookie,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_LOGIN_ERROR = "Invalid email or password"
_GENERIC_RESET_MESSAGE = (
    "If the account can use password sign-in, a reset link has been sent."
)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# X-API-Key auth for data endpoints lives in routers.deps.require_identity —
# that path both validates the key AND enforces the per-user daily quota,
# so there is no second implementation here. JWT auth for account-
# management endpoints is below.

async def current_user_from_jwt(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    settings = get_settings()
    session = build_browser_session_config(
        settings.environment,
        settings.jwt_expiry_hours * 3600,
    )
    token: str | None = None
    from_cookie = False
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    elif request.cookies.get(session.cookie_name):
        token = request.cookies[session.cookie_name]
        from_cookie = True
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing browser session or bearer token",
        )
    if from_cookie:
        _validate_cookie_request_origin(request)
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
    try:
        token_version = int(payload.get("sv", 0))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from None
    if token_version != user.session_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return user


def _browser_session_config() -> BrowserSessionConfig:
    settings = get_settings()
    return build_browser_session_config(
        settings.environment,
        settings.jwt_expiry_hours * 3600,
    )


def _validate_cookie_request_origin(request: Request) -> None:
    """Require an allowlisted Origin for cookie-authenticated writes."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin or origin not in allowed_browser_origins(get_settings()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Untrusted request origin")


async def _enforce_auth_security(
    action: str,
    request: Request,
    account: str,
) -> None:
    """Translate the Redis-backed security layer into stable HTTP errors."""
    try:
        await enforce_auth_attempt(action, client_ip(request), account)
    except AuthRateLimited as exc:
        log.warning(
            "auth_rate_limited action=%s scope=%s ip_hash_only=true",
            action,
            exc.scope,
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "auth_rate_limited",
                "message": "Too many authentication attempts. Try again later.",
            },
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except AuthSecurityUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = normalize_account(str(body.email))
    await _enforce_auth_security("register", request, email)
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalar_one_or_none():
        add_auth_audit(
            db,
            request,
            event_type="register",
            outcome="duplicate",
            account=email,
        )
        await db.commit()
        raise HTTPException(409, "Email already registered")

    user = User(
        email=email,
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
        add_auth_audit(
            db,
            request,
            event_type="register",
            outcome="duplicate",
            account=email,
        )
        await db.commit()
        raise HTTPException(409, "Email already registered") from None

    token = auth_service.generate_verification_token()
    db.add(EmailVerification(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ))
    add_auth_audit(
        db,
        request,
        event_type="register",
        outcome="created",
        account=email,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(user)

    await send_verification(user.email, user.name, token)

    return RegisterResponse(
        user=UserRead.model_validate(user),
        message="Verification email sent. Check your inbox (and spam).",
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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
    add_auth_audit(
        db,
        request,
        event_type="email_verify",
        outcome="verified",
        account=user.email,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(user)

    await send_welcome(user.email, user.name, plain)

    return VerifyResponse(user=UserRead.model_validate(user), api_key=plain)


async def _authenticate_password(
    body: LoginRequest,
    request: Request,
    db: AsyncSession,
    *,
    flow: str,
) -> User:
    email = normalize_account(str(body.email))
    ip = client_ip(request)
    await _enforce_auth_security("login", request, email)
    q = await db.execute(select(User).where(func.lower(User.email) == email))
    user = q.scalar_one_or_none()
    # Constant-time branch: run a bcrypt compare even when the user
    # does not exist, so attackers cannot enumerate valid emails by
    # measuring response latency.
    if user is None:
        auth_service.verify_password_dummy(body.password)
        password_valid = False
    elif not user.password_hash:
        # Keep Google-only and unknown accounts on the same timing/message path.
        auth_service.verify_password_dummy(body.password)
        password_valid = False
    else:
        password_valid = auth_service.verify_password(body.password, user.password_hash)
    if not password_valid:
        try:
            retry_after = await record_login_failure(ip, email)
        except AuthSecurityUnavailable:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Authentication service temporarily unavailable",
                headers={"Retry-After": "30"},
            ) from None
        add_auth_audit(
            db,
            request,
            event_type="login",
            outcome="invalid_credentials",
            account=email,
            user_id=user.id if user else None,
            details={"flow": flow},
        )
        await db.commit()
        headers = {"Retry-After": str(retry_after)} if retry_after > 0 else None
        raise HTTPException(401, _GENERIC_LOGIN_ERROR, headers=headers)
    if not user.is_active:
        add_auth_audit(
            db,
            request,
            event_type="login",
            outcome="inactive",
            account=email,
            user_id=user.id,
            details={"flow": flow},
        )
        await db.commit()
        raise HTTPException(403, "Email not verified")
    try:
        await clear_login_failures(ip, email)
    except AuthSecurityUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Authentication service temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from None
    user.last_login = datetime.now(timezone.utc)
    add_auth_audit(
        db,
        request,
        event_type="login",
        outcome="success",
        account=email,
        user_id=user.id,
        details={"flow": flow},
    )
    await db.commit()
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Issue a bearer JWT for non-browser clients."""
    user = await _authenticate_password(body, request, db, flow="bearer")
    token, expires_in = auth_service.create_access_token(
        user.id, user.session_version
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/session/login", response_model=BrowserSessionResponse)
async def browser_session_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a browser without exposing its JWT to JavaScript."""
    _validate_cookie_request_origin(request)
    user = await _authenticate_password(body, request, db, flow="browser")
    token, expires_in = auth_service.create_access_token(
        user.id, user.session_version
    )
    set_browser_session_cookie(response, token, _browser_session_config())
    return BrowserSessionResponse(expires_in=expires_in)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
):
    """End the browser session without invalidating bearer/API credentials."""
    _validate_cookie_request_origin(request)
    clear_browser_session_cookie(response, _browser_session_config())
    return MessageResponse(message="Signed out")


@router.post("/password-reset/request", response_model=MessageResponse)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Issue a one-time reset link without revealing account existence."""
    email = normalize_account(str(body.email))
    await _enforce_auth_security("password_reset", request, email)
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    token: str | None = None
    if user is not None and user.is_active and user.password_hash:
        now = datetime.now(timezone.utc)
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        token, token_hash = auth_service.generate_password_reset_token()
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(
                minutes=get_settings().password_reset_expiry_minutes
            ),
        ))

    add_auth_audit(
        db,
        request,
        event_type="password_reset_request",
        outcome="issued" if token else "ignored",
        account=email,
        user_id=user.id if user else None,
    )
    await db.commit()

    if token is not None and user is not None:
        await send_password_reset(user.email, user.name, token)
    return MessageResponse(message=_GENERIC_RESET_MESSAGE)


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    body: PasswordResetConfirm,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Consume a reset grant, change the password, and revoke all JWTs."""
    # The opaque token acts as the account dimension until the grant is
    # resolved. It is HMACed before reaching Redis and never appears in logs.
    await _enforce_auth_security("password_reset", request, body.token)
    token_hash = auth_service.hash_password_reset_token(body.token)
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    reset = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        add_auth_audit(
            db,
            request,
            event_type="password_reset_confirm",
            outcome="invalid_token",
        )
        await db.commit()
        raise HTTPException(400, "Invalid or expired password reset link")

    user = await db.get(User, reset.user_id)
    if user is None or not user.is_active or not user.password_hash:
        reset.used_at = now
        add_auth_audit(
            db,
            request,
            event_type="password_reset_confirm",
            outcome="ineligible_account",
            user_id=user.id if user else None,
        )
        await db.commit()
        raise HTTPException(400, "Invalid or expired password reset link")

    user.password_hash = auth_service.hash_password(body.new_password)
    user.session_version += 1
    reset.used_at = now
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.id != reset.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    add_auth_audit(
        db,
        request,
        event_type="password_reset_confirm",
        outcome="success",
        account=user.email,
        user_id=user.id,
    )
    await db.commit()
    clear_browser_session_cookie(response, _browser_session_config())
    return MessageResponse(
        message="Password updated. Sign in again on each device."
    )


@router.post("/sessions/revoke-all", response_model=MessageResponse)
async def revoke_all_sessions(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    """Invalidate all bearer/browser JWTs issued before this operation."""
    user.session_version += 1
    add_auth_audit(
        db,
        request,
        event_type="session_revoke_all",
        outcome="success",
        account=user.email,
        user_id=user.id,
    )
    await db.commit()
    clear_browser_session_cookie(response, _browser_session_config())
    return MessageResponse(message="All browser and bearer sessions revoked")


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(current_user_from_jwt)):
    return UserRead.model_validate(user)


@router.get("/me/export", response_model=AccountDataExport)
async def export_me(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> AccountDataExport:
    """Return a portable copy of data directly associated with the account.

    Password hashes, API-key hashes, and verification/reset token material
    are excluded because returning authentication secrets would weaken the
    account. Non-secret metadata is included so the export remains useful
    for access and audit purposes.
    """
    api_keys = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user.id)
            .order_by(ApiKey.created_at.asc())
        )
    ).scalars().all()
    history = (
        await db.execute(
            select(AskHistory)
            .where(AskHistory.user_id == user.id)
            .order_by(AskHistory.created_at.asc())
        )
    ).scalars().all()
    bookmarks = (
        await db.execute(
            select(Bookmark)
            .where(Bookmark.user_id == user.id)
            .order_by(Bookmark.created_at.asc())
        )
    ).scalars().all()
    verifications = (
        await db.execute(
            select(EmailVerification)
            .where(EmailVerification.user_id == user.id)
            .order_by(EmailVerification.created_at.asc())
        )
    ).scalars().all()
    resets = (
        await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id)
            .order_by(PasswordResetToken.created_at.asc())
        )
    ).scalars().all()
    security_events = (
        await db.execute(
            select(AuthAuditEvent)
            .where(AuthAuditEvent.user_id == user.id)
            .order_by(AuthAuditEvent.created_at.asc())
        )
    ).scalars().all()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="sclib-account-{user.id}.json"'
    )
    return AccountDataExport(
        generated_at=datetime.now(timezone.utc),
        profile={
            "id": user.id,
            "email": user.email,
            "email_verified": user.email_verified,
            "name": user.name,
            "institution": user.institution,
            "country": user.country,
            "age": user.age,
            "research_area": user.research_area,
            "purpose": user.purpose,
            "bio": user.bio,
            "orcid": user.orcid,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login": user.last_login,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "is_reviewer": user.is_reviewer,
            "auth_provider": user.auth_provider,
            "google_sub": user.google_sub,
            "avatar_url": user.avatar_url,
            "scopes": user.scopes,
            "profile": user.profile,
        },
        api_keys=[
            {
                "id": key.id,
                "key_prefix": key.key_prefix,
                "name": key.name,
                "created_at": key.created_at,
                "last_used": key.last_used,
                "revoked": key.revoked,
                "revoked_at": key.revoked_at,
                "total_requests": key.total_requests,
            }
            for key in api_keys
        ],
        ask_history=[
            {
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "sources": item.sources,
                "tokens_used": item.tokens_used,
                "latency_ms": item.latency_ms,
                "language": item.language,
                "created_at": item.created_at,
            }
            for item in history
        ],
        bookmarks=[
            {
                "id": item.id,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "created_at": item.created_at,
            }
            for item in bookmarks
        ],
        email_verifications=[
            {
                "id": item.id,
                "expires_at": item.expires_at,
                "used": item.used,
                "created_at": item.created_at,
            }
            for item in verifications
        ],
        password_resets=[
            {
                "id": item.id,
                "expires_at": item.expires_at,
                "used_at": item.used_at,
                "created_at": item.created_at,
            }
            for item in resets
        ],
        security_events=[
            {
                "id": item.id,
                "event_type": item.event_type,
                "outcome": item.outcome,
                "details": item.details,
                "created_at": item.created_at,
            }
            for item in security_events
        ],
    )


@router.patch("/me", response_model=UserRead)
async def update_me(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    """Update whitelisted profile fields on the current user.

    Email / id / auth_provider / is_active are deliberately NOT editable
    — they're system-owned identity. Clients PATCH only the fields they
    want to change; omitting a key leaves the existing value untouched.
    Passing an explicit ``null`` clears the field (useful for "remove my
    institution").
    """
    # Use exclude_unset so omitted keys don't overwrite stored values.
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/me", response_model=MessageResponse)
async def delete_me(
    body: AccountDeletionRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
) -> MessageResponse:
    """Permanently delete the current non-admin account and private rows.

    The exact account email and, for password-capable accounts, the current
    password provide a fresh confirmation beyond possession of a session.
    Security audit rows are retained only in de-identified form by the
    database's ``ON DELETE SET NULL`` constraint.
    """
    if user.is_admin:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Administrator accounts must be demoted before deletion",
        )
    if normalize_account(str(body.email)) != normalize_account(user.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account confirmation did not match")
    if user.password_hash and (
        not body.current_password
        or not auth_service.verify_password(body.current_password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account confirmation did not match")

    deleted_user_id = user.id
    add_auth_audit(
        db,
        request,
        event_type="account_delete",
        outcome="success",
        account=user.email,
        user_id=user.id,
    )
    # Make the audit row exist before deleting its referenced account; the
    # FK then clears user_id while retaining the privacy-preserving event.
    await db.flush()
    await db.delete(user)
    await db.commit()
    clear_browser_session_cookie(response, _browser_session_config())
    log.warning("account self-deleted user_id=%s", deleted_user_id)
    return MessageResponse(message="Account and associated private data deleted")


@router.get("/keys", response_model=list[ApiKeyRead])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    """All API keys owned by the current user, newest first.

    Includes revoked keys (dashboard shows them greyed out with the
    revocation timestamp) so the user can audit historical activity.
    """
    q = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    return [ApiKeyRead.model_validate(k) for k in q.scalars().all()]


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
        revoked_at=ak.revoked_at,
        total_requests=ak.total_requests,
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
    if not ak.revoked:
        ak.revoked = True
        ak.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return MessageResponse(message="Key revoked")


@router.get("/usage", response_model=UsageStats)
async def usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user_from_jwt),
):
    """Per-user quota + historical request counters for the dashboard.

    Today / week numbers are read from Redis (cheap, one MGET).
    All-time is the SUM of ``total_requests`` across the user's API
    keys — that's the canonical count since the quota counter itself
    only spans a rolling 7 days of retention.
    """
    settings = get_settings()
    today_used = await get_user_today_used(user.id)
    today_remaining = await get_user_remaining(user.id)
    week_used = await get_user_week_used(user.id)

    all_time_q = await db.execute(
        select(func.coalesce(func.sum(ApiKey.total_requests), 0))
        .where(ApiKey.user_id == user.id)
    )
    all_time_used = int(all_time_q.scalar_one() or 0)

    return UsageStats(
        today_used=today_used,
        today_remaining=today_remaining,
        daily_limit=settings.registered_daily_limit,
        week_used=week_used,
        all_time_used=all_time_used,
    )


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@router.get("/google/login", tags=["auth"])
async def google_login(request: Request):
    """Redirect to Google OAuth consent screen.

    The OAuth state parameter is stored in a server-side session cookie
    (via Starlette SessionMiddleware) and validated on callback.
    """
    settings = get_settings()
    oauth = get_oauth()
    return await oauth.google.authorize_redirect(
        request, settings.google_redirect_uri,
    )


@router.get("/google/callback", name="google_callback", tags=["auth"])
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback and establish an HttpOnly browser session.

    Flow:
      1. Exchange the authorization code for an access token + ID token.
      2. Extract userinfo (sub, email, name, picture).
      3. Upsert: find by google_sub OR email.
         - New user: create with Google info, mark active + email_verified.
         - Existing local user: bind Google account, set auth_provider="both".
      4. Store the JZIS JWT in a host-only HttpOnly cookie and redirect to
         the clean frontend callback URL.
    """
    settings = get_settings()
    oauth = get_oauth()

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        log.warning("Google OAuth token exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}?error=oauth_failed",
            status_code=302,
        )

    userinfo = token.get("userinfo", {})
    google_sub = userinfo.get("sub")
    raw_email = userinfo.get("email")

    if not google_sub or not raw_email:
        log.warning("Google userinfo missing sub/email: %s", userinfo)
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}?error=missing_userinfo",
            status_code=302,
        )
    email = normalize_account(str(raw_email))
    await _enforce_auth_security("login", request, email)

    # --- Upsert: find by google_sub OR email ---
    stmt = select(User).where(
        or_(User.google_sub == google_sub, func.lower(User.email) == email)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        # New user via Google — no password needed, email pre-verified by Google.
        user = User(
            email=email,
            name=userinfo.get("name") or email.split("@")[0],
            google_sub=google_sub,
            auth_provider="google",
            avatar_url=userinfo.get("picture"),
            email_verified=True,
            is_active=True,
            password_hash=None,
        )
        db.add(user)
        await db.flush()

        # Issue a default API key for the new Google user
        plain, key_hash, key_prefix = auth_service.generate_api_key()
        db.add(ApiKey(
            user_id=user.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name="Default (created on Google sign-in)",
        ))
    else:
        # ``is_active=False`` is also how administrators suspend an account.
        # OAuth proves control of the Google identity, but it must never
        # override an administrator's authorization decision.  Because the
        # current schema does not distinguish an unverified account from a
        # suspended one, fail closed for every existing inactive account.
        if not user.is_active:
            log.warning(
                "Google OAuth rejected for inactive account user=%s email=%s",
                user.id,
                user.email,
            )
            add_auth_audit(
                db,
                request,
                event_type="google_login",
                outcome="inactive",
                account=email,
                user_id=user.id,
            )
            await db.commit()
            return RedirectResponse(
                url=f"{settings.frontend_callback_url}?error=account_inactive",
                status_code=302,
            )

        # Existing user — bind Google if not already bound
        if not user.google_sub:
            user.google_sub = google_sub
        if userinfo.get("picture") and not user.avatar_url:
            user.avatar_url = userinfo["picture"]
        if user.auth_provider == "local":
            user.auth_provider = "both"
        # Google verifies ownership of the email identity, but the active
        # account state has already been checked above and is preserved.
        user.email_verified = True

    user.last_login = datetime.now(timezone.utc)
    add_auth_audit(
        db,
        request,
        event_type="google_login",
        outcome="success",
        account=email,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(user)

    # Issue JWT
    jwt_token, _ = auth_service.create_access_token(
        user.id, user.session_version
    )
    response = RedirectResponse(
        url=str(settings.frontend_callback_url),
        status_code=302,
    )
    set_browser_session_cookie(response, jwt_token, _browser_session_config())
    return response
