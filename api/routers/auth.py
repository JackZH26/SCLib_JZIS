"""Auth router: register / verify / login / me / keys / keys/{id} / google.

Endpoints from PROJECT_SPEC.md section 7, extended with Google OAuth.
The flow is:
  register (user created, is_active=False, verification token emailed)
    -> verify (is_active=True, first API key issued, welcome email)
    -> login (JWT for session management, e.g. dashboard)
  Google OAuth:
    -> /google/login (redirect to Google consent screen)
    -> /google/callback (handle Google redirect, upsert user, issue JWT)
  Other API calls authenticate via X-API-Key header (see deps below).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import RedirectResponse

log = logging.getLogger(__name__)

from models import get_db
from models.db import ApiKey, EmailVerification, User
from models.user import (
    ApiKeyCreate,
    ApiKeyRead,
    ApiKeyWithSecret,
    LoginRequest,
    MessageResponse,
    RegisterResponse,
    TokenResponse,
    UsageStats,
    UserCreate,
    UserRead,
    UserUpdate,
    VerifyResponse,
)
from config import get_settings
from services import auth_service
from services.email import send_verification, send_welcome
from services.google_oauth import get_oauth
from services.rate_limit import (
    get_user_remaining,
    get_user_today_used,
    get_user_week_used,
)
from sqlalchemy import func

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# X-API-Key auth for data endpoints lives in routers.deps.require_identity —
# that path both validates the key AND enforces the per-user daily quota,
# so there is no second implementation here. JWT auth for account-
# management endpoints is below.

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
    # Google-only accounts have no password hash — guide user to Google sign-in.
    if not user.password_hash:
        raise HTTPException(
            401,
            "This account uses Google Sign-In. Please use the Google button to log in.",
        )
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
    """Handle Google OAuth callback: upsert user, issue JWT, redirect to frontend.

    Flow:
      1. Exchange the authorization code for an access token + ID token.
      2. Extract userinfo (sub, email, name, picture).
      3. Upsert: find by google_sub OR email.
         - New user: create with Google info, mark active + email_verified.
         - Existing local user: bind Google account, set auth_provider="both".
      4. Issue a JZIS JWT and redirect to the frontend callback page with
         the token as a query parameter.
    """
    settings = get_settings()
    oauth = get_oauth()

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        log.warning("Google OAuth token exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}"
            f"?error=oauth_failed&detail={str(exc)[:100]}",
            status_code=302,
        )

    userinfo = token.get("userinfo", {})
    google_sub = userinfo.get("sub")
    email = userinfo.get("email")

    if not google_sub or not email:
        log.warning("Google userinfo missing sub/email: %s", userinfo)
        return RedirectResponse(
            url=f"{settings.frontend_callback_url}?error=missing_userinfo",
            status_code=302,
        )

    # --- Upsert: find by google_sub OR email ---
    stmt = select(User).where(
        or_(User.google_sub == google_sub, User.email == email)
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
        # Existing user — bind Google if not already bound
        if not user.google_sub:
            user.google_sub = google_sub
        if userinfo.get("picture") and not user.avatar_url:
            user.avatar_url = userinfo["picture"]
        if user.auth_provider == "local":
            user.auth_provider = "both"
        # Ensure user is active (covers edge case where a local user
        # hadn't verified email yet — Google proves ownership).
        user.email_verified = True
        user.is_active = True

    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    # Issue JWT
    jwt_token, _ = auth_service.create_access_token(user.id)

    return RedirectResponse(
        url=f"{settings.frontend_callback_url}?token={jwt_token}",
        status_code=302,
    )
