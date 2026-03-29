from __future__ import annotations

import base64
import hashlib
import hmac
import os


_PBKDF2_PREFIX = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000


def api_key_prefix(token: str) -> str:
    # short prefix for DB lookup/logging (not secret)
    return token[:8]


def hash_api_key(token: str) -> bytes:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    encoded = "$".join(
        [
            _PBKDF2_PREFIX,
            str(_PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        ]
    )
    return encoded.encode("ascii")


def verify_api_key(token: str, stored_hash: bytes) -> bool:
    if not stored_hash:
        return False
    try:
        encoded = stored_hash.decode("ascii")
    except UnicodeDecodeError:
        encoded = ""

    if encoded.startswith(_PBKDF2_PREFIX + "$"):
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
        actual = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)

    legacy = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.compare_digest(legacy, stored_hash or b"")

