from __future__ import annotations

from sqlalchemy import false
from sqlalchemy.orm import Query, Session

from qym_platform.auth import Principal
from qym_platform.db.models import OrgUnit, OrgUnitType, PlatformSetting, Run, RunWorkflowStatus, User, UserRole


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    return row.value if row else default


def manager_team_ids(db: Session, manager_user_id: str) -> set[str]:
    teams = db.query(OrgUnit).filter(
        OrgUnit.type == OrgUnitType.TEAM,
        OrgUnit.manager_user_id == manager_user_id,
    ).all()
    return {t.id for t in teams}


def _run_owner(db: Session, run: Run) -> User | None:
    return db.query(User).filter(User.id == run.owner_user_id).first()


def _same_team(db: Session, principal: Principal, run: Run) -> bool:
    """Check if the principal and run owner are on the same team."""
    if not principal.user.team_unit_id:
        return False
    owner = _run_owner(db, run)
    if not owner or not owner.team_unit_id:
        return False
    return owner.team_unit_id == principal.user.team_unit_id


def can_view_run(db: Session, principal: Principal, run: Run) -> bool:
    if principal.auth_type == "none":
        return True
    if principal.user.role == UserRole.ADMIN:
        return True
    if run.owner_user_id == principal.user.id:
        return True

    # Team members can view each other's runs
    if principal.user.role == UserRole.EMPLOYEE:
        return _same_team(db, principal, run)

    if principal.user.role == UserRole.MANAGER:
        owner = _run_owner(db, run)
        if not owner or not owner.team_unit_id:
            return False
        return owner.team_unit_id in manager_team_ids(db, principal.user.id)

    if principal.user.role in {UserRole.GM, UserRole.VP}:
        gm_vp_approved_only = _get_setting(db, "gm_vp_approved_only", "true").lower() == "true"
        if gm_vp_approved_only:
            return run.status == RunWorkflowStatus.APPROVED
        return run.status in {RunWorkflowStatus.SUBMITTED, RunWorkflowStatus.APPROVED}

    return False


def can_modify_run(db: Session, principal: Principal, run: Run) -> bool:
    if principal.auth_type == "none":
        return True
    if principal.user.role == UserRole.ADMIN:
        return True
    if run.owner_user_id == principal.user.id:
        return True
    if principal.user.role != UserRole.MANAGER:
        return False

    owner = _run_owner(db, run)
    if not owner or not owner.team_unit_id:
        return False
    return owner.team_unit_id in manager_team_ids(db, principal.user.id)


def can_review_run(db: Session, principal: Principal, run: Run) -> bool:
    if principal.auth_type == "none":
        return True
    if principal.user.role == UserRole.ADMIN:
        return True

    # Team members can review their own and each other's runs
    if principal.user.role == UserRole.EMPLOYEE:
        return run.owner_user_id == principal.user.id or _same_team(db, principal, run)

    if principal.user.role == UserRole.MANAGER:
        owner = _run_owner(db, run)
        if not owner or not owner.team_unit_id:
            return False
        return owner.team_unit_id in manager_team_ids(db, principal.user.id)

    return False


def apply_reviewable_run_filter(query: Query, db: Session, principal: Principal) -> Query:
    if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
        return query
    if principal.user.role != UserRole.MANAGER:
        return query.filter(false())

    team_ids = manager_team_ids(db, principal.user.id)
    if not team_ids:
        return query.filter(false())

    return query.join(User, User.id == Run.owner_user_id).filter(User.team_unit_id.in_(team_ids))
