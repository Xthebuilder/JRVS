"""
Authentication and authorization for JRVS MCP Server

Provides API key authentication and role-based access control.
"""

import hashlib
import secrets
from typing import Optional, Set, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass
from threading import Lock
import logging

from .exceptions import InvalidAPIKeyError, UnauthorizedError

logger = logging.getLogger(__name__)


@dataclass
class APIKey:
    """API key with metadata"""
    key_hash: str
    client_id: str
    created_at: datetime
    expires_at: Optional[datetime]
    roles: Set[str]
    enabled: bool = True
    last_used: Optional[datetime] = None
    use_count: int = 0


class AuthManager:
    """Manage API keys and permissions"""

    def __init__(self):
        self._keys: Dict[str, APIKey] = {}  # key_hash -> APIKey
        self._lock = Lock()

    def generate_api_key(
        self,
        client_id: str,
        roles: Set[str] = None,
        expires_in_days: Optional[int] = None
    ) -> str:
        """
        Generate new API key

        Args:
            client_id: Client identifier
            roles: Set of roles for RBAC
            expires_in_days: Optional expiration in days

        Returns:
            Generated API key (store this, it won't be retrievable later)
        """
        # Generate random key
        raw_key = secrets.token_urlsafe(32)

        # Hash for storage
        key_hash = self._hash_key(raw_key)

        # Calculate expiration
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        # Create API key object
        api_key = APIKey(
            key_hash=key_hash,
            client_id=client_id,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            roles=roles or {"user"}  # Default role
        )

        with self._lock:
            self._keys[key_hash] = api_key

        logger.info(f"Generated API key for client: {client_id}")

        return raw_key

    def validate_api_key(self, raw_key: str) -> Optional[APIKey]:
        """
        Validate API key and return APIKey object

        Returns:
            APIKey object if valid, None otherwise
        """
        key_hash = self._hash_key(raw_key)

        with self._lock:
            api_key = self._keys.get(key_hash)

            if api_key is None:
                return None

            # Check if enabled
            if not api_key.enabled:
                logger.warning(f"Disabled API key used: {api_key.client_id}")
                return None

            # Check expiration
            if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
                logger.warning(f"Expired API key used: {api_key.client_id}")
                return None

            # Update usage
            api_key.last_used = datetime.utcnow()
            api_key.use_count += 1

            return api_key

    def authenticate(self, raw_key: Optional[str]) -> str:
        """
        Authenticate and return client_id

        Args:
            raw_key: API key from request

        Returns:
            client_id

        Raises:
            InvalidAPIKeyError if authentication fails
        """
        if not raw_key:
            raise InvalidAPIKeyError()

        api_key = self.validate_api_key(raw_key)

        if api_key is None:
            raise InvalidAPIKeyError(key_preview=raw_key[:8])

        return api_key.client_id

    def authorize(self, raw_key: str, required_role: str) -> bool:
        """
        Check if API key has required role

        Args:
            raw_key: API key
            required_role: Required role

        Returns:
            True if authorized

        Raises:
            UnauthorizedError if not authorized
        """
        api_key = self.validate_api_key(raw_key)

        if api_key is None:
            raise InvalidAPIKeyError()

        # Check if has required role or admin role
        if required_role in api_key.roles or "admin" in api_key.roles:
            return True

        raise UnauthorizedError(required_permission=required_role)

    def revoke_api_key(self, raw_key: str) -> bool:
        """Revoke an API key"""
        key_hash = self._hash_key(raw_key)

        with self._lock:
            if key_hash in self._keys:
                self._keys[key_hash].enabled = False
                logger.info(f"Revoked API key: {self._keys[key_hash].client_id}")
                return True

        return False

    def get_client_info(self, raw_key: str) -> Optional[Dict]:
        """Get client information from API key"""
        api_key = self.validate_api_key(raw_key)

        if api_key is None:
            return None

        return {
            "client_id": api_key.client_id,
            "roles": list(api_key.roles),
            "created_at": api_key.created_at.isoformat(),
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "last_used": api_key.last_used.isoformat() if api_key.last_used else None,
            "use_count": api_key.use_count
        }

    def list_clients(self) -> list:
        """List all clients with API keys"""
        with self._lock:
            return [
                {
                    "client_id": key.client_id,
                    "roles": list(key.roles),
                    "enabled": key.enabled,
                    "use_count": key.use_count,
                    "last_used": key.last_used.isoformat() if key.last_used else None
                }
                for key in self._keys.values()
            ]

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        """Hash API key for storage"""
        return hashlib.sha256(raw_key.encode()).hexdigest()


# Global auth manager
auth_manager = AuthManager()


# Optional: Authentication decorator
def require_auth(func):
    """Decorator to require authentication"""
    async def wrapper(*args, api_key: Optional[str] = None, **kwargs):
        # Authenticate
        client_id = auth_manager.authenticate(api_key)

        # Call function with client_id
        return await func(*args, client_id=client_id, **kwargs)

    return wrapper


def require_role(role: str):
    """Decorator to require specific role"""
    def decorator(func):
        async def wrapper(*args, api_key: Optional[str] = None, **kwargs):
            # Authorize
            auth_manager.authorize(api_key, role)

            # Authenticate
            client_id = auth_manager.authenticate(api_key)

            # Call function
            return await func(*args, client_id=client_id, **kwargs)

        return wrapper
    return decorator


# Default API keys for development
def setup_development_keys():
    """Setup default API keys for development (DO NOT USE IN PRODUCTION)"""
    # Admin key
    admin_key = auth_manager.generate_api_key(
        client_id="dev-admin",
        roles={"admin", "user"}
    )

    # User key
    user_key = auth_manager.generate_api_key(
        client_id="dev-user",
        roles={"user"}
    )

    logger.warning("=" * 70)
    logger.warning("DEVELOPMENT API KEYS GENERATED")
    logger.warning("=" * 70)
    logger.warning(f"Admin Key: {admin_key}")
    logger.warning(f"User Key:  {user_key}")
    logger.warning("=" * 70)
    logger.warning("THESE KEYS ARE FOR DEVELOPMENT ONLY!")
    logger.warning("DO NOT USE IN PRODUCTION!")
    logger.warning("=" * 70)

    return {"admin": admin_key, "user": user_key}
