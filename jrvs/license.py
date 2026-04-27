"""
JRVS license validation — offline, HMAC-signed keys.

Key format:  JRVS-{TIER}-{YYYYMMDD}-{SIG}
  TIER      COM | PRO | TEAM
  YYYYMMDD  expiry date; 19991231 = perpetual
  SIG       first 16 hex chars of HMAC-SHA256("{tier}:{expiry}", secret)

Generate keys with:
    python scripts/generate_license.py PRO 20270101

IMPORTANT — before shipping:
  1. Pick a random secret (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`)
  2. Replace _VERIFY_SECRET below with that value
  3. Set the same value as JRVS_LICENSE_SECRET in your local env for key generation
  4. Never commit the real secret — the placeholder below is intentional
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from typing import Optional


# ── Secret ────────────────────────────────────────────────────────────────────
# Replace this before shipping. Keep your signing secret private.
_VERIFY_SECRET: bytes = os.environ.get(
    "JRVS_LICENSE_SECRET",
    "jrvs-license-v1-replace-before-shipping-32ch",
).encode()

# ── Tiers ─────────────────────────────────────────────────────────────────────

class Tier(IntEnum):
    COMMUNITY    = 0
    PROFESSIONAL = 1
    TEAM         = 2

_TIER_CODES = {"COM": Tier.COMMUNITY, "PRO": Tier.PROFESSIONAL, "TEAM": Tier.TEAM}
_TIER_LABELS = {Tier.COMMUNITY: "Community", Tier.PROFESSIONAL: "Professional", Tier.TEAM: "Team"}

# ── License data ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LicenseInfo:
    tier:   Tier
    expiry: Optional[date]  # None = perpetual

    @property
    def active(self) -> bool:
        return self.expiry is None or date.today() <= self.expiry

    @property
    def label(self) -> str:
        return _TIER_LABELS[self.tier]

    @property
    def expiry_str(self) -> str:
        return "perpetual" if self.expiry is None else self.expiry.isoformat()


_COMMUNITY = LicenseInfo(tier=Tier.COMMUNITY, expiry=None)

# ── Validation ────────────────────────────────────────────────────────────────

def _sig(tier: str, expiry: str) -> str:
    payload = f"{tier}:{expiry}".encode()
    return hmac.new(_VERIFY_SECRET, payload, hashlib.sha256).hexdigest()[:16]


def _parse(key: str) -> Optional[LicenseInfo]:
    parts = key.strip().upper().split("-")
    # JRVS-TEAM-YYYYMMDD-SIG → 4 parts; TEAM has no dash, so always 4
    if len(parts) != 4 or parts[0] != "JRVS":
        return None
    _, tier_str, expiry_str, sig = parts
    if tier_str not in _TIER_CODES:
        return None
    expected = _sig(tier_str, expiry_str)
    if not hmac.compare_digest(sig.lower(), expected):
        return None
    expiry: Optional[date] = None
    if expiry_str != "19991231":
        try:
            expiry = datetime.strptime(expiry_str, "%Y%m%d").date()
        except ValueError:
            return None
    return LicenseInfo(tier=_TIER_CODES[tier_str], expiry=expiry)


# ── Module state ──────────────────────────────────────────────────────────────

_loaded: Optional[LicenseInfo] = None


def load() -> LicenseInfo:
    """Read JRVS_LICENSE_KEY from env, validate, cache and return result."""
    global _loaded
    if _loaded is not None:
        return _loaded

    raw = os.environ.get("JRVS_LICENSE_KEY", "").strip()
    if not raw:
        _loaded = _COMMUNITY
        return _loaded

    info = _parse(raw)
    if info is None:
        _print_invalid(raw)
        _loaded = _COMMUNITY
        return _loaded

    if not info.active:
        _print_expired(info)
        _loaded = _COMMUNITY
        return _loaded

    _loaded = info
    return _loaded


def current() -> LicenseInfo:
    return _loaded if _loaded is not None else load()


# ── Feature gates ─────────────────────────────────────────────────────────────

class LicenseError(RuntimeError):
    pass


def require(min_tier: Tier, feature: str) -> None:
    """Raise LicenseError if the active tier is below min_tier."""
    info = current()
    if info.tier >= min_tier:
        return
    needed = _TIER_LABELS[min_tier]
    raise LicenseError(
        f"\n  {feature} requires a {needed} license.\n"
        f"  You are on the {info.label} tier (non-commercial use only).\n"
        f"  Upgrade at: https://github.com/Xthebuilder/JRVS_Private#licensing\n"
    )


def require_professional(feature: str) -> None:
    require(Tier.PROFESSIONAL, feature)


def require_team(feature: str) -> None:
    require(Tier.TEAM, feature)


# ── Startup banner ────────────────────────────────────────────────────────────

def print_banner() -> None:
    info = current()
    if info.tier == Tier.COMMUNITY:
        print(
            "\n  JRVS License : Community (non-commercial use only)\n"
            "  Upgrade      : https://github.com/Xthebuilder/JRVS_Private#licensing\n"
        )
    else:
        print(f"\n  JRVS License : {info.label} — {info.expiry_str}\n")


# ── Private helpers ───────────────────────────────────────────────────────────

def _print_invalid(raw: str) -> None:
    print(
        f"\n  JRVS License : INVALID KEY ({raw[:20]}...)\n"
        "  Falling back to Community tier.\n"
        "  Contact support: xmartinx01@gmail.com\n"
    )


def _print_expired(info: LicenseInfo) -> None:
    print(
        f"\n  JRVS License : EXPIRED ({info.expiry_str})\n"
        "  Falling back to Community tier.\n"
        "  Renew at: https://github.com/Xthebuilder/JRVS_Private#licensing\n"
    )
