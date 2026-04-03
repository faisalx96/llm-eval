from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.auth_oidc import (
    auth_mode_is_oidc,
    begin_provider_login,
    clear_authenticated_session,
    enabled_provider_names,
    exchange_provider_identity,
    get_session_user_and_provider,
    pop_login_next,
    provider_catalog,
    resolve_or_provision_user,
    sanitize_next,
    set_authenticated_session,
    store_login_next,
)
from qym_platform.db.models import User, UserRole
from qym_platform.deps import get_db
from qym_platform.settings import PlatformSettings


router = APIRouter()


def _platform_static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "_static"


@router.get("/login", response_model=None)
def login_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    settings = PlatformSettings()
    next_value = sanitize_next(request.query_params.get("next"))
    if auth_mode_is_oidc(settings):
        resolved = get_session_user_and_provider(db, request)
        if resolved:
            return RedirectResponse(url=next_value, status_code=303)
    idx = _platform_static_dir() / "dashboard" / "login.html"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Login UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/v1/auth/providers")
def auth_providers() -> Dict[str, Any]:
    settings = PlatformSettings()
    return {
        "auth_mode": settings.auth_mode,
        "providers": provider_catalog(settings),
    }


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
    if not auth_mode_is_oidc(settings):
        raise HTTPException(status_code=400, detail="Bootstrap admin is only available in oidc mode")
    if not settings.admin_bootstrap_token or req.bootstrap_token != settings.admin_bootstrap_token:
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")

    user = db.query(User).filter(User.id == principal.user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == UserRole.ADMIN:
        return {"ok": True, "user_id": user.id, "role": user.role.value}
    user.role = UserRole.ADMIN
    db.commit()
    db.refresh(user)
    return {"ok": True, "user_id": user.id, "role": user.role.value}
