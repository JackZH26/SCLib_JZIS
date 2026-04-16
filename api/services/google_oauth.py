"""Google OAuth2 service using authlib.

Registers Google as an OAuth provider and exposes the configured client.
The ``oauth`` singleton is imported by the auth router to drive the
redirect ↔ callback dance.

Usage in the auth router::

    from services.google_oauth import oauth

    @router.get("/google/login")
    async def google_login(request: Request):
        return await oauth.google.authorize_redirect(request, redirect_uri)

    @router.get("/google/callback")
    async def google_callback(request: Request):
        token = await oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo", {})
        ...
"""
from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth

from config import get_settings

log = logging.getLogger("sclib.google_oauth")

_oauth: OAuth | None = None


def get_oauth() -> OAuth:
    """Lazily create the OAuth singleton.

    We defer initialization so the Settings (and its env vars) are fully
    loaded before we hand a client_id / client_secret to authlib.
    """
    global _oauth
    if _oauth is not None:
        return _oauth

    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        log.warning(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set — "
            "Google OAuth endpoints will fail at runtime."
        )

    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid email profile",
            "prompt": "select_account",
        },
    )
    return _oauth
