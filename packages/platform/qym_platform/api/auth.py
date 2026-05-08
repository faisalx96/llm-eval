from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.auth_oidc import (
    auth_mode_is_oidc,
    begin_provider_login,
    clear_authenticated_session,
    exchange_provider_identity,
    get_session_user_and_provider,
    local_auth_enabled,
    pop_login_next,
    provider_catalog,
    request_root_path,
    resolve_or_provision_user,
    sanitize_next,
    session_auth_enabled,
    set_authenticated_session,
    store_login_next,
    with_root_path,
)
from qym_platform.db.models import LocalAuthCredential, User, UserIdentity, UserRole
from qym_platform.deps import get_db
from qym_platform.security import hash_password, verify_password
from qym_platform.settings import PlatformSettings


router = APIRouter()


def _platform_static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "_static"


def _login_bootstrap_payload(settings: PlatformSettings) -> Dict[str, Any]:
    local_enabled = local_auth_enabled(settings)
    return {
        "auth_mode": settings.auth_mode,
        "providers": provider_catalog(settings),
        "local_auth": {
            "enabled": local_enabled,
            "signup_enabled": local_enabled,
        },
    }


def _resolve_next(request: Request) -> str:
    default = with_root_path(request, "/")
    return sanitize_next(request.query_params.get("next"), default=default)


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not value or "@" not in value:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    return value


def _default_display_name(email: str, display_name: str = "") -> str:
    value = (display_name or "").strip()
    if value:
        return value
    local = (email or "").split("@", 1)[0].strip()
    if not local:
        return email
    parts = [part for part in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if part]
    return " ".join(part.capitalize() for part in parts) if parts else email


def _ensure_local_auth_enabled(settings: PlatformSettings) -> None:
    if not local_auth_enabled(settings):
        raise HTTPException(status_code=400, detail="Email/password auth is not enabled")


def _invalid_credentials() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid email or password")


@router.get("/login", response_model=None)
def login_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    settings = PlatformSettings()
    next_value = _resolve_next(request)
    if session_auth_enabled(settings):
        resolved = get_session_user_and_provider(db, request)
        if resolved:
            return RedirectResponse(url=next_value, status_code=303)
    idx = _platform_static_dir() / "dashboard" / "login.html"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Login UI not found")
    html = idx.read_text(encoding="utf-8")
    root_path = request_root_path(request)
    html = html.replace("__QYM_LOGIN_BOOTSTRAP_JSON__", json.dumps(_login_bootstrap_payload(settings)))
    html = html.replace("__QYM_ROOT_PATH_JSON__", json.dumps(root_path))
    html = html.replace("__QYM_PREFIX__", root_path)
    html = html.replace(
        "<!--__QYM_LOCAL_AUTH_MARKER__-->",
        '<meta name="qym-local-auth" content="enabled">' if local_auth_enabled(settings) else "",
    )
    return HTMLResponse(html)


@router.get("/v1/auth/providers")
def auth_providers() -> Dict[str, Any]:
    settings = PlatformSettings()
    return _login_bootstrap_payload(settings)


@router.get("/v1/auth/login/{provider}", response_model=None)
async def auth_login(provider: str, request: Request):
    settings = PlatformSettings()
    if not auth_mode_is_oidc(settings):
        raise HTTPException(status_code=400, detail="OIDC auth mode is not enabled")
    if provider not in {item["id"] for item in provider_catalog(settings)}:
        raise HTTPException(status_code=404, detail="Unknown provider")
    store_login_next(request, request.query_params.get("next"))
    return await begin_provider_login(request, provider, settings)


@router.get("/v1/auth/callback/{provider}", response_model=None)
async def auth_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    settings = PlatformSettings()
    if not auth_mode_is_oidc(settings):
        raise HTTPException(status_code=400, detail="OIDC auth mode is not enabled")
    identity = await exchange_provider_identity(request, provider, settings)
    user = resolve_or_provision_user(db, identity)
    set_authenticated_session(request, user, provider)
    return RedirectResponse(url=pop_login_next(request), status_code=303)


class PasswordLoginRequest(BaseModel):
    email: str
    password: str


class PasswordSignupRequest(PasswordLoginRequest):
    display_name: str = ""


@router.post("/v1/auth/login/password")
def auth_login_password(
    payload: PasswordLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    _ensure_local_auth_enabled(settings)

    email = _normalize_email(payload.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise _invalid_credentials()

    credential = db.query(LocalAuthCredential).filter(LocalAuthCredential.user_id == user.id).first()
    if not credential or not verify_password(payload.password, credential.password_hash):
        raise _invalid_credentials()

    credential.last_login_at = datetime.utcnow()
    db.commit()
    set_authenticated_session(request, user, "local_password")
    return {"ok": True, "next": _resolve_next(request)}


@router.post("/v1/auth/signup/password", status_code=status.HTTP_201_CREATED)
def auth_signup_password(
    payload: PasswordSignupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    _ensure_local_auth_enabled(settings)

    email = _normalize_email(payload.email)
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=email,
        display_name=_default_display_name(email, payload.display_name),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(
        LocalAuthCredential(
            user_id=user.id,
            password_hash=password_hash,
        )
    )
    db.add(
        UserIdentity(
            user_id=user.id,
            provider="local_password",
            subject=user.id,
            email=email,
            raw_claims={"email": email, "auth_type": "local_password"},
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    db.refresh(user)
    set_authenticated_session(request, user, "local_password")
    return {"ok": True, "next": _resolve_next(request)}


@router.post("/v1/auth/logout")
def auth_logout(request: Request) -> Dict[str, Any]:
    clear_authenticated_session(request)
    return {"ok": True}


class BootstrapAdminRequest(BaseModel):
    bootstrap_token: str


@router.post("/v1/auth/bootstrap-admin")
def bootstrap_admin(
    req: BootstrapAdminRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    if not settings.admin_bootstrap_token or req.bootstrap_token != settings.admin_bootstrap_token:
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")

    user = db.query(User).filter(User.id == principal.user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == UserRole.ADMIN:
        return {"ok": True, "user_id": user.id, "role": user.role.value}
    admin_exists = db.query(User.id).filter(User.role == UserRole.ADMIN, User.is_active == True).first() is not None
    if admin_exists:
        raise HTTPException(status_code=409, detail="Admin already exists")
    user.role = UserRole.ADMIN
    db.commit()
    db.refresh(user)
    return {"ok": True, "user_id": user.id, "role": user.role.value}
