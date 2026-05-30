from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.api.projects import serialize_project_payloads
from qym_platform.db.models import Project, ProjectMembership, User, UserRole
from qym_platform.deps import get_db
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
        project_models = db.query(Project).filter(Project.is_active == True).order_by(Project.name).all()
    else:
        memberships = (
            db.query(ProjectMembership, Project)
            .join(Project, Project.id == ProjectMembership.project_id)
            .filter(ProjectMembership.user_id == u.id, Project.is_active == True)
            .order_by(Project.name)
            .all()
        )
        project_models = [project for membership, project in memberships]
    projects = serialize_project_payloads(db, project_models, principal)
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
