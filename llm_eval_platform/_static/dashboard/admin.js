/**
 * Admin UI JavaScript
 * Handles user management, org structure, and platform settings
 */

// State
let users = [];
let orgUnits = [];
let settings = {};
let currentUser = null;
let deleteCallback = null;

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  const authResult = await loadCurrentUser();

  // Check authentication first
  if (authResult === 'unauthenticated') {
    showAuthError();
    return;
  }

  // Check admin access
  if (!currentUser || currentUser.role !== 'ADMIN') {
    showAccessDenied();
    return;
  }

  setupNavigation();
  await loadAllData();
  renderCurrentPage();
});

async function loadCurrentUser() {
  try {
    const res = await fetch('/v1/me');
    if (res.status === 401) {
      return 'unauthenticated';
    }
    if (res.ok) {
      currentUser = await res.json();
      return 'ok';
    }
    return 'error';
  } catch (e) {
    console.error('Failed to load current user:', e);
    return 'error';
  }
}

function showAuthError() {
  document.querySelector('.admin-container').innerHTML = `
    <div style="display: flex; align-items: center; justify-content: center; height: calc(100vh - 100px);">
      <div style="text-align: center; max-width: 360px; padding: 40px;">
        <div style="font-size: 64px; margin-bottom: 24px;">◈</div>
        <h1 style="font-size: 24px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px;">LLM-Eval Platform</h1>
        <p style="color: var(--text-muted); margin-bottom: 32px;">Sign in to access the admin panel</p>

        <button onclick="location.reload()" style="width: 100%; padding: 12px 24px; background: var(--accent-primary); color: var(--bg-base); border: none; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
          Sign in with SSO
        </button>
      </div>
    </div>
  `;
}

function showAccessDenied() {
  document.querySelector('.admin-container').innerHTML = `
    <div style="display: flex; align-items: center; justify-content: center; height: calc(100vh - 100px);">
      <div style="text-align: center; max-width: 400px; padding: 40px;">
        <div style="font-size: 64px; margin-bottom: 24px; color: var(--error);">⊘</div>
        <h1 style="font-size: 24px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px;">Access Denied</h1>
        <p style="color: var(--text-muted); margin-bottom: 32px;">Admin privileges are required to access this page</p>

        <div style="background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; padding: 24px; text-align: left;">
          <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">
            Your account does not have administrator privileges. Contact your platform administrator if you need access to this page.
          </p>
        </div>

        <a href="/" style="display: inline-block; margin-top: 24px; padding: 10px 24px; background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border-default); border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none;">
          ← Back to Dashboard
        </a>
      </div>
    </div>
  `;
}

async function loadAllData() {
  await Promise.all([
    loadUsers(),
    loadOrgUnits(),
    loadSettings()
  ]);
}

// --- Navigation ---
function setupNavigation() {
  document.querySelectorAll('.admin-nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const page = link.dataset.page;
      setActivePage(page);
    });
  });

  // Hash navigation is handled by renderCurrentPage() after data loads

  // User search
  document.getElementById('user-search')?.addEventListener('input', (e) => {
    renderUsers(e.target.value);
  });

  // Button handlers
  document.getElementById('add-user-btn')?.addEventListener('click', () => openUserModal());
  document.getElementById('add-org-unit-btn')?.addEventListener('click', () => openOrgUnitModal());
  document.getElementById('save-user-btn')?.addEventListener('click', saveUser);
  document.getElementById('save-org-unit-btn')?.addEventListener('click', saveOrgUnit);
  document.getElementById('save-settings-btn')?.addEventListener('click', saveSettings);
  document.getElementById('reset-settings-btn')?.addEventListener('click', resetSettings);
  document.getElementById('rebuild-closure-btn')?.addEventListener('click', rebuildClosure);
  document.getElementById('confirm-delete-btn')?.addEventListener('click', confirmDelete);

  // Org unit type change handler
  document.getElementById('org-unit-type')?.addEventListener('change', updateOrgUnitFormVisibility);
}

function setActivePage(page) {
  // Update nav
  document.querySelectorAll('.admin-nav-link').forEach(link => {
    link.classList.toggle('active', link.dataset.page === page);
  });

  // Update content
  document.querySelectorAll('.admin-page').forEach(section => {
    section.style.display = 'none';
  });
  document.getElementById(`${page}-page`).style.display = 'block';

  // Update hash
  window.location.hash = page;

  // Render the page content
  if (page === 'users') renderUsers();
  else if (page === 'org') renderOrgTree();
  else if (page === 'settings') renderSettings();
}

function renderCurrentPage() {
  const page = window.location.hash.substring(1) || 'users';
  setActivePage(page);
}

// --- Users ---
async function loadUsers() {
  try {
    const res = await fetch('/v1/admin/users');
    if (res.ok) {
      const data = await res.json();
      // Handle both {users: [...]} and direct array response
      users = Array.isArray(data) ? data : (data.users || []);
    } else {
      console.error('Failed to load users:', res.status, await res.text());
      showToast('error', 'Error', 'Failed to load users');
    }
  } catch (e) {
    console.error('Failed to load users:', e);
    showToast('error', 'Error', 'Failed to load users');
  }
}

function renderUsers(searchQuery = '') {
  const tbody = document.getElementById('users-tbody');
  if (!tbody) return;

  const filtered = searchQuery
    ? users.filter(u => 
        u.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (u.display_name || '').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : users;

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="empty-state">
          <p>No users found</p>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(user => {
    const team = user.team ? user.team.name : '—';
    const isCurrentUser = currentUser && currentUser.id === user.id;
    return `
      <tr data-user-id="${user.id}">
        <td>${escapeHtml(user.email)}</td>
        <td>${escapeHtml(user.display_name || '—')}</td>
        <td><span class="role-badge role-${user.role}">${user.role}</span></td>
        <td>${escapeHtml(team)}</td>
        <td>${user.is_active ? '✓ Active' : '✗ Inactive'}</td>
        <td class="table-actions">
          <a href="#" class="action-icon edit-action" onclick="editUser('${user.id}'); return false;" title="Edit user">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
          </a>
          ${isCurrentUser ? '' : `
          <a href="#" class="action-icon delete-action" onclick="deleteUser('${user.id}', '${escapeHtml(user.email)}'); return false;" title="Delete user">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </a>`}
        </td>
      </tr>
    `;
  }).join('');
}

function openUserModal(userId = null) {
  const modal = document.getElementById('user-modal');
  const title = document.getElementById('user-modal-title');
  const form = document.getElementById('user-form');
  
  form.reset();
  document.getElementById('user-id').value = '';
  
  // Populate team dropdown
  const teamSelect = document.getElementById('user-team');
  teamSelect.innerHTML = '<option value="">No Team</option>';
  const teams = orgUnits.filter(u => u.type === 'TEAM');
  teams.forEach(team => {
    teamSelect.innerHTML += `<option value="${team.id}">${escapeHtml(team.name)}</option>`;
  });

  if (userId) {
    title.textContent = 'Edit User';
    const user = users.find(u => u.id === userId);
    if (user) {
      document.getElementById('user-id').value = user.id;
      document.getElementById('user-email').value = user.email;
      document.getElementById('user-display-name').value = user.display_name || '';
      document.getElementById('user-title').value = user.title || '';
      document.getElementById('user-role').value = user.role;
      document.getElementById('user-team').value = user.team?.id || '';
    }
  } else {
    title.textContent = 'Add User';
  }

  modal.style.display = 'flex';
}

window.editUser = (userId) => openUserModal(userId);

async function saveUser() {
  const userId = document.getElementById('user-id').value;
  const data = {
    email: document.getElementById('user-email').value,
    display_name: document.getElementById('user-display-name').value,
    title: document.getElementById('user-title').value,
    role: document.getElementById('user-role').value,
    team_unit_id: document.getElementById('user-team').value || null
  };

  try {
    let res;
    if (userId) {
      res = await fetch(`/v1/admin/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
    } else {
      res = await fetch('/v1/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
    }

    if (res.ok) {
      showToast('success', 'Success', userId ? 'User updated' : 'User created');
      closeModal('user-modal');
      await Promise.all([loadUsers(), loadOrgUnits()]);
      renderUsers();
    } else {
      const err = await res.json();
      showToast('error', 'Error', err.detail || 'Failed to save user');
    }
  } catch (e) {
    showToast('error', 'Error', 'Failed to save user');
  }
}

window.deleteUser = (userId, userEmail) => {
  document.getElementById('delete-confirm-message').textContent =
    `Are you sure you want to delete user "${userEmail}"? This will also delete their API keys.`;

  deleteCallback = async () => {
    try {
      const res = await fetch(`/v1/admin/users/${userId}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('success', 'Success', 'User deleted');
        await Promise.all([loadUsers(), loadOrgUnits()]);
        renderUsers();
      } else {
        const err = await res.json();
        showToast('error', 'Error', err.detail || 'Failed to delete user');
      }
    } catch (e) {
      showToast('error', 'Error', 'Failed to delete user');
    }
  };

  document.getElementById('delete-confirm-modal').style.display = 'flex';
};

// --- Organization ---
async function loadOrgUnits() {
  try {
    // Load flat list of all org units for dropdowns
    const [treeRes, teamsRes] = await Promise.all([
      fetch('/v1/admin/org/tree'),
      fetch('/v1/admin/org/teams')
    ]);
    
    if (treeRes.ok) {
      const treeData = await treeRes.json();
      // Flatten tree into a list
      orgUnits = [];
      function flatten(node) {
        orgUnits.push({
          id: node.id,
          name: node.name,
          type: node.type,
          parent_id: node.parent_id,
          manager: node.manager,
          manager_id: node.manager?.id
        });
        if (node.children) {
          node.children.forEach(flatten);
        }
      }
      (treeData.tree || []).forEach(flatten);
    }
  } catch (e) {
    console.error('Failed to load org units:', e);
  }
}

function renderOrgTree() {
  const container = document.getElementById('org-tree');
  if (!container) return;

  if (orgUnits.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🏢</div>
        <p>No organization units defined</p>
        <button class="btn btn-primary" onclick="document.getElementById('add-org-unit-btn').click()">
          Create First Unit
        </button>
      </div>
    `;
    return;
  }

  // Build tree structure
  const rootUnits = orgUnits.filter(u => !u.parent_id);
  container.innerHTML = rootUnits.map(unit => renderOrgNode(unit)).join('');

  // Setup expand/collapse
  container.querySelectorAll('.org-node-header').forEach(header => {
    header.addEventListener('click', (e) => {
      if (e.target.closest('.table-btn')) return;
      const node = header.closest('.org-node');
      const children = node.querySelector('.org-node-children');
      const toggle = header.querySelector('.org-node-toggle');
      if (children) {
        children.style.display = children.style.display === 'none' ? 'block' : 'none';
        toggle?.classList.toggle('expanded');
        header.classList.toggle('expanded');
      }
    });
  });
}

function renderOrgNode(unit) {
  const children = orgUnits.filter(u => u.parent_id === unit.id);
  const hasChildren = children.length > 0;
  const iconClass = unit.type.toLowerCase();
  const managerName = unit.manager ? `${unit.manager.display_name || unit.manager.email}` : '';

  return `
    <div class="org-node" data-unit-id="${unit.id}">
      <div class="org-node-header">
        ${hasChildren ? '<span class="org-node-toggle expanded">▶</span>' : '<span class="org-node-toggle" style="visibility:hidden">▶</span>'}
        <span class="org-node-icon ${iconClass}">${unit.type === 'SECTOR' ? '🏛️' : unit.type === 'DEPARTMENT' ? '🏢' : '👥'}</span>
        <span class="org-node-name">${escapeHtml(unit.name)}</span>
        <span class="org-node-type">${unit.type}</span>
        ${managerName ? `<span class="org-node-manager">👤 ${escapeHtml(managerName)}</span>` : ''}
        <div class="org-node-actions">
          <a href="#" class="action-icon edit-action" onclick="editOrgUnit('${unit.id}'); return false;" title="Edit unit">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
          </a>
          <a href="#" class="action-icon delete-action" onclick="deleteOrgUnit('${unit.id}'); return false;" title="Delete unit">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </a>
        </div>
      </div>
      ${hasChildren ? `
        <div class="org-node-children">
          ${children.map(child => renderOrgNode(child)).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function openOrgUnitModal(unitId = null) {
  const modal = document.getElementById('org-unit-modal');
  const title = document.getElementById('org-unit-modal-title');
  const form = document.getElementById('org-unit-form');
  
  form.reset();
  document.getElementById('org-unit-id').value = '';

  // Populate parent dropdown (only sectors and departments can be parents)
  const parentSelect = document.getElementById('org-unit-parent');
  parentSelect.innerHTML = '<option value="">None (Top Level)</option>';
  orgUnits
    .filter(u => u.type !== 'TEAM')
    .forEach(unit => {
      parentSelect.innerHTML += `<option value="${unit.id}">${escapeHtml(unit.name)} (${unit.type})</option>`;
    });

  // Populate manager dropdown (only MANAGER role users)
  const managerSelect = document.getElementById('org-unit-manager');
  managerSelect.innerHTML = '<option value="">No Manager</option>';
  users
    .filter(u => u.role === 'MANAGER')
    .forEach(user => {
      managerSelect.innerHTML += `<option value="${user.id}">${escapeHtml(user.display_name || user.email)}</option>`;
    });

  if (unitId) {
    title.textContent = 'Edit Organization Unit';
    const unit = orgUnits.find(u => u.id === unitId);
    if (unit) {
      document.getElementById('org-unit-id').value = unit.id;
      document.getElementById('org-unit-name').value = unit.name;
      document.getElementById('org-unit-type').value = unit.type;
      document.getElementById('org-unit-parent').value = unit.parent_id || '';
      document.getElementById('org-unit-manager').value = unit.manager_id || '';
    }
  } else {
    title.textContent = 'Add Organization Unit';
  }

  updateOrgUnitFormVisibility();
  modal.style.display = 'flex';
}

function updateOrgUnitFormVisibility() {
  const type = document.getElementById('org-unit-type').value;
  const managerGroup = document.getElementById('manager-group');
  
  // Only teams have managers
  if (managerGroup) {
    managerGroup.style.display = type === 'TEAM' ? 'flex' : 'none';
  }
}

window.editOrgUnit = (unitId) => openOrgUnitModal(unitId);

window.deleteOrgUnit = (unitId) => {
  const unit = orgUnits.find(u => u.id === unitId);
  if (!unit) return;

  const children = orgUnits.filter(u => u.parent_id === unitId);
  if (children.length > 0) {
    showToast('error', 'Cannot Delete', 'This unit has child units. Delete or move them first.');
    return;
  }

  document.getElementById('delete-confirm-message').textContent = 
    `Are you sure you want to delete "${unit.name}"?`;
  
  deleteCallback = async () => {
    try {
      const res = await fetch(`/v1/admin/org/units/${unitId}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('success', 'Success', 'Unit deleted');
        await loadOrgUnits();
        renderOrgTree();
      } else {
        const err = await res.json();
        showToast('error', 'Error', err.detail || 'Failed to delete unit');
      }
    } catch (e) {
      showToast('error', 'Error', 'Failed to delete unit');
    }
  };

  document.getElementById('delete-confirm-modal').style.display = 'flex';
};

async function saveOrgUnit() {
  const unitId = document.getElementById('org-unit-id').value;
  const type = document.getElementById('org-unit-type').value;
  const managerId = type === 'TEAM' ? (document.getElementById('org-unit-manager').value || null) : null;

  try {
    let res;
    if (unitId) {
      // Update existing unit
      res = await fetch(`/v1/admin/org/units/${unitId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: document.getElementById('org-unit-name').value,
          parent_id: document.getElementById('org-unit-parent').value || null
        })
      });

      // If manager changed for a team, update separately
      if (res.ok && type === 'TEAM') {
        await fetch(`/v1/admin/org/teams/${unitId}/manager`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ manager_user_id: managerId })
        });
      }
    } else {
      // Create new unit
      res = await fetch('/v1/admin/org/units', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: document.getElementById('org-unit-name').value,
          type: type,
          parent_id: document.getElementById('org-unit-parent').value || null
        })
      });

      // If creating a team with a manager, assign the manager
      if (res.ok && type === 'TEAM' && managerId) {
        const result = await res.json();
        await fetch(`/v1/admin/org/teams/${result.id}/manager`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ manager_user_id: managerId })
        });
      }
    }

    if (res.ok) {
      showToast('success', 'Success', unitId ? 'Unit updated' : 'Unit created');
      closeModal('org-unit-modal');
      await loadOrgUnits();
      renderOrgTree();
      // Also reload users to update team dropdowns
      await loadUsers();
    } else {
      const err = await res.json();
      showToast('error', 'Error', err.detail || 'Failed to save unit');
    }
  } catch (e) {
    showToast('error', 'Error', 'Failed to save unit');
  }
}

async function rebuildClosure() {
  try {
    const res = await fetch('/v1/admin/org/rebuild-closure', { method: 'POST' });
    if (res.ok) {
      const result = await res.json();
      showToast('success', 'Success', `Closure rebuilt: ${result.closure_entries} entries created`);
    } else {
      const err = await res.json();
      showToast('error', 'Error', err.detail || 'Failed to rebuild closure');
    }
  } catch (e) {
    showToast('error', 'Error', 'Failed to rebuild closure');
  }
}

// --- Settings ---
async function loadSettings() {
  try {
    const res = await fetch('/v1/admin/settings');
    if (res.ok) {
      const data = await res.json();
      settings = data.settings || {};
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

function renderSettings() {
  // GM/VP Approved Only
  const gmVpApproved = document.getElementById('setting-gm-vp-approved-only');
  if (gmVpApproved) {
    gmVpApproved.checked = (settings['gm_vp_approved_only'] || 'true').toLowerCase() === 'true';
  }

  // Manager Visibility Scope (subtree = checked, direct = unchecked)
  const managerSubtree = document.getElementById('setting-manager-full-subtree');
  if (managerSubtree) {
    managerSubtree.checked = (settings['manager_visibility_scope'] || 'subtree') === 'subtree';
  }
}

async function saveSettings() {
  const settingsData = {
    gm_vp_approved_only: document.getElementById('setting-gm-vp-approved-only').checked ? 'true' : 'false',
    manager_visibility_scope: document.getElementById('setting-manager-full-subtree').checked ? 'subtree' : 'direct'
  };

  try {
    const res = await fetch('/v1/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: settingsData })
    });

    if (res.ok) {
      showToast('success', 'Success', 'Settings saved');
      await loadSettings();
    } else {
      const err = await res.json();
      showToast('error', 'Error', err.detail || 'Failed to save settings');
    }
  } catch (e) {
    showToast('error', 'Error', 'Failed to save settings');
  }
}

function resetSettings() {
  document.getElementById('setting-gm-vp-approved-only').checked = true;
  document.getElementById('setting-manager-full-subtree').checked = true;
  document.getElementById('setting-self-registration').checked = false;
  document.getElementById('setting-require-approval').checked = true;
}

// --- Modal Helpers ---
function closeModal(modalId) {
  document.getElementById(modalId).style.display = 'none';
}
window.closeModal = closeModal;

function confirmDelete() {
  if (deleteCallback) {
    deleteCallback();
    deleteCallback = null;
  }
  closeModal('delete-confirm-modal');
}

// --- Toast Notifications ---
function showToast(type, title, message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <div class="toast-icon">${type === 'success' ? '✓' : '✗'}</div>
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(title)}</div>
      <div class="toast-message">${escapeHtml(message)}</div>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// --- Utilities ---
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

