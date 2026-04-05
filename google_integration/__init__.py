"""JRVS Google Workspace Integration.

Exports the shared singleton and key classes for use throughout the codebase.
"""
from .client import google_workspace
from .auth import GoogleAuth
from .audit_log import audit_log, init_audit_log

__all__ = [
    "google_workspace",
    "GoogleAuth",
    "audit_log",
    "init_audit_log",
]
