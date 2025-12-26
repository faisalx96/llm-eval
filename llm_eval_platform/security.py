from __future__ import annotations

import hashlib
import hmac


def api_key_prefix(token: str) -> str:
    # short prefix for DB lookup/logging (not secret)
    return token[:8]


def hash_api_key(token: str) -> bytes:
    # Internal-only baseline. If you need stronger, switch to PBKDF2 + salt and store salt.
    return hashlib.sha256(token.encode("utf-8")).digest()


def verify_api_key(token: str, stored_hash: bytes) -> bool:
    return hmac.compare_digest(hash_api_key(token), stored_hash or b"")


