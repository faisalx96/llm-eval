from __future__ import annotations

import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm_eval_platform.auth import Principal, require_ui_principal
from llm_eval_platform.db.models import ApiKey, User, UserRole
from llm_eval_platform.deps import get_db
from llm_eval_platform.security import api_key_prefix, hash_api_key


router = APIRouter()


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="default")
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])


class CreateApiKeyResponse(BaseModel):
    id: str
    prefix: str
    token: str  # shown once


@router.get("/v1/me")
def me(principal: Principal = Depends(require_ui_principal)) -> Dict[str, Any]:
    u = principal.user
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "title": u.title,
        "role": u.role,
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


class CreateUserRequest(BaseModel):
    email: str
    display_name: str = ""
    title: str = ""
    role: UserRole = UserRole.EMPLOYEE


@router.post("/v1/admin/users")
def admin_create_user(
    req: CreateUserRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    # Minimal admin gate: VP only for now
    if principal.user.role != UserRole.VP:
        raise HTTPException(status_code=403, detail="Admin only")
    email = req.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return {"id": existing.id, "email": existing.email}
    u = User(email=email, display_name=req.display_name, title=req.title, role=req.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "email": u.email}


