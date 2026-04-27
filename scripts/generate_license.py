"""
Generate a JRVS license key.

Usage:
    JRVS_LICENSE_SECRET=your-secret python scripts/generate_license.py PRO 20270101
    JRVS_LICENSE_SECRET=your-secret python scripts/generate_license.py TEAM 19991231

Tiers:  COM (community) | PRO (professional) | TEAM (team)
Expiry: YYYYMMDD — use 19991231 for a perpetual license

The secret must match _VERIFY_SECRET in jrvs/license.py.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys


def generate(tier: str, expiry: str, secret: bytes) -> str:
    sig = hmac.new(secret, f"{tier}:{expiry}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"JRVS-{tier}-{expiry}-{sig}"


def main() -> None:
    secret = os.environ.get("JRVS_LICENSE_SECRET", "").encode()
    if not secret:
        sys.exit(
            "Error: set JRVS_LICENSE_SECRET in your environment before generating keys.\n"
            "  export JRVS_LICENSE_SECRET=your-secret-here"
        )

    p = argparse.ArgumentParser(description="Generate a JRVS license key.")
    p.add_argument("tier",   choices=["COM", "PRO", "TEAM"], help="License tier")
    p.add_argument("expiry", help="Expiry date as YYYYMMDD, or 19991231 for perpetual")
    args = p.parse_args()

    key = generate(args.tier.upper(), args.expiry, secret)
    print(key)


if __name__ == "__main__":
    main()
