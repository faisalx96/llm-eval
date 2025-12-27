from __future__ import annotations

import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm_eval_platform.auth import Principal, require_ui_principal
from llm_eval_platform.db.models import ApiKey, OrgUnit, OrgUnitType, User, UserRole
from llm_eval_platform.deps import get_db
from llm_eval_platform.security import api_key_prefix, hash_api_key


def _require_admin(principal: Principal) -> None:
    """Raise 403 if the principal is not an ADMIN."""
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")


def _check_manager_conflict(
    db: Session, team_unit_id: Optional[str], role: UserRole, exclude_user_id: Optional[str] = None
) -> None:
    """Raise 400 if assigning MANAGER role would create duplicate manager for team."""
    if role != UserRole.MANAGER or not team_unit_id:
        return
    query = db.query(User).filter(
        User.team_unit_id == team_unit_id,
        User.role == UserRole.MANAGER,
        User.is_active == True,
    )
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    existing_manager = query.first()
    if existing_manager:
        raise HTTPException(
            status_code=400,
            detail=f"Team already has a manager: {existing_manager.email}"
        )


router = APIRouter()


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="default")
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])


class CreateApiKeyResponse(BaseModel):
    id: str
    prefix: str
    token: str  # shown once


@router.get("/v1/me")
def me(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    u = principal.user
    team = None
    department = None
    sector = None

    if u.team_unit_id:
        t = db.query(OrgUnit).filter(OrgUnit.id == u.team_unit_id).first()
        if t:
            team = {"id": t.id, "name": t.name}
            if t.parent_id:
                d = db.query(OrgUnit).filter(OrgUnit.id == t.parent_id).first()
                if d:
                    department = {"id": d.id, "name": d.name}
                    if d.parent_id:
                        s = db.query(OrgUnit).filter(OrgUnit.id == d.parent_id).first()
                        if s:
                            sector = {"id": s.id, "name": s.name}

    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "title": u.title,
        "role": u.role.value if hasattr(u.role, "value") else u.role,
        "team": team,
        "department": department,
        "sector": sector,
    }


@router.get("/v1/me/api-keys")
def list_api_keys(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == principal.user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.prefix,
                "scopes": k.scopes,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            }
            for k in keys
        ]
    }


@router.post("/v1/me/api-keys", response_model=CreateApiKeyResponse)
def create_api_key(
    req: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> CreateApiKeyResponse:
    token = secrets.token_urlsafe(32)
    prefix = api_key_prefix(token)
    row = ApiKey(
        user_id=principal.user.id,
        name=req.name,
        prefix=prefix,
        key_hash=hash_api_key(token),
        scopes=req.scopes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return CreateApiKeyResponse(id=row.id, prefix=row.prefix, token=token)


@router.delete("/v1/me/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Revoke an API key (soft delete)."""
    from datetime import datetime
    key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == principal.user.id)
        .first()
    )
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at:
        raise HTTPException(status_code=400, detail="API key already revoked")
    key.revoked_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": key_id}


class CreateUserRequest(BaseModel):
    email: str
    display_name: str = ""
    title: str = ""
    role: UserRole = UserRole.EMPLOYEE
    team_unit_id: Optional[str] = None
    is_active: bool = True


@router.get("/v1/admin/users")
def admin_list_users(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> list[Dict[str, Any]]:
    """List all users (admin only)."""
    _require_admin(principal)
    users = db.query(User).order_by(User.email).all()
    result = []
    for u in users:
        team = None
        if u.team_unit_id:
            t = db.query(OrgUnit).filter(OrgUnit.id == u.team_unit_id).first()
            if t:
                team = {"id": t.id, "name": t.name}
        result.append({
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "title": u.title,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "team": team,
            "is_active": u.is_active,
        })
    return result


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

    # Validate team if provided
    if req.team_unit_id:
        team = db.query(OrgUnit).filter(OrgUnit.id == req.team_unit_id, OrgUnit.type == OrgUnitType.TEAM).first()
        if not team:
            raise HTTPException(status_code=400, detail="Team not found")

    # Prevent duplicate managers per team
    _check_manager_conflict(db, req.team_unit_id, req.role)

    u = User(
        email=email,
        display_name=req.display_name,
        title=req.title,
        role=req.role,
        team_unit_id=req.team_unit_id,
        is_active=req.is_active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "email": u.email}


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    title: Optional[str] = None
    role: Optional[UserRole] = None
    team_unit_id: Optional[str] = None
    is_active: Optional[bool] = None


@router.put("/v1/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update a user (admin only)."""
    _require_admin(principal)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        user.email = req.email.strip().lower()
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.title is not None:
        user.title = req.title
    if req.role is not None:
        user.role = req.role
    if req.team_unit_id is not None:
        if req.team_unit_id:
            team = db.query(OrgUnit).filter(OrgUnit.id == req.team_unit_id, OrgUnit.type == OrgUnitType.TEAM).first()
            if not team:
                raise HTTPException(status_code=400, detail="Team not found")
        user.team_unit_id = req.team_unit_id if req.team_unit_id else None

    # Prevent duplicate managers per team (check with updated values)
    final_role = req.role if req.role is not None else user.role
    final_team = user.team_unit_id  # already updated above if provided
    _check_manager_conflict(db, final_team, final_role, exclude_user_id=user_id)

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
    """Delete a user (admin only)."""
    _require_admin(principal)

    # Prevent self-deletion
    if user_id == principal.user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Clear manager reference from any team this user manages
    db.query(OrgUnit).filter(OrgUnit.manager_user_id == user_id).update({"manager_user_id": None})

    # Delete user's API keys
    db.query(ApiKey).filter(ApiKey.user_id == user_id).delete()

    db.delete(user)
    db.commit()
    return {"ok": True, "deleted_id": user_id}


