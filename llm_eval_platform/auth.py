from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from llm_eval_platform.db.models import ApiKey, User
from llm_eval_platform.deps import get_db
from llm_eval_platform.security import api_key_prefix, verify_api_key
from llm_eval_platform.settings import PlatformSettings


@dataclass(frozen=True)
class Principal:
    user: User
    auth_type: str  # api_key|proxy_headers|none


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def require_api_key_principal(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
) -> Principal:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer API key")

    prefix = api_key_prefix(token)
    row = (
        db.query(ApiKey)
        .filter(ApiKey.prefix == prefix)
        .filter(ApiKey.revoked_at.is_(None))
        .first()
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not verify_api_key(token, row.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")
    return Principal(user=user, auth_type="api_key")


def require_ui_principal(
    db: Session = Depends(get_db),
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    x_email: Optional[str] = Header(default=None, alias="X-Email"),
    x_admin_bootstrap: Optional[str] = Header(default=None, alias="X-Admin-Bootstrap"),
) -> Principal:
    """UI auth for internal deployments.

    - Prefer reverse-proxy headers (X-User-Email / X-Email)
    - Support first-admin bootstrap via X-Admin-Bootstrap == LLM_EVAL_ADMIN_BOOTSTRAP_TOKEN
    """
    settings = PlatformSettings()
    email = (x_user_email or x_email or "").strip().lower()

    if email:
        user = db.query(User).filter(User.email == email).first()
        if user and user.is_active:
            return Principal(user=user, auth_type="proxy_headers")

    # Bootstrap if allowed and no users exist
    has_any = db.query(User.id).limit(1).first() is not None
    if not has_any and settings.admin_bootstrap_token and x_admin_bootstrap == settings.admin_bootstrap_token:
        if not email:
            raise HTTPException(status_code=400, detail="Bootstrap requires X-User-Email")
        user = User(email=email, display_name=email, role="VP")  # bootstrap as top admin
        db.add(user)
        db.commit()
        db.refresh(user)
        return Principal(user=user, auth_type="bootstrap")

    raise HTTPException(status_code=401, detail="Missing user identity headers")


