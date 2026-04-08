from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import Project, ProjectMembership, User, UserRole
from qym_platform.deps import get_db
from qym_platform.openai_compat import create_chat_completion_compat
from qym_platform.secrets import (
    build_llm_config_storage,
    encryption_available,
    llm_config_api_key_hint,
    llm_config_has_api_key,
    resolve_llm_api_key,
)
from qym_platform.settings import PlatformSettings


router = APIRouter()


def _require_admin(principal: Principal) -> None:
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/v1/me")
def me(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    u = principal.user
    if u.role == UserRole.ADMIN:
        projects = [
            {
                "id": project.id,
                "slug": project.slug,
                "name": project.name,
                "role": "MANAGER",
            }
            for project in db.query(Project).filter(Project.is_active == True).order_by(Project.name).all()
        ]
    else:
        memberships = (
            db.query(ProjectMembership, Project)
            .join(Project, Project.id == ProjectMembership.project_id)
            .filter(ProjectMembership.user_id == u.id, Project.is_active == True)
            .order_by(Project.name)
            .all()
        )
        projects = [
            {
                "id": project.id,
                "slug": project.slug,
                "name": project.name,
                "role": membership.role.value,
            }
            for membership, project in memberships
        ]
    default_project = projects[0] if projects else None

    admin_exists = db.query(User.id).filter(User.role == UserRole.ADMIN, User.is_active == True).first() is not None
    can_bootstrap_admin = (
        principal.auth_type in {"oidc", "local_password"}
        and u.role != UserRole.ADMIN
        and bool(PlatformSettings().admin_bootstrap_token)
        and not admin_exists
    )

    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "title": u.title,
        "role": u.role.value if hasattr(u.role, "value") else u.role,
        "auth_type": principal.auth_type,
        "auth_provider": principal.provider,
        "needs_admin_bootstrap": not admin_exists,
        "can_bootstrap_admin": can_bootstrap_admin,
        "projects": projects,
        "default_project": default_project,
    }


@router.get("/v1/users")
def list_users(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> list[Dict[str, Any]]:
    _ = principal
    users = db.query(User).filter(User.is_active == True).order_by(User.email).all()
    return [
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "title": user.title,
            "role": user.role.value,
        }
        for user in users
    ]


class LLMConfigRequest(BaseModel):
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="gpt-4o-mini")


@router.get("/v1/me/llm-config")
def get_llm_config(
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    cfg = principal.user.llm_config if isinstance(principal.user.llm_config, dict) else {}
    return {
        "llm_base_url": cfg.get("llm_base_url", "https://api.openai.com/v1"),
        "llm_model": cfg.get("llm_model", "gpt-4o-mini"),
        "llm_api_key_set": llm_config_has_api_key(cfg),
        "llm_api_key_hint": llm_config_api_key_hint(cfg),
        "llm_config_storage_ready": encryption_available(settings),
    }


@router.put("/v1/me/llm-config")
def update_llm_config(
    req: LLMConfigRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    user = db.query(User).filter(User.id == principal.user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = user.llm_config if isinstance(user.llm_config, dict) else {}
    api_key = req.llm_api_key.strip()
    if api_key == "__KEEP__":
        try:
            api_key = resolve_llm_api_key(existing, settings)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if api_key:
        if not encryption_available(settings):
            raise HTTPException(status_code=400, detail="LLM config encryption is not configured")
        user.llm_config = build_llm_config_storage(
            base_url=req.llm_base_url,
            model=req.llm_model,
            api_key=api_key,
            settings=settings,
        )
    else:
        user.llm_config = {
            "llm_base_url": req.llm_base_url.strip().rstrip("/"),
            "llm_api_key_last4": "",
            "llm_model": req.llm_model.strip(),
        }
    db.commit()
    return {"ok": True}


@router.post("/v1/me/llm-config/test")
async def test_llm_config(
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    settings = PlatformSettings()
    cfg = principal.user.llm_config if isinstance(principal.user.llm_config, dict) else {}
    try:
        api_key = resolve_llm_api_key(cfg, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not api_key:
        raise HTTPException(status_code=400, detail="No API key configured")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=cfg.get("llm_base_url", "https://api.openai.com/v1"),
        api_key=api_key,
    )
    model = cfg.get("llm_model", "gpt-4o-mini")
    try:
        resp = await create_chat_completion_compat(
            client,
            model=model,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            max_tokens=4,
        )
        return {"ok": True, "model": model, "response": resp.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"LLM connection failed: {e}")


class CreateUserRequest(BaseModel):
    email: str
    display_name: str = ""
    role: UserRole = UserRole.MEMBER
    is_active: bool = True


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


@router.get("/v1/admin/users")
def admin_list_users(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> list[Dict[str, Any]]:
    _require_admin(principal)
    users = db.query(User).order_by(User.email).all()
    return [
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "title": user.title,
            "role": user.role.value,
            "is_active": user.is_active,
        }
        for user in users
    ]


@router.post("/v1/admin/users")
def admin_create_user(
    req: CreateUserRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    email = req.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return {"id": existing.id, "email": existing.email, "existing": True}

    user = User(
        email=email,
        display_name=req.display_name.strip(),
        role=req.role,
        is_active=req.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email}


@router.put("/v1/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        next_email = req.email.strip().lower()
        conflict = db.query(User).filter(User.email == next_email, User.id != user.id).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = next_email
    if req.display_name is not None:
        user.display_name = req.display_name.strip()
    if req.role is not None:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active

    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "ok": True}


@router.delete("/v1/admin/users/{user_id}")
def admin_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    if user_id == principal.user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return {"ok": True, "deleted_id": user_id}
