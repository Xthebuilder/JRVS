"""
lib/music_tools.py — JRVS music download helpers

Wraps the local ytdl CLI script (~/.local/bin/ytdl) using subprocess
with shell=False to prevent shell injection attacks.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

YTDL_BIN = os.path.expanduser("~/.local/bin/ytdl")
MUSIC_DIR = Path(os.path.expanduser("~/Music/ytdl"))

# Rough pattern to accept only http(s) URLs — rejects embedded shell metacharacters
_URL_RE = re.compile(r"^https?://[^\s;|&<>'\"`\\]+$")


def _validate_url(url: str) -> str:
    """Raise ValueError if url looks malicious or malformed."""
    url = url.strip()
    if not _URL_RE.match(url):
        raise ValueError(f"Rejected URL — failed safety check: {url!r}")
    return url


def _existing_download(url: str) -> Optional[Path]:
    """
    Return an existing file in MUSIC_DIR whose stem contains the last
    path segment of the URL (a heuristic, not exhaustive).
    Returns None when no match is found.
    """
    if not MUSIC_DIR.exists():
        return None
    # Use the last non-empty path segment of the URL as a loose fingerprint
    slug = url.rstrip("/").split("/")[-1].split("?")[0].lower()
    if not slug:
        return None
    for f in MUSIC_DIR.iterdir():
        if slug in f.name.lower():
            return f
    return None


def download_song(url: str) -> dict:
    """
    Download a YouTube URL as MP3 via the local ytdl script.

    Security: shell=False + list argv — the URL is passed as a single
    argument and never interpolated into a shell string, so appending
    ; rm -rf / or similar has no effect.

    Returns a dict with keys:
        status   : "already_exists" | "success" | "error"
        message  : human-readable description
        file     : path to the file (if known)
        returncode: subprocess return code (None for already_exists)
    """
    try:
        url = _validate_url(url)
    except ValueError as e:
        return {"status": "error", "message": str(e), "file": None, "returncode": None}

    # ── Step 4: check if already downloaded ──────────────────────────────────
    existing = _existing_download(url)
    if existing:
        return {
            "status": "already_exists",
            "message": f"File already exists: {existing.name}",
            "file": str(existing),
            "returncode": None,
        }

    # ── Ensure the binary is available ───────────────────────────────────────
    if not os.path.isfile(YTDL_BIN) and not os.path.islink(YTDL_BIN):
        return {
            "status": "error",
            "message": f"ytdl binary not found at {YTDL_BIN}",
            "file": None,
            "returncode": None,
        }

    # ── Run ytdl — shell=False, URL as a plain list element ──────────────────
    try:
        result = subprocess.run(
            [YTDL_BIN, url],   # argv list — no shell expansion, no injection
            shell=False,
            capture_output=True,
            text=True,
            timeout=600,       # 10-minute ceiling for long playlists
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "ytdl timed out after 10 minutes", "file": None, "returncode": -1}
    except Exception as e:
        return {"status": "error", "message": f"Subprocess error: {e}", "file": None, "returncode": -1}

    if result.returncode != 0:
        return {
            "status": "error",
            "message": result.stderr.strip() or "ytdl exited with an error",
            "file": None,
            "returncode": result.returncode,
        }

    # Try to surface the downloaded file name from stdout
    downloaded_file = None
    for line in result.stdout.splitlines():
        if "Destination" in line or line.strip().endswith(".mp3"):
            candidate = line.strip().split()[-1]
            if os.path.isfile(candidate):
                downloaded_file = candidate
                break

    return {
        "status": "success",
        "message": result.stdout.strip() or "Download complete.",
        "file": downloaded_file,
        "returncode": result.returncode,
    }


def list_downloads() -> list[dict]:
    """Return metadata for every file currently in MUSIC_DIR."""
    if not MUSIC_DIR.exists():
        return []
    files = []
    for f in sorted(MUSIC_DIR.iterdir()):
        if f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(stat.st_size / 1_048_576, 2),
            })
    return files
