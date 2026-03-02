"""Google OAuth2 Authorization Code flow for JRVS."""
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Lazy imports — only needed if google credentials are configured
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    _GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    _GOOGLE_AUTH_AVAILABLE = False


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]


class GoogleAuth:
    """Manages OAuth2 credentials for Google Workspace APIs."""

    def __init__(self, client_id: str, client_secret: str, token_path: Path):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = token_path
        self._credentials: Optional[object] = None  # google.oauth2.credentials.Credentials

    def is_configured(self) -> bool:
        """True if client_id and client_secret are set."""
        return bool(self.client_id and self.client_secret)

    def is_authenticated(self) -> bool:
        """True if valid (possibly auto-refreshed) credentials exist."""
        if not _GOOGLE_AUTH_AVAILABLE:
            return False
        creds = self._load_credentials()
        return creds is not None and creds.valid

    def get_auth_url(self) -> str:
        """Return the OAuth2 authorization URL the user must visit."""
        if not _GOOGLE_AUTH_AVAILABLE:
            raise RuntimeError(
                "google-auth-oauthlib is not installed. "
                "Run: pip install google-auth-oauthlib"
            )
        if not self.is_configured():
            raise RuntimeError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set."
            )

        flow = self._build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code(self, code: str) -> None:
        """Exchange an authorization code for tokens and persist them."""
        if not _GOOGLE_AUTH_AVAILABLE:
            raise RuntimeError("google-auth-oauthlib is not installed.")

        flow = self._build_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        self._save_credentials(creds)
        self._credentials = creds
        log.info("Google OAuth2 token obtained and saved to %s", self.token_path)

    def get_credentials(self) -> Optional[object]:
        """Return valid credentials, refreshing if expired. Returns None if not authenticated."""
        if not _GOOGLE_AUTH_AVAILABLE:
            return None

        creds = self._load_credentials()
        if creds is None:
            return None

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_credentials(creds)
                    log.info("Google credentials auto-refreshed.")
                except Exception as exc:
                    log.warning("Failed to refresh Google credentials: %s", exc)
                    return None
            else:
                return None

        self._credentials = creds
        return creds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_flow(self):
        """Build an InstalledAppFlow from client_id / client_secret."""
        client_config = {
            "installed": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        return flow

    def _load_credentials(self) -> Optional[object]:
        """Load credentials from disk, or return None if absent / corrupt."""
        if not self.token_path.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            return creds
        except Exception as exc:
            log.warning("Could not load Google token from %s: %s", self.token_path, exc)
            return None

    def _save_credentials(self, creds) -> None:
        """Persist credentials to token_path as JSON."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w") as fh:
            fh.write(creds.to_json())
