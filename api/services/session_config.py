"""Security-sensitive configuration for OAuth and browser session cookies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from starlette.responses import Response


@dataclass(frozen=True, slots=True)
class OAuthSessionConfig:
    session_cookie: str
    max_age: int
    path: str
    same_site: Literal["lax"]
    https_only: bool


@dataclass(frozen=True, slots=True)
class BrowserSessionConfig:
    cookie_name: str
    max_age: int
    path: str
    same_site: Literal["lax"]
    secure: bool
    httponly: bool


def build_oauth_session_config(environment: str) -> OAuthSessionConfig:
    """Return a host-locked production cookie and a usable local-dev cookie."""
    production = environment == "production"
    config = OAuthSessionConfig(
        session_cookie=(
            "__Host-sclib_oauth_state" if production else "sclib_oauth_state"
        ),
        max_age=300,
        path="/",
        same_site="lax",
        https_only=production,
    )

    # Keep the __Host- contract impossible to weaken accidentally when this
    # helper is extended. SessionMiddleware omits Domain unless configured.
    if production and (
        not config.session_cookie.startswith("__Host-")
        or not config.https_only
        or config.path != "/"
    ):
        raise RuntimeError("Invalid production OAuth session cookie settings")
    return config


def build_browser_session_config(
    environment: str,
    max_age: int,
) -> BrowserSessionConfig:
    """Return the central API's host-only browser session settings."""
    production = environment == "production"
    config = BrowserSessionConfig(
        cookie_name="__Host-sclib_session" if production else "sclib_session",
        max_age=max_age,
        path="/",
        same_site="lax",
        secure=production,
        httponly=True,
    )

    if production and (
        not config.cookie_name.startswith("__Host-")
        or not config.secure
        or not config.httponly
        or config.path != "/"
    ):
        raise RuntimeError("Invalid production browser session cookie settings")
    return config


def set_browser_session_cookie(
    response: Response,
    token: str,
    config: BrowserSessionConfig,
) -> None:
    """Attach a signed JWT as an HttpOnly, host-only browser cookie."""
    response.set_cookie(
        key=config.cookie_name,
        value=token,
        max_age=config.max_age,
        path=config.path,
        secure=config.secure,
        httponly=config.httponly,
        samesite=config.same_site,
    )


def clear_browser_session_cookie(
    response: Response,
    config: BrowserSessionConfig,
) -> None:
    """Expire the browser session using the same security attributes."""
    response.delete_cookie(
        key=config.cookie_name,
        path=config.path,
        secure=config.secure,
        httponly=config.httponly,
        samesite=config.same_site,
    )
