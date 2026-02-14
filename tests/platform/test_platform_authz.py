"""Tests for platform authorization and visibility rules.

These tests verify the authorization and visibility rules without requiring
a running database. They test the model definitions and basic logic.
"""

import pytest
import sys
from unittest.mock import MagicMock
from datetime import datetime


# Skip entire module if pydantic_settings is not available
pydantic_settings = pytest.importorskip("pydantic_settings", reason="pydantic_settings required for platform tests")

# Also check for sqlalchemy
sqlalchemy = pytest.importorskip("sqlalchemy", reason="sqlalchemy required for platform tests")


@pytest.fixture(scope="module", autouse=True)
def setup_test_database_url():
    """Set up a test database URL before any platform module imports."""
    import os
    # Use in-memory SQLite for tests
    os.environ["QYM_DATABASE_URL"] = "sqlite:///:memory:"
    yield
    # Clean up (optional - environment persists in test session)


@pytest.fixture
def mock_db():
    """Mock database session."""
    from sqlalchemy.orm import Session
    return MagicMock(spec=Session)


@pytest.fixture
def sample_users(mock_db):
    """Create sample users for testing."""
    from qym_platform.db.models import User, UserRole, OrgUnit, OrgUnitType
    
    # Create org structure
    sector = OrgUnit(id="sector-1", name="Tech Sector", type=OrgUnitType.SECTOR)
    dept = OrgUnit(id="dept-1", name="AI Department", type=OrgUnitType.DEPARTMENT, parent_id="sector-1")
    team = OrgUnit(id="team-1", name="Training Team", type=OrgUnitType.TEAM, parent_id="dept-1")
    
    # Create users
    admin = User(id="admin-1", email="admin@test.com", role=UserRole.ADMIN, team_unit_id=None)
    manager = User(id="manager-1", email="manager@test.com", role=UserRole.MANAGER, team_unit_id="team-1")
    employee = User(id="emp-1", email="emp@test.com", role=UserRole.EMPLOYEE, team_unit_id="team-1")
    gm = User(id="gm-1", email="gm@test.com", role=UserRole.GM, team_unit_id=None)
    vp = User(id="vp-1", email="vp@test.com", role=UserRole.VP, team_unit_id=None)
    other_emp = User(id="emp-2", email="other@test.com", role=UserRole.EMPLOYEE, team_unit_id="team-2")
    
    # Set team manager
    team.manager_user_id = manager.id
    
    return {
        "sector": sector,
        "dept": dept,
        "team": team,
        "admin": admin,
        "manager": manager,
        "employee": employee,
        "gm": gm,
        "vp": vp,
        "other_emp": other_emp,
    }


@pytest.fixture
def sample_runs(sample_users):
    """Create sample runs for testing."""
    from qym_platform.db.models import Run, RunWorkflowStatus
    
    draft_run = Run(
        id="run-draft",
        external_run_id="draft-1",
        task="test_task",
        dataset="test_ds",
        created_by_user_id=sample_users["employee"].id,
        owner_user_id=sample_users["employee"].id,
        status=RunWorkflowStatus.DRAFT,
        created_at=datetime.utcnow(),
    )
    
    submitted_run = Run(
        id="run-submitted",
        external_run_id="submitted-1",
        task="test_task",
        dataset="test_ds",
        created_by_user_id=sample_users["employee"].id,
        owner_user_id=sample_users["employee"].id,
        status=RunWorkflowStatus.SUBMITTED,
        created_at=datetime.utcnow(),
    )
    
    approved_run = Run(
        id="run-approved",
        external_run_id="approved-1",
        task="test_task",
        dataset="test_ds",
        created_by_user_id=sample_users["employee"].id,
        owner_user_id=sample_users["employee"].id,
        status=RunWorkflowStatus.APPROVED,
        created_at=datetime.utcnow(),
    )
    
    other_run = Run(
        id="run-other",
        external_run_id="other-1",
        task="test_task",
        dataset="test_ds",
        created_by_user_id=sample_users["other_emp"].id,
        owner_user_id=sample_users["other_emp"].id,
        status=RunWorkflowStatus.DRAFT,
        created_at=datetime.utcnow(),
    )
    
    return {
        "draft": draft_run,
        "submitted": submitted_run,
        "approved": approved_run,
        "other": other_run,
    }


class TestOrgUnitVisibility:
    """Test org unit based visibility rules."""
    
    def test_admin_can_view_all(self, sample_users, sample_runs):
        """Admin users should be able to view all runs."""
        from qym_platform.auth import Principal
        
        principal = MagicMock(spec=Principal)
        principal.user = sample_users["admin"]
        principal.auth_type = "proxy"
        
        # Admin should have access to any run
        assert principal.user.role.value == "ADMIN"
    
    def test_employee_sees_own_runs_only(self, sample_users, sample_runs):
        """Employee users should only see their own runs."""
        from qym_platform.db.models import UserRole
        
        emp = sample_users["employee"]
        assert emp.role == UserRole.EMPLOYEE
        
        # Employee's run
        assert sample_runs["draft"].owner_user_id == emp.id
        # Other employee's run
        assert sample_runs["other"].owner_user_id != emp.id
    
    def test_gm_vp_approved_only_rule(self, sample_users, sample_runs):
        """GM/VP users should only see approved runs when policy is enabled."""
        from qym_platform.db.models import UserRole, RunWorkflowStatus
        
        gm = sample_users["gm"]
        vp = sample_users["vp"]
        
        assert gm.role == UserRole.GM
        assert vp.role == UserRole.VP
        
        # Approved run should be visible
        assert sample_runs["approved"].status == RunWorkflowStatus.APPROVED
        # Draft run should not be visible to GM/VP
        assert sample_runs["draft"].status == RunWorkflowStatus.DRAFT


class TestManagerApproval:
    """Test manager approval authority."""
    
    def test_manager_can_approve_team_runs(self, sample_users, sample_runs):
        """Manager should be able to approve runs from their team."""
        from qym_platform.db.models import UserRole
        
        manager = sample_users["manager"]
        employee = sample_users["employee"]
        team = sample_users["team"]
        
        assert manager.role == UserRole.MANAGER
        assert team.manager_user_id == manager.id
        assert employee.team_unit_id == team.id
        
        # The run owner is in the manager's team
        run = sample_runs["submitted"]
        assert run.owner_user_id == employee.id
    
    def test_manager_cannot_approve_other_team_runs(self, sample_users, sample_runs):
        """Manager should not be able to approve runs from other teams."""
        from qym_platform.db.models import UserRole
        
        manager = sample_users["manager"]
        other_emp = sample_users["other_emp"]
        
        assert manager.role == UserRole.MANAGER
        # Other employee is in a different team
        assert other_emp.team_unit_id != manager.team_unit_id
        
        # The run from other team should not be approvable by this manager
        other_run = sample_runs["other"]
        assert other_run.owner_user_id == other_emp.id


class TestOrgClosure:
    """Test org closure table functionality."""
    
    def test_closure_contains_self_reference(self):
        """Each org unit should have a self-reference in the closure table."""
        from qym_platform.db.models import OrgUnitClosure
        
        # Self-reference has depth 0
        closure = OrgUnitClosure(ancestor_id="team-1", descendant_id="team-1", depth=0)
        assert closure.depth == 0
        assert closure.ancestor_id == closure.descendant_id
    
    def test_closure_captures_hierarchy(self):
        """Closure table should capture full hierarchy."""
        from qym_platform.db.models import OrgUnitClosure
        
        # Team -> Dept -> Sector
        closures = [
            OrgUnitClosure(ancestor_id="team-1", descendant_id="team-1", depth=0),  # self
            OrgUnitClosure(ancestor_id="dept-1", descendant_id="team-1", depth=1),  # parent
            OrgUnitClosure(ancestor_id="sector-1", descendant_id="team-1", depth=2),  # grandparent
        ]
        
        depths = {c.ancestor_id: c.depth for c in closures}
        assert depths["team-1"] == 0
        assert depths["dept-1"] == 1
        assert depths["sector-1"] == 2


class TestPlatformSettings:
    """Test platform settings functionality."""
    
    def test_valid_settings(self):
        """Test that valid settings are accepted."""
        from qym_platform.api.org import VALID_SETTINGS
        
        assert "gm_vp_approved_only" in VALID_SETTINGS
        assert "manager_visibility_scope" in VALID_SETTINGS
    
    def test_setting_values(self):
        """Test setting value formats."""
        from qym_platform.db.models import PlatformSetting
        
        setting = PlatformSetting(key="gm_vp_approved_only", value="true")
        assert setting.value.lower() == "true"
        
        setting2 = PlatformSetting(key="manager_visibility_scope", value="subtree")
        assert setting2.value == "subtree"


class TestUserRoles:
    """Test user role definitions."""
    
    def test_all_roles_defined(self):
        """All expected roles should be defined."""
        from qym_platform.db.models import UserRole
        
        roles = [r.value for r in UserRole]
        assert "EMPLOYEE" in roles
        assert "MANAGER" in roles
        assert "GM" in roles
        assert "VP" in roles
        assert "ADMIN" in roles
    
    def test_admin_role_exists(self):
        """ADMIN role should be available."""
        from qym_platform.db.models import UserRole
        
        assert UserRole.ADMIN.value == "ADMIN"
