from __future__ import annotations

import re
import secrets
from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import ApiKey, Project, ProjectMembership, ProjectRole, Run, User, UserRole
from qym_platform.deps import get_db
from qym_platform.permissions import can_manage_project_members, get_project_membership, has_project_access
from qym_platform.security import api_key_prefix, hash_api_key


router = APIRouter()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "project"


def _require_admin(principal: Principal) -> None:
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")


def _get_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_project_by_slug(db: Session, slug: str) -> Project:
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_project_access(db: Session, principal: Principal, project_id: str) -> Project:
    project = _get_project(db, project_id)
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _membership_role(db: Session, principal: Principal, project_id: str) -> str:
    if principal.user.role == UserRole.ADMIN:
        return ProjectRole.MANAGER.value
    membership = get_project_membership(db, principal.user.id, project_id)
    return membership.role.value if membership else ""


def _project_member_counts(db: Session, project_ids: Iterable[str]) -> Dict[str, int]:
    ids = [project_id for project_id in project_ids if project_id]
    if not ids:
        return {}
    rows = (
        db.query(ProjectMembership.project_id, func.count(ProjectMembership.id))
        .filter(ProjectMembership.project_id.in_(ids))
        .group_by(ProjectMembership.project_id)
        .all()
    )
    return {project_id: int(count) for project_id, count in rows}


def _project_run_counts(db: Session, project_ids: Iterable[str]) -> Dict[str, int]:
    ids = [project_id for project_id in project_ids if project_id]
    if not ids:
        return {}
    rows = (
        db.query(Run.project_id, func.count(Run.id))
        .filter(Run.project_id.in_(ids), Run.deleted_at.is_(None))
        .group_by(Run.project_id)
        .all()
    )
    return {project_id: int(count) for project_id, count in rows}


def _project_payload(
    db: Session,
    project: Project,
    principal: Principal,
    *,
    member_counts: Optional[Dict[str, int]] = None,
    run_counts: Optional[Dict[str, int]] = None,
    role: Optional[str] = None,
) -> Dict[str, Any]:
    member_count = (
        int(member_counts[project.id])
        if member_counts is not None and project.id in member_counts
        else db.query(ProjectMembership).filter(ProjectMembership.project_id == project.id).count()
    )
    run_count = (
        int(run_counts[project.id])
        if run_counts is not None and project.id in run_counts
        else db.query(Run.id).filter(Run.project_id == project.id, Run.deleted_at.is_(None)).count()
    )
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "is_active": project.is_active,
        "member_count": member_count,
        "run_count": run_count,
        "role": role if role is not None else _membership_role(db, principal, project.id),
        "created_at": to_api_timestamp(project.created_at),
        "updated_at": to_api_timestamp(project.updated_at),
    }


def serialize_project_payloads(db: Session, projects: Iterable[Project], principal: Principal) -> list[Dict[str, Any]]:
    project_list = list(projects)
    if not project_list:
        return []

    project_ids = [project.id for project in project_list]
    member_counts = _project_member_counts(db, project_ids)
    run_counts = _project_run_counts(db, project_ids)

    if principal.user.role == UserRole.ADMIN:
        role_map = {project.id: ProjectRole.MANAGER.value for project in project_list}
    else:
        role_rows = (
            db.query(ProjectMembership.project_id, ProjectMembership.role)
            .filter(ProjectMembership.user_id == principal.user.id, ProjectMembership.project_id.in_(project_ids))
            .all()
        )
        role_map = {project_id: role.value if hasattr(role, "value") else str(role) for project_id, role in role_rows}

    return [
        _project_payload(
            db,
            project,
            principal,
            member_counts=member_counts,
            run_counts=run_counts,
            role=role_map.get(project.id, ""),
        )
        for project in project_list
    ]


def _can_create_project(db: Session, principal: Principal) -> bool:
    if principal.user.role == UserRole.ADMIN:
        return True
    return (
        db.query(ProjectMembership.id)
        .filter(ProjectMembership.user_id == principal.user.id, ProjectMembership.role == ProjectRole.MANAGER)
        .first()
        is not None
    )


def _serialize_member(member: ProjectMembership, user: User) -> Dict[str, Any]:
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": member.role.value,
        "created_at": to_api_timestamp(member.created_at),
        "updated_at": to_api_timestamp(member.updated_at),
    }


def _ensure_not_last_manager(db: Session, project_id: str, target_user_id: str, next_role: Optional[ProjectRole]) -> None:
    current = (
        db.query(ProjectMembership)
        .filter(ProjectMembership.project_id == project_id, ProjectMembership.user_id == target_user_id)
        .first()
    )
    if not current or current.role != ProjectRole.MANAGER:
        return
    if next_role == ProjectRole.MANAGER:
        return
    manager_count = (
        db.query(ProjectMembership)
        .filter(ProjectMembership.project_id == project_id, ProjectMembership.role == ProjectRole.MANAGER)
        .count()
    )
    if manager_count <= 1:
        raise HTTPException(status_code=400, detail="Project must retain at least one manager")


class CreateProjectRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class UpsertMembershipRequest(BaseModel):
    user_id: str
    role: ProjectRole = ProjectRole.MEMBER


class UpdateMembershipRequest(BaseModel):
    role: ProjectRole


class CreateProjectKeyRequest(BaseModel):
    name: str = Field(default="default")
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])


@router.get("/v1/projects")
def list_projects(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    if principal.user.role == UserRole.ADMIN:
        projects = db.query(Project).order_by(Project.name).all()
    else:
        projects = (
            db.query(Project)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .filter(ProjectMembership.user_id == principal.user.id)
            .order_by(Project.name)
            .all()
        )
    return {"projects": serialize_project_payloads(db, projects, principal)}


@router.post("/v1/projects")
def create_project_for_creator(
    req: CreateProjectRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    if not _can_create_project(db, principal):
        raise HTTPException(status_code=403, detail="Only admins and project managers can create projects")
    slug = _slugify(req.slug or req.name)
    if db.query(Project).filter(Project.slug == slug).first():
        raise HTTPException(status_code=400, detail="Project slug already exists")
    project = Project(
        name=req.name.strip(),
        slug=slug,
        description=req.description.strip(),
        created_by_user_id=principal.user.id,
        is_active=True,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMembership(
            project_id=project.id,
            user_id=principal.user.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=principal.user.id,
        )
    )
    db.commit()
    db.refresh(project)
    return _project_payload(db, project, principal)


@router.get("/v1/projects/by-slug/{project_slug}")
def get_project_by_slug(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project = _get_project_by_slug(db, project_slug)
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return _project_payload(db, project, principal)


@router.get("/v1/projects/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project = _require_project_access(db, principal, project_id)
    return _project_payload(db, project, principal)


@router.get("/v1/projects/{project_id}/members")
def list_project_members(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    members = (
        db.query(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .filter(ProjectMembership.project_id == project_id)
        .order_by(ProjectMembership.role.desc(), User.email)
        .all()
    )
    return {"members": [_serialize_member(member, user) for member, user in members]}


@router.post("/v1/projects/{project_id}/members")
def add_project_member(
    project_id: str,
    req: UpsertMembershipRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    if not can_manage_project_members(db, principal, project_id):
        raise HTTPException(status_code=403, detail="Manager only")
    project = _get_project(db, project_id)
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    existing = (
        db.query(ProjectMembership)
        .filter(ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this project")
    member = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=req.role,
        added_by_user_id=principal.user.id,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _serialize_member(member, user)


@router.patch("/v1/projects/{project_id}/members/{user_id}")
def update_project_member(
    project_id: str,
    user_id: str,
    req: UpdateMembershipRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    if not can_manage_project_members(db, principal, project_id):
        raise HTTPException(status_code=403, detail="Manager only")
    member = (
        db.query(ProjectMembership)
        .filter(ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")
    _ensure_not_last_manager(db, project_id, user_id, req.role)
    member.role = req.role
    db.commit()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _serialize_member(member, user)


@router.delete("/v1/projects/{project_id}/members/{user_id}")
def remove_project_member(
    project_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    if not can_manage_project_members(db, principal, project_id):
        raise HTTPException(status_code=403, detail="Manager only")
    member = (
        db.query(ProjectMembership)
        .filter(ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")
    _ensure_not_last_manager(db, project_id, user_id, None)
    db.delete(member)
    db.commit()
    return {"ok": True, "project_id": project_id, "user_id": user_id}


@router.get("/v1/projects/{project_id}/api-keys")
def list_project_api_keys(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    keys = (
        db.query(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .filter(ApiKey.project_id == project_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {
        "api_keys": [
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.prefix,
                "project_id": key.project_id,
                "creator": {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                },
                "scopes": key.scopes,
                "created_at": to_api_timestamp(key.created_at),
                "revoked_at": to_api_timestamp(key.revoked_at),
            }
            for key, user in keys
        ]
    }


@router.post("/v1/projects/{project_id}/api-keys")
def create_project_api_key(
    project_id: str,
    req: CreateProjectKeyRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    token = secrets.token_urlsafe(32)
    row = ApiKey(
        user_id=principal.user.id,
        project_id=project_id,
        name=req.name,
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=req.scopes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "prefix": row.prefix, "token": token}


@router.delete("/v1/projects/{project_id}/api-keys/{key_id}")
def revoke_project_api_key(
    project_id: str,
    key_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_project_access(db, principal, project_id)
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.project_id == project_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    is_owner = key.user_id == principal.user.id
    is_manager = can_manage_project_members(db, principal, project_id)
    if not (principal.user.role == UserRole.ADMIN or is_owner or is_manager):
        raise HTTPException(status_code=403, detail="Access denied")
    if key.revoked_at:
        raise HTTPException(status_code=400, detail="API key already revoked")
    key.revoked_at = utc_now_naive()
    db.commit()
    return {"ok": True, "id": key.id}


@router.post("/v1/admin/projects")
def create_project(
    req: CreateProjectRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    slug = _slugify(req.slug or req.name)
    if db.query(Project).filter(Project.slug == slug).first():
        raise HTTPException(status_code=400, detail="Project slug already exists")
    project = Project(
        name=req.name.strip(),
        slug=slug,
        description=req.description.strip(),
        created_by_user_id=principal.user.id,
        is_active=True,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMembership(
            project_id=project.id,
            user_id=principal.user.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=principal.user.id,
        )
    )
    db.commit()
    db.refresh(project)
    return _project_payload(db, project, principal)


@router.patch("/v1/admin/projects/{project_id}")
def update_project(
    project_id: str,
    req: UpdateProjectRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    project = _get_project(db, project_id)
    if req.name is not None:
        project.name = req.name.strip()
    if req.slug is not None:
        next_slug = _slugify(req.slug)
        conflict = db.query(Project).filter(Project.slug == next_slug, Project.id != project.id).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Project slug already exists")
        project.slug = next_slug
    if req.description is not None:
        project.description = req.description.strip()
    if req.is_active is not None:
        project.is_active = req.is_active
    db.commit()
    db.refresh(project)
    return _project_payload(db, project, principal)


@router.delete("/v1/admin/projects/{project_id}")
def archive_project(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    _require_admin(principal)
    project = _get_project(db, project_id)
    has_runs = db.query(Run.id).filter(Run.project_id == project.id).first() is not None
    if has_runs:
        project.is_active = False
        db.commit()
        return {"ok": True, "project_id": project.id, "archived": True}
    db.query(ApiKey).filter(ApiKey.project_id == project.id).delete()
    db.query(ProjectMembership).filter(ProjectMembership.project_id == project.id).delete()
    db.delete(project)
    db.commit()
    return {"ok": True, "project_id": project.id, "deleted": True}
