"""Tests for platform model definitions used by authorization.

These tests verify model/enum definitions without requiring a running
database. Endpoint-level authorization behavior lives in
``test_endpoint_security.py``.
"""

import pytest


# Skip entire module if pydantic_settings is not available
pydantic_settings = pytest.importorskip("pydantic_settings", reason="pydantic_settings required for platform tests")

# Also check for sqlalchemy
sqlalchemy = pytest.importorskip("sqlalchemy", reason="sqlalchemy required for platform tests")


class TestPlatformSettings:
    """Test platform settings functionality."""

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
        """All expected platform roles should be defined."""
        from qym_platform.db.models import UserRole

        roles = {r.value for r in UserRole}
        assert roles == {"MEMBER", "ADMIN"}

    def test_admin_role_exists(self):
        """ADMIN role should be available."""
        from qym_platform.db.models import UserRole

        assert UserRole.ADMIN.value == "ADMIN"

    def test_project_roles_defined(self):
        """Project-level roles should be MEMBER and MANAGER."""
        from qym_platform.db.models import ProjectRole

        roles = {r.value for r in ProjectRole}
        assert roles == {"MEMBER", "MANAGER"}
