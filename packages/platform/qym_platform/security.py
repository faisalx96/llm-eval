from __future__ import annotations

import base64
import hashlib
import hmac
import os


_PBKDF2_PREFIX = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_PASSWORD_PBKDF2_PREFIX = "pbkdf2_sha256_pw"
_PASSWORD_MIN_LENGTH = 8


def api_key_prefix(token: str) -> str:
    # short prefix for DB lookup/logging (not secret)
    return token[:8]


def _encode_pbkdf2(secret: str, prefix: str, iterations: int = _PBKDF2_ITERATIONS) -> bytes:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
    encoded = "$".join(
        [
            prefix,
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        ]
    )
    return encoded.encode("ascii")


def _verify_pbkdf2(secret: str, stored_hash: bytes, prefix: str) -> bool:
    if not stored_hash:
        return False
    try:
        encoded = stored_hash.decode("ascii")
    except UnicodeDecodeError:
        encoded = ""

    if encoded.startswith(prefix + "$"):
        parts = encoded.split("$", 3)
        if len(parts) != 4:
            return False
        _, iterations_raw, salt_raw, derived_raw = parts
        try:
            iterations = int(iterations_raw)
            salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
            expected = base64.urlsafe_b64decode(derived_raw.encode("ascii"))
        except Exception:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    return False


def hash_api_key(token: str) -> bytes:
    return _encode_pbkdf2(token, _PBKDF2_PREFIX)


def verify_api_key(token: str, stored_hash: bytes) -> bool:
    if _verify_pbkdf2(token, stored_hash, _PBKDF2_PREFIX):
        return True

    legacy = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.compare_digest(legacy, stored_hash or b"")


def validate_password(password: str) -> str:
    value = password or ""
    if len(value) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long")
    return value


def hash_password(password: str) -> bytes:
    return _encode_pbkdf2(validate_password(password), _PASSWORD_PBKDF2_PREFIX)


def verify_password(password: str, stored_hash: bytes) -> bool:
    return _verify_pbkdf2(password or "", stored_hash, _PASSWORD_PBKDF2_PREFIX)
