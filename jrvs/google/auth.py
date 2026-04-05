"""
Google OAuth2 helper for JRVS.

First-time setup:
  1. Go to Google Cloud Console → Create a project → Enable Gmail, Docs & Sheets APIs.
  2. Create OAuth 2.0 credentials (Desktop app type).
  3. Download ``credentials.json`` and save it to the path in ``Config.GOOGLE_CREDENTIALS_FILE``.
  4. Run ``jrvs google auth`` — a browser window will open for consent.
  5. The token is written to ``Config.GOOGLE_TOKEN_FILE`` and reused silently on future calls.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


def get_credentials():
    """Return valid OAuth2 credentials, refreshing or re-authorising as needed.

    Raises ``RuntimeError`` when ``credentials.json`` is missing.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Google client libraries not installed.\n"
            "Run: pip install google-api-python-client google-auth-httplib2 "
            "google-auth-oauthlib"
        ) from exc

    creds: Credentials | None = None
    token_path = Config.GOOGLE_TOKEN_FILE
    creds_path = Config.GOOGLE_CREDENTIALS_FILE

    # Load saved token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), Config.GOOGLE_SCOPES)
        except Exception as exc:
            log.warning("Could not load token: %s — re-authorising", exc)
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, token_path)
            return creds
        except Exception as exc:
            log.warning("Token refresh failed: %s — re-authorising", exc)
            creds = None

    # Full OAuth flow
    if not creds or not creds.valid:
        if not creds_path.exists():
            raise RuntimeError(
                f"Google credentials file not found at:\n  {creds_path}\n\n"
                "Steps to fix:\n"
                "  1. Visit https://console.cloud.google.com/\n"
                "  2. Create a project, enable Gmail + Docs + Sheets APIs.\n"
                "  3. Create OAuth 2.0 Desktop credentials and download credentials.json.\n"
                f"  4. Save the file to: {creds_path}\n"
                "  5. Run: jrvs google auth"
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(creds_path), Config.GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        _save_token(creds, token_path)

    return creds


def run_auth_flow() -> None:
    """Force a fresh OAuth2 consent flow and save the token."""
    Config.ensure_dirs()
    get_credentials()
    log.info("Google OAuth2 authorisation successful")
    print(f"✓ Authorised. Token saved to: {Config.GOOGLE_TOKEN_FILE}")


def build_service(api: str, version: str):
    """Return a Google API service resource for *api*/*version*."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client not installed.\n"
            "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    creds = get_credentials()
    return build(api, version, credentials=creds)


def _save_token(creds, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json())
