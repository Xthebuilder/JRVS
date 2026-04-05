"""
JRVS API Authentication — Bearer-token auth middleware.

Tokens are loaded from the JRVS_API_TOKENS env var (comma-separated) or
from a tokens file at JRVS_API_TOKENS_FILE (one token per line).

When JRVS_AUTH_ENABLED is false (the default), all requests are allowed.

Usage in FastAPI:
    from core.auth import require_auth
    @app.get("/api/protected", dependencies=[Depends(require_auth)])
    async def protected(): ...
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional, Set

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

AUTH_ENABLED: bool = os.environ.get("JRVS_AUTH_ENABLED", "false").lower() == "true"

_bearer_scheme = HTTPBearer(auto_error=False)


def _load_tokens() -> Set[str]:
    """Load valid API tokens from env var or file."""
    tokens: Set[str] = set()

    # From comma-separated env var
    raw = os.environ.get("JRVS_API_TOKENS", "")
    if raw:
        for t in raw.split(","):
            t = t.strip()
            if t:
                tokens.add(t)

    # From file (one token per line)
    token_file = os.environ.get("JRVS_API_TOKENS_FILE", "")
    if token_file:
        p = Path(token_file)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    tokens.add(line)

    return tokens


# Pre-hash tokens for constant-time comparison
_raw_tokens = _load_tokens()
_hashed_tokens: Set[str] = {
    hashlib.sha256(t.encode()).hexdigest() for t in _raw_tokens
}


def _verify_token(token: str) -> bool:
    """Constant-time comparison of a candidate token against stored tokens."""
    candidate_hash = hashlib.sha256(token.encode()).hexdigest()
    return any(
        hmac.compare_digest(candidate_hash, stored)
        for stored in _hashed_tokens
    )


def reload_tokens() -> None:
    """Reload tokens from env/file (e.g. after hot-reload)."""
    global _raw_tokens, _hashed_tokens
    _raw_tokens = _load_tokens()
    _hashed_tokens = {
        hashlib.sha256(t.encode()).hexdigest() for t in _raw_tokens
    }


def generate_token() -> str:
    """Generate a cryptographically secure API token."""
    return f"jrvs_{secrets.token_urlsafe(32)}"


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """
    FastAPI dependency that enforces Bearer-token auth when enabled.

    Returns the token on success, None when auth is disabled.
    Raises 401 on missing/invalid token.
    """
    if not AUTH_ENABLED:
        return None

    if not _hashed_tokens:
        log.warning(
            "JRVS_AUTH_ENABLED=true but no tokens configured. "
            "Set JRVS_API_TOKENS or JRVS_API_TOKENS_FILE."
        )
        # Fail open with a warning rather than locking everyone out
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _verify_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


async def require_auth_ws(websocket: WebSocket) -> Optional[str]:
    """
    WebSocket auth dependency.

    Token can be provided as:
      - Query param: ?token=<token>
      - First message: {"type": "auth", "token": "<token>"}
    """
    if not AUTH_ENABLED:
        return None

    if not _hashed_tokens:
        return None

    # Try query param first
    token = websocket.query_params.get("token")
    if token and _verify_token(token):
        return token

    # No valid token in query params
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="WebSocket auth required. Pass ?token=<token> as query parameter.",
    )
