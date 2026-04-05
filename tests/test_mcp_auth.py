"""
Unit tests for mcp/auth.py

Tests AuthManager: key generation, validation, authentication,
authorization, revocation, and client info. No external dependencies.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.auth import AuthManager, APIKey
from mcp.exceptions import InvalidAPIKeyError, UnauthorizedError


@pytest.fixture
def auth():
    return AuthManager()


class TestKeyGeneration:
    def test_generate_returns_string(self, auth):
        key = auth.generate_api_key("client-1")
        assert isinstance(key, str)
        assert len(key) > 20

    def test_generated_keys_are_unique(self, auth):
        k1 = auth.generate_api_key("c1")
        k2 = auth.generate_api_key("c2")
        assert k1 != k2

    def test_default_role_is_user(self, auth):
        key = auth.generate_api_key("c")
        api_key = auth.validate_api_key(key)
        assert "user" in api_key.roles

    def test_custom_roles_stored(self, auth):
        key = auth.generate_api_key("c", roles={"admin", "reader"})
        api_key = auth.validate_api_key(key)
        assert "admin" in api_key.roles
        assert "reader" in api_key.roles

    def test_no_expiry_by_default(self, auth):
        key = auth.generate_api_key("c")
        api_key = auth.validate_api_key(key)
        assert api_key.expires_at is None

    def test_expiry_set_correctly(self, auth):
        key = auth.generate_api_key("c", expires_in_days=30)
        api_key = auth.validate_api_key(key)
        assert api_key.expires_at is not None
        delta = api_key.expires_at - datetime.utcnow()
        assert 29 <= delta.days <= 30

    def test_client_id_stored(self, auth):
        key = auth.generate_api_key("my-service")
        api_key = auth.validate_api_key(key)
        assert api_key.client_id == "my-service"


class TestKeyValidation:
    def test_valid_key_returns_api_key(self, auth):
        key = auth.generate_api_key("c")
        result = auth.validate_api_key(key)
        assert isinstance(result, APIKey)

    def test_invalid_key_returns_none(self, auth):
        assert auth.validate_api_key("not-a-valid-key") is None

    def test_revoked_key_returns_none(self, auth):
        key = auth.generate_api_key("c")
        auth.revoke_api_key(key)
        assert auth.validate_api_key(key) is None

    def test_use_count_increments(self, auth):
        key = auth.generate_api_key("c")
        auth.validate_api_key(key)
        auth.validate_api_key(key)
        api_key = auth.validate_api_key(key)
        assert api_key.use_count == 3

    def test_last_used_updated(self, auth):
        key = auth.generate_api_key("c")
        before = datetime.utcnow()
        auth.validate_api_key(key)
        api_key = auth.validate_api_key(key)
        assert api_key.last_used >= before

    def test_expired_key_returns_none(self, auth):
        key = auth.generate_api_key("c")
        # Manually set expiry to the past
        key_hash = AuthManager._hash_key(key)
        auth._keys[key_hash].expires_at = datetime.utcnow() - timedelta(seconds=1)
        assert auth.validate_api_key(key) is None


class TestAuthentication:
    def test_authenticate_valid_key(self, auth):
        key = auth.generate_api_key("my-client")
        client_id = auth.authenticate(key)
        assert client_id == "my-client"

    def test_authenticate_none_raises(self, auth):
        with pytest.raises(InvalidAPIKeyError):
            auth.authenticate(None)

    def test_authenticate_empty_string_raises(self, auth):
        with pytest.raises(InvalidAPIKeyError):
            auth.authenticate("")

    def test_authenticate_invalid_key_raises(self, auth):
        with pytest.raises(InvalidAPIKeyError):
            auth.authenticate("garbage-key-xyz")

    def test_authenticate_revoked_key_raises(self, auth):
        key = auth.generate_api_key("c")
        auth.revoke_api_key(key)
        with pytest.raises(InvalidAPIKeyError):
            auth.authenticate(key)


class TestAuthorization:
    def test_authorize_with_required_role(self, auth):
        key = auth.generate_api_key("c", roles={"editor"})
        assert auth.authorize(key, "editor") is True

    def test_admin_can_access_any_role(self, auth):
        key = auth.generate_api_key("admin-c", roles={"admin"})
        assert auth.authorize(key, "editor") is True
        assert auth.authorize(key, "reader") is True

    def test_authorize_raises_without_role(self, auth):
        key = auth.generate_api_key("c", roles={"user"})
        with pytest.raises(UnauthorizedError):
            auth.authorize(key, "admin")

    def test_authorize_invalid_key_raises(self, auth):
        with pytest.raises(InvalidAPIKeyError):
            auth.authorize("bad-key", "admin")


class TestRevocation:
    def test_revoke_existing_key(self, auth):
        key = auth.generate_api_key("c")
        assert auth.revoke_api_key(key) is True

    def test_revoke_nonexistent_key(self, auth):
        assert auth.revoke_api_key("not-a-key") is False

    def test_revoked_key_disabled(self, auth):
        key = auth.generate_api_key("c")
        auth.revoke_api_key(key)
        key_hash = AuthManager._hash_key(key)
        assert auth._keys[key_hash].enabled is False


class TestClientInfo:
    def test_get_client_info_shape(self, auth):
        key = auth.generate_api_key("svc", roles={"user"})
        info = auth.get_client_info(key)
        assert info is not None
        assert info["client_id"] == "svc"
        assert "user" in info["roles"]
        assert "created_at" in info
        assert "use_count" in info

    def test_get_client_info_invalid_key(self, auth):
        assert auth.get_client_info("bad-key") is None

    def test_list_clients_includes_generated(self, auth):
        auth.generate_api_key("svc-a")
        auth.generate_api_key("svc-b")
        clients = auth.list_clients()
        client_ids = [c["client_id"] for c in clients]
        assert "svc-a" in client_ids
        assert "svc-b" in client_ids


class TestHashKey:
    def test_same_key_same_hash(self):
        h1 = AuthManager._hash_key("abc")
        h2 = AuthManager._hash_key("abc")
        assert h1 == h2

    def test_different_keys_different_hashes(self):
        assert AuthManager._hash_key("abc") != AuthManager._hash_key("xyz")

    def test_hash_is_hex_string(self):
        h = AuthManager._hash_key("test")
        assert len(h) == 64  # SHA-256 hex
