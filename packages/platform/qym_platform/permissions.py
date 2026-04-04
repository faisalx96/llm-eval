from __future__ import annotations

from sqlalchemy import false
from sqlalchemy.orm import Query, Session

from qym_platform.auth import Principal
from qym_platform.db.models import ProjectMembership, ProjectRole, Run, UserRole


def get_project_membership(db: Session, user_id: str, project_id: str) -> ProjectMembership | None:
    return (
        db.query(ProjectMembership)
        .filter(ProjectMembership.user_id == user_id, ProjectMembership.project_id == project_id)
        .first()
    )


def visible_project_ids(db: Session, principal: Principal) -> set[str]:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        rows = db.query(ProjectMembership.project_id).distinct().all()
        return {row[0] for row in rows}
    rows = db.query(ProjectMembership.project_id).filter(ProjectMembership.user_id == principal.user.id).all()
    return {row[0] for row in rows}


def has_project_access(db: Session, principal: Principal, project_id: str) -> bool:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return True
    return get_project_membership(db, principal.user.id, project_id) is not None


def is_project_manager(db: Session, principal: Principal, project_id: str) -> bool:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return True
    membership = get_project_membership(db, principal.user.id, project_id)
    return bool(membership and membership.role == ProjectRole.MANAGER)


def can_manage_project_members(db: Session, principal: Principal, project_id: str) -> bool:
    return is_project_manager(db, principal, project_id)


def can_view_run(db: Session, principal: Principal, run: Run) -> bool:
    return has_project_access(db, principal, run.project_id)


def can_modify_run(db: Session, principal: Principal, run: Run) -> bool:
    return has_project_access(db, principal, run.project_id)


def can_review_run(db: Session, principal: Principal, run: Run) -> bool:
    return has_project_access(db, principal, run.project_id)


def can_approve_run(db: Session, principal: Principal, run: Run) -> bool:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return True
    if run.owner_user_id == principal.user.id:
        return False
    return is_project_manager(db, principal, run.project_id)


def can_delete_run(db: Session, principal: Principal, run: Run) -> bool:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return True
    if run.owner_user_id == principal.user.id:
        return True
    return is_project_manager(db, principal, run.project_id)


def apply_reviewable_run_filter(query: Query, db: Session, principal: Principal) -> Query:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return query

    project_ids = visible_project_ids(db, principal)
    if not project_ids:
        return query.filter(false())

    return query.filter(Run.project_id.in_(project_ids))
