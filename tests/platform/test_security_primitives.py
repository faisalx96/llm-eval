from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))

import pytest

from qym_platform.security import hash_api_key, hash_password, verify_api_key, verify_password


def test_new_api_key_hash_uses_versioned_pbkdf2_format() -> None:
    token = "secret-token"
    stored = hash_api_key(token)
    assert stored.decode("ascii").startswith("pbkdf2_sha256$")
    assert verify_api_key(token, stored) is True
    assert verify_api_key("wrong-token", stored) is False


def test_legacy_sha256_api_key_hash_still_verifies() -> None:
    token = "legacy-token"
    legacy_hash = hashlib.sha256(token.encode("utf-8")).digest()
    assert verify_api_key(token, legacy_hash) is True
    assert verify_api_key("wrong-token", legacy_hash) is False


def test_password_hash_uses_versioned_pbkdf2_format() -> None:
    password = "correct horse battery staple"
    stored = hash_password(password)
    assert stored.decode("ascii").startswith("pbkdf2_sha256_pw$")
    assert verify_password(password, stored) is True
    assert verify_password("wrong-password", stored) is False


def test_password_hash_enforces_minimum_length() -> None:
    with pytest.raises(ValueError, match="at least 8 characters"):
        hash_password("short")
