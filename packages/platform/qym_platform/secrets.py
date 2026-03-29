from __future__ import annotations

from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from qym_platform.settings import PlatformSettings


def llm_config_has_api_key(cfg: dict[str, Any] | None) -> bool:
    if not isinstance(cfg, dict):
        return False
    return bool(cfg.get("llm_api_key_encrypted") or cfg.get("llm_api_key"))


def llm_config_api_key_hint(cfg: dict[str, Any] | None) -> str:
    if not isinstance(cfg, dict):
        return ""
    last4 = str(cfg.get("llm_api_key_last4") or "")
    if last4:
        return "••••" + last4
    raw_key = str(cfg.get("llm_api_key") or "")
    if len(raw_key) >= 4:
        return "••••" + raw_key[-4:]
    return ""


def _encryption_key(settings: PlatformSettings | None = None) -> str:
    runtime_settings = settings or PlatformSettings()
    return (runtime_settings.llm_config_encryption_key or "").strip()


@lru_cache(maxsize=4)
def _fernet_for_key(key: str) -> Fernet:
    return Fernet(key.encode("utf-8"))


def encryption_available(settings: PlatformSettings | None = None) -> bool:
    return bool(_encryption_key(settings))


def encrypt_llm_api_key(api_key: str, settings: PlatformSettings | None = None) -> str:
    key = _encryption_key(settings)
    if not key:
        raise RuntimeError("LLM config encryption is not configured")
    return _fernet_for_key(key).encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_llm_api_key(token: str, settings: PlatformSettings | None = None) -> str:
    key = _encryption_key(settings)
    if not key:
        raise RuntimeError("LLM config encryption is not configured")
    try:
        return _fernet_for_key(key).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Stored LLM API key could not be decrypted") from exc


def resolve_llm_api_key(cfg: dict[str, Any] | None, settings: PlatformSettings | None = None) -> str:
    if not isinstance(cfg, dict):
        return ""
    encrypted = str(cfg.get("llm_api_key_encrypted") or "")
    if encrypted:
        return decrypt_llm_api_key(encrypted, settings)
    return str(cfg.get("llm_api_key") or "")


def build_llm_config_storage(
    *,
    base_url: str,
    model: str,
    api_key: str,
    settings: PlatformSettings | None = None,
) -> dict[str, Any]:
    encrypted_key = encrypt_llm_api_key(api_key, settings)
    return {
        "llm_base_url": base_url.strip().rstrip("/"),
        "llm_api_key_encrypted": encrypted_key,
        "llm_api_key_last4": api_key[-4:] if len(api_key) >= 4 else api_key,
        "llm_model": model.strip(),
    }
