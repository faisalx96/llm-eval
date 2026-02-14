"""Admin API for org units (Sector/Department/Team), user assignment, and closure maintenance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import (
    OrgUnit,
    OrgUnitClosure,
    OrgUnitType,
    PlatformSetting,
    User,
    UserRole,
)
from qym_platform.deps import get_db


router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _require_admin(principal: Principal) -> None:
    """Raise 403 if the principal is not an ADMIN."""
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")


def _validate_org_unit_for_role(
    db: Session, org_unit_id: Optional[str], role: UserRole
) -> None:
    """Validate that the org unit type matches the role requirements."""
    if not org_unit_id:
        return

    # ADMIN doesn't need org unit
    if role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Admin users should not be assigned to an org unit")

    unit = db.query(OrgUnit).filter(OrgUnit.id == org_unit_id).first()
    if not unit:
        raise HTTPException(status_code=400, detail="Org unit not found")

    # Map roles to expected org unit types
    expected_types = {
        UserRole.EMPLOYEE: OrgUnitType.TEAM,
        UserRole.MANAGER: OrgUnitType.TEAM,
        UserRole.GM: OrgUnitType.DEPARTMENT,
        UserRole.VP: OrgUnitType.SECTOR,
    }

    expected_type = expected_types.get(role)
    if expected_type and unit.type != expected_type:
        type_names = {
            OrgUnitType.TEAM: "Team",
            OrgUnitType.DEPARTMENT: "Department",
            OrgUnitType.SECTOR: "Sector",
        }
        raise HTTPException(
            status_code=400,
            detail=f"{role.value} must be assigned to a {type_names.get(expected_type, 'valid org unit')}"
        )


# ---------------------------------------------------------------------------
# Org tree / listing
# ---------------------------------------------------------------------------


def _org_unit_to_dict(unit: OrgUnit, db: Session) -> Dict[str, Any]:
    """Convert an OrgUnit to a dict with manager info."""
    manager = None

    # For teams, use manager_user_id
    if unit.type == OrgUnitType.TEAM and unit.manager_user_id:
        mgr = db.query(User).filter(User.id == unit.manager_user_id).first()
        if mgr:
            manager = {"id": mgr.id, "email": mgr.email, "display_name": mgr.display_name}

    # For departments, find GM assigned to this department
    elif unit.type == OrgUnitType.DEPARTMENT:
        gm = db.query(User).filter(
            User.team_unit_id == unit.id,
            User.role == UserRole.GM,
            User.is_active == True
        ).first()
        if gm:
            manager = {"id": gm.id, "email": gm.email, "display_name": gm.display_name}

    # For sectors, find VP assigned to this sector
    elif unit.type == OrgUnitType.SECTOR:
        vp = db.query(User).filter(
            User.team_unit_id == unit.id,
            User.role == UserRole.VP,
            User.is_active == True
        ).first()
        if vp:
            manager = {"id": vp.id, "email": vp.email, "display_name": vp.display_name}

    return {
        "id": unit.id,
        "name": unit.name,
        "type": unit.type.value,
        "parent_id": unit.parent_id,
        "manager": manager,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
    }


@router.get("/org/tree")
def get_org_tree(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return the full org tree: Sector → Department → Team."""
    _require_admin(principal)

    sectors = db.query(OrgUnit).filter(OrgUnit.type == OrgUnitType.SECTOR).order_by(OrgUnit.name).all()
    tree: List[Dict[str, Any]] = []

    for sector in sectors:
        sector_node = _org_unit_to_dict(sector, db)
        departments = (
            db.query(OrgUnit)
            .filter(OrgUnit.type == OrgUnitType.DEPARTMENT, OrgUnit.parent_id == sector.id)
            .order_by(OrgUnit.name)
            .all()
        )
        sector_node["children"] = []
        for dept in departments:
            dept_node = _org_unit_to_dict(dept, db)
            teams = (
                db.query(OrgUnit)
                .filter(OrgUnit.type == OrgUnitType.TEAM, OrgUnit.parent_id == dept.id)
                .order_by(OrgUnit.name)
                .all()
            )
            dept_node["children"] = [_org_unit_to_dict(t, db) for t in teams]
            sector_node["children"].append(dept_node)
        tree.append(sector_node)

    return {"tree": tree}


@router.get("/org/teams")
def list_teams(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List all TEAM org units (for dropdowns)."""
    _require_admin(principal)
    teams = db.query(OrgUnit).filter(OrgUnit.type == OrgUnitType.TEAM).order_by(OrgUnit.name).all()
    return {"teams": [_org_unit_to_dict(t, db) for t in teams]}


# ---------------------------------------------------------------------------
# Create / update / delete org units
# ---------------------------------------------------------------------------


class CreateOrgUnitRequest(BaseModel):
    name: str
    type: OrgUnitType
    parent_id: Optional[str] = None


@router.post("/org/units")
def create_org_unit(
    req: CreateOrgUnitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Create a new org unit (Sector/Department/Team)."""
    _require_admin(principal)

    # Validate hierarchy rules
    if req.type == OrgUnitType.SECTOR:
        if req.parent_id:
            raise HTTPException(status_code=400, detail="Sector cannot have a parent")
    elif req.type == OrgUnitType.DEPARTMENT:
        if not req.parent_id:
            raise HTTPException(status_code=400, detail="Department requires a parent Sector")
        parent = db.query(OrgUnit).filter(OrgUnit.id == req.parent_id).first()
        if not parent or parent.type != OrgUnitType.SECTOR:
            raise HTTPException(status_code=400, detail="Department parent must be a Sector")
    elif req.type == OrgUnitType.TEAM:
        if not req.parent_id:
            raise HTTPException(status_code=400, detail="Team requires a parent Department")
        parent = db.query(OrgUnit).filter(OrgUnit.id == req.parent_id).first()
        if not parent or parent.type != OrgUnitType.DEPARTMENT:
            raise HTTPException(status_code=400, detail="Team parent must be a Department")

    unit = OrgUnit(name=req.name, type=req.type, parent_id=req.parent_id)
    db.add(unit)
    db.commit()
    db.refresh(unit)

    # Rebuild closure for this unit
    _rebuild_closure_for_unit(db, unit)

    return _org_unit_to_dict(unit, db)


class UpdateOrgUnitRequest(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None  # moving to a new parent


@router.patch("/org/units/{unit_id}")
def update_org_unit(
    unit_id: str,
    req: UpdateOrgUnitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update an org unit (rename or move)."""
    _require_admin(principal)

    unit = db.query(OrgUnit).filter(OrgUnit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Org unit not found")

    if req.name is not None:
        unit.name = req.name

    if req.parent_id is not None and req.parent_id != unit.parent_id:
        # Validate move
        if unit.type == OrgUnitType.SECTOR:
            raise HTTPException(status_code=400, detail="Cannot move a Sector")
        if unit.type == OrgUnitType.DEPARTMENT:
            new_parent = db.query(OrgUnit).filter(OrgUnit.id == req.parent_id).first()
            if not new_parent or new_parent.type != OrgUnitType.SECTOR:
                raise HTTPException(status_code=400, detail="Department parent must be a Sector")
        if unit.type == OrgUnitType.TEAM:
            new_parent = db.query(OrgUnit).filter(OrgUnit.id == req.parent_id).first()
            if not new_parent or new_parent.type != OrgUnitType.DEPARTMENT:
                raise HTTPException(status_code=400, detail="Team parent must be a Department")
        unit.parent_id = req.parent_id
        # Rebuild closure after move
        rebuild_all_closure(db)

    db.commit()
    db.refresh(unit)
    return _org_unit_to_dict(unit, db)


@router.delete("/org/units/{unit_id}")
def delete_org_unit(
    unit_id: str,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete an org unit (blocked if has children or assigned users, unless force=true)."""
    _require_admin(principal)

    unit = db.query(OrgUnit).filter(OrgUnit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Org unit not found")

    # Check for children
    children = db.query(OrgUnit).filter(OrgUnit.parent_id == unit_id).count()
    if children > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"Org unit has {children} child unit(s). Use force=true to delete anyway (will orphan children).",
        )

    # Check for assigned users (only relevant for TEAM)
    if unit.type == OrgUnitType.TEAM:
        assigned = db.query(User).filter(User.team_unit_id == unit_id).count()
        if assigned > 0 and not force:
            raise HTTPException(
                status_code=400,
                detail=f"Team has {assigned} assigned user(s). Use force=true to delete anyway (will unassign users).",
            )
        if force and assigned > 0:
            db.query(User).filter(User.team_unit_id == unit_id).update({"team_unit_id": None})

    # Orphan children if force
    if force and children > 0:
        db.query(OrgUnit).filter(OrgUnit.parent_id == unit_id).update({"parent_id": None})

    # Delete closure entries
    db.query(OrgUnitClosure).filter(
        (OrgUnitClosure.ancestor_id == unit_id) | (OrgUnitClosure.descendant_id == unit_id)
    ).delete()

    db.delete(unit)
    db.commit()

    return {"ok": True, "deleted_id": unit_id}


# ---------------------------------------------------------------------------
# Assign team manager
# ---------------------------------------------------------------------------


class AssignManagerRequest(BaseModel):
    manager_user_id: Optional[str] = None  # null to remove manager


@router.put("/org/teams/{team_id}/manager")
def assign_team_manager(
    team_id: str,
    req: AssignManagerRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Assign a user as the manager of a team."""
    _require_admin(principal)

    team = db.query(OrgUnit).filter(OrgUnit.id == team_id, OrgUnit.type == OrgUnitType.TEAM).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    old_manager_id = team.manager_user_id

    if req.manager_user_id:
        user = db.query(User).filter(User.id == req.manager_user_id).first()
        if not user:
            raise HTTPException(status_code=400, detail="User not found")

        # Check if user is already manager of another team
        other_team = (
            db.query(OrgUnit)
            .filter(OrgUnit.manager_user_id == req.manager_user_id, OrgUnit.id != team_id)
            .first()
        )
        if other_team:
            raise HTTPException(
                status_code=400,
                detail=f"User is already manager of team '{other_team.name}'. Remove them first.",
            )

        # Update user's role and team assignment
        user.role = UserRole.MANAGER
        user.team_unit_id = team_id

    # Clear old manager's role if they're being replaced
    if old_manager_id and old_manager_id != req.manager_user_id:
        old_manager = db.query(User).filter(User.id == old_manager_id).first()
        if old_manager and old_manager.role == UserRole.MANAGER:
            old_manager.role = UserRole.EMPLOYEE

    # Also clear any other users who have MANAGER role on this team (data consistency fix)
    other_managers = (
        db.query(User)
        .filter(User.team_unit_id == team_id, User.role == UserRole.MANAGER)
        .all()
    )
    for mgr in other_managers:
        if mgr.id != req.manager_user_id:
            mgr.role = UserRole.EMPLOYEE

    team.manager_user_id = req.manager_user_id
    db.commit()
    db.refresh(team)
    return _org_unit_to_dict(team, db)


# ---------------------------------------------------------------------------
# Closure rebuild
# ---------------------------------------------------------------------------


def _rebuild_closure_for_unit(db: Session, unit: OrgUnit) -> None:
    """Insert closure entries for a single newly-created unit."""
    # Self-reference
    db.add(OrgUnitClosure(ancestor_id=unit.id, descendant_id=unit.id, depth=0))

    # Walk up parents and add closure entries
    depth = 1
    current_parent_id = unit.parent_id
    while current_parent_id:
        db.add(OrgUnitClosure(ancestor_id=current_parent_id, descendant_id=unit.id, depth=depth))
        parent = db.query(OrgUnit).filter(OrgUnit.id == current_parent_id).first()
        current_parent_id = parent.parent_id if parent else None
        depth += 1
    db.commit()


def rebuild_all_closure(db: Session) -> int:
    """Rebuild the entire OrgUnitClosure table from scratch."""
    db.query(OrgUnitClosure).delete()

    units = db.query(OrgUnit).all()
    count = 0

    for unit in units:
        # Self-reference
        db.add(OrgUnitClosure(ancestor_id=unit.id, descendant_id=unit.id, depth=0))
        count += 1

        # Walk up parents
        depth = 1
        current_parent_id = unit.parent_id
        while current_parent_id:
            db.add(OrgUnitClosure(ancestor_id=current_parent_id, descendant_id=unit.id, depth=depth))
            count += 1
            parent = db.query(OrgUnit).filter(OrgUnit.id == current_parent_id).first()
            current_parent_id = parent.parent_id if parent else None
            depth += 1

    db.commit()
    return count


@router.post("/org/rebuild-closure")
def rebuild_closure_endpoint(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Manually trigger a full closure table rebuild."""
    _require_admin(principal)
    count = rebuild_all_closure(db)
    return {"ok": True, "closure_entries": count}


# ---------------------------------------------------------------------------
# User management (list, update)
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(
    email: Optional[str] = Query(default=None),
    role: Optional[UserRole] = Query(default=None),
    team_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List/search users with optional filters."""
    _require_admin(principal)

    q = db.query(User).order_by(User.email)
    if email:
        q = q.filter(User.email.ilike(f"%{email}%"))
    if role:
        q = q.filter(User.role == role)
    if team_id:
        q = q.filter(User.team_unit_id == team_id)

    users = q.all()
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
            "role": u.role.value,
            "team": team,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })

    return {"users": result}


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[UserRole] = None
    team_unit_id: Optional[str] = None
    is_active: Optional[bool] = None


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update a user's profile (role, team, is_active)."""
    _require_admin(principal)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        new_email = req.email.strip().lower()
        # Check for duplicate email
        existing = db.query(User).filter(User.email == new_email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = new_email
    if req.display_name is not None:
        user.display_name = req.display_name

    # Track old values for manager sync logic
    old_team_id = user.team_unit_id
    old_role = user.role

    # Determine final role and org unit for validation
    final_role = req.role if req.role is not None else user.role
    final_org_unit = req.team_unit_id if req.team_unit_id is not None else user.team_unit_id

    # If role is changing to ADMIN, clear org unit
    if final_role == UserRole.ADMIN and final_org_unit:
        final_org_unit = None

    # Validate org unit matches role requirements
    _validate_org_unit_for_role(db, final_org_unit, final_role)

    if req.role is not None:
        user.role = req.role
    if req.team_unit_id is not None:
        user.team_unit_id = req.team_unit_id if req.team_unit_id else None
    # Clear org unit if becoming admin
    if final_role == UserRole.ADMIN:
        user.team_unit_id = None
    if req.is_active is not None:
        user.is_active = req.is_active

    # Sync manager relationship with team's manager_user_id
    new_role = user.role
    new_team_id = user.team_unit_id

    # If user is becoming a manager of a team, update the team's manager_user_id
    if new_role == UserRole.MANAGER and new_team_id:
        # Check if user is already manager of another team
        other_team = (
            db.query(OrgUnit)
            .filter(OrgUnit.manager_user_id == user_id, OrgUnit.id != new_team_id)
            .first()
        )
        if other_team:
            raise HTTPException(
                status_code=400,
                detail=f"User is already manager of team '{other_team.name}'. Remove them first.",
            )

        # Check if another user with MANAGER role is already assigned to this team
        existing_manager = (
            db.query(User)
            .filter(User.team_unit_id == new_team_id, User.role == UserRole.MANAGER, User.id != user_id)
            .first()
        )
        if existing_manager:
            mgr_name = existing_manager.display_name or existing_manager.email
            raise HTTPException(
                status_code=400,
                detail=f"Team already has a manager: {mgr_name}. Remove them first.",
            )

        team = db.query(OrgUnit).filter(OrgUnit.id == new_team_id).first()
        if team:
            # Check if team already has a different manager (via manager_user_id)
            if team.manager_user_id and team.manager_user_id != user_id:
                existing_mgr = db.query(User).filter(User.id == team.manager_user_id).first()
                mgr_name = existing_mgr.display_name or existing_mgr.email if existing_mgr else "another user"
                raise HTTPException(
                    status_code=400,
                    detail=f"Team '{team.name}' already has a manager: {mgr_name}. Remove them first.",
                )
            team.manager_user_id = user_id

    # If user was a manager and is leaving that role or team, clear old team's manager_user_id
    if old_role == UserRole.MANAGER and old_team_id:
        if new_role != UserRole.MANAGER or new_team_id != old_team_id:
            old_team = db.query(OrgUnit).filter(OrgUnit.id == old_team_id).first()
            if old_team and old_team.manager_user_id == user_id:
                old_team.manager_user_id = None

    db.commit()
    db.refresh(user)

    team = None
    if user.team_unit_id:
        t = db.query(OrgUnit).filter(OrgUnit.id == user.team_unit_id).first()
        if t:
            team = {"id": t.id, "name": t.name}

    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "title": user.title,
        "role": user.role.value,
        "team": team,
        "is_active": user.is_active,
    }


# ---------------------------------------------------------------------------
# Platform settings
# ---------------------------------------------------------------------------


VALID_SETTINGS = {"gm_vp_approved_only", "manager_visibility_scope", "allow_self_registration", "require_approval"}


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Get all platform settings."""
    _require_admin(principal)
    rows = db.query(PlatformSetting).all()
    return {"settings": {r.key: r.value for r in rows}}


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, str] = Field(default_factory=dict)


@router.put("/settings")
def update_settings(
    req: UpdateSettingsRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update platform settings (key-value pairs)."""
    _require_admin(principal)

    for key, value in req.settings.items():
        if key not in VALID_SETTINGS:
            raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
        row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(PlatformSetting(key=key, value=value))

    db.commit()

    rows = db.query(PlatformSetting).all()
    return {"settings": {r.key: r.value for r in rows}}

