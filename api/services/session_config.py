"""Security-sensitive configuration for the short-lived OAuth state cookie."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class OAuthSessionConfig:
    session_cookie: str
    max_age: int
    path: str
    same_site: Literal["lax"]
    https_only: bool


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
